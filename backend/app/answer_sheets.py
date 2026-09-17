"""Versioned A5 geometry and reproducible, opaque page identities."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

TEMPLATE_DIR = Path(__file__).parent / "templates"
PAGE_TYPES = {"OMR": "A5-OMR-v1", "OCR": "A5-OCR-v1"}


def page_token(qr_id: str, side: str, page: int, secret: str) -> str:
    body = f"CS1.{qr_id}.{side}.{page}"
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{body}.{signature}"


def parse_page_token(token: str, secret: str) -> tuple[str, str, int] | None:
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != "CS1" or parts[2] not in PAGE_TYPES:
        return None
    try:
        page = int(parts[3])
    except ValueError:
        return None
    if not 0 <= page <= 9 or not hmac.compare_digest(token, page_token(parts[1], parts[2], page, secret)):
        return None
    return parts[1], parts[2], page


def geometry(side: str) -> dict:
    return json.loads((TEMPLATE_DIR / f"{PAGE_TYPES[side]}.json").read_text(encoding="utf-8"))


def qr_drawing(token: str, size: float) -> Drawing:
    code = qr.QrCodeWidget(token, barLevel="M")
    x0, y0, x1, y1 = code.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1-x0), 0, 0, size / (y1-y0), 0, 0])
    drawing.add(code)
    return drawing


def build_pdf(students: list[dict], secret: str, choice_pages: int = 1, text_pages: int = 1) -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    output = io.BytesIO()
    doc = canvas.Canvas(output, pagesize=(148 * mm, 210 * mm), pageCompression=1)
    doc.setTitle("学生答题卡 A5")
    for student in students:
        # Keep a student's pages together, with a blank reverse if needed.
        for index in range(max(choice_pages, text_pages)):
            for side, count in (("OMR", choice_pages), ("OCR", text_pages)):
                if index >= count:
                    doc.showPage()
                    continue
                template = geometry(side)
                scale = 148 * mm / template["canonical_width"]
                height = template["canonical_height"]
                doc.saveState()
                doc.scale(scale, scale)
                def label(x, y, value, size=28):
                    doc.setFont("STSong-Light", size)
                    doc.drawString(x, height-y, str(value))
                def rectangle(box, fill=0):
                    doc.rect(box["x"], height-box["y"]-box["height"], box["width"], box["height"], stroke=1, fill=fill)
                doc.setLineWidth(2)
                for marker in template["markers"]:
                    rectangle(marker, 1)
                label(130, 160, "课堂答题卡", 48)
                label(130, 218, "选择题 · 正面" if side == "OMR" else "文字题 · 背面", 32)
                label(130, 278, f"姓名：{student['name']}", 30)
                label(130, 325, f"学生编号：{student['student_code']}", 30)
                label(130, 375, "考试：____________________   日期：____________", 26)
                token = page_token(student["qr_id"], side, index, secret)
                box = template["qr_region"]
                renderPDF.draw(qr_drawing(token, box["width"]), doc, box["x"], height-box["y"]-box["height"])
                label(box["x"], box["y"]+box["height"]+28, f"{side} / {index+1}", 22)
                if side == "OMR":
                    label(130, 448, "用黑色笔填满方框；修改时擦净，每题只选一项。", 25)
                    for region in template["question_regions"]:
                        first = region["options"][0]["bbox"]
                        label(first["x"]-74, first["y"]+30, region["question_no"]+index*40, 27)
                        for option in region["options"]:
                            rectangle(option["bbox"])
                            # Letters outside the sampling rectangle avoid false fill.
                            label(option["bbox"]["x"]+12, option["bbox"]["y"]-10, option["label"], 23)
                else:
                    label(130, 448, "按文字题顺序填写，每框一题；请勿超出边框。", 25)
                    for region in template["text_regions"]:
                        box = region["bbox"]
                        label(box["x"], box["y"]-15, f"文字题 {region['question_no']+index*10}", 24)
                        rectangle(box)
                label(130, 1960, "请保持四角定位点和二维码完整、清晰。", 24)
                label(130, 2000, f"A5 · 148 × 210 mm · {PAGE_TYPES[side]}", 22)
                doc.restoreState()
                doc.showPage()
    doc.save()
    return output.getvalue()
