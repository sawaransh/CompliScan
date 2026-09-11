"""OCR orchestration: decode → variants → PaddleOCR (+ deliberate RapidOCR pass) → merge.

One intentional pipeline: every pass is tagged with provenance in
``OCRBox.image_id`` (``<id>:<variant>`` / ``<id>:rapid`` / ``<id>:rotation``)
and reconciled deterministically. No fallback switching: a hard PaddleOCR
failure raises instead of returning other-engine results silently.
"""
from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

log = logging.getLogger("compliscan.ocr")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DIMENSION = 6000
MIN_DIMENSION = 32
# Longest side target window: shrink huge phone photos, enlarge tiny crops.
# 1600 keeps small print readable while keeping CPU inference times sane
# (a 12MP photo at 2880px needs minutes per scan; at 1600px, under a minute).
DOWNSCALE_TO = 1600
UPSCALE_TO = 1600
UPSCALE_CAP = 2.5
MERGE_IOU = 0.45
MERGE_IOU_SUBSTRING = 0.15
SUPPORTED_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


@dataclass
class OCRBox:
    text: str
    confidence: float
    bbox: list[int]
    image_id: str = ""
    line_id: str = ""
    block_id: str = ""
    original_text: str = ""
    normalized_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class OCRProvider(Protocol):
    """Application code consumes this standard result, never engine objects."""
    name: str
    def recognize(self, image: np.ndarray, image_id: str = "") -> list[OCRBox]: ...


