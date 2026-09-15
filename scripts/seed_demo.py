from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import CourseDay, CourseDayStatus, MemberRole, Organization, OrganizationMember, OrganizationSettings, Student, Subject, TimeSlot, User  # noqa: E402
from app.security import hash_password  # noqa: E402


DEFAULT_DAYS = ((5, "周五"), (6, "周六"), (7, "周日"))
DEFAULT_SLOTS = (
    ("A", "A 段", "07:50", "10:00"),
    ("B", "B 段", "10:20", "12:30"),
    ("C", "C 段", "13:20", "15:30"),
    ("D", "D 段", "15:50", "18:00"),
)
DEFAULT_SUBJECTS = ("英语", "数学", "语文", "物理", "化学")


def main() -> None:
    """Prepare the acceptance tenant; this is not a public create-org flow."""
    settings = get_settings()
    if not settings.seed_demo_password:
        raise RuntimeError("SEED_DEMO_PASSWORD must be set before running the acceptance bootstrap")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "teacher@example.com"))
        if user is None:
            user = User(email="teacher@example.com", display_name="Rodush", password_hash=hash_password(settings.seed_demo_password))
            db.add(user)
            db.flush()
        else:
            user.display_name = "Rodush"
            if not user.password_hash:
                user.password_hash = hash_password(settings.seed_demo_password)

        organization = db.scalar(select(Organization).where(Organization.name == "叶芝"))
        if organization is None:
            organization = Organization(name="叶芝", code_prefix="YZ")
            db.add(organization)
            db.flush()
        elif not db.scalar(select(Student.id).where(Student.organization_id == organization.id)) and organization.code_prefix != "YZ":
            organization.code_prefix = "YZ"
        if organization.settings is None:
            organization.settings = OrganizationSettings(organization_id=organization.id, organization_name="叶芝", student_code_label="学生编号")
        else:
            organization.settings.organization_name = organization.settings.organization_name or "叶芝"
            organization.settings.student_code_label = organization.settings.student_code_label or "学生编号"

        member = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == organization.id, OrganizationMember.user_id == user.id))
        if member is None:
            db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, login_name="rodush", role=MemberRole.OWNER))
        else:
            member.login_name = "rodush"
            member.role = MemberRole.OWNER

        for weekday, label in DEFAULT_DAYS:
            if db.scalar(select(CourseDay.id).where(CourseDay.organization_id == organization.id, CourseDay.weekday == weekday)) is None:
                db.add(CourseDay(organization_id=organization.id, weekday=weekday, display_name=label, status=CourseDayStatus.ACTIVE))
        for code, label, start, end in DEFAULT_SLOTS:
            if db.scalar(select(TimeSlot.id).where(TimeSlot.organization_id == organization.id, TimeSlot.slot_code == code)) is None:
                db.add(TimeSlot(organization_id=organization.id, slot_code=code, display_name=label, start_time=start, end_time=end))
        for name in DEFAULT_SUBJECTS:
            if db.scalar(select(Subject.id).where(Subject.organization_id == organization.id, Subject.name == name)) is None:
                db.add(Subject(organization_id=organization.id, name=name))
        db.commit()
    print("Acceptance tenant ready: 叶芝 / rodush")


if __name__ == "__main__":
    main()
