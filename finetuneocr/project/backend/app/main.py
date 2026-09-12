from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import cv2
import numpy as np
import logging
import time
from typing import List

from app.models.schemas import AnalysisResponse, HealthResponse, MultiAnalysisResponse
from app.preprocessing.image_processing import (
    build_ocr_variants,
    scale_bboxes_to_original,
    encode_image_to_base64,
    decode_upload,
    assess_quality,
)
from app.ocr.paddle_ocr import get_ocr_engine, merge_ocr_results
from app.ocr.rapid_ocr import get_rapid_engine
from app.extraction.field_extractor import get_field_extractor
from app.compliance.rule_engine import get_rule_engine
from app.evidence.annotator import get_annotator, encode_image_to_base64 as annotator_encode

import os
FREE_TIER = os.getenv("OCR_FREE_TIER") == "1"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 5


def _unrotate_box(bbox: List[int], w: int, h: int, code: int) -> List[int]:
    """Map a bbox from a cv2-rotated image back to original coords."""
    x1, y1, x2, y2 = bbox
    if code == cv2.ROTATE_90_CLOCKWISE:  # (x,y) -> (H-1-y, x)
        return [y1, h - 1 - x2, y2, h - 1 - x1]
    if code == cv2.ROTATE_90_COUNTERCLOCKWISE:  # (x,y) -> (y, W-1-x)
        return [w - 1 - y2, x1, w - 1 - y1, x2]
    if code == cv2.ROTATE_180:  # (x,y) -> (W-1-x, H-1-y)
        return [w - 1 - x2, h - 1 - y2, w - 1 - x1, h - 1 - y1]
    return bbox

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="CompliScan API",
    description="Packaged Commodity Compliance Scanner",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize lightweight components. OCR models are loaded lazily on first scan.
ocr_engine = get_ocr_engine()
rapid_engine = get_rapid_engine()
field_extractor = get_field_extractor()
rule_engine = get_rule_engine()
annotator = get_annotator()

@app.on_event("startup")
async def _prewarm_paddle():
    # On Render free, first POST would otherwise download 16MB + init Paddle inside the 30s request window and 502.
    # Warm in background on deploy so the first officer scan is ~5s, not 30s+timeout. Fits 512MB because FREE_TIER uses single variant + 1280px cap.
    if FREE_TIER:
        logger.info("Free tier: skipping Paddle pre-warm (RapidONNX only, ~80MB)")
        return
    if os.getenv("OCR_PREWARM", "1") == "1":
        try:
            logger.info("Pre-warming PaddleOCR in background (download once, cached at /opt/render/.paddleocr)")
            await asyncio.to_thread(ocr_engine._ensure_ocr)
            logger.info("PaddleOCR pre-warm complete")
        except Exception as e:
            logger.warning(f"Paddle pre-warm skipped: {e}")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        service="CompliScan API",
        version="1.0.0"
    )


async def _decode_and_validate(contents: bytes, filename: str) -> np.ndarray:
    """Size-guard + HEIC/EXIF-safe decode shared by single & multi endpoints."""
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{filename}: image too large (max 10MB)")
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail=f"{filename}: empty file")
    try:
        original_image = await asyncio.to_thread(decode_upload, contents)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{filename}: {exc}")
    h0, w0 = original_image.shape[:2]
    if max(h0, w0) > 6000 or min(h0, w0) < 32:
        raise HTTPException(status_code=400, detail=f"{filename}: image dimensions out of range")
    return original_image


