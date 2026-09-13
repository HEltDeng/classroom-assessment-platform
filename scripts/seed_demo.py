from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import MemberRole, Organization, OrganizationMember, OrganizationSettings, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.seed_demo_password:
        raise RuntimeError("SEED_DEMO_PASSWORD must be set before running demo seed")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "teacher@example.com"))
        if user is None:
            user = User(email="teacher@example.com", display_name="演示教师", password_hash=hash_password(settings.seed_demo_password))
            db.add(user)
            db.flush()
        organization = db.scalar(select(Organization).where(Organization.name == "演示课堂机构"))
        if organization is None:
            organization = Organization(name="演示课堂机构")
            organization.settings = OrganizationSettings(organization_name="演示课堂机构", student_code_label="学生编号")
            db.add(organization)
            db.flush()
        member = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == organization.id, OrganizationMember.user_id == user.id))
        if member is None:
            db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=MemberRole.OWNER))
        db.commit()
    print("Demo seed ready: teacher@example.com (password comes from SEED_DEMO_PASSWORD)")


if __name__ == "__main__":
    main()
