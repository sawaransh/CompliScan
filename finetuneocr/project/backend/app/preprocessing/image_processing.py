import cv2
import numpy as np
import base64
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


def preprocess_image(image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Preprocess image for better OCR results WITHOUT destroying detail.

    PaddleOCR already does its own internal preprocessing, so we keep this
    gentle: only resize extremes + mild denoise / contrast lift.
    The original image is never modified.

    Returns:
        Tuple of (original_image, preprocessed_image, scale)
        scale = processed_width / original_width, used to map OCR boxes
        back to original coordinates.
    """
    original = image.copy()
    h, w = original.shape[:2]

    # Step 1: normalize size.
    # Dense legal-declaration print is tiny; OCR needs pixels. Target
    # longest side ~1600px: upscale small images, downscale huge ones.
    max_dim = 2880
    min_dim = 1600
    scale = 1.0
    processed = original.copy()
    longest = max(h, w)
    if longest > max_dim:
        scale = max_dim / longest
        new_w, new_h = int(w * scale), int(h * scale)
        processed = cv2.resize(processed, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.info(f"Downscaled image from {w}x{h} to {new_w}x{new_h} (scale={scale:.3f})")
    elif longest < min_dim:
        scale = min_dim / longest
        # cap upscale at 2.5x to avoid huge blurry images
        scale = min(scale, 2.5)
        new_w, new_h = int(w * scale), int(h * scale)
        processed = cv2.resize(processed, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        logger.info(f"Upscaled image from {w}x{h} to {new_w}x{new_h} (scale={scale:.3f})")

    # Step 2: mild denoise only (preserve edges/text).
    # fastNlMeans on color is slow; use small bilateral filter.
    try:
        denoised = cv2.bilateralFilter(processed, 5, 50, 50)
    except Exception:
        denoised = processed

    # Step 3: gentle contrast lift on L channel (LAB) instead of
    # aggressive grayscale CLAHE + sharpen which was destroying text.
    try:
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        l = clahe.apply(l)
        processed = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    except Exception:
        processed = denoised

    logger.info("Image preprocessing completed")
    return original, processed, scale


def build_ocr_variants(image: np.ndarray) -> Tuple[np.ndarray, List[Tuple[str, np.ndarray, float]]]:
    """
    Build OCR-ready variants while keeping every bbox mappable to original pixels.

    Returns:
        original image and a list of (variant_name, variant_image, scale).
    """
    import os
    FREE_TIER = os.getenv("OCR_FREE_TIER") == "1"
    original, enhanced, scale = preprocess_image(image)
    if FREE_TIER:
        # Free 512MB: single variant keeps Paddle at ~300MB instead of 600MB for 5 variants.
        return original, [("enhanced", enhanced, scale)]
    variants: List[Tuple[str, np.ndarray, float]] = [
        ("enhanced", enhanced, scale),
        ("original", original, 1.0),
    ]

    h, w = enhanced.shape[:2]
    if h > 0 and w > 0:
        gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)

        # CLAHE grayscale helps faint black-on-color declarations without
        # throwing away coordinates or relying on one threshold setting.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)
        variants.append(("gray-clahe", cv2.cvtColor(gray_clahe, cv2.COLOR_GRAY2BGR), scale))

        # A mild unsharp mask often recovers tiny MRP/date print after camera blur.
        blur = cv2.GaussianBlur(gray_clahe, (0, 0), 1.0)
        sharp = cv2.addWeighted(gray_clahe, 1.55, blur, -0.55, 0)
        variants.append(("sharp", cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR), scale))

        # Adaptive threshold is useful for nutrition/manufacturer panels and
        # printed black text on noisy packaging. Kept as a separate pass because
        # it can damage stylised brand text.
        block = max(21, min(61, (min(h, w) // 30) | 1))
        binary = cv2.adaptiveThreshold(
            gray_clahe,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            9,
        )
        variants.append(("binary", cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR), scale))

    return original, variants


def scale_bboxes_to_original(ocr_results: list, scale: float) -> list:
    """Map OCR bboxes from processed-image coords back to original coords."""
    if not scale or scale == 1.0:
        return ocr_results
    inv = 1.0 / scale
    for r in ocr_results:
        x1, y1, x2, y2 = r["bbox"]
        r["bbox"] = [int(x1 * inv), int(y1 * inv), int(x2 * inv), int(y2 * inv)]
    return ocr_results


def decode_upload(contents: bytes) -> np.ndarray:
    """Decode an uploaded file to BGR, handling phone-photo pitfalls.

    - cv2.imdecode alone fails on HEIC/HEIF (iPhone default) and silently
      ignores EXIF orientation (sideways photos -> garbage OCR).
    - PIL + pillow-heif + exif_transpose fixes both; OpenCV is the fallback.
    """
    try:
        import io
        from PIL import Image, ImageOps
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except Exception:
            pass
        pil = Image.open(io.BytesIO(contents))
        pil = ImageOps.exif_transpose(pil)
        if pil.mode in ("RGBA", "LA", "PA"):
            bg = Image.new("RGB", pil.size, (255, 255, 255))
            bg.paste(pil, mask=pil.split()[-1])
            pil = bg
        else:
            pil = pil.convert("RGB")
        arr = np.array(pil)
        if arr.size == 0:
            raise ValueError("empty image")
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception as e:
        logger.warning(f"PIL decode failed ({e}), trying OpenCV")
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unsupported or corrupt image file (use JPG/PNG/WEBP/HEIC)")
    return image


def assess_quality(image: np.ndarray, ocr_results: list) -> dict:
    """Spec S14 prototype: blur + tiny-text readability signals.

    Never claims legal font-size compliance from pixels; only flags
    low-evidence cases so the pipeline can ask for a clearer photo
    instead of declaring a false violation.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    heights = sorted(
        r["bbox"][3] - r["bbox"][1]
        for r in (ocr_results or [])
        if r.get("text", "").strip()
    )
    median_h = float(heights[len(heights) // 2]) if heights else 0.0
    # A "text line" taller than a quarter of the photo's short side is
    # almost never real text: sideways photo, motion streak, or a giant
    # false detection. Treat as insufficient evidence, not a verdict.
    suspicious = bool(median_h > 0.25 * min(h, w)) and len(heights) > 0
    quality = {
        "blur_score": round(blur_score, 1),
        "blurry": bool(blur_score < 25.0),
        "median_text_height_px": round(median_h, 1),
        "tiny_text": bool(0 < median_h < 12.0),
        "suspicious_layout": suspicious,
        "ocr_regions": len(heights),
    }
    logger.info(f"Quality: blur={blur_score:.1f} median_h={median_h:.1f}px regions={len(heights)} suspicious={suspicious}")
    return quality


def encode_image_to_base64(image: np.ndarray) -> str:
    """Encode image to data-URL base64 string for <img src> display."""
    _, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    b64 = base64.b64encode(buffer).decode('utf-8')
    return f"data:image/jpeg;base64,{b64}"


def decode_base64_to_image(base64_str: str) -> np.ndarray:
    """Decode base64 string to OpenCV image."""
    try:
        # Remove data URL prefix if present
        if base64_str.startswith('data:image'):
            base64_str = base64_str.split(',')[1]
        
        img_data = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return image
    except Exception as e:
        logger.error(f"Failed to decode base64 image: {e}")
        raise


def get_image_dimensions(image: np.ndarray) -> Tuple[int, int]:
    """Get image width and height."""
    h, w = image.shape[:2]
    return w, h