async def _ocr_single_image(original: np.ndarray, tag: str, processing_steps: List[str]):
    """Full OCR stack for ONE image: variants + RapidOCR + rotation fallback.

    Returns (ocr_results, quality, ocr_errors). All bboxes are in the
    original image's pixel space.
    """
    h0, w0 = original.shape[:2]
    original, ocr_variants = build_ocr_variants(original)

    ocr_groups: List[List[dict]] = []
    ocr_errors = []
    if FREE_TIER:
        # Free 512MB: RapidONNX only (~80MB) — Paddle alone needs 300MB+ and 502s on Render free even with single variant.
        try:
            _, enhanced_img, enhanced_scale = ocr_variants[0]
            rapid_results = await asyncio.to_thread(rapid_engine.detect_text, enhanced_img)
            if enhanced_scale != 1.0 and rapid_results:
                rapid_results = scale_bboxes_to_original(rapid_results, enhanced_scale)
            for item in rapid_results:
                item["source_variant"] = "rapid"
            ocr_groups.append(rapid_results)
            processing_steps.append(f"[{tag}] rapid: {len(rapid_results)} text regions")
        except Exception as exc:
            logger.warning(f"[{tag}] RapidOCR variant failed: {exc}")
    else:
        for variant_name, variant_image, scale in ocr_variants:
            try:
                variant_results = await asyncio.to_thread(ocr_engine.detect_text, variant_image)
                if scale != 1.0 and variant_results:
                    variant_results = scale_bboxes_to_original(variant_results, scale)
                for item in variant_results:
                    item["source_variant"] = variant_name
                ocr_groups.append(variant_results)
                processing_steps.append(f"[{tag}] {variant_name}: {len(variant_results)} text regions")
            except Exception as exc:
                message = f"[{tag}] {variant_name}: OCR failed ({exc})"
                ocr_errors.append(message)
                processing_steps.append(message)
                logger.warning(message)
        try:
            _, enhanced_img, enhanced_scale = ocr_variants[0]
            rapid_results = await asyncio.to_thread(rapid_engine.detect_text, enhanced_img)
            if enhanced_scale != 1.0 and rapid_results:
                rapid_results = scale_bboxes_to_original(rapid_results, enhanced_scale)
            for item in rapid_results:
                item["source_variant"] = "rapid"
            ocr_groups.append(rapid_results)
            processing_steps.append(f"[{tag}] rapid: {len(rapid_results)} text regions")
        except Exception as exc:
            logger.warning(f"[{tag}] RapidOCR variant failed: {exc}")

    ocr_results = merge_ocr_results(*ocr_groups) if ocr_groups else []
    quality = assess_quality(original, ocr_results)

    if not FREE_TIER:
        readable = [r for r in ocr_results if r.get("text", "").strip()]
        if len(readable) < 3 or quality.get("suspicious_layout"):
            for code, label in ((cv2.ROTATE_90_CLOCKWISE, "rot90"),
                                (cv2.ROTATE_180, "rot180"),
                                (cv2.ROTATE_90_COUNTERCLOCKWISE, "rot270")):
                try:
                    rotated = cv2.rotate(original, code)
                    rot_results = await asyncio.to_thread(ocr_engine.detect_text, rotated)
                    rot_readable = [r for r in rot_results if r.get("text", "").strip()]
                    if len(rot_readable) > len(readable):
                        for item in rot_results:
                            item["bbox"] = _unrotate_box(item["bbox"], w0, h0, code)
                            item["source_variant"] = label
                        ocr_results = rot_results
                        quality = assess_quality(original, ocr_results)
                        processing_steps.append(f"[{tag}] {label}: recovered {len(rot_results)} regions (replaced bad pass)")
                        break
                except Exception as exc:
                    logger.warning(f"[{tag}] Rotation pass {label} failed: {exc}")
    processing_steps.append(f"[{tag}] merged OCR: {len(ocr_results)} unique text regions")
    return ocr_results, quality, ocr_errors


def _merge_fields_across_images(per_image_fields: List[List[dict]]) -> List[dict]:
    """One verdict per product: keep each declaration's strongest evidence,
    remembering which image it came from."""
    best = {}
    for fields in per_image_fields:
        for f in fields:
            cur = best.get(f["name"])
            if cur is None or f["confidence"] > cur["confidence"]:
                best[f["name"]] = f
    order = ["product_name", "mrp", "net_quantity", "manufacturer",
             "manufacturing_date", "consumer_care", "packer", "importer"]
    return sorted(best.values(),
                  key=lambda f: order.index(f["name"]) if f["name"] in order else 99)


