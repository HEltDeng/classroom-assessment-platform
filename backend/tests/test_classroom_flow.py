from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test-classroom-assessment.sqlite3")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-local-tests")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import MemberRole, Organization, OrganizationMember, OrganizationSettings, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"organization_name": "测试机构", "teacher_login_name": "tester", "password": "test-password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_complete_classroom_flow() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TestingSession() as db:
        user = User(email="teacher@example.com", display_name="测试教师", password_hash=hash_password("test-password"))
        organization = Organization(name="测试机构")
        organization.settings = OrganizationSettings(organization_name="测试机构", student_code_label="学员编号")
        organization.members.append(OrganizationMember(user=user, login_name="tester", role=MemberRole.OWNER))
        db.add(organization)
        db.commit()

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        headers = auth_headers(client)
        organizations = client.get("/api/v1/organizations", headers=headers)
        assert organizations.status_code == 200
        organization_id = organizations.json()[0]["id"]
        headers["X-Organization-Id"] = organization_id

        created_class = client.post("/api/v1/classes", headers=headers, json={"name": "初一 A 班"})
        assert created_class.status_code == 201, created_class.text
        class_id = created_class.json()["id"]
        second_class = client.post("/api/v1/classes", headers=headers, json={"name": "周六实验班"})
        assert second_class.status_code == 201, second_class.text
        second_class_id = second_class.json()["id"]

        bulk = client.post("/api/v1/classes/{}/students".format(class_id), headers=headers, json={"students": [
            {"student_code": "S001", "name": "张三"},
            {"student_code": "S002", "name": "李四"},
        ]})
        assert bulk.status_code == 200, bulk.text
        class_detail = client.get(f"/api/v1/classes/{class_id}", headers=headers)
        assert class_detail.json()["student_count"] == 2
        student_one, student_two = class_detail.json()["students"]
        assert len(client.get(f"/api/v1/classes/{class_id}/students", headers=headers).json()) == 2

        removed = client.post(f"/api/v1/classes/{class_id}/students/{student_one['id']}/remove", headers=headers)
        assert removed.status_code == 200
        assert client.get(f"/api/v1/classes/{class_id}", headers=headers).json()["student_count"] == 1

        rejoined = client.post(f"/api/v1/classes/{class_id}/students/{student_one['id']}", headers=headers, json={})
        assert rejoined.status_code == 200
        moved_without_confirmation = client.post(f"/api/v1/classes/{second_class_id}/students/{student_one['id']}", headers=headers, json={})
        assert moved_without_confirmation.status_code == 409
        moved = client.post(f"/api/v1/classes/{second_class_id}/students/{student_one['id']}", headers=headers, json={"move_existing": True})
        assert moved.status_code == 200
        assert client.get(f"/api/v1/classes/{class_id}", headers=headers).json()["student_count"] == 1
        assert client.get(f"/api/v1/classes/{second_class_id}", headers=headers).json()["student_count"] == 1

        # Move the student back so the assessment roster contains both students.
        moved_back = client.post(f"/api/v1/classes/{class_id}/students/{student_one['id']}", headers=headers, json={"move_existing": True})
        assert moved_back.status_code == 200

        session_response = client.post("/api/v1/sessions", headers=headers, json={
            "class_id": class_id,
            "name": "进门测",
            "question_count": 4,
            "answer_keys": [
                {"question_no": 1, "value": "B"},
                {"question_no": 2, "value": "C"},
                {"question_no": 3, "value": "A"},
                {"question_no": 4, "value": "D"},
            ],
        })
        assert session_response.status_code == 201, session_response.text
        session_id = session_response.json()["id"]
        started = client.post(f"/api/v1/sessions/{session_id}/start", headers=headers)
        assert started.status_code == 200

        first_submission = client.post(f"/api/v1/sessions/{session_id}/submissions", headers=headers, json={
            "student_id": student_one["id"],
            "answers": [
                {"question_no": 1, "value": "B"}, {"question_no": 2, "value": "C"},
                {"question_no": 3, "value": "A"}, {"question_no": 4, "value": "D"},
            ],
            "source": "mock",
        })
        assert first_submission.status_code == 200, first_submission.text
        assert first_submission.json()["is_update"] is False
        first_results = client.get(f"/api/v1/sessions/{session_id}/results", headers=headers)
        assert first_results.status_code == 200
        assert first_results.json()["submitted_count"] == 1
        assert first_results.json()["pending_count"] == 1
        assert first_results.json()["questions"][0]["counts"]["B"] == 1
        assert first_results.json()["questions"][0]["correct_rate"] == 100.0

        second_submission = client.post(f"/api/v1/sessions/{session_id}/submissions", headers=headers, json={
            "student_id": student_two["id"],
            "answers": [
                {"question_no": 1, "value": "A"}, {"question_no": 2, "value": "C"},
                {"question_no": 3, "value": "D"}, {"question_no": 4, "value": "D"},
            ],
            "source": "mock",
            "review_required": True,
        })
        assert second_submission.status_code == 200, second_submission.text
        final_results = client.get(f"/api/v1/sessions/{session_id}/results", headers=headers).json()
        assert final_results["submitted_count"] == 2
        assert final_results["pending_count"] == 0
        assert final_results["review_required_count"] == 1
        assert final_results["questions"][0]["counts"] == {"A": 1, "B": 1, "C": 0, "D": 0}
        assert final_results["questions"][0]["correct_rate"] == 50.0
        assert any(student["status"] == "REVIEW_REQUIRED" for student in final_results["students"])

        duplicate_update = client.post(f"/api/v1/sessions/{session_id}/submissions", headers=headers, json={
            "student_id": student_two["id"],
            "answers": [
                {"question_no": 1, "value": "B"}, {"question_no": 2, "value": "C"},
                {"question_no": 3, "value": "A"}, {"question_no": 4, "value": "D"},
            ],
            "source": "mock",
        })
        assert duplicate_update.status_code == 200, duplicate_update.text
        assert duplicate_update.json()["is_update"] is True
        assert client.get(f"/api/v1/sessions/{session_id}/submissions", headers=headers).json().__len__() == 2

        recognition_update = client.post(f"/api/v1/sessions/{session_id}/recognition-results", headers=headers, json={
            "student_code": student_one["student_code"],
            "page_type": "ANSWER_SHEET",
            "confidence": 0.6,
            "answers": [
                {"question_no": 1, "value": "B"}, {"question_no": 2, "value": "C"},
                {"question_no": 3, "value": "A"}, {"question_no": 4, "value": "D"},
            ],
        })
        assert recognition_update.status_code == 200, recognition_update.text
        assert recognition_update.json()["page_type"] == "ANSWER_SHEET"
        assert recognition_update.json()["confidence"] == 0.6
        assert recognition_update.json()["status"] == "REVIEW_REQUIRED"

        scannable_sessions = client.get(f"/api/v1/classes/{class_id}/sessions?status=ACTIVE", headers=headers)
        assert scannable_sessions.status_code == 200
        assert [item["id"] for item in scannable_sessions.json()] == [session_id]
        scanner_session_response = client.post(f"/api/v1/sessions/{session_id}/scan-session", headers=headers)
        assert scanner_session_response.status_code == 200, scanner_session_response.text
        scanner_session_id = scanner_session_response.json()["id"]
        capture_id = str(uuid4())
        scan_headers = {**headers, "Idempotency-Key": capture_id}
        scan_data = {
            "session_id": session_id,
            "scan_session_id": scanner_session_id,
            "page_token": "opaque-page-token-for-test",
            "client_capture_id": capture_id,
        }
        scan_files = {"image": ("answer-sheet.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")}
        scan_response = client.post("/api/v1/scans", headers=scan_headers, data=scan_data, files=scan_files)
        assert scan_response.status_code == 201, scan_response.text
        scan = scan_response.json()
        assert scan["session_id"] == session_id
        assert scan["scan_session_id"] == scanner_session_id
        assert scan["client_capture_id"] == capture_id
        assert scan["status"] == "PROCESSING"
        retry_response = client.post(
            "/api/v1/scans",
            headers=scan_headers,
            data=scan_data,
            files=scan_files,
        )
        assert retry_response.status_code == 201, retry_response.text
        assert retry_response.json()["server_scan_id"] == scan["server_scan_id"]
        scan_recognition = client.post(
            f"/api/v1/sessions/{session_id}/recognition-results",
            headers=headers,
            json={
                "scan_id": scan["server_scan_id"],
                "student_id": student_two["id"],
                "page_type": "ANSWER_SHEET",
                "confidence": 0.6,
                "answers": [
                    {"question_no": 1, "value": "B"}, {"question_no": 2, "value": "C"},
                    {"question_no": 3, "value": "A"}, {"question_no": 4, "value": "D"},
                ],
            },
        )
        assert scan_recognition.status_code == 200, scan_recognition.text
        assert client.get(f"/api/v1/scans/{scan['server_scan_id']}", headers=headers).json()["status"] == "REVIEW_REQUIRED"

        active_sessions = client.get("/api/v1/sessions?status=ACTIVE", headers=headers)
        assert active_sessions.status_code == 200
        assert [item["id"] for item in active_sessions.json()] == [session_id]

        closed = client.post(f"/api/v1/sessions/{session_id}/close", headers=headers)
        assert closed.status_code == 200
        rejected_after_close = client.post(f"/api/v1/sessions/{session_id}/submissions", headers=headers, json={
            "student_id": student_one["id"], "answers": [{"question_no": 1, "value": "B"}], "source": "mock",
        })
        assert rejected_after_close.status_code == 409
    finally:
        app.dependency_overrides.clear()
