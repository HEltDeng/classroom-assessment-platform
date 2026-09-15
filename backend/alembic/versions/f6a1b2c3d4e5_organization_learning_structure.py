"""add organization learning structure

Revision ID: f6a1b2c3d4e5
Revises: bd5cec266163
Create Date: 2026-09-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "bd5cec266163"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


school_stage = sa.Enum("PRIMARY", "MIDDLE", "HIGH", name="schoolstage", native_enum=False)
course_day_status = sa.Enum("ACTIVE", "INACTIVE", name="coursedaystatus", native_enum=False)
exam_type = sa.Enum("ENTRY", "IN_CLASS", "EXIT", "CUSTOM", name="examtype", native_enum=False)
qr_status = sa.Enum("ACTIVE", "REVOKED", name="qrcodestatus", native_enum=False)


def upgrade() -> None:
    op.add_column("organizations", sa.Column("code_prefix", sa.String(length=12), nullable=False, server_default="ORG"))
    op.add_column("organizations", sa.Column("student_serial", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "subjects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_org_subject_name"),
    )
    op.create_index("ix_subjects_organization_id", "subjects", ["organization_id"], unique=False)

    op.create_table(
        "time_slots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("slot_code", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("applicable_school_stage", school_stage, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slot_code", name="uq_org_time_slot_code"),
    )
    op.create_index("ix_time_slots_organization_id", "time_slots", ["organization_id"], unique=False)

    op.create_table(
        "organization_course_days",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column("status", course_day_status, nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "weekday", name="uq_org_course_day"),
    )
    op.create_index("ix_organization_course_days_organization_id", "organization_course_days", ["organization_id"], unique=False)

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("classes", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("teacher_id", sa.String(length=36), nullable=True))
            batch_op.add_column(sa.Column("school_stage", school_stage, nullable=False, server_default="PRIMARY"))
            batch_op.add_column(sa.Column("grade", sa.String(length=80), nullable=True))
            batch_op.add_column(sa.Column("day_of_week", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("time_slot_id", sa.String(length=36), nullable=True))
            batch_op.create_index("ix_classes_teacher_id", ["teacher_id"], unique=False)
            batch_op.create_index("ix_classes_time_slot_id", ["time_slot_id"], unique=False)
            batch_op.create_foreign_key("fk_classes_teacher_id", "organization_members", ["teacher_id"], ["id"], ondelete="RESTRICT")
            batch_op.create_foreign_key("fk_classes_time_slot_id", "time_slots", ["time_slot_id"], ["id"], ondelete="RESTRICT")
    else:
        op.add_column("classes", sa.Column("teacher_id", sa.String(length=36), nullable=True))
        op.add_column("classes", sa.Column("school_stage", school_stage, nullable=False, server_default="PRIMARY"))
        op.add_column("classes", sa.Column("grade", sa.String(length=80), nullable=True))
        op.add_column("classes", sa.Column("day_of_week", sa.Integer(), nullable=True))
        op.add_column("classes", sa.Column("time_slot_id", sa.String(length=36), nullable=True))
        op.create_index("ix_classes_teacher_id", "classes", ["teacher_id"], unique=False)
        op.create_index("ix_classes_time_slot_id", "classes", ["time_slot_id"], unique=False)
        op.create_foreign_key("fk_classes_teacher_id", "classes", "organization_members", ["teacher_id"], ["id"], ondelete="RESTRICT")
        op.create_foreign_key("fk_classes_time_slot_id", "classes", "time_slots", ["time_slot_id"], ["id"], ondelete="RESTRICT")

    op.add_column("students", sa.Column("school_stage", school_stage, nullable=False, server_default="PRIMARY"))
    op.add_column("students", sa.Column("gender", sa.String(length=20), nullable=True))
    op.add_column("students", sa.Column("phone", sa.String(length=40), nullable=True))
    op.add_column("students", sa.Column("parent_phone", sa.String(length=40), nullable=True))
    op.add_column("students", sa.Column("remark", sa.String(length=500), nullable=True))

    op.create_table(
        "student_qr_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", qr_status, nullable=False, server_default="ACTIVE"),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_student_qr_codes_student_id", "student_qr_codes", ["student_id"], unique=False)
    op.create_index("ix_student_qr_codes_token_hash", "student_qr_codes", ["token_hash"], unique=True)

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("assessment_sessions", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("subject_id", sa.String(length=36), nullable=True))
            batch_op.add_column(sa.Column("exam_type", exam_type, nullable=False, server_default="CUSTOM"))
            batch_op.add_column(sa.Column("total_score", sa.Float(), nullable=False, server_default="0"))
            batch_op.create_index("ix_assessment_sessions_subject_id", ["subject_id"], unique=False)
            batch_op.create_foreign_key("fk_assessment_sessions_subject_id", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")
    else:
        op.add_column("assessment_sessions", sa.Column("subject_id", sa.String(length=36), nullable=True))
        op.add_column("assessment_sessions", sa.Column("exam_type", exam_type, nullable=False, server_default="CUSTOM"))
        op.add_column("assessment_sessions", sa.Column("total_score", sa.Float(), nullable=False, server_default="0"))
        op.create_index("ix_assessment_sessions_subject_id", "assessment_sessions", ["subject_id"], unique=False)
        op.create_foreign_key("fk_assessment_sessions_subject_id", "assessment_sessions", "subjects", ["subject_id"], ["id"], ondelete="RESTRICT")

    op.add_column("questions", sa.Column("points", sa.Float(), nullable=False, server_default="1"))
    op.add_column("submissions", sa.Column("score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("submissions", "score")
    op.drop_column("questions", "points")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("assessment_sessions", recreate="always") as batch_op:
            batch_op.drop_constraint("fk_assessment_sessions_subject_id", type_="foreignkey")
            batch_op.drop_index("ix_assessment_sessions_subject_id")
            batch_op.drop_column("total_score")
            batch_op.drop_column("exam_type")
            batch_op.drop_column("subject_id")
    else:
        op.drop_constraint("fk_assessment_sessions_subject_id", "assessment_sessions", type_="foreignkey")
        op.drop_index("ix_assessment_sessions_subject_id", table_name="assessment_sessions")
        op.drop_column("assessment_sessions", "total_score")
        op.drop_column("assessment_sessions", "exam_type")
        op.drop_column("assessment_sessions", "subject_id")

    op.drop_index("ix_student_qr_codes_token_hash", table_name="student_qr_codes")
    op.drop_index("ix_student_qr_codes_student_id", table_name="student_qr_codes")
    op.drop_table("student_qr_codes")
    op.drop_column("students", "remark")
    op.drop_column("students", "parent_phone")
    op.drop_column("students", "phone")
    op.drop_column("students", "gender")
    op.drop_column("students", "school_stage")

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("classes", recreate="always") as batch_op:
            batch_op.drop_constraint("fk_classes_time_slot_id", type_="foreignkey")
            batch_op.drop_constraint("fk_classes_teacher_id", type_="foreignkey")
            batch_op.drop_index("ix_classes_time_slot_id")
            batch_op.drop_index("ix_classes_teacher_id")
            batch_op.drop_column("time_slot_id")
            batch_op.drop_column("day_of_week")
            batch_op.drop_column("grade")
            batch_op.drop_column("school_stage")
            batch_op.drop_column("teacher_id")
    else:
        op.drop_constraint("fk_classes_time_slot_id", "classes", type_="foreignkey")
        op.drop_constraint("fk_classes_teacher_id", "classes", type_="foreignkey")
        op.drop_index("ix_classes_time_slot_id", table_name="classes")
        op.drop_index("ix_classes_teacher_id", table_name="classes")
        op.drop_column("classes", "time_slot_id")
        op.drop_column("classes", "day_of_week")
        op.drop_column("classes", "grade")
        op.drop_column("classes", "school_stage")
        op.drop_column("classes", "teacher_id")

    op.drop_index("ix_organization_course_days_organization_id", table_name="organization_course_days")
    op.drop_table("organization_course_days")
    op.drop_index("ix_time_slots_organization_id", table_name="time_slots")
    op.drop_table("time_slots")
    op.drop_index("ix_subjects_organization_id", table_name="subjects")
    op.drop_table("subjects")
    op.drop_column("organizations", "student_serial")
    op.drop_column("organizations", "code_prefix")
