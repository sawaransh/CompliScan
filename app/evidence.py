from __future__ import annotations
from pathlib import Path
import cv2
from .ocr import OCRBox

def annotate(path: Path, boxes: list[OCRBox], out_path: Path, fields: dict | None = None) -> None:
    """Render declaration evidence only; raw OCR boxes remain available in JSON for debugging."""
    img = cv2.imread(str(path))
    if img is None:
        return
    evidence = []
    if fields:
        for name, field in fields.items():
            if name.startswith("_") or not field.get("detected") or not field.get("bbox"): continue
            evidence.append((name.replace("_", " ").title(), field["bbox"], field.get("confidence", 0)))
    else:
        evidence = [(box.text[:28], box.bbox, box.confidence) for box in boxes]
    for label, bbox, confidence in evidence:
        x1, y1, x2, y2 = bbox
        if x2 <= x1 or y2 <= y1:
            continue
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 170, 0), 2)
        label = f"{label}  {confidence:.2f}"
        cv2.putText(img, label, (x1, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 170, 0), 2, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)
