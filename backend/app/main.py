from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
from copy import copy
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from jwt import InvalidTokenError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db
from .dependencies import bearer, get_current_membership, get_current_user, require_admin, user_from_token
from .models import (
    AnswerKey,
    AssessmentSession,
    ClassEnrollment,
    ClassModel,
    ClassStatus,
    CourseDay,
    CourseDayStatus,
    ExamType,
    MemberRole,
    Organization,
    OrganizationMember,
    OrganizationSettings,
    OrganizationStatus,
    Question,
    QuestionType,
    QRCodeStatus,
    ScanRecord,
    ScanStatus,
    SchoolStage,
    SessionParticipant,
    SessionStatus,
    ScannerSession,
    ScannerSessionStatus,
    Student,
    StudentAnswer,
    StudentStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
    StudentQRCode,
    Subject,
    TimeSlot,
    User,
)
from .realtime import event_broker
from .schemas import (
    AddStudentToClass,
    BulkAttachStudents,
    BulkStudentCreate,
    ClassCreate,
    ClassDetailOut,
    ClassOut,
    ClassUpdate,
    CourseDayCreate,
    CourseDayOut,
    CourseDayUpdate,
    LoginRequest,
    MeOut,
    MessageOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationSettingsUpdate,
    QRTokenOut,
    RecognitionResultCreate,
    ResultsOut,
    ScanOut,
    SessionCreate,
    SessionOut,
    ScannerAssessmentOut,
    ScannerSessionOut,
    StudentImportConfirm,
    StudentImportItem,
    StudentImportMatch,
    StudentImportPreviewOut,
    StudentImportResult,
    StudentCreate,
    StudentLiveState,
    StudentOut,
    StudentUpdate,
    SubmissionCreate,
    SubmissionOut,
    SubjectCreate,
    SubjectOut,
    SubjectUpdate,
    TeacherCreate,
    TeacherOut,
    TimeSlotCreate,
    TimeSlotOut,
    TimeSlotUpdate,
    TransferStudent,
    TokenOut,
)
from .security import create_access_token, decode_access_token, hash_password, verify_password


settings = get_settings()
settings.validate_runtime()

app = FastAPI(
    title="智慧课堂系统 API",
    version="0.1.0",
    description="Organization-aware classroom assessment, submissions, results and SSE events.",
    docs_url="/docs",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


WEEKDAY_LABELS = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
SCHOOL_STAGE_LABELS = {SchoolStage.PRIMARY: "小学", SchoolStage.MIDDLE: "初中", SchoolStage.HIGH: "高中"}


def suggested_prefix(name: str) -> str:
    letters = re.findall(r"[A-Za-z0-9]", name)
    if letters:
        return "".join(letters[:4]).upper()
    return "ORG"


def normalize_prefix(value: str | None, organization_name: str) -> str:
    prefix = (value or suggested_prefix(organization_name)).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", prefix):
        raise HTTPException(status_code=422, detail="机构代码前缀只能包含 2-12 位英文字母或数字")
    return prefix


def next_student_code(db: Session, organization_id: str) -> str:
    """Atomically advance the organization counter before creating a student.

    PostgreSQL serializes the UPDATE on the organization row. The unique
    constraint on students remains the final database-level safety net.
    """
    for _ in range(100):
        serial = db.execute(
            update(Organization)
            .where(Organization.id == organization_id)
            .values(student_serial=Organization.student_serial + 1)
            .returning(Organization.student_serial)
        ).scalar_one()
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        code = f"{organization.code_prefix}{serial:04d}"
        if db.scalar(select(Student.id).where(Student.organization_id == organization_id, Student.student_code == code)) is None:
            return code
    raise HTTPException(status_code=409, detail="Unable to allocate a unique student number")


def issue_student_qr(db: Session, student: Student) -> tuple[str, int]:
    for qr_code in student.qr_codes:
        if qr_code.status == QRCodeStatus.ACTIVE:
            qr_code.status = QRCodeStatus.REVOKED
            qr_code.revoked_at = now_utc()
    version = max((qr_code.version for qr_code in student.qr_codes), default=0) + 1
    token = secrets.token_urlsafe(32)
    db.add(StudentQRCode(student_id=student.id, token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(), version=version))
    return token, version


def current_qr(db: Session, student: Student) -> StudentQRCode | None:
    return db.scalar(
        select(StudentQRCode).where(
            StudentQRCode.student_id == student.id,
            StudentQRCode.status == QRCodeStatus.ACTIVE,
        ).order_by(StudentQRCode.version.desc())
    )


def org_id_from_context(context: tuple[User, OrganizationMember]) -> str:
    return context[1].organization_id


def is_admin(context: tuple[User, OrganizationMember]) -> bool:
    return context[1].role in {MemberRole.OWNER, MemberRole.ADMIN}


def class_is_visible(class_model: ClassModel, context: tuple[User, OrganizationMember]) -> bool:
    membership = context[1]
    return membership.role in {MemberRole.OWNER, MemberRole.ADMIN} or class_model.teacher_id == membership.id


def ensure_class_access(class_model: ClassModel, context: tuple[User, OrganizationMember]) -> None:
    if not class_is_visible(class_model, context):
        raise HTTPException(status_code=403, detail="You can only access classes assigned to you")


def get_org(db: Session, org_id: str) -> Organization:
    organization = db.scalar(
        select(Organization).options(selectinload(Organization.settings)).where(Organization.id == org_id)
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def class_or_404(db: Session, class_id: str, org_id: str) -> ClassModel:
    class_model = db.scalar(select(ClassModel).where(ClassModel.id == class_id, ClassModel.organization_id == org_id))
    if class_model is None:
        raise HTTPException(status_code=404, detail="Class not found")
    return class_model


def student_or_404(db: Session, student_id: str, org_id: str) -> Student:
    student = db.scalar(select(Student).where(Student.id == student_id, Student.organization_id == org_id))
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def session_or_404(db: Session, session_id: str, org_id: str) -> AssessmentSession:
    session = db.scalar(
        select(AssessmentSession)
        .options(
            selectinload(AssessmentSession.class_model).selectinload(ClassModel.teacher_membership).selectinload(OrganizationMember.user),
            selectinload(AssessmentSession.class_model).selectinload(ClassModel.time_slot),
            selectinload(AssessmentSession.subject),
            selectinload(AssessmentSession.questions).selectinload(Question.answer_key),
            selectinload(AssessmentSession.participants),
        )
        .where(AssessmentSession.id == session_id, AssessmentSession.organization_id == org_id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Assessment session not found")
    return session


def scanner_session_or_404(db: Session, scanner_session_id: str, org_id: str) -> ScannerSession:
    scanner_session = db.scalar(
        select(ScannerSession)
        .options(
            selectinload(ScannerSession.assessment_session).selectinload(AssessmentSession.class_model),
            selectinload(ScannerSession.opened_by_user),
            selectinload(ScannerSession.opened_by_member),
        )
        .where(ScannerSession.id == scanner_session_id, ScannerSession.organization_id == org_id)
    )
    if scanner_session is None:
        raise HTTPException(status_code=404, detail="Scanner session not found")
    return scanner_session


def scanner_session_out(scanner_session: ScannerSession) -> dict[str, Any]:
    return {
        "id": scanner_session.id,
        "organization_id": scanner_session.organization_id,
        "assessment_session_id": scanner_session.assessment_session_id,
        "opened_by": scanner_session.opened_by_user.display_name,
        "opened_by_member_id": scanner_session.opened_by_member_id,
        "status": scanner_session.status,
        "opened_at": scanner_session.opened_at,
        "closed_at": scanner_session.closed_at,
    }


def scanner_assessment_out(db: Session, session: AssessmentSession) -> dict[str, Any]:
    submitted_count = db.scalar(
        select(func.count(Submission.id)).where(Submission.session_id == session.id)
    ) or 0
    participant_count = db.scalar(
        select(func.count(SessionParticipant.id)).where(SessionParticipant.session_id == session.id)
    ) or 0
    return {
        "id": session.id,
        "organization_id": session.organization_id,
        "class_id": session.class_id,
        "class_name": session.class_model.name,
        "name": session.name,
        "status": session.status,
        "question_count": session.question_count,
        "submitted_count": submitted_count,
        "participant_count": participant_count,
    }


def get_or_create_scanner_session(
    db: Session,
    session: AssessmentSession,
    context: tuple[User, OrganizationMember],
) -> ScannerSession:
    user, membership = context
    existing = db.scalar(
        select(ScannerSession).where(
            ScannerSession.organization_id == membership.organization_id,
            ScannerSession.assessment_session_id == session.id,
            ScannerSession.opened_by_member_id == membership.id,
        )
    )
    if existing is not None:
        if existing.status != ScannerSessionStatus.OPEN:
            existing.status = ScannerSessionStatus.OPEN
            existing.closed_at = None
            db.commit()
        return scanner_session_or_404(db, existing.id, membership.organization_id)

    scanner_session = ScannerSession(
        organization_id=membership.organization_id,
        assessment_session_id=session.id,
        opened_by_user_id=user.id,
        opened_by_member_id=membership.id,
        status=ScannerSessionStatus.OPEN,
    )
    db.add(scanner_session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ScannerSession).where(
                ScannerSession.organization_id == membership.organization_id,
                ScannerSession.assessment_session_id == session.id,
                ScannerSession.opened_by_member_id == membership.id,
            )
        )
        if existing is None:
            raise
        scanner_session = existing
    return scanner_session_or_404(db, scanner_session.id, membership.organization_id)


def scan_storage_root() -> Path:
    configured = Path(settings.scan_storage_dir)
    return configured if configured.is_absolute() else Path(__file__).resolve().parents[1] / configured


def persist_scan_image(image: UploadFile, destination: Path) -> tuple[str, int]:
    content_type = (image.content_type or "").lower()
    if content_type not in {"image/jpeg", "image/jpg", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="扫描图片必须是 JPEG 格式")
    content = image.file.read(settings.max_scan_image_bytes + 1)
    if len(content) > settings.max_scan_image_bytes:
        raise HTTPException(status_code=413, detail="扫描图片不能超过 15 MB")
    if not content or not content.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=422, detail="扫描图片无效，请重新拍摄")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(content).hexdigest(), len(content)


def scan_out(scan: ScanRecord) -> dict[str, Any]:
    session = scan.assessment_session
    student = scan.student
    return {
        "server_scan_id": scan.id,
        "session_id": scan.assessment_session_id,
        "scan_session_id": scan.scanner_session_id,
        "class_id": session.class_id,
        "client_capture_id": scan.client_capture_id,
        "status": scan.status,
        "request_id": scan.request_id,
        "student_name": student.name if student else None,
        "student_code": student.student_code if student else None,
        "page_type": scan.page_type,
        "created_at": scan.created_at,
        "processed_at": scan.processed_at,
    }


def ensure_session_access(session: AssessmentSession, context: tuple[User, OrganizationMember]) -> None:
    ensure_class_access(session.class_model, context)


def organization_out(organization: Organization) -> dict[str, Any]:
    return {
        "id": organization.id,
        "name": organization.name,
        "code_prefix": organization.code_prefix,
        "student_serial": organization.student_serial,
        "status": organization.status,
        "settings": organization.settings,
        "created_at": organization.created_at,
    }


def class_out(db: Session, class_model: ClassModel) -> dict[str, Any]:
    count = db.scalar(
        select(func.count(ClassEnrollment.id)).where(
            ClassEnrollment.class_id == class_model.id,
            ClassEnrollment.left_at.is_(None),
            ClassEnrollment.student.has(status=StudentStatus.ACTIVE),
        )
    ) or 0
    return {
        "id": class_model.id,
        "organization_id": class_model.organization_id,
        "name": class_model.name,
        "teacher_id": class_model.teacher_id,
        "teacher_name": class_model.teacher_membership.user.display_name if class_model.teacher_membership else None,
        "school_stage": class_model.school_stage,
        "grade": class_model.grade,
        "day_of_week": class_model.day_of_week,
        "time_slot_id": class_model.time_slot_id,
        "time_slot_name": class_model.time_slot.display_name if class_model.time_slot else None,
        "status": class_model.status,
        "student_count": count,
        "created_at": class_model.created_at,
    }


def session_out(session: AssessmentSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "organization_id": session.organization_id,
        "class_id": session.class_id,
        "class_name": session.class_model.name,
        "subject_id": session.subject_id,
        "subject_name": session.subject.name if session.subject else None,
        "exam_type": session.exam_type,
        "name": session.name,
        "question_count": session.question_count,
        "total_score": session.total_score,
        "status": session.status,
        "created_at": session.created_at,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "questions": [
            {
                "id": question.id,
                "question_no": question.question_no,
                "question_type": question.question_type,
                "points": question.points,
                "correct_answer": question.answer_key.value,
            }
            for question in session.questions
        ],
    }


def active_enrollment(db: Session, class_id: str, student_id: str) -> ClassEnrollment | None:
    return db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.student_id == student_id,
            ClassEnrollment.left_at.is_(None),
        )
    )


