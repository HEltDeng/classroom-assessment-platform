"""add tenant-scoped scanner sessions and scan receipts

Revision ID: f6a1b2c3d4e8
Revises: f6a1b2c3d4e7
Create Date: 2026-09-15 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e8"
down_revision: Union[str, Sequence[str], None] = "f6a1b2c3d4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scanner_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("assessment_session_id", sa.String(length=36), nullable=False),
        sa.Column("opened_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("opened_by_member_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OPEN", "CLOSED", name="scannersessionstatus", native_enum=False),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assessment_session_id"], ["assessment_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["opened_by_member_id"], ["organization_members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "assessment_session_id", "opened_by_member_id", name="uq_scanner_session_owner"),
    )
    op.create_index("ix_scanner_sessions_organization_id", "scanner_sessions", ["organization_id"], unique=False)
    op.create_index("ix_scanner_sessions_assessment_session_id", "scanner_sessions", ["assessment_session_id"], unique=False)
    op.create_index("ix_scanner_sessions_opened_by_user_id", "scanner_sessions", ["opened_by_user_id"], unique=False)
    op.create_index("ix_scanner_sessions_opened_by_member_id", "scanner_sessions", ["opened_by_member_id"], unique=False)
    op.create_index("ix_scanner_sessions_assessment_status", "scanner_sessions", ["assessment_session_id", "status"], unique=False)

    op.create_table(
        "scans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("assessment_session_id", sa.String(length=36), nullable=False),
        sa.Column("scanner_session_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_member_id", sa.String(length=36), nullable=False),
        sa.Column("client_capture_id", sa.String(length=64), nullable=False),
        sa.Column("page_token_hash", sa.String(length=128), nullable=False),
        sa.Column("image_path", sa.String(length=500), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_type", sa.String(length=80), server_default="ANSWER_SHEET", nullable=False),
        sa.Column("student_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PROCESSING", "SUCCESS", "REVIEW_REQUIRED", "FAILED", name="scanstatus", native_enum=False),
            server_default="PROCESSING",
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assessment_session_id"], ["assessment_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scanner_session_id"], ["scanner_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by_member_id"], ["organization_members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "client_capture_id", name="uq_scan_org_client_capture"),
    )
    op.create_index("ix_scans_organization_id", "scans", ["organization_id"], unique=False)
    op.create_index("ix_scans_assessment_session_id", "scans", ["assessment_session_id"], unique=False)
    op.create_index("ix_scans_scanner_session_id", "scans", ["scanner_session_id"], unique=False)
    op.create_index("ix_scans_uploaded_by_user_id", "scans", ["uploaded_by_user_id"], unique=False)
    op.create_index("ix_scans_uploaded_by_member_id", "scans", ["uploaded_by_member_id"], unique=False)
    op.create_index("ix_scans_page_token_hash", "scans", ["page_token_hash"], unique=False)
    op.create_index("ix_scans_student_id", "scans", ["student_id"], unique=False)
    op.create_index("ix_scans_request_id", "scans", ["request_id"], unique=False)
    op.create_index("ix_scans_session_status", "scans", ["assessment_session_id", "status"], unique=False)
    op.create_index("ix_scans_scanner_session_created", "scans", ["scanner_session_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scans_scanner_session_created", table_name="scans")
    op.drop_index("ix_scans_session_status", table_name="scans")
    op.drop_index("ix_scans_request_id", table_name="scans")
    op.drop_index("ix_scans_student_id", table_name="scans")
    op.drop_index("ix_scans_page_token_hash", table_name="scans")
    op.drop_index("ix_scans_uploaded_by_member_id", table_name="scans")
    op.drop_index("ix_scans_uploaded_by_user_id", table_name="scans")
    op.drop_index("ix_scans_scanner_session_id", table_name="scans")
    op.drop_index("ix_scans_assessment_session_id", table_name="scans")
    op.drop_index("ix_scans_organization_id", table_name="scans")
    op.drop_table("scans")
    op.drop_index("ix_scanner_sessions_assessment_status", table_name="scanner_sessions")
    op.drop_index("ix_scanner_sessions_opened_by_member_id", table_name="scanner_sessions")
    op.drop_index("ix_scanner_sessions_opened_by_user_id", table_name="scanner_sessions")
    op.drop_index("ix_scanner_sessions_assessment_session_id", table_name="scanner_sessions")
    op.drop_index("ix_scanner_sessions_organization_id", table_name="scanner_sessions")
    op.drop_table("scanner_sessions")
