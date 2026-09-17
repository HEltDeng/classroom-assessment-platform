from math import ceil

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from reportlab.graphics import renderSVG
from sqlalchemy import select
from sqlalchemy.orm import Session

from .answer_sheets import build_pdf, page_token, qr_drawing
from .db import get_db
from .dependencies import get_current_membership
from .models import ClassEnrollment, Student, StudentStatus


def register_sheet_routes(app):
    # Import after main's route helpers have been defined.
    from . import main as m

    def accessible_student(db, student_id, context):
        student = m.student_or_404(db, student_id, m.org_id_from_context(context))
        if context[1].role == m.MemberRole.TEACHER:
            enrolled = db.scalars(m.scoped_classes_query(context).join(ClassEnrollment).where(ClassEnrollment.student_id == student.id, ClassEnrollment.left_at.is_(None))).first()
            if not enrolled:
                raise HTTPException(403, "无权查看该学生答题卡")
        return student

    def printable_student(db, student):
        record = m.current_qr(db, student)
        if record is None:
            m.issue_student_qr(db, student)
            db.flush()
            record = m.current_qr(db, student)
        return {"name": student.name, "student_code": student.student_code, "qr_id": record.id}

    def pdf_response(students, db, choice_pages=1, text_pages=1):
        if not students:
            raise HTTPException(422, "没有可打印的学生")
        data = [printable_student(db, s) for s in students]
        db.commit()
        return Response(build_pdf(data, (m.settings.qr_signing_secret or m.settings.jwt_secret), choice_pages, text_pages), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="answer-sheets-a5.pdf"', "Cache-Control": "no-store"})

    @app.get("/api/v1/students/{student_id}/answer-card")
    def student_card(student_id: str, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        student = accessible_student(db, student_id, context)
        data = printable_student(db, student)
        db.commit()
        svg = renderSVG.drawToString(qr_drawing(page_token(data["qr_id"], "OMR", 0, (m.settings.qr_signing_secret or m.settings.jwt_secret)), 240))
        return {"student_id": student.id, "name": student.name, "student_code": student.student_code, "qr_svg": svg, "format": "A5", "choice_capacity": 40, "text_capacity": 10}

    @app.get("/api/v1/students/{student_id}/answer-sheet.pdf")
    def student_pdf(student_id: str, choice_pages: int = Query(1, ge=1, le=3), text_pages: int = Query(1, ge=1, le=10), context=Depends(get_current_membership), db: Session = Depends(get_db)):
        return pdf_response([accessible_student(db, student_id, context)], db, choice_pages, text_pages)

    @app.get("/api/v1/classes/{class_id}/answer-sheets.pdf")
    def class_pdf(class_id: str, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        classroom = m.class_or_404(db, class_id, m.org_id_from_context(context))
        m.ensure_class_access(classroom, context)
        students = db.scalars(select(Student).join(ClassEnrollment).where(ClassEnrollment.class_id == class_id, ClassEnrollment.left_at.is_(None), Student.status == StudentStatus.ACTIVE).order_by(Student.student_code)).all()
        return pdf_response(students, db)

    @app.get("/api/v1/sessions/{session_id}/answer-sheets.pdf")
    def session_pdf(session_id: str, context=Depends(get_current_membership), db: Session = Depends(get_db)):
        session = m.session_or_404(db, session_id, m.org_id_from_context(context))
        m.ensure_session_access(session, context)
        students = [m.student_or_404(db, p.student_id, session.organization_id) for p in session.participants]
        choices = sum(q.question_type in {m.QuestionType.SINGLE_CHOICE, m.QuestionType.MCQ} for q in session.questions)
        return pdf_response(students, db, max(1, ceil(choices/40)), max(1, ceil((len(session.questions)-choices)/10)))
