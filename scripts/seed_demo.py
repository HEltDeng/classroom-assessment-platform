from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CourseDay, MemberRole, Organization, OrganizationMember, OrganizationSettings, Subject, TimeSlot, User  # noqa: E402
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
        if not db.query(CourseDay).filter(CourseDay.organization_id == organization.id).count():
            db.add_all(CourseDay(organization_id=organization.id, weekday=weekday, display_name=label) for weekday, label in ((5, "周五"), (6, "周六"), (7, "周日")))
        if not db.query(TimeSlot).filter(TimeSlot.organization_id == organization.id).count():
            db.add_all(
                TimeSlot(organization_id=organization.id, slot_code=code, display_name=label, start_time=start, end_time=end)
                for code, label, start, end in (("A", "A 段", "07:50", "10:00"), ("B", "B 段", "10:20", "12:30"), ("C", "C 段", "13:20", "15:30"), ("D", "D 段", "15:50", "18:00"))
            )
        if not db.query(Subject).filter(Subject.organization_id == organization.id).count():
            db.add_all(Subject(organization_id=organization.id, name=name) for name in ("英语", "数学", "语文", "物理", "化学"))
        db.commit()
    print("Demo seed ready: teacher@example.com (password comes from SEED_DEMO_PASSWORD)")


if __name__ == "__main__":
    main()
