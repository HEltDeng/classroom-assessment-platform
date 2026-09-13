from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db
from .dependencies import bearer, get_current_membership, get_current_user, user_from_token
from .models import (
    AnswerKey,
    AssessmentSession,
    ClassEnrollment,
    ClassModel,
    ClassStatus,
    MemberRole,
    Organization,
    OrganizationMember,
    OrganizationSettings,
    OrganizationStatus,
    Question,
    SessionParticipant,
    SessionStatus,
    Student,
    StudentAnswer,
    StudentStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
    User,
)
from .realtime import event_broker
from .schemas import (
    AddStudentToClass,
    BulkStudentCreate,
    ClassCreate,
    ClassDetailOut,
    ClassOut,
    ClassUpdate,
    LoginRequest,
    MeOut,
    MessageOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationSettingsUpdate,
    RecognitionResultCreate,
    ResultsOut,
    SessionCreate,
    SessionOut,
    StudentCreate,
    StudentLiveState,
    StudentOut,
    StudentUpdate,
    SubmissionCreate,
    SubmissionOut,
    TokenOut,
)
from .security import create_access_token, hash_password, verify_password


settings = get_settings()
settings.validate_runtime()

app = FastAPI(
    title="Classroom Assessment Platform API",
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


def org_id_from_context(context: tuple[User, OrganizationMember]) -> str:
    return context[1].organization_id


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
            selectinload(AssessmentSession.class_model),
            selectinload(AssessmentSession.questions).selectinload(Question.answer_key),
            selectinload(AssessmentSession.participants),
        )
        .where(AssessmentSession.id == session_id, AssessmentSession.organization_id == org_id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Assessment session not found")
    return session


def organization_out(organization: Organization) -> dict[str, Any]:
    return {
        "id": organization.id,
        "name": organization.name,
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
        "name": session.name,
        "question_count": session.question_count,
        "status": session.status,
        "created_at": session.created_at,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "questions": [
            {
                "id": question.id,
                "question_no": question.question_no,
                "question_type": question.question_type,
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


def create_or_update_submission(
    db: Session,
    session: AssessmentSession,
    payload: SubmissionCreate,
) -> tuple[Submission, bool]:
    if payload.source == SubmissionSource.MOCK and not settings.allow_dev_submission:
        raise HTTPException(status_code=403, detail="Development submission is disabled")
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only an ACTIVE session accepts submissions")
    participant = db.scalar(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session.id,
            SessionParticipant.student_id == payload.student_id,
        )
    )
    if participant is None:
        raise HTTPException(status_code=422, detail="Student is not a participant in this session")
    question_map = {question.question_no: question for question in session.questions}
    seen: set[int] = set()
    for answer in payload.answers:
        if answer.question_no in seen or answer.question_no not in question_map:
            raise HTTPException(status_code=422, detail="Answers must contain unique valid question numbers")
        seen.add(answer.question_no)
    existing = db.scalar(
        select(Submission)
        .options(selectinload(Submission.answers))
        .where(Submission.session_id == session.id, Submission.student_id == payload.student_id)
    )
    is_update = existing is not None
    submission = existing or Submission(session_id=session.id, student_id=payload.student_id)
    submission.status = SubmissionStatus.REVIEW_REQUIRED if payload.review_required else SubmissionStatus.SUBMITTED
    submission.source = payload.source
    submission.page_type = payload.page_type
    submission.confidence = payload.confidence
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
                is_correct=answer.value == question.answer_key.value,
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
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": user}


@app.get("/api/v1/me", response_model=MeOut, tags=["auth"])
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    memberships = db.scalars(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.organization).selectinload(Organization.settings))
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.created_at)
    ).all()
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "memberships": memberships}


@app.get("/api/v1/organizations", response_model=list[OrganizationOut], tags=["organizations"])
def list_organizations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    organizations = db.scalars(
        select(Organization)
        .join(OrganizationMember)
        .options(selectinload(Organization.settings))
        .where(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at)
    ).all()
    return [organization_out(organization) for organization in organizations]


