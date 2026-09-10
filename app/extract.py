from __future__ import annotations

import re
from typing import Iterable

from .ocr import OCRBox


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def joined(boxes: Iterable[OCRBox]) -> str:
    return "\n".join(clean_text(b.text) for b in boxes)


def find_box(boxes: list[OCRBox], keywords: list[str]) -> OCRBox | None:
    for box in boxes:
        low = box.text.lower()
        if any(k and k.lower() in low for k in keywords):
            return box
    return None


def parse_first(pattern: str, text: str, flags: int = re.I) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def extract_fields(boxes: list[OCRBox]) -> dict:
    text = joined(boxes)
    manufacturer = parse_first(
        r"(?:manufactured\s*(?:by|&\s*packed\s*by)|manufactured\s*and\s*packed\s*by|mfd\.?\s*(?:by|&\s*pkd\.?\s*by)|packed\s*by|imported\s*by)\s*[:\-]?\s*([^\n]+)", text)
    address = parse_first(r"(?:address)\s*[:\-]?\s*([^\n]+)", text)
    if not address:
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        for idx, line in enumerate(lines):
            if any(k in line.lower() for k in ["manufactured", "packed by", "imported by"]):
                if idx + 1 < len(lines) and any(ch.isdigit() for ch in lines[idx + 1]):
                    address = lines[idx + 1]
                    break

    mrp_values = []
    for m in re.finditer(r"(?:m\.?\s*r\.?\s*p\.?\s*[:\-]?\s*(?:rs\.?|inr)?\s*|maximum\s+retail\s+price\s*[:\-]?\s*(?:rs\.?|inr)?\s*)(\d+(?:\.\d{1,2})?)", text, re.I):
        mrp_values.append(float(m.group(1)))
    mrp = mrp_values[0] if mrp_values else None

    qty = parse_first(r"(?:net\s*(?:quantity|qty|wt|weight|contents?)|net)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml|cl|pcs?|pieces?)\b", text)
    net_quantity = qty
    date = parse_first(r"(?:mfd|mfg|manufactured|packed|packing|best\s*before|date)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{2,4}|\d{2,4}[/-]\d{1,2})", text)
    consumer = parse_first(r"(?:customer\s*care|consumer\s*care|care\s*line|helpline|toll\s*free)\s*[:\-]?\s*([^\n]+)", text)
    if not consumer:
        consumer = parse_first(r"\b(1\d{9,12})\b", text)
    origin = parse_first(r"country\s+of\s+origin\s*[:\-]?\s*([^\n]+)", text)

    product_name = None
    labels = ["mrp", "net", "manufactured", "packed", "customer", "consumer", "country", "mfd", "mfg"]
    for box in boxes:
        low = box.text.lower().strip()
        if len(re.findall(r"[a-zA-Z]", box.text)) >= 3 and not any(k in low for k in labels):
            if len(box.text.strip()) >= 4:
                product_name = box.text.strip()
                break

    def field_value(value, keywords: list[str], fallback_conf: float = 0.55) -> dict:
        box = find_box(boxes, keywords)
        return {
            "value": value,
            "detected": value is not None,
            "confidence": round(box.confidence if box else (fallback_conf if value is not None else 0.0), 3),
            "bbox": box.bbox if box else None,
        }

    return {
        "product_name": field_value(product_name, [product_name] if product_name else []),
        "manufacturer": field_value(manufacturer, ["manufactured", "mfd", "packed by", "imported by"]),
        "address": field_value(address, ["address", address] if address else ["plot", "road", "industrial", "new delhi", "bengaluru"]),
        "net_quantity": field_value(net_quantity, ["net"]),
        "mrp": field_value(mrp, ["mrp", "maximum retail price"]),
        "date": field_value(date, ["mfd", "mfg", "manufactured", "packed"]),
        "consumer_care": field_value(consumer, ["customer care", "consumer care", "helpline", "toll free"]),
        "country_of_origin": field_value(origin, ["country of origin"]),
        "_mrp_values": mrp_values,
    }
