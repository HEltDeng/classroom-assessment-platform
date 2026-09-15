from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import (
    ClassStatus,
    CourseDayStatus,
    ExamType,
    MemberRole,
    OrganizationStatus,
    QuestionType,
    QRCodeStatus,
    ScanStatus,
    SchoolStage,
    SessionStatus,
    ScannerSessionStatus,
    StudentStatus,
    SubmissionSource,
    SubmissionStatus,
)


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(APIModel):
    id: str
    email: EmailStr
    display_name: str


class OrganizationSettingsOut(APIModel):
    organization_name: str | None
    logo: str | None
    student_code_label: str


class OrganizationOut(APIModel):
    id: str
    name: str
    code_prefix: str
    student_serial: int
    status: OrganizationStatus
    settings: OrganizationSettingsOut | None = None
    created_at: datetime


class MembershipOut(APIModel):
    organization_id: str
    login_name: str
    role: MemberRole
    organization: OrganizationOut


class MeOut(UserOut):
    organization_id: str
    teacher_id: str
    login_name: str
    role: MemberRole
    organization: OrganizationOut
    memberships: list[MembershipOut]


class LoginRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=160)
    teacher_login_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    organization_id: str
    organization_name: str
    teacher_id: str
    teacher_name: str
    login_name: str
    role: MemberRole


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code_prefix: str | None = Field(default=None, min_length=2, max_length=12, pattern="^[A-Za-z0-9]+$")
    organization_name: str | None = Field(default=None, max_length=160)
    logo: str | None = Field(default=None, max_length=20000)
    student_code_label: str = Field(default="学生编号", min_length=1, max_length=80)


class OrganizationSettingsUpdate(BaseModel):
    code_prefix: str | None = Field(default=None, min_length=2, max_length=12, pattern="^[A-Za-z0-9]+$")
    organization_name: str | None = Field(default=None, max_length=160)
    logo: str | None = Field(default=None, max_length=20000)
    student_code_label: str = Field(min_length=1, max_length=80)


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    teacher_id: str | None = None
    school_stage: SchoolStage = SchoolStage.PRIMARY
    grade: str | None = Field(default=None, max_length=80)
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    time_slot_id: str | None = None


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    teacher_id: str | None = None
    school_stage: SchoolStage | None = None
    grade: str | None = Field(default=None, max_length=80)
    day_of_week: int | None = Field(default=None, ge=1, le=7)
    time_slot_id: str | None = None
    status: ClassStatus | None = None


class StudentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    school_stage: SchoolStage = SchoolStage.PRIMARY
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=40)
    parent_phone: str | None = Field(default=None, max_length=40)
    remark: str | None = Field(default=None, max_length=500)
    # Accepted for old clients but never used as the business identifier.
    student_code: str | None = Field(default=None, max_length=80)


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    school_stage: SchoolStage | None = None
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=40)
    parent_phone: str | None = Field(default=None, max_length=40)
    remark: str | None = Field(default=None, max_length=500)
    status: StudentStatus | None = None
    # Accepted for old clients but ignored so student_code remains immutable.
    student_code: str | None = Field(default=None, max_length=80)


class BulkStudentCreate(BaseModel):
    students: list[StudentCreate] = Field(min_length=1, max_length=500)


class AddStudentToClass(BaseModel):
    move_existing: bool = False


class BulkAttachStudents(BaseModel):
    student_ids: list[str] = Field(min_length=1, max_length=500)
    move_existing: bool = False


class TransferStudent(BaseModel):
    target_class_id: str
    from_class_id: str | None = None


class StudentOut(APIModel):
    id: str
    organization_id: str
    student_code: str
    name: str
    school_stage: SchoolStage
    gender: str | None = None
    phone: str | None = None
    parent_phone: str | None = None
    remark: str | None = None
    status: StudentStatus
    created_at: datetime
    updated_at: datetime