@app.post("/api/v1/organizations", response_model=OrganizationOut, status_code=201, tags=["organizations"])
def create_organization(payload: OrganizationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = Organization(name=payload.name.strip())
    if not organization.name:
        raise HTTPException(status_code=422, detail="Organization name is required")
    organization.settings = OrganizationSettings(
        organization_name=payload.organization_name or organization.name,
        logo=payload.logo,
        student_code_label=payload.student_code_label,
    )
    organization.members.append(OrganizationMember(user_id=user.id, role=MemberRole.OWNER))
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization_out(organization)


@app.patch("/api/v1/organizations/{organization_id}/settings", response_model=OrganizationOut, tags=["organizations"])
def update_organization_settings(
    organization_id: str,
    payload: OrganizationSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    membership = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user.id))
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    organization = get_org(db, organization_id)
    organization.settings = organization.settings or OrganizationSettings(organization_id=organization.id)
    organization.settings.organization_name = payload.organization_name
    organization.settings.logo = payload.logo
    organization.settings.student_code_label = payload.student_code_label
    db.commit()
    db.refresh(organization)
    return organization_out(organization)


@app.get("/api/v1/classes", response_model=list[ClassOut], tags=["classes"])
def list_classes(context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    classes = db.scalars(
        select(ClassModel).where(ClassModel.organization_id == org_id_from_context(context)).order_by(ClassModel.status, ClassModel.name)
    ).all()
    return [class_out(db, class_model) for class_model in classes]


@app.post("/api/v1/classes", response_model=ClassOut, status_code=201, tags=["classes"])
def create_class(payload: ClassCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    class_model = ClassModel(organization_id=org_id_from_context(context), name=payload.name.strip())
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
    students = db.scalars(
        select(Student)
        .join(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_id, ClassEnrollment.left_at.is_(None))
        .order_by(Student.name, Student.student_code)
    ).all()
    return {**class_out(db, class_model), "students": students}


@app.get("/api/v1/classes/{class_id}/students", response_model=list[StudentOut], tags=["classes"])
def list_class_students(class_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[Student]:
    class_or_404(db, class_id, org_id_from_context(context))
    return db.scalars(
        select(Student)
        .join(ClassEnrollment)
        .where(ClassEnrollment.class_id == class_id, ClassEnrollment.left_at.is_(None))
        .order_by(Student.name, Student.student_code)
    ).all()


@app.patch("/api/v1/classes/{class_id}", response_model=ClassOut, tags=["classes"])
def update_class(class_id: str, payload: ClassUpdate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    class_model = class_or_404(db, class_id, org_id_from_context(context))
    if payload.name is not None:
        class_model.name = payload.name.strip()
    if payload.status is not None:
        class_model.status = payload.status
    db.commit()
    db.refresh(class_model)
    return class_out(db, class_model)


@app.post("/api/v1/classes/{class_id}/students", response_model=list[StudentOut], tags=["classes"])
def bulk_add_students(class_id: str, payload: BulkStudentCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[Student]:
    class_or_404(db, class_id, org_id_from_context(context))
    org_id = org_id_from_context(context)
    result: list[Student] = []
    for item in payload.students:
        code = item.student_code.strip()
        name = item.name.strip()
        student = db.scalar(select(Student).where(Student.organization_id == org_id, Student.student_code == code))
        if student is None:
            student = Student(organization_id=org_id, student_code=code, name=name)
            db.add(student)
            db.flush()
        else:
            student.name = name
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
    class_or_404(db, class_id, org_id)
    student = student_or_404(db, student_id, org_id)
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
    class_or_404(db, class_id, org_id_from_context(context))
    student_or_404(db, student_id, org_id_from_context(context))
    enrollment = active_enrollment(db, class_id, student_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Active enrollment not found")
    enrollment.left_at = now_utc()
    db.commit()
    return {"message": "Student removed from class; student record and history were retained"}


@app.get("/api/v1/students", response_model=list[StudentOut], tags=["students"])
def list_students(search: str | None = Query(default=None, max_length=120), context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[Student]:
    query = select(Student).where(Student.organization_id == org_id_from_context(context))
    if search:
        like = f"%{search.strip()}%"
        query = query.where((Student.name.ilike(like)) | (Student.student_code.ilike(like)))
    return db.scalars(query.order_by(Student.name, Student.student_code)).all()


@app.post("/api/v1/students", response_model=StudentOut, status_code=201, tags=["students"])
def create_student(payload: StudentCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> Student:
    student = Student(organization_id=org_id_from_context(context), student_code=payload.student_code.strip(), name=payload.name.strip())
    db.add(student)
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
    for field in ("student_code", "name", "status"):
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


@app.post("/api/v1/sessions", response_model=SessionOut, status_code=201, tags=["sessions"])
def create_session(payload: SessionCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    class_model = class_or_404(db, payload.class_id, org_id)
    if class_model.status != ClassStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Archived class cannot start a new session")
    session = AssessmentSession(
        organization_id=org_id,
        class_id=class_model.id,
        created_by=context[0].id,
        name=payload.name.strip() if payload.name and payload.name.strip() else None,
        question_count=payload.question_count,
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
        .options(selectinload(AssessmentSession.class_model), selectinload(AssessmentSession.questions).selectinload(Question.answer_key))
        .where(AssessmentSession.organization_id == org_id_from_context(context))
        .order_by(AssessmentSession.created_at.desc())
    ).all()
    return [session_out(session) for session in sessions]


@app.get("/api/v1/sessions/{session_id}", response_model=SessionOut, tags=["sessions"])
def get_session(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    return session_out(session_or_404(db, session_id, org_id_from_context(context)))


@app.post("/api/v1/sessions/{session_id}/start", response_model=SessionOut, tags=["sessions"])
def start_session(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
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
    if session.status != SessionStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Only a CLOSED session can be archived")
    session.status = SessionStatus.ARCHIVED
    session.archived_at = now_utc()
    db.commit()
    return session_out(session_or_404(db, session.id, session.organization_id))


@app.post("/api/v1/sessions/{session_id}/submissions", response_model=SubmissionOut, tags=["submissions"])
def submit_answers(session_id: str, payload: SubmissionCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    session = session_or_404(db, session_id, org_id_from_context(context))
    submission, is_update = create_or_update_submission(db, session, payload)
    event_broker.publish(session.id, {"kind": "submission.updated", "session_id": session.id, "student_id": submission.student_id})
    return submission_out(submission, session, is_update)


@app.post("/api/v1/sessions/{session_id}/recognition-results", response_model=SubmissionOut, tags=["submissions"])
def submit_recognition_result(session_id: str, payload: RecognitionResultCreate, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = org_id_from_context(context)
    student = student_or_404(db, payload.student_id, org_id) if payload.student_id else db.scalar(select(Student).where(Student.organization_id == org_id, Student.student_code == payload.student_code))
    if student is None:
        raise HTTPException(status_code=422, detail="Recognition result identity does not match a student")
    session = session_or_404(db, session_id, org_id)
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
    event_broker.publish(session.id, {"kind": "submission.updated", "session_id": session.id, "student_id": submission.student_id})
    return submission_out(submission, session, is_update)


@app.get("/api/v1/sessions/{session_id}/submissions", response_model=list[SubmissionOut], tags=["submissions"])
def list_submissions(session_id: str, context: tuple[User, OrganizationMember] = Depends(get_current_membership), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    session = session_or_404(db, session_id, org_id_from_context(context))
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
    return build_results(db, session)


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
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization.has(status=OrganizationStatus.ACTIVE),
            OrganizationMember.organization_id == select(AssessmentSession.organization_id).where(AssessmentSession.id == session_id).scalar_subquery(),
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this session organization")
    session_or_404(db, session_id, membership.organization_id)
    subscriber = event_broker.subscribe(session_id)
    return StreamingResponse(
        event_broker.stream(session_id, subscriber),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