def class_metadata_or_422(
    db: Session,
    organization_id: str,
    *,
    teacher_id: str | None,
    school_stage: SchoolStage,
    day_of_week: int | None,
    time_slot_id: str | None,
) -> tuple[OrganizationMember | None, TimeSlot | None]:
    teacher = None
    if teacher_id:
        teacher = db.scalar(
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(
                OrganizationMember.id == teacher_id,
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role.in_([MemberRole.OWNER, MemberRole.ADMIN, MemberRole.TEACHER]),
            )
        )
        if teacher is None:
            raise HTTPException(status_code=422, detail="授课教师不属于当前机构")
    if day_of_week is not None:
        day = db.scalar(select(CourseDay).where(CourseDay.organization_id == organization_id, CourseDay.weekday == day_of_week))
        if day is None or day.status != CourseDayStatus.ACTIVE:
            raise HTTPException(status_code=422, detail="所选上课日当前未启用")
    slot = None
    if time_slot_id:
        slot = db.scalar(select(TimeSlot).where(TimeSlot.id == time_slot_id, TimeSlot.organization_id == organization_id))
        if slot is None or not slot.active:
            raise HTTPException(status_code=422, detail="所选上课时段当前未启用")
        if slot.applicable_school_stage is not None and slot.applicable_school_stage != school_stage:
            raise HTTPException(status_code=422, detail="所选时段不适用于当前学段")
    return teacher, slot


def scoped_classes_query(context: tuple[User, OrganizationMember]):
    org_id = org_id_from_context(context)
    query = select(ClassModel).where(ClassModel.organization_id == org_id)
    if context[1].role == MemberRole.TEACHER:
        query = query.where(ClassModel.teacher_id == context[1].id)
    return query


def create_or_update_submission(
    db: Session,
    session: AssessmentSession,
    payload: SubmissionCreate,
) -> tuple[Submission, bool]:
    if payload.source == SubmissionSource.MOCK and not settings.allow_dev_submission:
        raise HTTPException(status_code=403, detail="Development submission is disabled")
    if session.status not in {SessionStatus.ACTIVE, SessionStatus.CLOSED} or (session.status == SessionStatus.CLOSED and payload.source == SubmissionSource.MOCK):
        raise HTTPException(status_code=409, detail="当前考试不接受此类提交")
    participant = db.scalar(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session.id,
            SessionParticipant.student_id == payload.student_id,
        )
    )
    if participant is None:
        raise HTTPException(status_code=422, detail="Student is not a participant in this session")
    db.execute(select(AssessmentSession.id).where(AssessmentSession.id == session.id).with_for_update())
    question_map = {question.question_no: question for question in session.questions}
    seen: set[int] = set()
    for answer in payload.answers:
        if answer.question_no in seen or answer.question_no not in question_map:
            raise HTTPException(status_code=422, detail="Answers must contain unique valid question numbers")
        if question_map[answer.question_no].question_type in {QuestionType.SINGLE_CHOICE, QuestionType.MCQ} and answer.value not in {"", "A", "B", "C", "D"}:
            raise HTTPException(status_code=422, detail="选择题答案必须为 A/B/C/D 或空白")
        seen.add(answer.question_no)
    existing = db.scalar(
        select(Submission)
        .options(selectinload(Submission.answers))
        .where(Submission.session_id == session.id, Submission.student_id == payload.student_id)
    )
    if existing and payload.source == SubmissionSource.RECOGNITION:
        from .schemas import SubmissionAnswerInput
        incoming = {answer.question_no for answer in payload.answers}
        payload.answers.extend(SubmissionAnswerInput(question_no=a.question_no, value=a.value, confidence=a.confidence) for a in existing.answers if a.question_no not in incoming)
        payload.review_required = payload.review_required or any(a.confidence is not None and a.confidence < 0.8 for a in payload.answers)
    if payload.source == SubmissionSource.RECOGNITION:
        payload.review_required = payload.review_required or len(payload.answers) < session.question_count
    is_update = existing is not None
    submission = existing or Submission(session_id=session.id, student_id=payload.student_id)
    submission.status = SubmissionStatus.REVIEW_REQUIRED if payload.review_required else SubmissionStatus.SUBMITTED
    submission.source = payload.source
    submission.page_type = payload.page_type
    submission.confidence = payload.confidence
    submission.score = sum(question_map[answer.question_no].points for answer in payload.answers if answer.value.strip() == question_map[answer.question_no].answer_key.value.strip() and (answer.confidence is None or answer.confidence >= 0.8))
    if existing:
        existing.answers.clear()
        # Flush deletions before inserting replacement rows so the unique
        # (submission_id, question_id) key cannot collide during an update.
        db.flush()
    for answer in payload.answers:
        question = question_map[answer.question_no]
        submission.answers.append(
            StudentAnswer(
                question_id=question.id,
                question_no=question.question_no,
                value=answer.value,
                confidence=answer.confidence,
                is_correct=answer.value.strip() == question.answer_key.value.strip() and (answer.confidence is None or answer.confidence >= 0.8),
            )
        )
    db.add(submission)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A submission already exists; retry as an update") from exc
    db.refresh(submission)
    return submission, is_update


