import cv2
import numpy as np
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class RapidOCREngine:
    """Second OCR opinion via PP-OCRv4 ONNX (lightweight, no torch).

    Optional by design: if the package/models are unavailable the engine
    reports unavailable and the pipeline continues with PaddleOCR only.
    Output format matches PaddleOCREngine: text/bbox/confidence dicts.
    """

    def __init__(self):
        self.available = False
        self.ocr = None
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR()
            self.available = True
            logger.info("RapidOCR initialized")
        except Exception as e:
            logger.warning(f"RapidOCR unavailable, continuing without it: {e}")

    @staticmethod
    def _poly_to_bbox(box) -> List[int]:
        try:
            pts = np.array(box, dtype=float).reshape(-1, 2)
            return [int(np.min(pts[:, 0])), int(np.min(pts[:, 1])),
                    int(np.max(pts[:, 0])), int(np.max(pts[:, 1]))]
        except Exception:
            return [0, 0, 0, 0]

    def detect_text(self, image: np.ndarray) -> List[Dict[str, Any]]:
        if not self.available or image is None or image.size == 0:
            return []
        try:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if len(image.shape) == 3 else image
            out = self.ocr(rgb)
            # rapidocr returns (results, elapse); be tolerant of plain lists
            results = out[0] if isinstance(out, tuple) else out
            parsed = []
            for item in results or []:
                try:
                    box, text, conf = item[0], str(item[1]), float(item[2])
                except Exception:
                    continue
                if not text.strip():
                    continue
                parsed.append({
                    "text": text.strip(),
                    "bbox": self._poly_to_bbox(box),
                    "confidence": max(0.0, min(1.0, conf)),
                })
            logger.info(f"RapidOCR detected {len(parsed)} text regions")
            return parsed
        except Exception as e:
            logger.warning(f"RapidOCR pass failed: {e}")
            return []


def get_rapid_engine() -> RapidOCREngine:
    return RapidOCREngine()