def _combine_quality(quals: List[dict]) -> dict:
    """Product-level quality: only weak if EVERY image is weak."""
    return {
        "blurry": bool(quals) and all(q["blurry"] for q in quals),
        "tiny_text": bool(quals) and all(q["tiny_text"] for q in quals),
        "suspicious_layout": bool(quals) and all(q.get("suspicious_layout") for q in quals),
        "blur_score": min([q["blur_score"] for q in quals]) if quals else 0.0,
        "median_text_height_px": min([q["median_text_height_px"] for q in quals]) if quals else 0.0,
        "ocr_regions": sum(q["ocr_regions"] for q in quals),
        "images": quals,
    }


def _apply_quality_gate(compliance_result: dict, quality: dict, processing_steps: List[str]):
    """Downgrade would-be COMPLIANT to REVIEW when evidence is insufficient."""
    if compliance_result["status"] == "COMPLIANT" and (
        quality["blurry"] or quality["tiny_text"] or quality.get("suspicious_layout")
    ):
        reasons = []
        if quality["blurry"]:
            reasons.append(f"photo looks blurry (sharpness {quality['blur_score']})")
        if quality["tiny_text"]:
            reasons.append(
                f"declaration print looks too small to verify "
                f"(median text height {quality['median_text_height_px']}px)"
            )
        if quality.get("suspicious_layout"):
            reasons.append("text layout looks unreadable (photo may be sideways)")
        compliance_result["status"] = "REVIEW_REQUIRED"
        compliance_result["review_items"].append({
            "rule_id": "PC-QUALITY-001",
            "field": "readability",
            "requirement": "Declarations must be legible in the uploaded photo",
            "reason": "Photo quality is insufficient for a reliable verdict: "
                      + " and ".join(reasons)
                      + ". Please retake a sharp, straight-on, well-lit photo.",
            "evidence": f"blur_score={quality['blur_score']}, "
                        f"median_text_height={quality['median_text_height_px']}px, "
                        f"ocr_regions={quality['ocr_regions']}",
            "bbox": None,
            "confidence": 0.0,
        })
        processing_steps.append("Quality gate: downgraded to REVIEW_REQUIRED (photo quality)")


def _fields_to_schema(extracted_fields: List[dict]) -> List[dict]:
    return [
        {
            "name": f["name"],
            "value": f["value"],
            "confidence": f["confidence"],
            "bbox": f["bbox"],
            "source_text": f["source_text"],
            "source_image": f.get("source_image"),
            "source_filename": f.get("source_filename"),
        }
        for f in extracted_fields
    ]


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_product(image: UploadFile = File(...)):
    """
    Analyze a SINGLE product package image for Legal Metrology compliance.
    """
    start_time = time.time()
    processing_steps = []

    try:
        filename = image.filename or "image"
        contents = await image.read()
        original_image = await _decode_and_validate(contents, filename)
        h0, w0 = original_image.shape[:2]
        processing_steps.append(f"Image loaded: {w0}x{h0}")

        ocr_results, quality, ocr_errors = await _ocr_single_image(original_image, filename, processing_steps)

        processing_steps.append("Extracting declarations...")
        extracted_fields = field_extractor.extract_fields(ocr_results)
        for f in extracted_fields:
            f["source_image"] = 0
            f["source_filename"] = filename
        processing_steps.append(f"Extracted {len(extracted_fields)} fields")

        processing_steps.append("Checking Legal Metrology rules...")
        compliance_result = rule_engine.evaluate_compliance(
            extracted_fields,
            ocr_results=ocr_results,
            ocr_errors=ocr_errors,
            photo_quality=quality,
        )

        _apply_quality_gate(compliance_result, quality, processing_steps)
        processing_steps.append(f"Compliance status: {compliance_result['status']}")

        processing_steps.append("Preparing evidence...")
        annotated = annotator.create_annotated_image(
            original_image, ocr_results, extracted_fields, compliance_result["checks"]
        )
        response = AnalysisResponse(
            status=compliance_result["status"],
            fields=_fields_to_schema(extracted_fields),
            checks=compliance_result["checks"],
            violations=compliance_result["violations"],
            review_items=compliance_result["review_items"],
            annotated_image=annotator_encode(annotated),
            original_image=encode_image_to_base64(original_image),
            ocr_results=ocr_results,
            processing_steps=processing_steps,
            quality=quality,
        )

        elapsed = time.time() - start_time
        logger.info(f"Analysis completed in {elapsed:.2f}s")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/api/analyze-multi", response_model=MultiAnalysisResponse)
