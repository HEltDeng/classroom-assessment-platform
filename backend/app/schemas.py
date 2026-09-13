from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import (
    ClassStatus,
    MemberRole,
    OrganizationStatus,
    QuestionType,
    SessionStatus,
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
    status: OrganizationStatus
    settings: OrganizationSettingsOut | None = None
    created_at: datetime


class MembershipOut(APIModel):
    organization_id: str
    role: MemberRole
    organization: OrganizationOut


class MeOut(UserOut):
    memberships: list[MembershipOut]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    organization_name: str | None = Field(default=None, max_length=160)
    logo: str | None = Field(default=None, max_length=20000)
    student_code_label: str = Field(default="学生编号", min_length=1, max_length=80)


class OrganizationSettingsUpdate(BaseModel):
    organization_name: str | None = Field(default=None, max_length=160)
    logo: str | None = Field(default=None, max_length=20000)
    student_code_label: str = Field(min_length=1, max_length=80)


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: ClassStatus | None = None


class StudentCreate(BaseModel):
    student_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)


class StudentUpdate(BaseModel):
    student_code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: StudentStatus | None = None


class BulkStudentCreate(BaseModel):
    students: list[StudentCreate] = Field(min_length=1, max_length=500)


class AddStudentToClass(BaseModel):
    move_existing: bool = False


class StudentOut(APIModel):
    id: str
    organization_id: str
    student_code: str
    name: str
    status: StudentStatus
    created_at: datetime


class ClassOut(APIModel):
    id: str
    organization_id: str
    name: str
    status: ClassStatus
    student_count: int = 0
    created_at: datetime


class ClassDetailOut(ClassOut):
    students: list[StudentOut] = Field(default_factory=list)


class AnswerKeyInput(BaseModel):
    question_no: int = Field(ge=1)
    value: str = Field(pattern="^[ABCD]$")
    question_type: QuestionType = QuestionType.MCQ


class SessionCreate(BaseModel):
    class_id: str
    name: str | None = Field(default=None, max_length=200)
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
    correct_answer: str


class SessionOut(APIModel):
    id: str
    organization_id: str
    class_id: str
    class_name: str
    name: str | None
    question_count: int
    status: SessionStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    questions: list[QuestionOut] = Field(default_factory=list)


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
    student_id: str | None = None
    student_code: str | None = Field(default=None, max_length=80)
    page_type: str = Field(default="ANSWER_SHEET", min_length=1, max_length=80)
    answers: list[SubmissionAnswerInput] = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_required: bool = False
    idempotency_key: str | None = Field(default=None, max_length=180)

    @model_validator(mode="after")
    def validate_identity(self) -> "RecognitionResultCreate":
        if not self.student_id and not self.student_code:
            raise ValueError("student_id or student_code is required")
        return self


class SubmissionOut(BaseModel):
    id: str
    session_id: str
    student_id: str
    status: SubmissionStatus
    source: SubmissionSource
    page_type: str | None
    confidence: float | None
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


class MessageOut(BaseModel):
    message: str
