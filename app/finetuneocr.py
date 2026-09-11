"""Client for the working finetuneocr OCR service.

The mobile app feeds captures here; this module forwards normalized image
bytes to the finetuneocr backend (``POST /api/analyze`` per image) and maps its
``ocr_results`` into our :class:`OCRBox` model. Everything downstream —
extraction, coverage, compliance, evidence, dashboard — is unchanged.

If the OCR service is unreachable we fail loudly with startup guidance.
There is deliberately no silent local fallback.
"""
from __future__ import annotations

import logging
import os

import cv2

from .ocr import OCRBox

log = logging.getLogger("compliscan.finetuneocr")

FINETUNEOCR_URL = os.getenv("FINETUNEOCR_URL", "http://127.0.0.1:8001").rstrip("/")
FINETUNEOCR_TIMEOUT = float(os.getenv("FINETUNEOCR_TIMEOUT", "180"))
PROVIDER_NAME = "finetuneocr"


def service_health() -> dict:
    """Reachability probe used by /api/health. Never raises."""
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(f"{FINETUNEOCR_URL}/health", timeout=5) as res:
            payload = json.loads(res.read())
        return {"reachable": True, "service": payload.get("service"), "version": payload.get("version")}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)[:160]}


def recognize_image(image, filename: str, image_id: str) -> list[OCRBox]:
    """Send one image to the finetuneocr OCR service, return standard boxes."""
    import urllib.request
    import urllib.error
    import json
    import uuid

    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("Could not encode capture for OCR service.")
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename or "capture.jpg"}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + bytes(encoded) + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{FINETUNEOCR_URL}/api/analyze", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=FINETUNEOCR_TIMEOUT) as res:
            payload = json.loads(res.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "")
        except Exception:
            detail = ""
        raise RuntimeError(f"OCR service rejected the image ({exc.code}): {detail}") from exc
    except Exception as exc:
        raise RuntimeError(
            f"OCR service not reachable at {FINETUNEOCR_URL} ({exc}). "
            "Start it first — see run.sh."
        ) from exc

    boxes: list[OCRBox] = []
    for item in payload.get("ocr_results", []):
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            x1, y1, x2, y2 = (int(v) for v in item.get("bbox", [0, 0, 0, 0]))
        except Exception:
            continue
        try:
            conf = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
        except Exception:
            conf = 0.0
        boxes.append(OCRBox(text, conf, [x1, y1, x2, y2], image_id=image_id, original_text=text))
    return boxes
