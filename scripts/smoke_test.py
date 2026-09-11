"""Deterministic semantic smoke test; PaddleOCR itself is exercised in deployment."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.ocr import OCRBox
from app.declarations.extractor import extract_fields
from app.compliance import evaluate, load_rules
from app.config import RULES_PATH

boxes = [
    OCRBox("Manufactured by: ABC Foods Pvt Ltd", .98, [10, 10, 340, 32], original_text="Manufactured by: ABC Foods Pvt Ltd"),
    OCRBox("Address: 12 Market Road, Delhi 110001", .96, [10, 42, 360, 64], original_text="Address: 12 Market Road, Delhi 110001"),
    OCRBox("NET WT 70G", .96, [10, 74, 180, 96], original_text="NET WT 70G"),
    OCRBox("M.R.P. Rs. 20/-", .98, [10, 106, 180, 128], original_text="M.R.P. Rs. 20/-"),
    OCRBox("MFD: 08/2026", .97, [10, 138, 170, 160], original_text="MFD: 08/2026"),
    OCRBox("Consumer Care: 18001234567", .96, [10, 170, 280, 192], original_text="Consumer Care: 18001234567"),
]
fields = extract_fields(boxes)
assert fields["mrp"]["value"] == "20"
assert fields["net_quantity"]["value"] == "70 g"
assert fields["date"]["value"] == "08/2026"
result = evaluate([{"boxes": boxes, "image_id": "fixture", "quality": {"sharpness_score": 90, "contrast_score": 90, "glare_score": 95, "quality_score": 90, "text_visibility_score": 50}}], load_rules(RULES_PATH))
assert all(check["status"] != "FAIL" for check in result["checks"] if not check["field"].get("detected"))
print("semantic extraction and no-false-fail smoke test passed")

# Split declarations across OCR boxes must join into single fields.
split_boxes = [
    OCRBox("MRP", .97, [10, 10, 70, 32], original_text="MRP"),
    OCRBox("Rs 120", .95, [10, 38, 120, 60], original_text="Rs 120"),
    OCRBox("MFD BY", .94, [10, 70, 120, 92], original_text="MFD BY"),
    OCRBox("ABC Foods Pvt Ltd", .96, [10, 98, 320, 120], original_text="ABC Foods Pvt Ltd"),
    OCRBox("MFD:", .93, [10, 130, 80, 152], original_text="MFD:"),
    OCRBox("08/2026", .95, [90, 130, 200, 152], original_text="08/2026"),
]
split_fields = extract_fields(split_boxes)
assert split_fields["mrp"]["value"] == "120", split_fields["mrp"]
assert split_fields["mrp"]["normalized_value"] == 120.0
assert "ABC Foods" in (split_fields["manufacturer"]["value"] or ""), split_fields["manufacturer"]
assert split_fields["date"]["value"] == "08/2026", split_fields["date"]
assert split_fields["mrp"]["source_text"] is not None and split_fields["mrp"]["bbox"] is not None
print("split-box join and MFD disambiguation smoke test passed")
