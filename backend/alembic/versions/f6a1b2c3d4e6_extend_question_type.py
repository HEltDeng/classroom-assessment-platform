"""extend question type storage for OMR and OCR-ready questions

Revision ID: f6a1b2c3d4e6
Revises: f6a1b2c3d4e5
Create Date: 2026-09-15 00:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e6"
down_revision: Union[str, Sequence[str], None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


question_type = sa.Enum(
    "SINGLE_CHOICE",
    "MULTIPLE_CHOICE",
    "TRUE_FALSE",
    "OCR_SHORT_ANSWER",
    "OCR_NUMBER",
    "OTHER",
    "MCQ",
    "TEXT",
    name="questiontype",
    native_enum=False,
)


def upgrade() -> None:
    # The original v1 column was VARCHAR(4) for MCQ/TEXT. Recreate it with
    # the complete enum storage length while retaining all legacy values.
    with op.batch_alter_table("questions", recreate="always") as batch_op:
        batch_op.alter_column(
            "question_type",
            existing_type=sa.String(length=4),
            type_=question_type,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("questions", recreate="always") as batch_op:
        batch_op.alter_column(
            "question_type",
            existing_type=question_type,
            type_=sa.String(length=4),
            existing_nullable=False,
        )
