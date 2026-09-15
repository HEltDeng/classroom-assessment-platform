"""add organization-scoped teacher login names

Revision ID: f6a1b2c3d4e7
Revises: f6a1b2c3d4e6
Create Date: 2026-09-15 09:30:00.000000
"""

from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e7"
down_revision: Union[str, Sequence[str], None] = "f6a1b2c3d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _login_base(email: str | None) -> str:
    local_part = (email or "").split("@", 1)[0].lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "", local_part)
    return (normalized or "teacher")[:80]


def upgrade() -> None:
    # A temporary server default lets PostgreSQL and SQLite add the required
    # column without making existing memberships invalid. The values are then
    # replaced with stable, organization-scoped login names before the unique
    # constraint is created.
    op.add_column(
        "organization_members",
        sa.Column("login_name", sa.String(length=80), nullable=False, server_default="teacher"),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT m.id, m.organization_id, u.email "
            "FROM organization_members AS m "
            "JOIN users AS u ON u.id = m.user_id "
            "ORDER BY m.organization_id, m.created_at, m.id"
        )
    ).mappings()
    used: dict[str, set[str]] = {}
    for row in rows:
        organization_id = str(row["organization_id"])
        names = used.setdefault(organization_id, set())
        base = _login_base(row["email"])
        candidate = base
        suffix = 2
        while candidate in names:
            suffix_text = str(suffix)
            candidate = f"{base[:80 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        names.add(candidate)
        connection.execute(
            sa.text("UPDATE organization_members SET login_name = :login_name WHERE id = :id"),
            {"login_name": candidate, "id": row["id"]},
        )
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("organization_members", recreate="always") as batch_op:
            batch_op.alter_column("login_name", server_default=None, existing_type=sa.String(length=80), existing_nullable=False)
            batch_op.create_unique_constraint("uq_org_login_name", ["organization_id", "login_name"])
    else:
        op.alter_column("organization_members", "login_name", server_default=None, existing_type=sa.String(length=80), existing_nullable=False)
        op.create_unique_constraint("uq_org_login_name", "organization_members", ["organization_id", "login_name"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("organization_members", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_org_login_name", type_="unique")
    else:
        op.drop_constraint("uq_org_login_name", "organization_members", type_="unique")
    op.drop_column("organization_members", "login_name")
