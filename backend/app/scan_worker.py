"""Durable scan queue consumer. Run one worker per backend database."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from .db import SessionLocal
from .models import ScanRecord, ScanStatus, SessionStatus, SubmissionSource
from .schemas import SubmissionAnswerInput, SubmissionCreate

logger = logging.getLogger(__name__)


def result_path(scan):
    return Path(scan.image_path).with_suffix(".recognition.json")


def process_scan(db, scan, recognize=None):
    from . import main as m
    session = m.session_or_404(db, scan.assessment_session_id, scan.organization_id)
    if session.status not in {SessionStatus.ACTIVE, SessionStatus.CLOSED}:
        scan.status = ScanStatus.FAILED
        scan.failure_reason = "考试已归档或尚未发布"
        db.commit()
        return
    if not scan.student_id or not scan.page_type.startswith("A5-"):
        scan.status = ScanStatus.REVIEW_REQUIRED
        scan.failure_reason = "请使用系统下载的 A5 答题卡，确认学生身份和页面类型"
        db.commit()
        return
    template, page_index = scan.page_type.split(":")
    side = "OMR" if template == "A5-OMR-v1" else "OCR"
    if recognize is None:
        with Path(scan.image_path).open("rb") as image:
            response = httpx.post(m.settings.recognition_service_url.rstrip("/") + "/recognize/page", data={"template_version": template, "page_type": side}, files={"image": ("page.jpg", image, "image/jpeg")}, timeout=m.settings.recognition_timeout_seconds)
        response.raise_for_status()
        result = response.json()
    else:
        result = recognize(Path(scan.image_path).read_bytes(), template, side)
    if result.get("template_version") != template or result.get("page_type") != side:
        raise ValueError("Recognition template mismatch")
    choice_types = {m.QuestionType.SINGLE_CHOICE, m.QuestionType.MCQ}
    questions = [q for q in session.questions if (q.question_type in choice_types) == (side == "OMR")]
    capacity = 40 if side == "OMR" else 10
    questions = questions[int(page_index)*capacity:(int(page_index)+1)*capacity]
    if not questions:
        scan.status = ScanStatus.FAILED
        scan.failure_reason = "本场考试没有此页对应的题目"
        db.commit()
        return
    by_slot = {a["question_no"]: a for a in result.get("answers", [])}
    mapped = []
    review = result.get("page_quality", {}).get("status") != "OK"
    for slot, question in enumerate(questions, 1):
        answer = by_slot.get(slot, {})
        value = answer.get("value") if side == "OMR" else answer.get("raw_text")
        # OCR is always reviewed before it is accepted as a verified transcript.
        uncertain = answer.get("status") != "RECOGNIZED" or answer.get("confidence", 0) < 0.8 or side == "OCR"
        review = review or uncertain
        mapped.append({"question_no": question.question_no, "value": value or "", "confidence": 0 if uncertain else answer.get("confidence", 0), "status": answer.get("status", "REVIEW_REQUIRED")})
    result["mapped_answers"] = mapped
    result_path(scan).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    scan.status = ScanStatus.REVIEW_REQUIRED if review else ScanStatus.SUCCESS
    scan.failure_reason = "需要核验文字或不确定答案" if review else None
    scan.processed_at = m.now_utc()
    db.flush()
    payload = SubmissionCreate(student_id=scan.student_id, source=SubmissionSource.RECOGNITION, answers=[SubmissionAnswerInput(**{k: a[k] for k in ("question_no", "value", "confidence")}) for a in mapped], review_required=review, page_type=side)
    m.create_or_update_submission(db, session, payload)
    m.event_broker.publish(session.id, {"kind": "submission.updated", "session_id": session.id, "student_id": scan.student_id})


def main():
    from .config import get_settings
    if not get_settings().recognition_service_url:
        raise RuntimeError("RECOGNITION_SERVICE_URL must be configured")
    while True:
        with SessionLocal() as db:
            scan = db.scalar(select(ScanRecord).where(ScanRecord.status == ScanStatus.PROCESSING).order_by(ScanRecord.created_at).limit(1))
            if scan:
                try:
                    process_scan(db, scan)
                except Exception:
                    db.rollback()
                    scan.status = ScanStatus.FAILED
                    scan.failure_reason = "识别服务处理失败，请检查服务后重试"
                    db.commit()
                    logger.warning("Recognition failed for scan %s", scan.id)
            else:
                time.sleep(2)


if __name__ == "__main__":
    main()
