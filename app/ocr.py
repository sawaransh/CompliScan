from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class OCRBox:
    text: str
    confidence: float
    bbox: list[int]

    def to_dict(self) -> dict:
        return asdict(self)


def image_quality(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(gray.std())
    glare = float(np.mean(gray > 245))
    return {
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "sharpness_raw": round(sharpness, 2),
        "contrast_raw": round(contrast, 2),
        "glare_ratio": round(glare, 4),
        "sharpness_score": round(min(100.0, sharpness / 8.0), 1),
        "contrast_score": round(min(100.0, contrast * 2.2), 1),
        "glare_score": round(max(0.0, 100.0 - glare * 220.0), 1),
    }


def preprocess_for_tesseract(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return cv2.bilateralFilter(gray, 7, 50, 50)


def _paddle_boxes(result: Any) -> list[OCRBox]:
    payload = result
    try:
        if hasattr(payload, "json"):
            raw = payload.json
            raw = raw() if callable(raw) else raw
            if isinstance(raw, str):
                raw = json.loads(raw)
            payload = raw
    except Exception:
        pass

    if hasattr(payload, "res"):
        payload = payload.res
    if isinstance(payload, dict) and "res" in payload and isinstance(payload["res"], dict):
        payload = payload["res"]
    if not isinstance(payload, dict):
        return []

    texts = payload.get("rec_texts") or payload.get("texts") or payload.get("rec_text") or []
    scores = payload.get("rec_scores") or payload.get("scores") or payload.get("rec_score") or []
    boxes = payload.get("rec_boxes") or payload.get("dt_polys") or payload.get("boxes") or []
    if isinstance(texts, str):
        texts = [texts]
    if np.isscalar(scores):
        scores = [scores]

    out: list[OCRBox] = []
    for i, text in enumerate(texts):
        text = str(text).strip()
        if not text:
            continue
        score = float(scores[i]) if i < len(scores) else 0.75
        box = boxes[i] if i < len(boxes) else None
        if box is None:
            bbox = [0, 0, 0, 0]
        else:
            arr = np.asarray(box).astype(float).reshape(-1, 2)
            bbox = [int(arr[:, 0].min()), int(arr[:, 1].min()), int(arr[:, 0].max()), int(arr[:, 1].max())]
        out.append(OCRBox(text=text, confidence=max(0.0, min(1.0, score)), bbox=bbox))
    return out


def run_paddle(path: Path) -> list[OCRBox]:
    from paddleocr import PaddleOCR
    kwargs = {"lang": "en"}
    for key, value in {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }.items():
        kwargs[key] = value
    ocr = PaddleOCR(**kwargs)
    results = ocr.predict(input=str(path))
    out: list[OCRBox] = []
    for result in results:
        out.extend(_paddle_boxes(result))
    return out


def run_tesseract(path: Path) -> list[OCRBox]:
    import pytesseract
    from pytesseract import Output

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Unable to read image: {path}")
    processed = preprocess_for_tesseract(image)
    data = pytesseract.image_to_data(processed, output_type=Output.DICT, config="--psm 11")
    out: list[OCRBox] = []
    for i, raw_text in enumerate(data.get("text", [])):
        text = (raw_text or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i]) / 100.0
        except Exception:
            conf = 0.0
        x, y = int(data["left"][i]), int(data["top"][i])
        bw, bh = int(data["width"][i]), int(data["height"][i])
        out.append(OCRBox(text=text, confidence=max(0.0, min(1.0, conf)), bbox=[x, y, x + bw, y + bh]))
    return out


def run_mock(path: Path) -> list[OCRBox]:
    name = path.name.lower()
    if "conflicting" in name:
        return [
            OCRBox("Heritage Foods", .99, [80, 80, 300, 125]),
            OCRBox("Premium Milk", .99, [80, 145, 330, 190]),
            OCRBox("NET QUANTITY 500 ml", .98, [80, 230, 330, 270]),
            OCRBox("MRP Rs. 99", .99, [80, 310, 230, 350]),
            OCRBox("MRP Rs. 109", .98, [450, 310, 610, 350]),
            OCRBox("Mfd: 08/2026", .97, [80, 385, 250, 425]),
            OCRBox("Customer Care 1800-000-000", .94, [80, 460, 370, 500]),
            OCRBox("Manufactured by Heritage Foods Ltd.", .97, [80, 535, 540, 575]),
            OCRBox("123 Industrial Area, New Delhi", .97, [80, 590, 460, 625]),
        ]
    if "missing" in name:
        return [
            OCRBox("FreshGlow Shampoo", .99, [80, 90, 360, 140]),
            OCRBox("NET QUANTITY 200 ml", .98, [80, 240, 330, 280]),
            OCRBox("MRP Rs. 249", .98, [80, 320, 240, 360]),
            OCRBox("Mfd: 07/2026", .96, [80, 395, 240, 430]),
        ]
    return [
        OCRBox("PureSip Aloe Face Wash", .99, [80, 85, 390, 135]),
        OCRBox("Manufactured by PureSip Industries Pvt Ltd.", .98, [80, 520, 560, 565]),
        OCRBox("123 Industrial Area, Bengaluru", .96, [80, 580, 520, 620]),
        OCRBox("NET QUANTITY 150 ml", .99, [80, 220, 320, 260]),
        OCRBox("MRP Rs. 299", .99, [80, 300, 240, 340]),
        OCRBox("Mfd: 08/2026", .96, [80, 390, 230, 425]),
        OCRBox("Customer Care: 1800-123-4567", .96, [80, 460, 430, 500]),
        OCRBox("Country of Origin: India", .95, [80, 650, 370, 690]),
    ]


def choose_backend(requested: str) -> tuple[str, str | None]:
    requested = requested.lower().strip()
    if requested in {"paddle", "tesseract", "mock"}:
        return requested, None
    try:
        import paddleocr  # noqa: F401
        return "paddle", None
    except Exception as exc:
        paddle_error = f"PaddleOCR unavailable: {exc}"
    try:
        import pytesseract  # noqa: F401
        return "tesseract", paddle_error
    except Exception as exc:
        return "mock", f"{paddle_error}; Tesseract unavailable: {exc}"


def run_ocr(path: Path, requested_backend: str) -> tuple[str, list[OCRBox], str | None]:
    backend, warning = choose_backend(requested_backend)
    if backend == "paddle":
        try:
            return backend, run_paddle(path), warning
        except Exception as exc:
            if requested_backend == "paddle":
                raise
            warning = f"PaddleOCR failed: {exc}"
            try:
                return "tesseract", run_tesseract(path), warning
            except Exception as texc:
                return "mock", run_mock(path), f"{warning}; Tesseract failed: {texc}"
    if backend == "tesseract":
        return backend, run_tesseract(path), warning
    return backend, run_mock(path), warning
