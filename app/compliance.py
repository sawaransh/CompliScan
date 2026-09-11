from __future__ import annotations

import json
from pathlib import Path

from .declarations.extractor import extract_fields
from .evidence_coverage import apply_coverage, capture_recommendation
from .ocr import OCRBox


def load_rules(path: Path) -> dict:
    return json.loads(path.read_text())


def readability_score(quality_by_image: list[dict]) -> float:
    if not quality_by_image:
        return 0.0
    vals = [0.45*q["sharpness_score"] + 0.35*q["contrast_score"] + 0.20*q["glare_score"] for q in quality_by_image]
    return round(sum(vals) / len(vals), 1)


def evaluate(image_results: list[dict], rules: dict) -> dict:
    merged_boxes: list[OCRBox] = []
    for image_result in image_results:
        merged_boxes.extend(image_result["boxes"])
    fields = apply_coverage(extract_fields(merged_boxes), image_results)
    readability = readability_score([x["quality"] for x in image_results])
    fields["readability"] = {"value": readability, "detected": True, "confidence": round(readability/100.0, 3), "bbox": None}

    checks = []
    for rule in rules["checks"]:
        key = rule["id"]
        if key == "readability":
            status = "PASS" if readability >= 65 else "REVIEW" if readability >= 45 else "FAIL"
            checks.append({"id": key, "label": rule["label"], "status": status, "reason": f"Composite image-quality/readability score: {readability}/100 (prototype threshold).", "field": fields[key]})
            continue
        field = fields.get(key, {"detected": False, "confidence": 0, "value": None, "bbox": None})
        if not field["detected"]:
            status, reason = ("NOT_ASSESSABLE", "Required visual evidence has not been captured clearly enough; request a targeted close-up.") if field.get("coverage", 0) < .65 else ("REVIEW", "The declaration area appears captured, but text interpretation is uncertain.")
        elif field["confidence"] < 0.55:
            status, reason = "REVIEW", "Declaration was detected, but OCR confidence is low; officer verification recommended."
        else:
            status, reason = "PASS", "Declaration extracted with sufficient OCR confidence for this prototype."
        checks.append({"id": key, "label": rule["label"], "status": status, "reason": reason, "field": field})

    mrp_values = []
    for image_result in image_results:
        image_fields = image_result.get("fields") or extract_fields(image_result.get("boxes", []))
        mrp_values.extend(image_fields.get("_mrp_values", []))
    unique_mrp = sorted({round(v, 2) for v in mrp_values})
    conflicts = []
    if len(unique_mrp) > 1:
        conflicts.append({"type": "MRP_CONFLICT", "values": unique_mrp, "severity": "HIGH", "message": "Different MRP values were extracted across provided package images. Officer verification required."})

    failed = sum(1 for c in checks if c["status"] == "FAIL") + len(conflicts)
    review = sum(1 for c in checks if c["status"] == "REVIEW")
    passed = sum(1 for c in checks if c["status"] == "PASS")
    not_assessable = sum(1 for c in checks if c["status"] == "NOT_ASSESSABLE")
    overall = "NON-COMPLIANT" if failed else "REVIEW" if review or not_assessable else "COMPLIANT"
    # Photo-quality gate: never certify COMPLIANT on blurry/tiny-print evidence.
    # Every check passed but the text itself is unreliable → human review.
    if overall == "COMPLIANT":
        weak = [r for r in image_results if (r.get("quality") or {}).get("readability", {}).get("blurry") or (r.get("quality") or {}).get("readability", {}).get("tiny_text")]
        if weak and image_results:
            readability_field = dict(fields.get("readability", {}))
            readability_field["confidence"] = min(readability_field.get("confidence", 1), 0.5)
            checks.append({"id": "photo-quality", "label": "Photo quality for small print", "status": "REVIEW",
                           "reason": "All declarations read, but the photo evidence is blurry or the print is tiny; officer verification recommended.",
                           "field": readability_field})
            review += 1
            overall = "REVIEW"
    recommendation = capture_recommendation(fields, image_results)
    return {"overall_status": overall, "summary": {"passed": passed, "failed": failed, "review": review, "not_assessable": not_assessable, "total_checks": len(checks)+len(conflicts)}, "checks": checks, "conflicts": conflicts, "fields": {k:v for k,v in fields.items() if not k.startswith("_")}, "capture_recommendation": recommendation, "inspection_ready": recommendation["inspection_ready"]}