def submission_out(submission: Submission, session: AssessmentSession, is_update: bool) -> dict[str, Any]:
    return {
        "id": submission.id,
        "session_id": submission.session_id,
        "student_id": submission.student_id,
        "status": submission.status,
        "source": submission.source,
        "page_type": submission.page_type,
        "confidence": submission.confidence,
        "score": submission.score,
        "is_update": is_update,
        "correct_count": sum(1 for answer in submission.answers if answer.is_correct),
        "question_count": session.question_count,
        "submitted_at": submission.submitted_at,
        "updated_at": submission.updated_at,
    }


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "classroom-assessment-api"}


@app.get("/ready", tags=["system"])
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(select(1))
    return {"status": "ready", "database": "ok"}


@app.post("/api/v1/auth/login", response_model=TokenOut, tags=["auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    organization_name = payload.organization_name.strip().lower()
    login_name = payload.teacher_login_name.strip().lower()
    membership = db.scalar(
        select(OrganizationMember)
        .join(Organization, OrganizationMember.organization_id == Organization.id)
        .join(User, OrganizationMember.user_id == User.id)
        .options(
            selectinload(OrganizationMember.user),
            selectinload(OrganizationMember.organization),
        )
        .where(
            func.lower(Organization.name) == organization_name,
            func.lower(OrganizationMember.login_name) == login_name,
            Organization.status == OrganizationStatus.ACTIVE,
            User.is_active.is_(True),
        )
    )
    user = membership.user if membership else None
    if membership is None or user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="机构名称、老师或密码不正确")
    return {
        "access_token": create_access_token(user.id, membership.organization_id, membership.id, membership.role.value),
        "token_type": "bearer",
        "user": user,
        "organization_id": membership.organization_id,
        "organization_name": membership.organization.name,
        "teacher_id": membership.id,
        "teacher_name": user.display_name,
        "login_name": membership.login_name,
        "role": membership.role,
    }


@app.get("/api/v1/me", response_model=MeOut, tags=["auth"])
def me(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    user, membership = context
    organization = get_org(db, membership.organization_id)
    membership = db.scalar(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.organization).selectinload(Organization.settings))
        .where(OrganizationMember.id == membership.id)
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="No active organization membership")
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "organization_id": organization.id,
        "teacher_id": membership.id,
        "login_name": membership.login_name,
        "role": membership.role,
        "organization": organization,
        "memberships": [membership],
    }


@app.get("/api/v1/organizations", response_model=list[OrganizationOut], tags=["organizations"])
def list_organizations(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [organization_out(get_org(db, org_id_from_context(context)))]


@app.post("/api/v1/organizations", response_model=OrganizationOut, status_code=201, tags=["organizations"])
def create_organization(_: OrganizationCreate, user: User = Depends(get_current_user)) -> dict[str, Any]:
    # Organization provisioning belongs to the future platform-admin surface;
    # ordinary tenant users must never create a new tenant from the login app.
    raise HTTPException(status_code=403, detail="机构创建由平台管理后台执行")


@app.patch("/api/v1/organizations/{organization_id}/settings", response_model=OrganizationOut, tags=["organizations"])
def update_organization_settings(
    organization_id: str,
    payload: OrganizationSettingsUpdate,
    context: tuple[User, OrganizationMember] = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if context[1].organization_id != organization_id or not is_admin(context):
        raise HTTPException(status_code=403, detail="Insufficient organization role")
    organization = get_org(db, organization_id)
    if payload.code_prefix is not None:
        next_prefix = normalize_prefix(payload.code_prefix, organization.name)
        if next_prefix != organization.code_prefix and db.scalar(select(Student.id).where(Student.organization_id == organization.id)):
            raise HTTPException(status_code=409, detail="机构已有学生后不能更换学生编号前缀")
        organization.code_prefix = next_prefix
    organization.settings = organization.settings or OrganizationSettings(organization_id=organization.id)
    settings_values = payload.model_dump(exclude_unset=True)
    if "organization_name" in settings_values:
        organization.settings.organization_name = settings_values["organization_name"]
    if "logo" in settings_values:
        organization.settings.logo = settings_values["logo"]
    organization.settings.student_code_label = settings_values["student_code_label"]
    db.commit()
    db.refresh(organization)
    return organization_out(organization)


def teacher_out(db: Session, membership: OrganizationMember) -> dict[str, Any]:
    class_count = db.scalar(
        select(func.count(ClassModel.id)).where(
            ClassModel.teacher_id == membership.id,
            ClassModel.status == ClassStatus.ACTIVE,
        )
    ) or 0
    return {
        "id": membership.id,
        "user_id": membership.user_id,
        "display_name": membership.user.display_name,
        "login_name": membership.login_name,
        "email": membership.user.email,
        "role": membership.role,
        "active": membership.user.is_active,
        "class_count": class_count,
    }


@app.get("/api/v1/teachers", response_model=list[TeacherOut], tags=["teachers"])
def list_teachers(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    members = db.scalars(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.user))
        .where(
            OrganizationMember.organization_id == org_id_from_context(context),
            OrganizationMember.role.in_([MemberRole.OWNER, MemberRole.ADMIN, MemberRole.TEACHER]),
            OrganizationMember.user.has(is_active=True),
        )
        .order_by(OrganizationMember.role, OrganizationMember.created_at)
    ).all()
    return [teacher_out(db, member) for member in members]


@app.post("/api/v1/teachers", response_model=TeacherOut, status_code=201, tags=["teachers"])
def create_teacher(payload: TeacherCreate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    display_name = payload.display_name.strip()
    login_name = payload.login_name.strip().lower()
    if not display_name:
        raise HTTPException(status_code=422, detail="教师姓名不能为空")
    if payload.role == MemberRole.OWNER:
        raise HTTPException(status_code=422, detail="新教师只能设置为教师或机构管理员")
    if db.scalar(select(OrganizationMember.id).where(OrganizationMember.organization_id == org_id, func.lower(OrganizationMember.login_name) == login_name)):
        raise HTTPException(status_code=409, detail="该登录名称已经存在")
    user = None
    if payload.email:
        email = str(payload.email).strip().lower()
        user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        email = f"teacher-{secrets.token_hex(12)}@accounts.mychangliapp.cn"
        user = User(email=email, display_name=display_name, password_hash=hash_password(payload.password))
        db.add(user)
        db.flush()
    else:
        existing = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user.id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="该教师已经在当前机构")
        if not user.is_active:
            raise HTTPException(status_code=409, detail="该教师账号已停用")
        user.display_name = display_name
    membership = OrganizationMember(organization_id=org_id, user_id=user.id, login_name=login_name, role=payload.role)
    db.add(membership)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="教师登录名称或账号已存在") from exc
    db.refresh(membership)
    return teacher_out(db, membership)


