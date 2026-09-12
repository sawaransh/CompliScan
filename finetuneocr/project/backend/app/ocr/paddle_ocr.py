import cv2
import numpy as np
import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


def _iou(a: List[int], b: List[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _text_key(text: str) -> str:
    return re.sub(r"[^a-z0-9₹]+", "", _normalize_text(text).lower())


def _box_area(box: List[int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _clip_bbox(box: List[int], width: Optional[int] = None, height: Optional[int] = None) -> List[int]:
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    if width is not None:
        x1, x2 = max(0, x1), min(width - 1, x2)
    if height is not None:
        y1, y2 = max(0, y1), min(height - 1, y2)
    return [x1, y1, x2, y2]


def merge_ocr_results(*groups: List[Dict[str, Any]], iou_thresh: float = 0.45) -> List[Dict[str, Any]]:
    """Union OCR passes; keep stronger duplicate evidence."""
    candidates: List[Dict[str, Any]] = []
    for group in groups:
        for item in group or []:
            text = _normalize_text(str(item.get("text", "")))
            bbox = item.get("bbox") or [0, 0, 0, 0]
            if not text or _box_area(bbox) <= 0:
                continue
            normalized = dict(item)
            normalized["text"] = text
            normalized["bbox"] = _clip_bbox(bbox)
            normalized["confidence"] = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
            candidates.append(normalized)

    candidates.sort(
        key=lambda r: (
            -float(r["confidence"]),
            -len(_text_key(r["text"])),
            -_box_area(r["bbox"]),
        )
    )

    merged: List[Dict[str, Any]] = []
    for cand in candidates:
        cand_key = _text_key(cand["text"])
        duplicate_index = None
        for idx, existing in enumerate(merged):
            existing_key = _text_key(existing["text"])
            same_text = cand_key and existing_key and (cand_key in existing_key or existing_key in cand_key)
            if _iou(cand["bbox"], existing["bbox"]) > iou_thresh or (same_text and _iou(cand["bbox"], existing["bbox"]) > 0.15):
                duplicate_index = idx
                break
        if duplicate_index is None:
            merged.append(cand)
            continue

        existing = merged[duplicate_index]
        cand_score = cand["confidence"] + min(len(cand_key), 40) / 100.0
        existing_score = existing["confidence"] + min(len(_text_key(existing["text"])), 40) / 100.0
        if cand_score > existing_score:
            merged[duplicate_index] = cand

    merged.sort(key=lambda r: (((r["bbox"][1] + r["bbox"][3]) // 2), r["bbox"][0]))
    return merged


class PaddleOCREngine:
    def __init__(self, use_angle_cls: bool = True, lang: str = 'en'):
        self.use_angle_cls = use_angle_cls
        self.lang = lang
        self.ocr = None
        logger.info("PaddleOCR engine configured for lazy initialization")

    def _ensure_ocr(self):
        if self.ocr is not None:
            return
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - depends on optional runtime wheels
            raise RuntimeError(f"PaddleOCR is not installed or could not be imported: {exc}") from exc
        # Tuned for small dense label text (nutrition panels, MRP print):
        # - lower det thresholds so faint/small text is still proposed
        # - larger unclip ratio to keep tiny boxes from collapsing
        # - higher limit side so downscaling doesn't erase small print
        # - lower drop_score so weak recognitions are kept (rule engine
        #   decides PASS vs REVIEW, not the OCR layer)
        import os
        free = os.getenv("OCR_FREE_TIER") == "1"
        try:
            self.ocr = PaddleOCR(
                use_angle_cls=False if free else self.use_angle_cls,
                lang=self.lang,
                show_log=False,
                det_db_thresh=0.3,
                det_db_box_thresh=0.4,
                det_db_unclip_ratio=2.0,
                det_limit_side_len=1600 if free else 2880,
                det_limit_type='max',
                drop_score=0.3,
            )
        except Exception as e:
            logger.warning(f"Tuned PaddleOCR init failed ({e}), using defaults")
            self.ocr = PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                show_log=False,
            )
        logger.info("PaddleOCR initialized")

    @staticmethod
    def _poly_to_bbox(bbox_points) -> List[int]:
        """Convert 4-point polygon (or rect) to [x1, y1, x2, y2]."""
        try:
            pts = np.array(bbox_points, dtype=float).reshape(-1, 2)
            xs, ys = pts[:, 0], pts[:, 1]
            return _clip_bbox([int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys))])
        except Exception:
            return [0, 0, 0, 0]

    def _parse_result(self, result) -> List[Dict[str, Any]]:
        """Handle both PaddleOCR 2.x ([[[box,(txt,conf)]]]) and 3.x/PaddleX (dicts)."""
        ocr_results: List[Dict[str, Any]] = []
        if not result:
            return ocr_results
        try:
            # PaddleX style: [{'boxes': [...], 'rec_texts': [...], 'rec_scores': [...]}]
            if isinstance(result, list) and result and isinstance(result[0], dict):
                for page in result:
                    boxes = page.get("boxes") or page.get("dt_polys") or page.get("rec_polys") or []
                    texts = page.get("rec_texts") or page.get("texts") or []
                    scores = page.get("rec_scores") or page.get("scores") or []
                    for i, box in enumerate(boxes):
                        txt = texts[i] if i < len(texts) else ""
                        conf = float(scores[i]) if i < len(scores) else 0.0
                        txt = _normalize_text(str(txt))
                        if not txt:
                            continue
                        ocr_results.append({
                            "text": txt,
                            "bbox": self._poly_to_bbox(box),
                            "confidence": max(0.0, min(1.0, conf)),
                        })
                return ocr_results

            # Classic 2.x style: [[ [box, (text, conf)], ... ]]
            pages = result[0] if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list) else result
            lines = pages

            def _is_line(obj) -> bool:
                # line = [box_polygon, (text, score)]
                if not isinstance(obj, (list, tuple)) or len(obj) < 2:
                    return False
                box, rec = obj[0], obj[1]
                if not isinstance(box, (list, tuple)) or not box:
                    return False
                # box is a list of [x, y] points
                first_pt = box[0] if isinstance(box, (list, tuple)) else None
                if not isinstance(first_pt, (list, tuple)) or len(first_pt) < 2:
                    return False
                if not isinstance(first_pt[0], (int, float)):
                    return False
                return isinstance(rec, (list, tuple)) and len(rec) >= 1 and isinstance(rec[0], str)

            # Only flatten when we have pages-of-lines, not lines themselves.
            if lines and not _is_line(lines[0]):
                maybe_pages = True
                for pg in lines:
                    if not isinstance(pg, (list, tuple)):
                        maybe_pages = False
                        break
                    for ln in pg:
                        if not _is_line(ln):
                            maybe_pages = False
                            break
                if maybe_pages:
                    flat = []
                    for pg in lines:
                        flat.extend(pg)
                    lines = flat
            for line in lines:
                if not line or len(line) < 2:
                    continue
                bbox_points, rec = line[0], line[1]
                if isinstance(rec, (list, tuple)):
                    text = str(rec[0]) if len(rec) > 0 else ""
                    confidence = float(rec[1]) if len(rec) > 1 else 0.0
                else:
                    text, confidence = str(rec), 0.0
                text = _normalize_text(text)
                if not text:
                    continue
                ocr_results.append({
                    "text": text,
                    "bbox": self._poly_to_bbox(bbox_points),
                    "confidence": max(0.0, min(1.0, confidence)),
                })
        except Exception as e:
            logger.warning(f"OCR parse fallback: {e}")
        return ocr_results

    def detect_text(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Run OCR on the image and return structured results.

        Returns:
            List of dicts with keys: text, bbox, confidence
            bbox format: [x1, y1, x2, y2] (top-left, bottom-right)
            in the SAME pixel space as the input image.
        """
        if image is None or image.size == 0:
            return []
        # PaddleOCR works on 3-channel images; ensure that.
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        try:
            self._ensure_ocr()
            try:
                result = self.ocr.ocr(image, cls=True)
            except TypeError:
                # newer PaddleOCR removed cls kwarg
                result = self.ocr.ocr(image)
            ocr_results = self._parse_result(result)
            logger.info(f"OCR detected {len(ocr_results)} text regions")
            return ocr_results
        except Exception as e:
            logger.error(f"OCR error: {e}")
            raise


def get_ocr_engine() -> PaddleOCREngine:
    return PaddleOCREngine()
