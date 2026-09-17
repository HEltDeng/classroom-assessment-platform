"""Synthetic marks on the actual PDF; never used as real handwriting evidence."""
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(sys.argv[1])
template_root = Path(sys.argv[2])
for index, side in enumerate(["OMR", "OCR"]):
    bitmap = pdf[index].render(scale=3.53).to_pil().convert("L")
    image = cv2.resize(np.asarray(bitmap), (1480, 2100))
    template = json.loads((template_root / f"A5-{side}-v1.json").read_text())
    if side == "OMR":
        for index, question in enumerate(template['question_regions']):
            box = question['options'][index % 4]['bbox']
            cv2.rectangle(image, (box['x']+4, box['y']+4), (box['x']+box['width']-4, box['y']+box['height']-4), 0, -1)
    else:
        for index, question in enumerate(template['text_regions']):
            box = question['bbox']
            cv2.putText(image, 'because' if index % 2 == 0 else 'environment', (box['x']+25, box['y']+60), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 3, cv2.LINE_AA)
    image = cv2.copyMakeBorder(image, 100, 100, 100, 100, cv2.BORDER_CONSTANT, value=90)
    token, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    if not token.startswith('CS1.'):
        raise RuntimeError('Printed QR failed decoding')
    cv2.imwrite(str(Path(sys.argv[1]).with_name(f'filled-{side}.jpg')), image)
print('Actual PDF rendered; both QR codes decoded; synthetic ink applied.')
