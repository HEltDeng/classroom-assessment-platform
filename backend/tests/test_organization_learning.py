from __future__ import annotations

import io
import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test-classroom-assessment.sqlite3")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-local-tests")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CourseDay, CourseDayStatus, MemberRole, Organization, OrganizationMember, OrganizationSettings, Subject, TimeSlot, User  # noqa: E402
from app.security import decode_access_token, hash_password  # noqa: E402


def workbook_bytes(rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["姓名", "学段", "备注"])
    for row in rows:
        worksheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def login_headers(client: TestClient, organization_name: str, login_name: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"organization_name": organization_name, "teacher_login_name": login_name, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_organization_student_master_import_membership_and_exam_flow() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with testing_session() as db:
        user = User(email="owner@example.com", display_name="机构管理员", password_hash=hash_password("owner-password"))
        organization = Organization(name="叶芝", code_prefix="YZ")
        organization.settings = OrganizationSettings(organization_name="叶芝", student_code_label="学生编号")
        organization.members.append(OrganizationMember(user=user, login_name="owner", role=MemberRole.OWNER))
        organization.course_days.extend(CourseDay(weekday=weekday, display_name=label, status=CourseDayStatus.ACTIVE) for weekday, label in ((5, "周五"), (6, "周六"), (7, "周日")))
        organization.time_slots.extend(TimeSlot(slot_code=code, display_name=label, start_time=start, end_time=end) for code, label, start, end in (("A", "A 段", "07:50", "10:00"), ("B", "B 段", "10:20", "12:30"), ("C", "C 段", "13:20", "15:30"), ("D", "D 段", "15:50", "18:00")))
        organization.subjects.extend(Subject(name=name) for name in ("英语", "数学", "语文", "物理", "化学"))
        db.add(organization)
        db.commit()

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        headers = login_headers(client, "叶芝", "owner", "owner-password")
        organization = client.get("/api/v1/me", headers=headers).json()["organization"]
        assert organization["code_prefix"] == "YZ"
        assert organization["student_serial"] == 0
        assert client.post("/api/v1/organizations", headers=headers, json={"name": "不应创建"}).status_code == 403

        course_days = client.get("/api/v1/course-days", headers=headers)
        assert course_days.status_code == 200
        assert {item["weekday"] for item in course_days.json()} == {5, 6, 7}
        time_slots = client.get("/api/v1/time-slots", headers=headers).json()
        slot_b = next(item for item in time_slots if item["slot_code"] == "B")
        subjects = client.get("/api/v1/subjects", headers=headers).json()
        math = next(item for item in subjects if item["name"] == "数学")

        teacher_a = client.post(
            "/api/v1/teachers",
            headers=headers,
            json={"display_name": "王老师", "login_name": "wang", "email": "wang@example.com", "password": "teacher-password"},
        )
        teacher_b = client.post(
            "/api/v1/teachers",
            headers=headers,
            json={"display_name": "李老师", "login_name": "li", "email": "li@example.com", "password": "teacher-password"},
        )
        assert teacher_a.status_code == 201, teacher_a.text
        assert teacher_b.status_code == 201, teacher_b.text

        class_a = client.post(
            "/api/v1/classes",
            headers=headers,
            json={
                "name": "王老师 · 初中 · 周六 · B段",
                "teacher_id": teacher_a.json()["id"],
                "school_stage": "MIDDLE",
                "grade": "初二",
                "day_of_week": 6,
                "time_slot_id": slot_b["id"],
            },
        )
        class_b = client.post(
            "/api/v1/classes",
            headers=headers,
            json={
                "name": "李老师 · 初中 · 周日 · B段",
                "teacher_id": teacher_b.json()["id"],
                "school_stage": "MIDDLE",
                "grade": "初二",
                "day_of_week": 7,
                "time_slot_id": slot_b["id"],
            },
        )
        assert class_a.status_code == 201, class_a.text
        assert class_b.status_code == 201, class_b.text
        class_a_id = class_a.json()["id"]
        class_b_id = class_b.json()["id"]
        assert class_a.json()["school_stage"] == "MIDDLE"
        assert class_a.json()["time_slot_name"] == "B 段"

        names = [[f"学生{index:02d}", "初中", "首批导入"] for index in range(1, 21)]
        preview = client.post(
            "/api/v1/students/import/preview",
            headers=headers,
            files={"file": ("students.xlsx", workbook_bytes(names), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()
        assert preview_data["total_rows"] == 20
        assert preview_data["prepare_create_count"] == 20
        assert preview_data["existing_count"] == 0
        assert client.get("/api/v1/students", headers=headers).json() == []

        confirmed = client.post(
            "/api/v1/students/import/confirm",
            headers=headers,
            json={
                "class_id": class_a_id,
                "items": [
                    {
                        "row_number": item["row_number"],
                        "name": item["name"],
                        "school_stage": "MIDDLE",
                        "remark": "首批导入",
                        "action": "CREATE",
                    }
                    for item in preview_data["items"]
                ],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["created_count"] == 20
        assert confirmed.json()["membership_added_count"] == 20
        students = client.get("/api/v1/students", headers=headers).json()
        codes = sorted((student["student_code"] for student in students), key=lambda code: int(code[2:]))
        assert codes == [f"YZ{index:04d}" for index in range(1, 21)]
        student_by_name = {student["name"]: student for student in students}
        student_one = student_by_name["学生01"]
        student_two = student_by_name["学生02"]
        student_two_code = student_two["student_code"]
        immutable_code = client.patch(
            f"/api/v1/students/{student_one['id']}",
            headers=headers,
            json={"student_code": "YZ9999"},
        )
        assert immutable_code.status_code == 200, immutable_code.text
        assert immutable_code.json()["student_code"] == "YZ0001"

        existing_preview = client.post(
            "/api/v1/students/import/preview",
            headers=headers,
            files={"file": ("existing.csv", "姓名\n学生01\n".encode("utf-8"), "text/csv")},
        )
        assert existing_preview.status_code == 200, existing_preview.text
        existing_item = existing_preview.json()["items"][0]
        assert existing_preview.json()["existing_count"] == 1
        assert existing_item["status"] == "EXISTING_SUSPECT"
        reused = client.post(
            "/api/v1/students/import/confirm",
            headers=headers,
            json={
                "items": [
                    {
                        "row_number": existing_item["row_number"],
                        "name": "学生01",
                        "school_stage": "MIDDLE",
                        "action": "USE_EXISTING",
                        "student_id": existing_item["matches"][0]["id"],
                    }
                ],
            },
        )
        assert reused.status_code == 200, reused.text
        assert reused.json()["created_count"] == 0
        assert len(client.get("/api/v1/students", headers=headers).json()) == 20

        duplicate_one = client.post("/api/v1/students", headers=headers, json={"name": "张三", "school_stage": "MIDDLE"})
        duplicate_two = client.post("/api/v1/students", headers=headers, json={"name": "张三", "school_stage": "MIDDLE"})
        assert duplicate_one.status_code == 201, duplicate_one.text
        assert duplicate_two.status_code == 201, duplicate_two.text
        duplicate_preview = client.post(
            "/api/v1/students/import/preview",
            headers=headers,
            files={
                "file": (
                    "duplicate.xlsx",
                    workbook_bytes([["学生01", "初中", ""], ["张三", "初中", ""], ["", "初中", "缺姓名"]]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert duplicate_preview.status_code == 200, duplicate_preview.text
        duplicate_data = duplicate_preview.json()
        assert duplicate_data["existing_count"] == 1
        assert duplicate_data["duplicate_count"] == 1
        assert duplicate_data["error_count"] == 1
        assert duplicate_data["items"][1]["status"] == "DUPLICATE_IN_ORG"
        assert duplicate_data["items"][2]["status"] == "EMPTY_NAME"

        attached = client.post(
            f"/api/v1/classes/{class_b_id}/student-memberships",
            headers=headers,
            json={"student_ids": [student_one["id"]]},
        )
        assert attached.status_code == 200, attached.text
        transferred = client.post(
            f"/api/v1/students/{student_two['id']}/transfer",
            headers=headers,
            json={"from_class_id": class_a_id, "target_class_id": class_b_id},
        )
        assert transferred.status_code == 200, transferred.text
        assert transferred.json()["student_code"] == student_two_code
        assert client.get(f"/api/v1/classes/{class_a_id}", headers=headers).json()["student_count"] == 19
        assert client.get(f"/api/v1/classes/{class_b_id}", headers=headers).json()["student_count"] == 2

        removed = client.post(f"/api/v1/classes/{class_b_id}/students/{student_one['id']}/remove", headers=headers)
        assert removed.status_code == 200, removed.text
        assert client.get(f"/api/v1/classes/{class_b_id}", headers=headers).json()["student_count"] == 1
        retained = client.get(f"/api/v1/students?search={student_one['student_code']}", headers=headers)
        assert retained.status_code == 200
        assert retained.json()[0]["id"] == student_one["id"]

        answer_values = "ABCDABCDAB"
        exam = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={
                "class_id": class_b_id,
                "name": "初二数学进门测",
                "subject_id": math["id"],
                "exam_type": "ENTRY",
                "question_count": 10,
                "answer_keys": [
                    {"question_no": index + 1, "value": value, "points": 2, "question_type": "SINGLE_CHOICE"}
                    for index, value in enumerate(answer_values)
                ],
            },
        )
        assert exam.status_code == 201, exam.text
        exam_data = exam.json()
        assert exam_data["exam_type"] == "ENTRY"
        assert exam_data["subject_name"] == "数学"
        assert exam_data["total_score"] == 20
        assert len(exam_data["questions"]) == 10
        exam_id = exam_data["id"]
        assert client.get(f"/api/v1/sessions/{exam_id}", headers=headers).json()["total_score"] == 20
        assert client.post(f"/api/v1/sessions/{exam_id}/start", headers=headers).status_code == 200

        qr = client.post(f"/api/v1/students/{student_two['id']}/qr-token", headers=headers)
        assert qr.status_code == 200, qr.text
        token = qr.json()["token"]
        recognized = client.post(
            f"/api/v1/sessions/{exam_id}/recognition-results",
            headers=headers,
            json={
                "student_qr_token": token,
                "confidence": 0.95,
                "answers": [{"question_no": index + 1, "value": value} for index, value in enumerate(answer_values)],
            },
        )
        assert recognized.status_code == 200, recognized.text
        assert recognized.json()["score"] == 20
        assert recognized.json()["correct_count"] == 10
        results = client.get(f"/api/v1/sessions/{exam_id}/results", headers=headers)
        assert results.status_code == 200, results.text
        assert results.json()["submitted_count"] == 1
        assert results.json()["students"][0]["score"] == 20

        for report_type in ("score-sheet", "subscore", "answer-stats"):
            report = client.get(f"/api/v1/sessions/{exam_id}/exports/{report_type}.xlsx", headers=headers)
            assert report.status_code == 200, report.text
            assert report.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        template = client.get("/api/v1/students/import/template.xlsx", headers=headers)
        assert template.status_code == 200
        assert template.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert client.get("/api/v1/students/export.xlsx", headers=headers).status_code == 200
        assert client.get(f"/api/v1/classes/{class_b_id}/export.xlsx", headers=headers).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_login_name_is_scoped_to_organization_and_session_cannot_switch() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with testing_session() as db:
        first_user = User(email="first@example.com", display_name="第一位教师", password_hash=hash_password("same-password"))
        second_user = User(email="second@example.com", display_name="第二位教师", password_hash=hash_password("same-password"))
        first_org = Organization(name="第一机构", code_prefix="ONE")
        second_org = Organization(name="第二机构", code_prefix="TWO")
        first_org.settings = OrganizationSettings(organization_name="第一机构", student_code_label="学生编号")
        second_org.settings = OrganizationSettings(organization_name="第二机构", student_code_label="学生编号")
        first_org.members.append(OrganizationMember(user=first_user, login_name="teacher", role=MemberRole.OWNER))
        second_org.members.append(OrganizationMember(user=second_user, login_name="teacher", role=MemberRole.OWNER))
        db.add_all([first_org, second_org])
        db.commit()

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        first_login = client.post("/api/v1/auth/login", json={"organization_name": "第一机构", "teacher_login_name": "teacher", "password": "same-password"})
        second_login = client.post("/api/v1/auth/login", json={"organization_name": "第二机构", "teacher_login_name": "teacher", "password": "same-password"})
        assert first_login.status_code == 200
        assert second_login.status_code == 200
        first_token = first_login.json()["access_token"]
        claims = decode_access_token(first_token)
        assert claims["organization_id"] == first_login.json()["organization_id"]
        assert claims["teacher_id"] == first_login.json()["teacher_id"]
        first_headers = {"Authorization": f"Bearer {first_token}"}
        assert client.get("/api/v1/me", headers=first_headers).json()["organization"]["name"] == "第一机构"
        mismatch = client.get("/api/v1/me", headers={**first_headers, "X-Organization-Id": second_login.json()["organization_id"]})
        assert mismatch.status_code == 403
    finally:
        app.dependency_overrides.clear()
