from __future__ import annotations

import json
from pathlib import Path

from .extract import extract_fields
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
    fields = extract_fields(merged_boxes)
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
            status, reason = "FAIL", "Required declaration was not extracted from the provided images."
        elif field["confidence"] < 0.55:
            status, reason = "REVIEW", "Declaration was detected, but OCR confidence is low; officer verification recommended."
        else:
            status, reason = "PASS", "Declaration extracted with sufficient OCR confidence for this prototype."
        checks.append({"id": key, "label": rule["label"], "status": status, "reason": reason, "field": field})

    mrp_values = []
    for image_result in image_results:
        mrp_values.extend(image_result["fields"].get("_mrp_values", []))
    unique_mrp = sorted({round(v, 2) for v in mrp_values})
    conflicts = []
    if len(unique_mrp) > 1:
        conflicts.append({"type": "MRP_CONFLICT", "values": unique_mrp, "severity": "HIGH", "message": "Different MRP values were extracted across provided package images. Officer verification required."})

    failed = sum(1 for c in checks if c["status"] == "FAIL") + len(conflicts)
    review = sum(1 for c in checks if c["status"] == "REVIEW")
    passed = sum(1 for c in checks if c["status"] == "PASS")
    overall = "NON-COMPLIANT" if failed else "REVIEW" if review else "COMPLIANT"
    return {"overall_status": overall, "summary": {"passed": passed, "failed": failed, "review": review, "total_checks": len(checks)+len(conflicts)}, "checks": checks, "conflicts": conflicts, "fields": {k:v for k,v in fields.items() if not k.startswith("_")}}
