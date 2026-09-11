from __future__ import annotations
import re
from ..ocr import OCRBox
from .normalizer import normalize, normalize_for_match

# Window-join guards: lines farther apart than this are never one declaration.
MAX_WINDOW_GAP = 120
MAX_VALUE_GAP = 140
MIN_WINDOW_CONFIDENCE = 0.35
MAX_WINDOW_WIDTH = 3


def _lines(boxes: list[OCRBox]) -> list[list[OCRBox]]:
    """Row-aware line grouping: bucket by centre height, sort left-to-right."""
    groups: list[list[OCRBox]] = []
    for box in sorted(boxes, key=lambda b: (b.bbox[1], b.bbox[0])):
        cy = (box.bbox[1] + box.bbox[3]) / 2
        for group in groups:
            gy = sum((b.bbox[1]+b.bbox[3])/2 for b in group)/len(group)
            if abs(cy-gy) <= max(14, (box.bbox[3]-box.bbox[1])*.8): group.append(box); break
        else: groups.append([box])
    # Row-major order fixes inverted reads such as a value box above its label.
    ordered = [sorted(g, key=lambda b: b.bbox[0]) for g in groups]
    ordered.sort(key=lambda g: ((g[0].bbox[1]+g[0].bbox[3])//2, g[0].bbox[0]))
    return ordered


def _line_text(line: list[OCRBox]) -> str:
    return " ".join(b.normalized_text or b.text for b in line)


def _line_conf(line: list[OCRBox]) -> float:
    return sum(b.confidence for b in line) / len(line) if line else 0.0


def _gap(prev: list[OCRBox], nxt: list[OCRBox]) -> float:
    return nxt[0].bbox[1] - prev[-1].bbox[3]


def _union_box(boxes: list[OCRBox]) -> list[int]:
    return [min(b.bbox[0] for b in boxes), min(b.bbox[1] for b in boxes),
            max(b.bbox[2] for b in boxes), max(b.bbox[3] for b in boxes)]


def _field(value, box, semantic=.8, normalized_value=None):
    return {"value": value, "normalized_value": normalized_value if normalized_value is not None else value, "detected": value is not None, "confidence": round((box.confidence * semantic) if box and value is not None else 0, 3), "ocr_confidence": round(box.confidence, 3) if box else 0, "semantic_confidence": semantic if value is not None else 0, "coverage": 0.0, "bbox": box.bbox if box else None, "image_id": box.image_id if box else None, "source_text": box.original_text if box else None, "officer_verified": False}


def _match_windows(entries: list[tuple[str, OCRBox]], pattern: str) -> tuple[str | None, OCRBox | None]:
    """Try 1-3 consecutive lines so split declarations ("MRP" / "Rs 120") join.

    Windows with a low-confidence line or a large vertical gap are rejected;
    wider windows pay a small penalty so single-line hits win ties.
    """
    best: tuple[float, str, OCRBox] | None = None
    for i in range(len(entries)):
        window_boxes: list[OCRBox] = []
        for width in range(1, MAX_WINDOW_WIDTH + 1):
            if i + width > len(entries): break
            text, box = entries[i + width - 1]
            window_boxes.append(box)
            if box.confidence < MIN_WINDOW_CONFIDENCE: break
            if width > 1 and _gap([entries[i + width - 2][1]], [box]) > MAX_WINDOW_GAP: break
            joined = " ".join(entries[i + k][0] for k in range(width))
            match = re.search(pattern, joined, re.I)
            if not match: continue
            conf = sum(b.confidence for b in window_boxes) / len(window_boxes)
            score = conf - 0.03 * (width - 1) + min(len(joined), 30) * 0.001
            if best is None or score > best[0]:
                best = (score, match.group(1).strip(), window_boxes[0])
    return (best[1], best[2]) if best else (None, None)


def _nearby_value(entries: list[tuple[str, OCRBox]], label_re: str, value_re: str) -> tuple[str | None, OCRBox | None]:
    """Label on one line, value on a nearby line (handles split MRP/qty)."""
    best: tuple[float, str, OCRBox] | None = None
    for i, (text, box) in enumerate(entries):
        if not re.search(label_re, text, re.I): continue
        window = [box]
        for width in range(1, 5):
            if i + width >= len(entries): break
            nxt = entries[i + width][1]
            if nxt.confidence < MIN_WINDOW_CONFIDENCE: break
            if _gap(window, [nxt]) > MAX_VALUE_GAP: break
            window.append(nxt)
            joined = " ".join(entries[i + k][0] for k in range(width + 1))
            hit = re.search(value_re, joined, re.I)
            if not hit: continue
            conf = sum(b.confidence for b in window) / len(window)
            score = conf - 0.02 * width + min(len(hit.group(1)), 30) * 0.002
            if best is None or score > best[0]:
                best = (score, hit.group(1).strip(), box)
    return (best[1], best[2]) if best else (None, None)


MFR_STOP = re.compile(r"mrp|net\s*(wt|quantity|weight)|mfg|mfd\s*:|exp|1800|1860|helpline|care|fssai|lic\.?\s*no|ingredients?|nutrition", re.I)


def _manufacturer_block(entries: list[tuple[str, OCRBox]]) -> tuple[str | None, OCRBox | None]:
    """Assemble multi-line manufacturer/packer blocks, stopping at next section."""
    for i, (text, box) in enumerate(entries):
        if not re.search(r"(manufactured|packed\s*by|imported\s*by|mfd\s+by|mktd?\s*by)", text, re.I): continue
        if re.search(r"\bmfd\s*:", text, re.I) and "by" not in text.lower(): continue
        collected = [text]
        for j in range(i + 1, min(i + 5, len(entries))):
            nxt_text, nxt_box = entries[j]
            if nxt_box.confidence < MIN_WINDOW_CONFIDENCE: break
            if _gap([entries[j - 1][1]], [nxt_box]) > MAX_VALUE_GAP: break
            if MFR_STOP.search(nxt_text) or len(" ".join(collected)) > 200: break
            collected.append(nxt_text)
        return " ".join(collected), box
    return None, None


def _product_name(entries: list[tuple[str, OCRBox]]) -> tuple[str | None, OCRBox | None]:
    labels = ("mrp", "net", "manufact", "packed", "customer", "consumer", "country", "origin", "made in", "mfd", "mfg", "address")
    singletons = {"mrp", "net", "wt", "qty", "tax", "taxes", "rs", "g", "ml", "india"}
    best: tuple[float, str, OCRBox] | None = None
    total = max(1, len(entries))
    for idx, (text, box) in enumerate(entries):
        low = text.lower()
        letters = re.findall(r"[A-Za-z]", text)
        if len(letters) < 3 or len(text.strip()) < 4: continue
        if box.confidence < 0.4 or any(x in low for x in labels): continue
        if len(text.strip()) > 60: continue  # descriptions/addresses, not names
        if re.match(r"^\d", text.strip()): continue  # house numbers, quantities
        tokens = set(re.findall(r"[a-z]+", low))
        if tokens and tokens <= singletons: continue
        if re.search(r"mrp|net\s*wt|₹|\brs\b", low): continue
        if sum(ch.isdigit() for ch in text) / max(1, len(text)) > 0.4: continue
        height = box.bbox[3] - box.bbox[1]
        score = len(text) * (1 + height / 40) * box.confidence
        if re.match(r"^[A-Z][A-Z!&' ]{2,14}$", text.strip()): score *= 2.0
        score *= 1 + 0.5 * (1 - idx / total)  # brand/product sits near the top
        if best is None or score > best[0]:
            best = (score, text.strip(), box)
    return (best[1], best[2]) if best else (None, None)


def extract_fields(boxes: list[OCRBox], semantic_resolver=None) -> dict:
    for box in boxes: box.normalized_text = normalize(box.text)
    lines = _lines(boxes)
    entries = [(normalize_for_match(_line_text(line)), line[0]) for line in lines if line]

    mrp, mrp_box = _match_windows(entries, r"(?:MRP|maximum retail price)\s*[:\-]?\s*₹?\s*(\d+(?:\.\d{1,2})?)")
    if not mrp:
        mrp, mrp_box = _nearby_value(entries, r"MRP|maximum retail price", r"(?:₹|Rs\.?|INR)?\s*(\d+(?:\.\d{1,2})?)")
    qty, qty_box = _match_windows(entries, r"(?:net\s*(?:quantity|qty|wt|weight|contents?)|net)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml|cl|pcs?|pieces?)\b")
    if not qty:
        qty, qty_box = _nearby_value(entries, r"net\s*(?:quantity|qty|wt|weight|contents?)?", r"(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml|cl|pcs?|pieces?)\b")
    if qty and qty_box:
        unit_match = re.search(r"(kg|g|mg|l|ml|cl|pcs?|pieces?)\b", qty_box.normalized_text, re.I)
        if unit_match and unit_match.group(1).lower() not in qty.lower():
            qty = f"{qty} {unit_match.group(1).lower()}"
    date, date_box = _match_windows(entries, r"\b(?:mfd|mfg|manufacturing date|packed on|packing date|date of packing)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{2,4}|\d{2,4}[/-]\d{1,2})")
    manufacturer, manufacturer_box = _manufacturer_block(entries)
    if not manufacturer:
        manufacturer, manufacturer_box = _match_windows(entries, r"(?:manufactured\s*(?:by|and\s*packed\s*by)|packed\s*by|imported\s*by|mfd\s+by)\s*[:\-]?\s*(.+)")
    # Gemini is opt-in through GEMINI_API_KEY and only sees unresolved short labels.
    if semantic_resolver and semantic_resolver.enabled and not (manufacturer or date):
        for line, line_box in entries:
            if re.search(r"\bmfd\b", line, re.I):
                resolved = semantic_resolver.classify_label(line)
                if resolved and resolved.get("field") == "manufacturer": manufacturer, manufacturer_box = line, line_box
                break
    # MFD only means a company when followed by BY; a date uses the date pattern above.
    address, address_box = _match_windows(entries, r"(?:address|registered office)\s*[:\-]?\s*(.+)")
    if not address and manufacturer_box:
        idx = next((i for i, (_, b) in enumerate(entries) if b is manufacturer_box), -1)
        if idx >= 0 and idx+1 < len(entries) and any(c.isdigit() for c in entries[idx+1][0]): address, address_box = entries[idx+1]
    consumer, consumer_box = _match_windows(entries, r"(?:customer\s*care|consumer\s*care|care\s*line|helpline|toll\s*free)\s*[:\-]?\s*(.+)")
    origin, origin_box = _match_windows(entries, r"(?:country\s+of\s+origin|made\s+in)\s*[:\-]?\s*(.+)")
    product, product_box = _product_name(entries)
    merged = "\n".join(text for text, _ in entries)
    mrp_values = [float(m) for m in re.findall(r"(?:MRP|maximum retail price)\s*[:\-]?\s*₹?\s*(\d+(?:\.\d{1,2})?)", merged, re.I)]
    return {"product_name": _field(product, product_box, .70), "manufacturer": _field(manufacturer, manufacturer_box, .90), "address": _field(address, address_box, .78), "net_quantity": _field(qty, qty_box, .95), "mrp": _field(mrp, mrp_box, .97, float(mrp) if mrp else None), "date": _field(date, date_box, .92), "consumer_care": _field(consumer, consumer_box, .88), "country_of_origin": _field(origin, origin_box, .90), "_mrp_values": mrp_values}
