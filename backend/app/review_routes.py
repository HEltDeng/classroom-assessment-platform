import json
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .dependencies import get_current_membership
from .models import ScanRecord, ScanStatus, SessionStatus, Submission, SubmissionStatus, SubmissionSource
from .scan_worker import result_path
from .schemas import SubmissionAnswerInput, SubmissionCreate


class ReviewInput(BaseModel):
    answers: list[SubmissionAnswerInput] = Field(min_length=1, max_length=100)


def register_review_routes(app):
    from . import main as m

    def accessible_scan(db, scan_id, context):
        scan = db.scalar(select(ScanRecord).where(ScanRecord.id == scan_id, ScanRecord.organization_id == m.org_id_from_context(context)))
        if not scan:
            raise HTTPException(404, "扫描记录不存在")
        m.ensure_session_access(scan.assessment_session, context)
        return scan

    @app.get("/api/v1/sessions/{session_id}/scans")
    def scans(session_id: str, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        session = m.session_or_404(db, session_id, m.org_id_from_context(context))
        m.ensure_session_access(session, context)
        records = db.scalars(select(ScanRecord).where(ScanRecord.assessment_session_id == session.id).order_by(ScanRecord.created_at.desc())).all()
        return [{**m.scan_out(scan), "failure_reason": scan.failure_reason, "recognition": json.loads(result_path(scan).read_text(encoding="utf-8")) if result_path(scan).exists() else None} for scan in records]

    @app.get("/api/v1/scans/{scan_id}/image")
    def image(scan_id: str, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        scan = accessible_scan(db, scan_id, context)
        if not Path(scan.image_path).is_file():
            raise HTTPException(404, "扫描图片不存在")
        return FileResponse(scan.image_path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/scans/{scan_id}/retry")
    def retry(scan_id: str, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        scan = accessible_scan(db, scan_id, context)
        if scan.assessment_session.status not in {SessionStatus.ACTIVE, SessionStatus.CLOSED}:
            raise HTTPException(409, "当前考试不能重新识别")
        if scan.status not in {ScanStatus.FAILED, ScanStatus.REVIEW_REQUIRED}:
            raise HTTPException(409, "只有失败或待复核记录可重试")
        scan.status = ScanStatus.PROCESSING
        scan.failure_reason = None
        db.commit()
        return m.scan_out(scan)

    @app.post("/api/v1/scans/{scan_id}/review")
    def review(scan_id: str, payload: ReviewInput, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        scan = accessible_scan(db, scan_id, context)
        if not scan.student_id or not result_path(scan).exists() or scan.status != ScanStatus.REVIEW_REQUIRED:
            raise HTTPException(409, "此记录尚无可复核的识别结果")
        original = json.loads(result_path(scan).read_text(encoding="utf-8"))
        expected = {a["question_no"] for a in original["mapped_answers"]}
        if len(payload.answers) != len(expected) or {a.question_no for a in payload.answers} != expected:
            raise HTTPException(422, "请核验此页全部题目")
        session = m.session_or_404(db, scan.assessment_session_id, scan.organization_id)
        if session.status not in {SessionStatus.ACTIVE, SessionStatus.CLOSED}:
            raise HTTPException(409, "已归档考试不能修改")
        scan.status = ScanStatus.SUCCESS
        scan.failure_reason = None
        db.flush()
        submission = db.scalar(select(Submission).where(Submission.session_id == session.id, Submission.student_id == scan.student_id))
        if submission:
            submission.status = SubmissionStatus.SUBMITTED
        others = db.scalar(select(ScanRecord.id).where(ScanRecord.assessment_session_id == session.id, ScanRecord.student_id == scan.student_id, ScanRecord.status == ScanStatus.REVIEW_REQUIRED).limit(1))
        m.create_or_update_submission(db, session, SubmissionCreate(student_id=scan.student_id, answers=payload.answers, source=SubmissionSource.RECOGNITION, review_required=bool(others)))
        original["review"] = {"reviewer_id": context[0].id, "reviewed_at": m.now_utc().isoformat(), "answers": [a.model_dump() for a in payload.answers]}
        result_path(scan).write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        m.event_broker.publish(session.id, {"kind": "submission.updated", "session_id": session.id, "student_id": scan.student_id})
        return m.scan_out(scan)