@app.get("/api/v1/subjects", response_model=list[SubjectOut], tags=["settings"])
def list_subjects(include_inactive: bool = Query(default=False), context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[Subject]:
    query = select(Subject).where(Subject.organization_id == org_id_from_context(context))
    if not include_inactive:
        query = query.where(Subject.active.is_(True))
    return db.scalars(query.order_by(Subject.name)).all()


@app.post("/api/v1/subjects", response_model=SubjectOut, status_code=201, tags=["settings"])
def create_subject(payload: SubjectCreate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> Subject:
    subject = Subject(organization_id=org_id_from_context(context), name=payload.name.strip())
    if not subject.name:
        raise HTTPException(status_code=422, detail="科目名称不能为空")
    db.add(subject)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该科目已经存在") from exc
    db.refresh(subject)
    return subject


@app.patch("/api/v1/subjects/{subject_id}", response_model=SubjectOut, tags=["settings"])
def update_subject(subject_id: str, payload: SubjectUpdate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> Subject:
    subject = db.scalar(select(Subject).where(Subject.id == subject_id, Subject.organization_id == org_id_from_context(context)))
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    if payload.name is not None:
        subject.name = payload.name.strip()
    if payload.active is not None:
        subject.active = payload.active
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该科目已经存在") from exc
    db.refresh(subject)
    return subject


@app.get("/api/v1/time-slots", response_model=list[TimeSlotOut], tags=["settings"])
def list_time_slots(include_inactive: bool = Query(default=False), context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[TimeSlot]:
    query = select(TimeSlot).where(TimeSlot.organization_id == org_id_from_context(context))
    if not include_inactive:
        query = query.where(TimeSlot.active.is_(True))
    return db.scalars(query.order_by(TimeSlot.slot_code)).all()


@app.post("/api/v1/time-slots", response_model=TimeSlotOut, status_code=201, tags=["settings"])
def create_time_slot(payload: TimeSlotCreate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> TimeSlot:
    slot = TimeSlot(organization_id=org_id_from_context(context), **payload.model_dump())
    db.add(slot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="时段编码已经存在") from exc
    db.refresh(slot)
    return slot


@app.patch("/api/v1/time-slots/{time_slot_id}", response_model=TimeSlotOut, tags=["settings"])
def update_time_slot(time_slot_id: str, payload: TimeSlotUpdate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> TimeSlot:
    slot = db.scalar(select(TimeSlot).where(TimeSlot.id == time_slot_id, TimeSlot.organization_id == org_id_from_context(context)))
    if slot is None:
        raise HTTPException(status_code=404, detail="Time slot not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(slot, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="时段编码已经存在") from exc
    db.refresh(slot)
    return slot


@app.get("/api/v1/course-days", response_model=list[CourseDayOut], tags=["settings"])
def list_course_days(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[CourseDay]:
    return db.scalars(select(CourseDay).where(CourseDay.organization_id == org_id_from_context(context)).order_by(CourseDay.weekday)).all()


@app.post("/api/v1/course-days", response_model=CourseDayOut, status_code=201, tags=["settings"])
def create_course_day(payload: CourseDayCreate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> CourseDay:
    day = CourseDay(organization_id=org_id_from_context(context), **payload.model_dump())
    db.add(day)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该上课日已经配置") from exc
    db.refresh(day)
    return day


@app.patch("/api/v1/course-days/{weekday}", response_model=CourseDayOut, tags=["settings"])
def update_course_day(weekday: int, payload: CourseDayUpdate, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> CourseDay:
    day = db.scalar(select(CourseDay).where(CourseDay.organization_id == org_id_from_context(context), CourseDay.weekday == weekday))
    if day is None:
        raise HTTPException(status_code=404, detail="Course day not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(day, field, value)
    db.commit()
    db.refresh(day)
    return day


@app.get("/api/v1/classes", response_model=list[ClassOut], tags=["classes"])
def list_classes(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    classes = db.scalars(
        scoped_classes_query(context)
        .options(selectinload(ClassModel.teacher_membership).selectinload(OrganizationMember.user), selectinload(ClassModel.time_slot))
        .order_by(ClassModel.status, ClassModel.name)
    ).all()
    return [class_out(db, class_model) for class_model in classes]


@app.get("/api/v1/classes/{class_id}/sessions", response_model=list[ScannerAssessmentOut], tags=["scanner"])
def list_scannable_sessions(
    class_id: str,
    status: SessionStatus | None = Query(default=None),
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    query = (
        select(AssessmentSession)
        .options(selectinload(AssessmentSession.class_model))
        .where(
            AssessmentSession.organization_id == org_id_from_context(context),
            AssessmentSession.class_id == class_model.id,
        )
    )
    if status is not None:
        query = query.where(AssessmentSession.status == status)
    if status is None:
        query = query.where(AssessmentSession.status.in_([SessionStatus.ACTIVE, SessionStatus.CLOSED]))
    sessions = db.scalars(query.order_by(AssessmentSession.created_at.desc())).all()
    return [scanner_assessment_out(db, session) for session in sessions]


@app.post("/api/v1/classes", response_model=ClassOut, status_code=201, tags=["classes"])
def create_class(payload: ClassCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    # New Web clients always choose a teacher. For legacy callers that omit it,
    # keep the class owned by the creating organization member instead of
    # creating an unassigned class that cannot be managed by teacher scope.
    teacher_id = payload.teacher_id or context[1].id
    teacher, slot = class_metadata_or_422(
        db,
        org_id,
        teacher_id=teacher_id,
        school_stage=payload.school_stage,
        day_of_week=payload.day_of_week,
        time_slot_id=payload.time_slot_id,
    )
    class_model = ClassModel(
        organization_id=org_id,
        name=payload.name.strip(),
        teacher_id=teacher_id,
        school_stage=payload.school_stage,
        grade=payload.grade.strip() if payload.grade else None,
        day_of_week=payload.day_of_week,
        time_slot_id=payload.time_slot_id,
    )
    class_model.teacher_membership = teacher
    class_model.time_slot = slot
    if not class_model.name:
        raise HTTPException(status_code=422, detail="Class name is required")
    db.add(class_model)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A class with this name already exists") from exc
    db.refresh(class_model)
    return class_out(db, class_model)


@app.get("/api/v1/classes/{class_id}", response_model=ClassDetailOut, tags=["classes"])
def get_class(class_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    students = db.scalars(
        select(Student)
        .join(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_id, ClassEnrollment.left_at.is_(None))
        .order_by(Student.name, Student.student_code)
    ).all()
    return {**class_out(db, class_model), "students": students}


@app.get("/api/v1/classes/{class_id}/students", response_model=list[StudentOut], tags=["classes"])
def list_class_students(class_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[Student]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    return db.scalars(
        select(Student)
        .join(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_id, ClassEnrollment.left_at.is_(None))
        .order_by(Student.name, Student.student_code)
    ).all()


@app.patch("/api/v1/classes/{class_id}", response_model=ClassOut, tags=["classes"])
def update_class(class_id: str, payload: ClassUpdate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    if payload.name is not None:
        class_model.name = payload.name.strip()
    values = payload.model_dump(exclude_unset=True)
    next_teacher_id = values.get("teacher_id", class_model.teacher_id)
    next_stage = values.get("school_stage", class_model.school_stage)
    next_day = values.get("day_of_week", class_model.day_of_week)
    next_slot_id = values.get("time_slot_id", class_model.time_slot_id)
    teacher, slot = class_metadata_or_422(
        db,
        class_model.organization_id,
        teacher_id=next_teacher_id,
        school_stage=next_stage,
        day_of_week=next_day,
        time_slot_id=next_slot_id,
    )
    class_model.teacher_id = next_teacher_id
    class_model.teacher_membership = teacher
    class_model.school_stage = next_stage
    class_model.grade = values.get("grade", class_model.grade)
    class_model.day_of_week = next_day
    class_model.time_slot_id = next_slot_id
    class_model.time_slot = slot
    if payload.status is not None:
        class_model.status = payload.status
    db.commit()
    db.refresh(class_model)
    return class_out(db, class_model)


@app.post("/api/v1/classes/{class_id}/students", response_model=list[StudentOut], tags=["classes"])
def bulk_add_students(class_id: str, payload: BulkStudentCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[Student]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    org_id = org_id_from_context(context)
    result: list[Student] = []
    for item in payload.students:
        name = item.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="学生姓名不能为空")
        student = db.scalar(
            select(Student).where(
                Student.organization_id == org_id,
                Student.name == name,
                Student.status == StudentStatus.ACTIVE,
            ).order_by(Student.created_at)
        )
        if student is None:
            student = Student(organization_id=org_id, student_code=next_student_code(db, org_id), name=name)
            db.add(student)
            db.flush()
            issue_student_qr(db, student)
        else:
            student.status = StudentStatus.ACTIVE
        current = active_enrollment(db, class_id, student.id)
        if current is None:
            db.add(ClassEnrollment(class_id=class_id, student_id=student.id))
        result.append(student)
    db.commit()
    return result


@app.post("/api/v1/classes/{class_id}/students/{student_id}", response_model=StudentOut, tags=["classes"])
def add_student_to_class(
    class_id: str,
    student_id: str,
    payload: AddStudentToClass,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Student:
    org_id = org_id_from_context(context)
    class_model = class_or_404(db, class_id, org_id)
    ensure_class_access(class_model, context)
    student = student_or_404(db, student_id, org_id)
    if student.status != StudentStatus.ACTIVE:
        if not is_admin(context):
            raise HTTPException(status_code=409, detail="归档学生不能加入班级")
        student.status = StudentStatus.ACTIVE
    current = active_enrollment(db, class_id, student_id)
    if current:
        return student
    other = db.scalar(
        select(ClassEnrollment).where(
            ClassEnrollment.student_id == student_id,
            ClassEnrollment.left_at.is_(None),
            ClassEnrollment.class_id != class_id,
        )
    )
    if other and not payload.move_existing:
        raise HTTPException(status_code=409, detail="Student is enrolled in another class; confirm move_existing=true")
    if other:
        other.left_at = now_utc()
    db.add(ClassEnrollment(class_id=class_id, student_id=student_id))
    db.commit()
    return student


@app.post("/api/v1/classes/{class_id}/students/{student_id}/remove", response_model=MessageOut, tags=["classes"])
def remove_student_from_class(class_id: str, student_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, str]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    student_or_404(db, student_id, org_id_from_context(context))
    enrollment = active_enrollment(db, class_id, student_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Active enrollment not found")
    enrollment.left_at = now_utc()
    db.commit()
    return {"message": "Student removed from class; student record and history were retained"}


@app.post("/api/v1/classes/{class_id}/student-memberships", response_model=list[StudentOut], tags=["classes"])
def bulk_attach_students(
    class_id: str,
    payload: BulkAttachStudents,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[Student]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    result: list[Student] = []
    for student_id in dict.fromkeys(payload.student_ids):
        student = student_or_404(db, student_id, org_id_from_context(context))
        if student.status != StudentStatus.ACTIVE:
            raise HTTPException(status_code=409, detail=f"学生 {student.name} 已归档，不能加入班级")
        current = active_enrollment(db, class_id, student.id)
        if current is None:
            db.add(ClassEnrollment(class_id=class_id, student_id=student.id))
        result.append(student)
    db.commit()
    return result


@app.post("/api/v1/students/{student_id}/transfer", response_model=StudentOut, tags=["students"])
def transfer_student(
    student_id: str,
    payload: TransferStudent,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Student:
    org_id = org_id_from_context(context)
    student = student_or_404(db, student_id, org_id)
    target = class_or_404(db, payload.target_class_id, org_id)
    ensure_class_access(target, context)
    if target.status != ClassStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="不能转入已归档班级")
    source = None
    if payload.from_class_id:
        source = class_or_404(db, payload.from_class_id, org_id)
        ensure_class_access(source, context)
        source_enrollment = active_enrollment(db, source.id, student.id)
        if source_enrollment is None:
            raise HTTPException(status_code=404, detail="学生不在指定的原班级")
        source_enrollment.left_at = now_utc()
    else:
        source_enrollment = db.scalar(
            select(ClassEnrollment)
            .join(ClassModel)
            .where(
                ClassEnrollment.student_id == student.id,
                ClassEnrollment.left_at.is_(None),
                ClassEnrollment.class_id != target.id,
                ClassModel.organization_id == org_id,
            ).order_by(ClassEnrollment.joined_at)
        )
        if source_enrollment is not None:
            source = class_or_404(db, source_enrollment.class_id, org_id)
            ensure_class_access(source, context)
            source_enrollment.left_at = now_utc()
    if active_enrollment(db, target.id, student.id) is None:
        db.add(ClassEnrollment(class_id=target.id, student_id=student.id))
    db.commit()
    return student


@app.get("/api/v1/students", response_model=list[StudentOut], tags=["students"])
def list_students(
    search: str | None = Query(default=None, max_length=120),
    class_id: str | None = Query(default=None),
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[Student]:
    org_id = org_id_from_context(context)
    if class_id:
        target_class = class_or_404(db, class_id, org_id)
        ensure_class_access(target_class, context)
    query = select(Student).where(Student.organization_id == org_id)
    if context[1].role == MemberRole.TEACHER and not class_id:
        query = query.join(ClassEnrollment).join(ClassModel).where(
            ClassEnrollment.left_at.is_(None),
            ClassModel.teacher_id == context[1].id,
        ).distinct()
    if search:
        like = f"%{search.strip()}%"
        query = query.where((Student.name.ilike(like)) | (Student.student_code.ilike(like)))
    return db.scalars(query.order_by(Student.name, Student.student_code)).all()


@app.post("/api/v1/students", response_model=StudentOut, status_code=201, tags=["students"])
def create_student(payload: StudentCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> Student:
    org_id = org_id_from_context(context)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="学生姓名不能为空")
    student = Student(
        organization_id=org_id,
        student_code=next_student_code(db, org_id),
        name=name,
        school_stage=payload.school_stage,
        gender=payload.gender.strip() if payload.gender else None,
        phone=payload.phone.strip() if payload.phone else None,
        parent_phone=payload.parent_phone.strip() if payload.parent_phone else None,
        remark=payload.remark.strip() if payload.remark else None,
    )
    db.add(student)
    db.flush()
    issue_student_qr(db, student)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student code already exists in this organization") from exc
    db.refresh(student)
    return student


@app.patch("/api/v1/students/{student_id}", response_model=StudentOut, tags=["students"])
def update_student(student_id: str, payload: StudentUpdate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> Student:
    student = student_or_404(db, student_id, org_id_from_context(context))
    if payload.status is not None and not is_admin(context):
        raise HTTPException(status_code=403, detail="只有机构管理员可以归档或恢复学生")
    for field in ("name", "school_stage", "gender", "phone", "parent_phone", "remark", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(student, field, value.strip() if isinstance(value, str) else value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student code already exists in this organization") from exc
    db.refresh(student)
    return student


def cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_school_stage(value: Any) -> SchoolStage | None:
    text = cell_text(value)
    if not text:
        return None
    aliases = {
        "小学": SchoolStage.PRIMARY,
        "primary": SchoolStage.PRIMARY,
        "初中": SchoolStage.MIDDLE,
        "middle": SchoolStage.MIDDLE,
        "高中": SchoolStage.HIGH,
        "high": SchoolStage.HIGH,
    }
    return aliases.get(text.lower(), SchoolStage(text.upper()) if text.upper() in SchoolStage.__members__ else None)


def parse_student_import_file(content: bytes, filename: str) -> list[dict[str, Any]]:
    if not content:
        raise HTTPException(status_code=422, detail="导入文件为空")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="导入文件不能超过 10 MB")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    rows: list[list[Any]] = []
    try:
        if suffix in {"xlsx", "xlsm"}:
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            worksheet = workbook.active
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            workbook.close()
        elif suffix == "csv":
            decoded = content.decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(decoded)))
        else:
            raise HTTPException(status_code=422, detail="仅支持 .xlsx、.xlsm 或 .csv 文件")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="文件解析失败，请下载模板后重新填写") from exc

    non_empty_rows = [row for row in rows if any(cell_text(value) for value in row)]
    if not non_empty_rows:
        raise HTTPException(status_code=422, detail="导入文件没有可读取的数据")
    header = [cell_text(value).lower() for value in non_empty_rows[0]]
    name_headers = {"姓名", "name", "student_name", "学生姓名"}
    stage_headers = {"学段", "school_stage", "stage"}
    remark_headers = {"备注", "remark", "说明"}
    has_header = any(value in name_headers | stage_headers | remark_headers for value in header)
    if has_header:
        name_index = next((index for index, value in enumerate(header) if value in name_headers), 0)
        stage_index = next((index for index, value in enumerate(header) if value in stage_headers), None)
        remark_index = next((index for index, value in enumerate(header) if value in remark_headers), None)
        data_rows = non_empty_rows[1:]
        start_row = 2
    else:
        name_index, stage_index, remark_index = 0, 1, 2
        data_rows = non_empty_rows
        start_row = 1
    if len(data_rows) > 500:
        raise HTTPException(status_code=422, detail="单次最多导入 500 名学生")
    result = []
    for offset, row in enumerate(data_rows):
        name = cell_text(row[name_index]) if name_index < len(row) else ""
        stage_value = row[stage_index] if stage_index is not None and stage_index < len(row) else None
        stage = parse_school_stage(stage_value)
        result.append(
            {
                "row_number": start_row + offset,
                "name": name,
                "school_stage": stage,
                "school_stage_raw": cell_text(stage_value),
                "remark": cell_text(row[remark_index]) if remark_index is not None and remark_index < len(row) else None,
            }
        )
    return result


def import_match(db: Session, organization_id: str, name: str) -> list[dict[str, Any]]:
    candidates = db.scalars(
        select(Student).where(Student.organization_id == organization_id, Student.name == name).order_by(Student.student_code)
    ).all()
    matches = []
    for student in candidates:
        classes = db.scalars(
            select(ClassModel.name)
            .join(ClassEnrollment)
            .where(
                ClassEnrollment.class_id == ClassModel.id,
                ClassEnrollment.student_id == student.id,
                ClassEnrollment.left_at.is_(None),
            ).order_by(ClassModel.name)
        ).all()
        matches.append(
            StudentImportMatch(
                id=student.id,
                student_code=student.student_code,
                name=student.name,
                school_stage=student.school_stage,
                current_classes=classes,
            ).model_dump(mode="json")
        )
    return matches


@app.post("/api/v1/students/import/preview", response_model=StudentImportPreviewOut, tags=["students"])
async def preview_student_import(
    file: UploadFile = File(...),
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    raw_rows = parse_student_import_file(content, file.filename or "students.xlsx")
    organization_id = org_id_from_context(context)
    seen_names: set[str] = set()
    items: list[dict[str, Any]] = []
    existing_count = prepare_create_count = duplicate_count = error_count = 0
    for raw in raw_rows:
        name = raw["name"]
        item = {
            "row_number": raw["row_number"],
            "name": name,
            "school_stage": raw["school_stage"],
            "remark": raw["remark"] or None,
            "status": "",
            "default_action": "SKIP",
            "matches": [],
            "error": None,
        }
        if not name:
            item.update(status="EMPTY_NAME", error="姓名不能为空")
            error_count += 1
        elif raw["school_stage_raw"] and raw["school_stage"] is None:
            item.update(status="INVALID_STAGE", error="学段只能填写小学、初中或高中")
            error_count += 1
        elif name in seen_names:
            item.update(status="DUPLICATE_INPUT", error="文件内出现重复姓名，请确认是否为同名学生")
            duplicate_count += 1
        else:
            seen_names.add(name)
            matches = import_match(db, organization_id, name)
            item["matches"] = matches
            if len(matches) == 0:
                item.update(status="PREPARE_CREATE", default_action="CREATE")
                prepare_create_count += 1
            elif len(matches) == 1:
                item.update(status="EXISTING_SUSPECT", default_action="USE_EXISTING")
                existing_count += 1
            else:
                item.update(status="DUPLICATE_IN_ORG", default_action="SKIP", error="机构内存在多个同名学生，必须选择具体学生或新建")
                duplicate_count += 1
        items.append(item)
    return {
        "file_name": file.filename or "students.xlsx",
        "total_rows": len(raw_rows),
        "existing_count": existing_count,
        "prepare_create_count": prepare_create_count,
        "duplicate_count": duplicate_count,
        "error_count": error_count,
        "items": items,
    }


@app.post("/api/v1/students/import/confirm", response_model=StudentImportResult, tags=["students"])
def confirm_student_import(
    payload: StudentImportConfirm,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    class_model = None
    if payload.class_id:
        class_model = class_or_404(db, payload.class_id, org_id)
        ensure_class_access(class_model, context)
        if class_model.status != ClassStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="不能导入到已归档班级")
    created_count = reused_count = skipped_count = membership_added_count = 0
    students: list[Student] = []
    for item in payload.items:
        if item.action == "SKIP":
            skipped_count += 1
            continue
        if item.action == "USE_EXISTING":
            if not item.student_id:
                raise HTTPException(status_code=422, detail=f"第 {item.row_number} 行必须选择已有学生")
            student = student_or_404(db, item.student_id, org_id)
            if student.name != item.name:
                raise HTTPException(status_code=422, detail=f"第 {item.row_number} 行所选学生与姓名不匹配")
            reused_count += 1
        else:
            student = Student(
                organization_id=org_id,
                student_code=next_student_code(db, org_id),
                name=item.name.strip(),
                school_stage=item.school_stage,
                remark=item.remark.strip() if item.remark else None,
            )
            db.add(student)
            db.flush()
            issue_student_qr(db, student)
            created_count += 1
        if class_model and student.status != StudentStatus.ACTIVE:
            raise HTTPException(status_code=409, detail=f"学生 {student.name} 已归档，不能直接加入班级")
        if class_model and active_enrollment(db, class_model.id, student.id) is None:
            db.add(ClassEnrollment(class_id=class_model.id, student_id=student.id))
            membership_added_count += 1
        students.append(student)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="导入确认时发生数据冲突，请重新预览") from exc
    return {
        "created_count": created_count,
        "reused_count": reused_count,
        "skipped_count": skipped_count,
        "membership_added_count": membership_added_count,
        "students": students,
    }


@app.post("/api/v1/students/{student_id}/qr-token", response_model=QRTokenOut, tags=["students"])
def issue_student_qr_token(student_id: str, context: tuple[User, OrganizationMember] = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, Any]:
    student = student_or_404(db, student_id, org_id_from_context(context))
    token, version = issue_student_qr(db, student)
    db.commit()
    return {"student_id": student.id, "token": token, "version": version, "status": QRCodeStatus.ACTIVE}


@app.post("/api/v1/sessions", response_model=SessionOut, status_code=201, tags=["sessions"])
def create_session(payload: SessionCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    class_model = class_or_404(db, payload.class_id, org_id)
    ensure_class_access(class_model, context)
    if class_model.status != ClassStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Archived class cannot start a new session")
    subject = None
    if payload.subject_id:
        subject = db.scalar(select(Subject).where(Subject.id == payload.subject_id, Subject.organization_id == org_id, Subject.active.is_(True)))
        if subject is None:
            raise HTTPException(status_code=422, detail="科目不属于当前机构或已停用")
    session = AssessmentSession(
        organization_id=org_id,
        class_id=class_model.id,
        created_by=context[0].id,
        subject_id=subject.id if subject else None,
        exam_type=payload.exam_type,
        name=payload.name.strip() if payload.name and payload.name.strip() else None,
        question_count=payload.question_count,
        total_score=sum(answer.points for answer in payload.answer_keys),
    )
    active_students = db.scalars(
        select(Student)
        .join(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_model.id, ClassEnrollment.left_at.is_(None), Student.status == StudentStatus.ACTIVE)
        .order_by(Student.name, Student.student_code)
    ).all()
    for student in active_students:
        session.participants.append(SessionParticipant(student_id=student.id, student_code=student.student_code, student_name=student.name))
    for answer in payload.answer_keys:
        question = Question(question_no=answer.question_no, question_type=answer.question_type)
        question.points = answer.points
        question.answer_key = AnswerKey(value=answer.value)
        session.questions.append(question)
    db.add(session)
    db.commit()
    return session_out(session_or_404(db, session.id, org_id))


@app.get("/api/v1/sessions", response_model=list[SessionOut], tags=["sessions"])
def list_sessions(status: SessionStatus | None = Query(default=None), context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(AssessmentSession)
    if status is not None:
        query = query.where(AssessmentSession.status == status)
    sessions = db.scalars(
        query
        .options(
            selectinload(AssessmentSession.class_model).selectinload(ClassModel.teacher_membership).selectinload(OrganizationMember.user),
            selectinload(AssessmentSession.class_model).selectinload(ClassModel.time_slot),
            selectinload(AssessmentSession.subject),
            selectinload(AssessmentSession.questions).selectinload(Question.answer_key),
        )
        .where(AssessmentSession.organization_id == org_id_from_context(context))
        .where(
            AssessmentSession.class_id.in_(
                select(ClassModel.id).where(
                    ClassModel.organization_id == org_id_from_context(context),
                    *([ClassModel.teacher_id == context[1].id] if context[1].role == MemberRole.TEACHER else []),
                )
            )
        )
        .order_by(AssessmentSession.created_at.desc())
    ).all()
    return [session_out(session) for session in sessions]


@app.get("/api/v1/sessions/{session_id}", response_model=SessionOut, tags=["sessions"])
def get_session(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    return session_out(session)


@app.post("/api/v1/sessions/{session_id}/start", response_model=SessionOut, tags=["sessions"])
def start_session(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    if session.status != SessionStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only a DRAFT session can be started")
    session.status = SessionStatus.ACTIVE
    session.started_at = now_utc()
    db.commit()
    event_broker.publish(session.id, {"kind": "session.started", "session_id": session.id})
    return session_out(session_or_404(db, session.id, session.organization_id))


@app.post("/api/v1/sessions/{session_id}/close", response_model=SessionOut, tags=["sessions"])
def close_session(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only an ACTIVE session can be closed")
    session.status = SessionStatus.CLOSED
    session.ended_at = now_utc()
    db.commit()
    event_broker.publish(session.id, {"kind": "session.closed", "session_id": session.id})
    return session_out(session_or_404(db, session.id, session.organization_id))


@app.post("/api/v1/sessions/{session_id}/archive", response_model=SessionOut, tags=["sessions"])
def archive_session(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    if session.status != SessionStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Only a CLOSED session can be archived")
    session.status = SessionStatus.ARCHIVED
    session.archived_at = now_utc()
    db.commit()
    return session_out(session_or_404(db, session.id, session.organization_id))


@app.post("/api/v1/sessions/{session_id}/scan-session", response_model=ScannerSessionOut, tags=["scanner"])
def open_scan_session(
    session_id: str,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    if session.status not in {SessionStatus.ACTIVE, SessionStatus.CLOSED}:
        raise HTTPException(status_code=409, detail="草稿或已归档考试不能扫描")
    return scanner_session_out(get_or_create_scanner_session(db, session, context))


@app.get("/api/v1/sessions/{session_id}/scan-session", response_model=ScannerSessionOut, tags=["scanner"])
def get_scan_session(
    session_id: str,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    scanner_session = db.scalar(
        select(ScannerSession)
        .options(selectinload(ScannerSession.opened_by_user))
        .where(
            ScannerSession.organization_id == org_id_from_context(context),
            ScannerSession.assessment_session_id == session.id,
            ScannerSession.opened_by_member_id == context[1].id,
        )
    )
    if scanner_session is None:
        raise HTTPException(status_code=404, detail="Scanner session not found")
    return scanner_session_out(scanner_session_or_404(db, scanner_session.id, org_id_from_context(context)))


@app.post("/api/v1/scans", response_model=ScanOut, status_code=201, tags=["scanner"])
def upload_scan(
    session_id: str = Form(...),
    scan_session_id: str = Form(...),
    page_token: str = Form(..., min_length=1, max_length=256),
    client_capture_id: str = Form(..., min_length=1, max_length=64),
    image: UploadFile = File(...),
    page_type: str = Form(default="ANSWER_SHEET", min_length=1, max_length=80),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    try:
        canonical_capture_id = str(UUID(client_capture_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="client_capture_id 必须是 UUID") from exc
    if idempotency_key is None or idempotency_key.strip().lower() != canonical_capture_id:
        raise HTTPException(status_code=400, detail="Idempotency-Key 必须与 client_capture_id 一致")
    from .answer_sheets import parse_page_token, PAGE_TYPES
    normalized_page_token = page_token.strip()
    card_identity = parse_page_token(normalized_page_token, settings.qr_signing_secret or settings.jwt_secret)
    if normalized_page_token.startswith("CS1.") and card_identity is None:
        raise HTTPException(422, "答题卡二维码签名无效，请重新下载")
    page_token_hash = hashlib.sha256(normalized_page_token.encode("utf-8")).hexdigest()

    session = session_or_404(db, session_id, org_id)
    ensure_session_access(session, context)
    if session.status not in {SessionStatus.ACTIVE, SessionStatus.CLOSED}:
        raise HTTPException(status_code=409, detail="草稿或已归档考试不能接收扫描")
    scanner_session = scanner_session_or_404(db, scan_session_id, org_id)
    if scanner_session.assessment_session_id != session.id:
        raise HTTPException(status_code=409, detail="扫描会话与测试不匹配")
    if scanner_session.opened_by_member_id != context[1].id:
        raise HTTPException(status_code=403, detail="当前账号不能使用此扫描会话")
    if scanner_session.status != ScannerSessionStatus.OPEN:
        raise HTTPException(status_code=409, detail="扫描会话已关闭")

    existing = db.scalar(
        select(ScanRecord)
        .options(
            selectinload(ScanRecord.assessment_session).selectinload(AssessmentSession.class_model),
            selectinload(ScanRecord.student),
        )
        .where(ScanRecord.organization_id == org_id, ScanRecord.client_capture_id == canonical_capture_id)
    )
    if existing is not None:
        if (
            existing.assessment_session_id != session.id
            or existing.scanner_session_id != scanner_session.id
            or existing.page_token_hash != page_token_hash
        ):
            raise HTTPException(status_code=409, detail="client_capture_id 已绑定其他扫描请求")
        return scan_out(existing)

    scan_id = str(uuid4())
    destination = scan_storage_root() / org_id / session.id / f"{scan_id}.jpg"
    image_sha256, image_size = persist_scan_image(image, destination)
    student = None
    qr_code = db.scalar(
        select(StudentQRCode)
        .options(selectinload(StudentQRCode.student))
        .where(StudentQRCode.token_hash == page_token_hash, StudentQRCode.status == QRCodeStatus.ACTIVE)
    )
    if card_identity:
        qr_code = db.scalar(select(StudentQRCode).options(selectinload(StudentQRCode.student)).where(StudentQRCode.id == card_identity[0], StudentQRCode.status == QRCodeStatus.ACTIVE))
        page_type = f"{PAGE_TYPES[card_identity[1]]}:{card_identity[2]}"
    elif page_type.startswith("A5-"):
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "页面标识无效")
    if qr_code and qr_code.student.organization_id == org_id:
        participant = db.scalar(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session.id,
                SessionParticipant.student_id == qr_code.student_id,
            )
        )
        if participant is not None:
            student = qr_code.student

    if card_identity and student is None:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "答题卡已失效或学生不在本场考试名单中")
    scan = ScanRecord(
        id=scan_id,
        organization_id=org_id,
        assessment_session_id=session.id,
        scanner_session_id=scanner_session.id,
        uploaded_by_user_id=context[0].id,
        uploaded_by_member_id=context[1].id,
        client_capture_id=canonical_capture_id,
        page_token_hash=page_token_hash,
        image_path=str(destination),
        image_sha256=image_sha256,
        image_size_bytes=image_size,
        page_type=page_type.strip() or "ANSWER_SHEET",
        student_id=student.id if student else None,
        status=ScanStatus.PROCESSING,
        request_id=(request_id or str(uuid4())).strip()[:120],
    )
    db.add(scan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        existing = db.scalar(
            select(ScanRecord)
            .options(
                selectinload(ScanRecord.assessment_session).selectinload(AssessmentSession.class_model),
                selectinload(ScanRecord.student),
            )
            .where(ScanRecord.organization_id == org_id, ScanRecord.client_capture_id == canonical_capture_id)
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="扫描回执创建冲突，请重试") from exc
        if (
            existing.assessment_session_id != session.id
            or existing.scanner_session_id != scanner_session.id
            or existing.page_token_hash != page_token_hash
        ):
            raise HTTPException(status_code=409, detail="client_capture_id 已绑定其他扫描请求") from exc
        return scan_out(existing)
    db.refresh(scan)
    event_broker.publish(
        session.id,
        {"kind": "scan.received", "session_id": session.id, "scan_id": scan.id, "status": scan.status},
    )
    return scan_out(scan)


@app.get("/api/v1/scans/{server_scan_id}", response_model=ScanOut, tags=["scanner"])
def get_scan_status(
    server_scan_id: str,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    scan = db.scalar(
        select(ScanRecord)
        .options(
            selectinload(ScanRecord.assessment_session).selectinload(AssessmentSession.class_model),
            selectinload(ScanRecord.student),
        )
        .where(ScanRecord.id == server_scan_id, ScanRecord.organization_id == org_id_from_context(context))
    )
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    ensure_session_access(scan.assessment_session, context)
    return scan_out(scan)


@app.post("/api/v1/sessions/{session_id}/submissions", response_model=SubmissionOut, tags=["submissions"])
def submit_answers(session_id: str, payload: SubmissionCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    submission, is_update = create_or_update_submission(db, session, payload)
    event_broker.publish(session.id, {"kind": "submission.updated", "session_id": session.id, "student_id": submission.student_id})
    return submission_out(submission, session, is_update)


@app.post("/api/v1/sessions/{session_id}/recognition-results", response_model=SubmissionOut, tags=["submissions"])
def submit_recognition_result(session_id: str, payload: RecognitionResultCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    student = None
    if payload.student_id:
        student = student_or_404(db, payload.student_id, org_id)
    elif payload.student_qr_token:
        token_hash = hashlib.sha256(payload.student_qr_token.encode("utf-8")).hexdigest()
        qr = db.scalar(
            select(StudentQRCode)
            .options(selectinload(StudentQRCode.student))
            .where(StudentQRCode.token_hash == token_hash, StudentQRCode.status == QRCodeStatus.ACTIVE)
        )
        if qr and qr.student.organization_id == org_id:
            student = qr.student
    else:
        student = db.scalar(select(Student).where(Student.organization_id == org_id, Student.student_code == payload.student_code))
    if student is None:
        raise HTTPException(status_code=422, detail="Recognition result identity does not match a student")
    session = session_or_404(db, session_id, org_id)
    ensure_session_access(session, context)
    scan = None
    if payload.scan_id:
        scan = db.scalar(
            select(ScanRecord).where(
                ScanRecord.id == payload.scan_id,
                ScanRecord.organization_id == org_id,
                ScanRecord.assessment_session_id == session.id,
            )
        )
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found in this test")
    submission_payload = SubmissionCreate(
        student_id=student.id,
        answers=payload.answers,
        source=SubmissionSource.RECOGNITION,
        review_required=payload.review_required or (payload.confidence is not None and payload.confidence < 0.8),
        idempotency_key=payload.idempotency_key,
        page_type=payload.page_type,
        confidence=payload.confidence,
    )
    submission, is_update = create_or_update_submission(db, session, submission_payload)
    if scan is not None:
        scan.student_id = student.id
        scan.page_type = payload.page_type
        scan.status = ScanStatus.REVIEW_REQUIRED if submission.status == SubmissionStatus.REVIEW_REQUIRED else ScanStatus.SUCCESS
        scan.failure_reason = None
        scan.processed_at = now_utc()
        db.commit()
    event_broker.publish(session.id, {"kind": "submission.updated", "session_id": session.id, "student_id": submission.student_id})
    return submission_out(submission, session, is_update)


@app.get("/api/v1/sessions/{session_id}/submissions", response_model=list[SubmissionOut], tags=["submissions"])
def list_submissions(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    submissions = db.scalars(select(Submission).options(selectinload(Submission.answers)).where(Submission.session_id == session.id)).all()
    return [submission_out(submission, session, False) for submission in submissions]


def build_results(db: Session, session: AssessmentSession) -> dict[str, Any]:
    submissions = db.scalars(
        select(Submission).options(selectinload(Submission.answers)).where(Submission.session_id == session.id)
    ).all()
    by_student = {submission.student_id: submission for submission in submissions}
    submitted_count = len(submissions)
    question_stats = []
    aggregate_correct = 0
    for question in session.questions:
        counts = {option: 0 for option in "ABCD"}
        names_by_option = {option: [] for option in "ABCD"}
        correct_count = 0
        answered_count = 0
        for submission in submissions:
            answer = next((item for item in submission.answers if item.question_id == question.id), None)
            if answer is None:
                continue
            answered_count += 1
            if answer.value in counts:
                counts[answer.value] += 1
                participant = next((p for p in session.participants if p.student_id == submission.student_id), None)
                if participant:
                    names_by_option[answer.value].append(participant.student_name)
            if answer.is_correct:
                correct_count += 1
        aggregate_correct += correct_count
        question_stats.append(
            {
                "question_no": question.question_no,
                "question_type": question.question_type,
                "correct_answer": question.answer_key.value,
                "answered_count": answered_count,
                "submitted_count": submitted_count,
                "counts": counts,
                "correct_count": correct_count,
                "correct_rate": round((correct_count / submitted_count) * 100, 1) if submitted_count else 0,
                "students_by_option": names_by_option,
            }
        )
    students = []
    review_count = 0
    for participant in session.participants:
        submission = by_student.get(participant.student_id)
        if submission and submission.status == SubmissionStatus.REVIEW_REQUIRED:
            review_count += 1
        students.append(
            StudentLiveState(
                student_id=participant.student_id,
                student_code=participant.student_code,
                student_name=participant.student_name,
                status=(submission.status.value if submission else "PENDING"),
                submission_id=submission.id if submission else None,
                source=submission.source if submission else None,
                submitted_at=submission.submitted_at if submission else None,
                answers={answer.question_no: answer.value for answer in submission.answers} if submission else {},
                score=submission.score if submission and submission.score is not None else 0,
                correct_count=sum(1 for answer in submission.answers if answer.is_correct) if submission else 0,
            ).model_dump(mode="json")
        )
    average = round((aggregate_correct / (submitted_count * session.question_count)) * 100, 1) if submitted_count and session.question_count else 0
    return {
        "session": session_out(session),
        "participant_count": len(session.participants),
        "submitted_count": submitted_count,
        "pending_count": len(session.participants) - submitted_count,
        "review_required_count": review_count,
        "average_correct_rate": average,
        "questions": question_stats,
        "students": students,
    }


@app.get("/api/v1/sessions/{session_id}/results", response_model=ResultsOut, tags=["results"])
def results(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    return build_results(db, session)


def xlsx_response(filename: str, headers: list[str], rows: list[list[Any]]) -> Response:
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "数据"
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    worksheet.freeze_panes = "A2"
    for cell in worksheet[1]:
        font = copy(cell.font)
        font.bold = True
        cell.font = font
    output = io.BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/v1/students/import/template.xlsx", tags=["students"])
def export_student_import_template(context: tuple[User, OrganizationMember] = Depends(get_current_membership)) -> Response:
    return xlsx_response("学生名单模板.xlsx", ["姓名", "学段", "备注"], [["张三", "初中", ""]])


@app.get("/api/v1/students/export.xlsx", tags=["students"])
def export_students(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> Response:
    query = select(Student).where(Student.organization_id == org_id_from_context(context))
    if context[1].role == MemberRole.TEACHER:
        query = query.join(ClassEnrollment).join(ClassModel).where(ClassEnrollment.left_at.is_(None), ClassModel.teacher_id == context[1].id).distinct()
    students = db.scalars(query.order_by(Student.student_code)).all()
    enrollments = db.scalars(
        select(ClassEnrollment)
        .options(selectinload(ClassEnrollment.class_model).selectinload(ClassModel.teacher_membership).selectinload(OrganizationMember.user))
        .where(ClassEnrollment.left_at.is_(None), ClassEnrollment.student_id.in_([student.id for student in students]))
    ).all() if students else []
    by_student: dict[str, list[ClassEnrollment]] = {}
    for enrollment in enrollments:
        by_student.setdefault(enrollment.student_id, []).append(enrollment)
    rows = []
    for student in students:
        current = by_student.get(student.id, [])
        rows.append([
            student.student_code,
            student.name,
            SCHOOL_STAGE_LABELS[student.school_stage],
            student.status.value,
            "、".join(enrollment.class_model.name for enrollment in current),
            "、".join(
                enrollment.class_model.teacher_membership.user.display_name
                for enrollment in current
                if enrollment.class_model.teacher_membership
            ),
        ])
    return xlsx_response("机构学生库.xlsx", ["学生编号", "姓名", "学段", "状态", "当前班级", "教师"], rows)


@app.get("/api/v1/classes/{class_id}/export.xlsx", tags=["classes"])
def export_class(class_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> Response:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    ensure_class_access(class_model, context)
    students = db.scalars(
        select(Student)
        .join(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_id, ClassEnrollment.left_at.is_(None))
        .order_by(Student.student_code)
    ).all()
    teacher_name = class_model.teacher_membership.user.display_name if class_model.teacher_membership else ""
    rows = [[student.student_code, student.name, class_model.name, teacher_name] for student in students]
    return xlsx_response("班级学生名单.xlsx", ["学生编号", "姓名", "班级", "教师"], rows)


@app.get("/api/v1/sessions/{session_id}/exports/{report_type}.xlsx", tags=["results"])
def export_session_report(
    session_id: str,
    report_type: str,
    context: tuple[User, OrganizationMember] = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Response:
    session = session_or_404(db, session_id, org_id_from_context(context))
    ensure_session_access(session, context)
    result = build_results(db, session)
    if report_type == "score-sheet":
        ordered = sorted(result["students"], key=lambda student: (-student.get("score", 0), student["student_code"]))
        rows = []
        for rank, student in enumerate(ordered, start=1):
            rows.append([
                rank,
                student["student_code"],
                student["student_name"],
                student.get("score", 0),
                student.get("correct_count", 0),
                session.question_count,
                student["status"],
            ])
        return xlsx_response("成绩单.xlsx", ["排名", "学生编号", "姓名", "得分", "答对题数", "题目数", "状态"], rows)
    if report_type == "subscore":
        headers = ["学生编号", "姓名"] + [f"第 {question.question_no} 题" for question in session.questions] + ["总分"]
        rows = []
        for student in result["students"]:
            answers = student.get("answers", {})
            points = [
                question.points if answers.get(str(question.question_no)) == question.answer_key.value or answers.get(question.question_no) == question.answer_key.value else 0
                for question in session.questions
            ]
            rows.append([student["student_code"], student["student_name"], *points, student.get("score", 0)])
        return xlsx_response("小分表.xlsx", headers, rows)
    if report_type == "answer-stats":
        rows = [
            [
                question["question_no"],
                question["correct_answer"],
                question["counts"]["A"],
                question["counts"]["B"],
                question["counts"]["C"],
                question["counts"]["D"],
                question["answered_count"],
                question["correct_rate"],
            ]
            for question in result["questions"]
        ]
        return xlsx_response("答题统计.xlsx", ["题号", "正确答案", "A", "B", "C", "D", "已作答", "正确率"], rows)
    raise HTTPException(status_code=404, detail="Unknown report type")


@app.get("/api/v1/sessions/{session_id}/stream", tags=["realtime"])
def stream(
    session_id: str,
    request: Request,
    access_token: str | None = Query(default=None),
    credentials=Depends(bearer),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    token = access_token or (credentials.credentials if credentials else None)
    user = user_from_token(db, token)
    try:
        claims = decode_access_token(token or "")
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.id == claims["teacher_id"],
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == claims["organization_id"],
            OrganizationMember.organization.has(status=OrganizationStatus.ACTIVE),
        )
    )
    if membership is None or membership.organization_id != db.scalar(select(AssessmentSession.organization_id).where(AssessmentSession.id == session_id)):
        raise HTTPException(status_code=403, detail="Not a member of this session organization")
    session = session_or_404(db, session_id, membership.organization_id)
    ensure_session_access(session, (user, membership))
    subscriber = event_broker.subscribe(session_id)
    return StreamingResponse(
        event_broker.stream(session_id, subscriber),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


from .sheet_routes import register_sheet_routes
register_sheet_routes(app)

from .review_routes import register_review_routes
register_review_routes(app)
