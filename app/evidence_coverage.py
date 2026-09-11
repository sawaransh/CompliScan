from __future__ import annotations

PANEL_FIELDS = ["manufacturer", "address", "net_quantity", "mrp", "date", "consumer_care", "country_of_origin"]

def apply_coverage(fields: dict, image_results: list[dict]) -> dict:
    # Seeing declarations establishes field coverage; otherwise quality/text density is only weak evidence.
    quality = max((item["quality"].get("quality_score", 0) for item in image_results), default=0) / 100
    for key, field in fields.items():
        if key.startswith("_") or key == "readability": continue
        if field.get("detected"):
            field["coverage"] = round(min(.99, .65 + field.get("confidence", 0)*.35), 3)
        elif key == "product_name":
            field["coverage"] = round(quality*.45, 3)
        else:
            field["coverage"] = round(quality*.32, 3)
    return fields

def capture_recommendation(fields: dict, image_results: list[dict]) -> dict:
    unresolved = [key for key in PANEL_FIELDS if fields.get(key, {}).get("coverage", 0) < .65]
    if not unresolved:
        return {"capture_required": False, "inspection_ready": True, "reason": "Enough evidence has been captured for the current screening assessment.", "expected_fields": []}
    candidate = max(image_results, key=lambda r: r["quality"].get("text_visibility_score", 0), default=None)
    if candidate and candidate["quality"].get("width") and candidate["quality"].get("height"):
        width, height = candidate["quality"]["width"], candidate["quality"]["height"]
        bbox, target = [int(width*.08), int(height*.40), int(width*.92), int(height*.92)], candidate.get("image_id", "")
    else: bbox, target = None, None
    return {"capture_required": True, "inspection_ready": False, "target_image_id": target, "target_bbox": bbox, "reason": "The small-print declaration panel is not sufficiently evidenced yet.", "expected_fields": unresolved, "capture_instruction": "Move closer to the highlighted small-print information panel; keep the text flat, sharp and glare-free."}