class ClassOut(APIModel):
    id: str
    organization_id: str
    name: str
    teacher_id: str | None = None
    teacher_name: str | None = None
    school_stage: SchoolStage
    grade: str | None = None
    day_of_week: int | None = None
    time_slot_id: str | None = None
    time_slot_name: str | None = None
    status: ClassStatus
    student_count: int = 0
    created_at: datetime


class ClassDetailOut(ClassOut):
    students: list[StudentOut] = Field(default_factory=list)


class AnswerKeyInput(BaseModel):
    question_no: int = Field(ge=1)
    value: str = Field(pattern="^[ABCD]$")
    points: float = Field(default=1, gt=0, le=1000)
    question_type: QuestionType = QuestionType.SINGLE_CHOICE


class SessionCreate(BaseModel):
    class_id: str
    name: str | None = Field(default=None, max_length=200)
    subject_id: str | None = None
    exam_type: ExamType = ExamType.CUSTOM
    question_count: int = Field(ge=1, le=100)
    answer_keys: list[AnswerKeyInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_questions(self) -> "SessionCreate":
        numbers = [answer.question_no for answer in self.answer_keys]
        if len(numbers) != self.question_count or sorted(numbers) != list(range(1, self.question_count + 1)):
            raise ValueError("answer_keys must contain exactly one answer for every question number")
        return self


class QuestionOut(APIModel):
    id: str
    question_no: int
    question_type: QuestionType
    points: float
    correct_answer: str


class SessionOut(APIModel):
    id: str
    organization_id: str
    class_id: str
    class_name: str
    subject_id: str | None = None
    subject_name: str | None = None
    exam_type: ExamType
    name: str | None
    question_count: int
    total_score: float
    status: SessionStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    questions: list[QuestionOut] = Field(default_factory=list)


class ScannerAssessmentOut(BaseModel):
    id: str
    organization_id: str
    class_id: str
    class_name: str
    name: str | None
    status: SessionStatus
    question_count: int
    submitted_count: int = 0
    participant_count: int = 0


class ScannerSessionOut(BaseModel):
    id: str
    organization_id: str
    assessment_session_id: str
    opened_by: str
    opened_by_member_id: str
    status: ScannerSessionStatus
    opened_at: datetime
    closed_at: datetime | None = None


class ScanOut(BaseModel):
    server_scan_id: str
    session_id: str
    scan_session_id: str
    class_id: str
    client_capture_id: str
    status: ScanStatus
    request_id: str
    student_name: str | None = None
    student_code: str | None = None
    page_type: str
    created_at: datetime
    processed_at: datetime | None = None


class SubmissionAnswerInput(BaseModel):
    question_no: int = Field(ge=1)
    value: str = Field(pattern="^[ABCD]$")
    confidence: float | None = Field(default=None, ge=0, le=1)


class SubmissionCreate(BaseModel):
    student_id: str
    answers: list[SubmissionAnswerInput] = Field(min_length=1, max_length=100)
    source: SubmissionSource = SubmissionSource.MOCK
    review_required: bool = False
    idempotency_key: str | None = Field(default=None, max_length=180)
    page_type: str | None = Field(default=None, max_length=80)
    confidence: float | None = Field(default=None, ge=0, le=1)


class RecognitionResultCreate(BaseModel):
    scan_id: str | None = None
    student_id: str | None = None
    student_code: str | None = Field(default=None, max_length=80)
    student_qr_token: str | None = Field(default=None, min_length=16, max_length=256)
    page_type: str = Field(default="ANSWER_SHEET", min_length=1, max_length=80)
    answers: list[SubmissionAnswerInput] = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_required: bool = False
    idempotency_key: str | None = Field(default=None, max_length=180)

    @model_validator(mode="after")
    def validate_identity(self) -> "RecognitionResultCreate":
        if not self.student_id and not self.student_code and not self.student_qr_token:
            raise ValueError("student_id, student_code or student_qr_token is required")
        return self


class SubmissionOut(BaseModel):
    id: str
    session_id: str
    student_id: str
    status: SubmissionStatus
    source: SubmissionSource
    page_type: str | None
    confidence: float | None
    score: float | None
    is_update: bool
    correct_count: int
    question_count: int
    submitted_at: datetime
    updated_at: datetime


class StudentLiveState(BaseModel):
    student_id: str
    student_code: str
    student_name: str
    status: str
    submission_id: str | None = None
    source: SubmissionSource | None = None
    submitted_at: datetime | None = None
    answers: dict[int, str] = Field(default_factory=dict)
    score: float = 0
    correct_count: int = 0


class QuestionStats(BaseModel):
    question_no: int
    correct_answer: str
    answered_count: int
    submitted_count: int
    counts: dict[str, int]
    correct_count: int
    correct_rate: float
    students_by_option: dict[str, list[str]]


class ResultsOut(BaseModel):
    session: SessionOut
    participant_count: int
    submitted_count: int
    pending_count: int
    review_required_count: int
    average_correct_rate: float
    questions: list[QuestionStats]
    students: list[StudentLiveState]


class TeacherCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    login_name: str = Field(min_length=1, max_length=80, pattern="^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1, max_length=200)
    role: MemberRole = MemberRole.TEACHER
    email: EmailStr | None = None


class TeacherOut(BaseModel):
    id: str
    user_id: str
    display_name: str
    login_name: str
    email: EmailStr
    role: MemberRole
    active: bool
    class_count: int = 0


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SubjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None


class SubjectOut(APIModel):
    id: str
    organization_id: str
    name: str
    active: bool
    created_at: datetime


class TimeSlotCreate(BaseModel):
    slot_code: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=80)
    start_time: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    end_time: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    applicable_school_stage: SchoolStage | None = None
    active: bool = True


class TimeSlotUpdate(BaseModel):
    slot_code: str | None = Field(default=None, min_length=1, max_length=40)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    start_time: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    end_time: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    applicable_school_stage: SchoolStage | None = None
    active: bool | None = None


class TimeSlotOut(APIModel):
    id: str
    organization_id: str
    slot_code: str
    display_name: str
    start_time: str
    end_time: str
    applicable_school_stage: SchoolStage | None
    active: bool


class CourseDayUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    status: CourseDayStatus | None = None


class CourseDayCreate(BaseModel):
    weekday: int = Field(ge=1, le=7)
    display_name: str = Field(min_length=1, max_length=40)
    status: CourseDayStatus = CourseDayStatus.ACTIVE


class CourseDayOut(APIModel):
    id: str
    organization_id: str
    weekday: int
    display_name: str
    status: CourseDayStatus


class StudentImportMatch(BaseModel):
    id: str
    student_code: str
    name: str
    school_stage: SchoolStage
    current_classes: list[str] = Field(default_factory=list)


class StudentImportItem(BaseModel):
    row_number: int
    name: str
    school_stage: SchoolStage | None = None
    remark: str | None = None
    status: str
    default_action: str
    matches: list[StudentImportMatch] = Field(default_factory=list)
    error: str | None = None


class StudentImportPreviewOut(BaseModel):
    file_name: str
    total_rows: int
    existing_count: int
    prepare_create_count: int
    duplicate_count: int
    error_count: int
    items: list[StudentImportItem]


class StudentImportDecision(BaseModel):
    row_number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    school_stage: SchoolStage = SchoolStage.PRIMARY
    remark: str | None = Field(default=None, max_length=500)
    action: str = Field(pattern="^(USE_EXISTING|CREATE|SKIP)$")
    student_id: str | None = None


class StudentImportConfirm(BaseModel):
    items: list[StudentImportDecision] = Field(min_length=1, max_length=500)
    class_id: str | None = None


class StudentImportResult(BaseModel):
    created_count: int
    reused_count: int
    skipped_count: int
    membership_added_count: int
    students: list[StudentOut]


class QRTokenOut(BaseModel):
    student_id: str
    token: str
    version: int
    status: QRCodeStatus


class MessageOut(BaseModel):
    message: str
