"""Allow OCR text without truncating answers.

Revision ID: a517001
Revises: f6a1b2c3d4e8
"""
from alembic import op
import sqlalchemy as sa

revision = "a517001"
down_revision = "f6a1b2c3d4e8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE scans SET image_path = replace(image_path, '/opt/classroom-assessment-platform/current/backend/data/scans/', '/opt/classroom-assessment-platform/data/scans/') WHERE image_path LIKE '/opt/classroom-assessment-platform/current/backend/data/scans/%'")
    for table in ("answer_keys", "student_answers"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("value", existing_type=sa.String(16), type_=sa.String(2000), existing_nullable=False)


def downgrade():
    raise RuntimeError("Refusing to truncate existing text answers; use a reviewed data migration")
