from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ClassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"


class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class QuestionType(str, Enum):
    MCQ = "MCQ"
    TEXT = "TEXT"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class SubmissionSource(str, Enum):
    MOCK = "mock"
    ANDROID = "android"
    RECOGNITION = "recognition"


timestamp_column = lambda: mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def enum_column(enum_type: type[Enum]):
    return SqlEnum(enum_type, native_enum=False, values_callable=lambda values: [member.value for member in values])


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[OrganizationStatus] = mapped_column(enum_column(OrganizationStatus), default=OrganizationStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    settings: Mapped[OrganizationSettings] = relationship(back_populates="organization", uselist=False, cascade="all, delete-orphan")
    members: Mapped[list[OrganizationMember]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    classes: Mapped[list[ClassModel]] = relationship(back_populates="organization")
    students: Mapped[list[Student]] = relationship(back_populates="organization")


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False)
    organization_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    logo: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_code_label: Mapped[str] = mapped_column(String(80), default="学生编号", nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="settings")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(240), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    memberships: Mapped[list[OrganizationMember]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[MemberRole] = mapped_column(enum_column(MemberRole), default=MemberRole.TEACHER, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class ClassModel(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_org_class_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[ClassStatus] = mapped_column(enum_column(ClassStatus), default=ClassStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="classes")
    enrollments: Mapped[list[ClassEnrollment]] = relationship(back_populates="class_model")
    sessions: Mapped[list[AssessmentSession]] = relationship(back_populates="class_model")


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("organization_id", "student_code", name="uq_org_student_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    student_code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[StudentStatus] = mapped_column(enum_column(StudentStatus), default=StudentStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="students")
    enrollments: Mapped[list[ClassEnrollment]] = relationship(back_populates="student")


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    __table_args__ = (
        Index("ix_active_enrollment_student", "student_id", "left_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    joined_at: Mapped[datetime] = timestamp_column()
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    class_model: Mapped[ClassModel] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship(back_populates="enrollments")


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SessionStatus] = mapped_column(enum_column(SessionStatus), default=SessionStatus.DRAFT, nullable=False, index=True)
    created_at: Mapped[datetime] = timestamp_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    class_model: Mapped[ClassModel] = relationship(back_populates="sessions")
    questions: Mapped[list[Question]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="Question.question_no")
    participants: Mapped[list[SessionParticipant]] = relationship(back_populates="session", cascade="all, delete-orphan")
    submissions: Mapped[list[Submission]] = relationship(back_populates="session", cascade="all, delete-orphan")


class SessionParticipant(Base):
    __tablename__ = "session_participants"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_session_participant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True)
    student_code: Mapped[str] = mapped_column(String(80), nullable=False)
    student_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = timestamp_column()

    session: Mapped[AssessmentSession] = relationship(back_populates="participants")
    student: Mapped[Student] = relationship()


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("session_id", "question_no", name="uq_session_question_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[QuestionType] = mapped_column(enum_column(QuestionType), default=QuestionType.MCQ, nullable=False)
    created_at: Mapped[datetime] = timestamp_column()

    session: Mapped[AssessmentSession] = relationship(back_populates="questions")
    answer_key: Mapped[AnswerKey] = relationship(back_populates="question", uselist=False, cascade="all, delete-orphan")
    answers: Mapped[list[StudentAnswer]] = relationship(back_populates="question")


class AnswerKey(Base):
    __tablename__ = "answer_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = timestamp_column()

    question: Mapped[Question] = relationship(back_populates="answer_key")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_session_student_submission"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("assessment_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[SubmissionStatus] = mapped_column(enum_column(SubmissionStatus), default=SubmissionStatus.SUBMITTED, nullable=False)
    source: Mapped[SubmissionSource] = mapped_column(enum_column(SubmissionSource), default=SubmissionSource.MOCK, nullable=False)
    page_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    submitted_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    session: Mapped[AssessmentSession] = relationship(back_populates="submissions")
    student: Mapped[Student] = relationship()
    answers: Mapped[list[StudentAnswer]] = relationship(back_populates="submission", cascade="all, delete-orphan", order_by="StudentAnswer.question_no")


class StudentAnswer(Base):
    __tablename__ = "student_answers"
    __table_args__ = (UniqueConstraint("submission_id", "question_id", name="uq_submission_question_answer"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False, index=True)
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship(back_populates="answers")