# ============================================================
# Decode + validation (PIL-first: EXIF orientation, HEIC, RGBA)
# ============================================================
def decode_upload(contents: bytes) -> np.ndarray:
    """Decode uploaded bytes to BGR, honouring EXIF orientation and HEIC."""
    if not contents:
        raise ValueError("Empty image file.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Image exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit.")
    image: np.ndarray | None = None
    try:
        from PIL import Image, ImageOps
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except Exception:
            pass
        with Image.open(io.BytesIO(contents)) as pil:
            pil = ImageOps.exif_transpose(pil)
            if pil.mode in ("RGBA", "LA", "PA"):
                canvas = Image.new("RGB", pil.size, (255, 255, 255))
                canvas.paste(pil, mask=pil.split()[-1])
                pil = canvas
            else:
                pil = pil.convert("RGB")
            image = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception:
        image = None
    if image is None or image.size == 0:
        raw = np.frombuffer(contents, dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("Unsupported or corrupt image file (use JPG/PNG/WEBP/HEIC).")
    height, width = image.shape[:2]
    if max(height, width) > MAX_DIMENSION or min(height, width) < MIN_DIMENSION:
        raise ValueError(f"Image dimensions out of range ({width}x{height}).")
    return image


def prepare_upload(contents: bytes, filename: str, upload_dir: Path, idx: int) -> tuple[Path, np.ndarray]:
    """Decode once, then persist a normalized file every later stage can read."""
    image = decode_upload(contents)
    suffix = Path(filename or ".jpg").suffix.lower() or ".jpg"
    if suffix not in SUPPORTED_SUFFIXES:
        suffix = ".jpg"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"image_{idx}{suffix}"
    cv2.imwrite(str(path), image)
    return path, image


# ============================================================
# Quality scoring (unchanged contract: dict consumed by UI + gates)
# ============================================================
def image_quality(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast, glare = float(gray.std()), float(np.mean(gray > 245))
    text_edges = float(np.mean(cv2.Canny(gray, 60, 160) > 0))
    scores = {"sharpness_score": round(min(100.0, sharpness / 8.0), 1), "contrast_score": round(min(100.0, contrast * 2.2), 1), "glare_score": round(max(0.0, 100.0 - glare * 220.0), 1), "text_visibility_score": round(min(100.0, text_edges * 800), 1)}
    quality_score = round(.4*scores["sharpness_score"] + .3*scores["contrast_score"] + .2*scores["glare_score"] + .1*scores["text_visibility_score"], 1)
    if scores["glare_score"] < 45: guidance = "Too much glare. Change the angle and avoid reflected light."
    elif scores["sharpness_score"] < 35: guidance = "Image is blurred. Hold the camera steady and focus on the text."
    elif scores["text_visibility_score"] < 12: guidance = "Text is too small or low contrast. Move closer to the declaration panel."
    else: guidance = "Image quality is suitable for analysis."
    return {"width": int(image.shape[1]), "height": int(image.shape[0]), "sharpness_raw": round(sharpness, 2), "contrast_raw": round(contrast, 2), "glare_ratio": round(glare, 4), **scores, "quality_score": quality_score, "decision": "GOOD_TO_ANALYZE" if quality_score >= 42 else "RETAKE_REQUIRED", "guidance": guidance}


def assess_readability(image: np.ndarray, boxes: list[OCRBox]) -> dict:
    """Post-OCR readability signals: tiny-text and layout warnings for review."""
    heights = sorted(b.bbox[3] - b.bbox[1] for b in boxes if b.text.strip())
    median_h = float(heights[len(heights) // 2]) if heights else 0.0
    blur = float(cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
    height, width = image.shape[:2]
    return {
        "blur_score": round(blur, 1),
        "blurry": blur < 25.0,
        "median_text_height_px": round(median_h, 1),
        "tiny_text": 0.0 < median_h < 12.0,
        "suspicious_layout": bool(heights) and median_h > 0.25 * min(height, width),
        "ocr_regions": len(heights),
    }


# ============================================================
# Preprocessing variants (all bbox-mappable to original pixels)
# ============================================================
def normalize_size(image: np.ndarray) -> tuple[np.ndarray, float]:
    longest = max(image.shape[:2])
    if longest > DOWNSCALE_TO:
        scale = DOWNSCALE_TO / longest
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale
    if longest < UPSCALE_TO:
        scale = min(UPSCALE_TO / longest, UPSCALE_CAP)
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC), scale
    return image, 1.0


def _to_bgr(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def preprocess_variants(image: np.ndarray) -> dict[str, tuple[np.ndarray, float]]:
    """OCR-ready variants plus each variant's scale relative to the original."""
    original = image.copy()
    sized, scale = normalize_size(image)
    # LAB-space denoise + gentle contrast lift preserves colour edges for print.
    try:
        denoised = cv2.bilateralFilter(sized, 5, 50, 50)
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        lightness, green_red, blue_yellow = cv2.split(lab)
        clahe_lab = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced = cv2.cvtColor(cv2.merge([clahe_lab.apply(lightness), green_red, blue_yellow]), cv2.COLOR_LAB2BGR)
    except Exception:
        enhanced = sized
    gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    try:
        gray_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    except Exception:
        gray_clahe = gray
    blurred = cv2.GaussianBlur(gray_clahe, (0, 0), 1.0)
    sharpened = cv2.addWeighted(gray_clahe, 1.55, blurred, -0.55, 0)
    try:
        block = max(21, min(61, (min(gray_clahe.shape[:2]) // 30) | 1))
        binary = cv2.adaptiveThreshold(gray_clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 9)
    except Exception:
        binary = gray_clahe
    return {
        "enhanced": (enhanced, scale),
        "original": (original, 1.0),
        "gray-clahe": (_to_bgr(gray_clahe), scale),
        "sharp": (_to_bgr(sharpened), scale),
        "binary": (_to_bgr(binary), scale),
    }


# ============================================================
# Providers
# ============================================================
def _paddle_boxes(result: Any, image_id: str) -> list[OCRBox]:
    payload = result
    try:
        raw = getattr(payload, "json", payload); raw = raw() if callable(raw) else raw
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except Exception: pass
    payload = getattr(payload, "res", payload)
    if isinstance(payload, dict) and isinstance(payload.get("res"), dict): payload = payload["res"]
    if isinstance(payload, dict):
        texts = payload.get("rec_texts") or payload.get("texts") or []
        scores = payload.get("rec_scores") or payload.get("scores") or []
        boxes = payload.get("rec_boxes") or payload.get("dt_polys") or payload.get("boxes") or []
    elif isinstance(payload, list):
        # Classic PaddleOCR 2.x line format: [[poly, (text, score)], ...].
        texts, scores, boxes = [], [], []
        for item in payload:
            try:
                poly, (text, score) = item[0], item[1]
            except Exception:
                continue
            boxes.append(poly); texts.append(text); scores.append(score)
    else:
        return []
    if isinstance(texts, str): texts = [texts]
    out: list[OCRBox] = []
    for i, raw_text in enumerate(texts):
        text = str(raw_text).strip()
        if not text: continue
        arr = np.asarray(boxes[i] if i < len(boxes) else [[0, 0], [0, 0]]).astype(float).reshape(-1, 2)
        bbox = [int(arr[:, 0].min()), int(arr[:, 1].min()), int(arr[:, 0].max()), int(arr[:, 1].max())]
        score = float(scores[i]) if i < len(scores) else 0.0
        out.append(OCRBox(text, max(0, min(1, score)), bbox, image_id=image_id, original_text=text))
    return out


class PaddleOCRProvider:
    name = "paddle"
    def __init__(self) -> None:
        from paddleocr import PaddleOCR
        base: dict[str, Any] = {"lang": "en", "use_doc_orientation_classify": False, "use_doc_unwarping": False, "use_textline_orientation": False}
        # Tuned detection keeps weak/small print for downstream merging.
        tuned_new = dict(base, text_det_thresh=0.3, text_det_box_thresh=0.4, text_det_unclip_ratio=2.0, text_det_limit_side_len=1600, text_det_limit_type="max", drop_score=0.3)
        tuned_old = dict(base, det_db_thresh=0.3, det_db_box_thresh=0.4, det_db_unclip_ratio=2.0, det_limit_side_len=1600, det_limit_type="max", drop_score=0.3)
        for kwargs in (tuned_new, tuned_old, base):
            try:
                self._ocr = PaddleOCR(**kwargs)
                return
            except Exception:
                continue
        raise RuntimeError("PaddleOCR could not be initialised")
    def recognize(self, image: np.ndarray, image_id: str = "") -> list[OCRBox]:
        return [box for result in self._ocr.predict(input=image) for box in _paddle_boxes(result, image_id)]


class RapidOCRProvider:
    """Deliberate second pass over the enhanced variant, merged deterministically.

    Not a fallback: it runs alongside PaddleOCR on every scan and its boxes
    carry ``:rapid`` provenance. Absence (missing dependency) only logs.
    """
    name = "rapid"
    def __init__(self) -> None:
        self.available = False
        try:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            self.available = True
        except Exception as exc:
            log.warning("RapidOCR pass disabled: %s", exc)
    def recognize(self, image: np.ndarray, image_id: str = "") -> list[OCRBox]:
        if not self.available:
            return []
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if image.ndim == 3 else image
        out = self._ocr(rgb)
        results = out[0] if isinstance(out, tuple) else out
        boxes: list[OCRBox] = []
        for item in results or []:
            try:
                poly, text, score = item[0], item[1], item[2]
            except Exception:
                continue
            text = str(text).strip()
            if not text:
                continue
            arr = np.asarray(poly).astype(float).reshape(-1, 2)
            bbox = [int(arr[:, 0].min()), int(arr[:, 1].min()), int(arr[:, 0].max()), int(arr[:, 1].max())]
            boxes.append(OCRBox(text, max(0.0, min(1.0, float(score))), bbox, image_id=image_id, original_text=text))
        return boxes


# ============================================================
# Deterministic merge with provenance
# ============================================================
def _text_key(text: str) -> str:
    return re.sub(r"[^a-z0-9₹]+", "", text.lower())


def _box_area(bbox: list[int]) -> int:
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def _iou(a: list[int], b: list[int]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2-x1) * max(0, y2-y1); union = max(1, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)
    return inter / union


def _merge_score(box: OCRBox) -> float:
    return box.confidence + min(len(_text_key(box.text)), 40) / 100


def reconcile_variant_boxes(boxes: list[OCRBox]) -> list[OCRBox]:
    """Greedy union: same text strongly overlapping, or same text nearby.

    On conflict the higher (confidence + length-preference) box wins, so a
    longer reading at similar confidence replaces a truncated one. Provenance
    in ``image_id`` survives; output is in row-major reading order.
    """
    candidates = [b for b in boxes if b.text.strip() and _box_area(b.bbox) > 0]
    ranked = sorted(candidates, key=lambda b: (_merge_score(b), _box_area(b.bbox)), reverse=True)
    kept: list[OCRBox] = []
    for cand in ranked:
        ckey = _text_key(cand.text)
        duplicate = False
        for i, old in enumerate(kept):
            okey = _text_key(old.text)
            iou = _iou(cand.bbox, old.bbox)
            same_text = bool(ckey) and (ckey == okey or ckey in okey or okey in ckey)
            if iou > MERGE_IOU or (same_text and iou > MERGE_IOU_SUBSTRING):
                if _merge_score(cand) > _merge_score(old):
                    kept[i] = cand
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
    kept.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) // 2, b.bbox[0]))
    return kept


def _unrotate_bbox(bbox: list[int], width: int, height: int, rotation: int) -> list[int]:
    """Map a box recognised on a rotated copy back into original pixel space."""
    x1, y1, x2, y2 = bbox
    if rotation == cv2.ROTATE_90_CLOCKWISE:
        return [y1, height - 1 - x2, y2, height - 1 - x1]
    if rotation == cv2.ROTATE_90_COUNTERCLOCKWISE:
        return [width - 1 - y2, x1, width - 1 - y1, x2]
    if rotation == cv2.ROTATE_180:
        return [width - 1 - x2, height - 1 - y2, width - 1 - x1, height - 1 - y1]
    return bbox


def run_ocr(path: Path, image_id: str = "") -> tuple[str, list[OCRBox], str | None]:
    """Single intentional pipeline; every box stays in original coordinates."""
    try:
        image = decode_upload(Path(path).read_bytes())
    except ValueError as exc:
        raise ValueError(f"Unable to read image {path}: {exc}") from exc
    global _PADDLE_PROVIDER, _RAPID_PROVIDER
    try:
        if _PADDLE_PROVIDER is None:
            _PADDLE_PROVIDER = PaddleOCRProvider()
        provider = _PADDLE_PROVIDER
    except Exception as exc: raise RuntimeError("PaddleOCR is required for analysis. Install paddlepaddle and paddleocr before scanning.") from exc
    if _RAPID_PROVIDER is None:
        _RAPID_PROVIDER = RapidOCRProvider()
    rapid = _RAPID_PROVIDER
    variants = preprocess_variants(image)
    all_boxes: list[OCRBox] = []
    for variant_name, (variant, scale) in variants.items():
        try:
            found = provider.recognize(variant, f"{image_id}:{variant_name}")
        except Exception as exc:
            if variant_name == "original": raise RuntimeError(f"PaddleOCR could not analyze the image: {exc}") from exc
            continue
        if scale != 1.0:
            for box in found:
                box.bbox = [round(v / scale) for v in box.bbox]
        all_boxes.extend(found)
    # Deliberate RapidOCR pass over the enhanced variant (tagged, merged).
    try:
        enhanced, rapid_scale = variants["enhanced"]
        for box in rapid.recognize(enhanced, f"{image_id}:rapid"):
            if rapid_scale != 1.0:
                box.bbox = [round(v / rapid_scale) for v in box.bbox]
            all_boxes.append(box)
    except Exception as exc:
        log.warning("RapidOCR pass failed: %s", exc)

    # Labels photographed sideways are common in the field. Recover when the
    # normal pass found very little text, or the layout looks rotated
    # (a few giant boxes spanning the frame). The fast path stays fast.
    merged = reconcile_variant_boxes(all_boxes)
    readability = assess_readability(image, merged)
    if len(merged) < 3 or readability["suspicious_layout"]:
        height, width = image.shape[:2]
        best = merged
        for rotation in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
            try:
                rotated = cv2.rotate(image, rotation)
                recovered = provider.recognize(rotated, f"{image_id}:rotation")
                for box in recovered:
                    box.bbox = _unrotate_bbox(box.bbox, width, height, rotation)
                if len(recovered) > len(best): best = recovered
            except Exception:
                continue
        merged = reconcile_variant_boxes(best)
    return provider.name, merged, None


# Module-level singletons: model weights load once per process, not per image.
_PADDLE_PROVIDER: OCRProvider | None = None
_RAPID_PROVIDER: RapidOCRProvider | None = None