async def analyze_product_multi(images: List[UploadFile] = File(...)):
    """
    Analyze MULTIPLE images of ONE product (front/back/sides) and produce a
    single compliance verdict. Each declaration uses its strongest evidence
    across all images; the verdict is FAIL only on sharp, confident reads.
    """
    start_time = time.time()
    processing_steps = []

    try:
        if not images:
            raise HTTPException(status_code=400, detail="No images uploaded")
        if len(images) > MAX_IMAGES:
            raise HTTPException(status_code=413, detail=f"Max {MAX_IMAGES} images per product")

        # Decode everything first so a bad file fails fast.
        decoded = []
        for idx, upl in enumerate(images):
            filename = upl.filename or f"image-{idx + 1}"
            contents = await upl.read()
            original_image = await _decode_and_validate(contents, filename)
            h, w = original_image.shape[:2]
            decoded.append({"filename": filename, "image": original_image, "w": w, "h": h})
            processing_steps.append(f"Image {idx + 1}/{len(images)} loaded: {filename} ({w}x{h})")

        # OCR + field extraction per image.
        per_image_ocr = []
        per_image_fields = []
        per_image_quality = []
        all_ocr_errors = []
        for idx, item in enumerate(decoded):
            tag = f"img{idx + 1}:{item['filename']}"
            ocr_results, quality, ocr_errors = await _ocr_single_image(
                item["image"], tag, processing_steps)
            fields = field_extractor.extract_fields(ocr_results)
            for f in fields:
                f["source_image"] = idx
                f["source_filename"] = item["filename"]
            processing_steps.append(f"[{tag}] extracted {len(fields)} fields")
            per_image_ocr.append(ocr_results)
            per_image_fields.append(fields)
            per_image_quality.append(quality)
            all_ocr_errors.extend(ocr_errors)

        # One product-level verdict from the strongest evidence per field.
        processing_steps.append("Merging declarations across images...")
        merged_fields = _merge_fields_across_images(per_image_fields)
        processing_steps.append(f"Merged to {len(merged_fields)} unique declarations")

        combined_ocr = [r for group in per_image_ocr for r in group]
        combined_quality = _combine_quality(per_image_quality)

        processing_steps.append("Checking Legal Metrology rules...")
        compliance_result = rule_engine.evaluate_compliance(
            merged_fields,
            ocr_results=combined_ocr,
            ocr_errors=all_ocr_errors,
            photo_quality=combined_quality,
        )
        _apply_quality_gate(compliance_result, combined_quality, processing_steps)
        processing_steps.append(f"Compliance status: {compliance_result['status']}")

        # Per-image evidence, annotated with the product-level check colours.
        processing_steps.append("Preparing evidence...")
        image_results = []
        for idx, item in enumerate(decoded):
            annotated = annotator.create_annotated_image(
                item["image"], per_image_ocr[idx], per_image_fields[idx],
                compliance_result["checks"],
            )
            image_results.append({
                "index": idx,
                "filename": item["filename"],
                "width": item["w"],
                "height": item["h"],
                "ocr_regions": len(per_image_ocr[idx]),
                "fields": _fields_to_schema(per_image_fields[idx]),
                "ocr_results": per_image_ocr[idx],
                "annotated_image": annotator_encode(annotated),
                "original_image": encode_image_to_base64(item["image"]),
                "quality": per_image_quality[idx],
            })

        response = MultiAnalysisResponse(
            status=compliance_result["status"],
            fields=_fields_to_schema(merged_fields),
            checks=compliance_result["checks"],
            violations=compliance_result["violations"],
            review_items=compliance_result["review_items"],
            images=image_results,
            processing_steps=processing_steps,
            quality=combined_quality,
        )

        elapsed = time.time() - start_time
        logger.info(f"Multi-image analysis ({len(images)} images) completed in {elapsed:.2f}s")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multi analysis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
