import re
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def _clean(s: str, limit: int = 140) -> str:
    s = re.sub(r"\s+", " ", s or "").strip(" :.-")
    return s[:limit].strip()


def _ocr_normalize(s: str) -> str:
    """Normalize common OCR punctuation/spacing drift without changing evidence text."""
    s = s or ""
    s = s.replace("₹", " Rs ")
    s = re.sub(r"[|]", "I", s)
    # OCR often fuses label and value: "MRP120", "Rs20.00", "NETWT43g".
    s = re.sub(r"(?i)\bMRP(\d)", r"MRP \1", s)
    s = re.sub(r"(?i)\bRs\.?(\d)", r"Rs \1", s)
    s = re.sub(r"(?i)\bNET\s*WT\.?(\d)", r"NET WT \1", s)
    s = re.sub(r"\bM\s*R\s*P\b", "MRP", s, flags=re.I)
    s = re.sub(r"\bM\s*F\s*[GD]\b", "MFG", s, flags=re.I)
    s = re.sub(r"\bP\s*K\s*D\b", "PKD", s, flags=re.I)
    s = re.sub(r"\bE\s*X\s*P\b", "EXP", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _union_bbox(boxes: List[List[int]]) -> List[int]:
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    return [int(x1), int(y1), int(x2), int(y2)]


# Each entry: (compiled regex,). Value = whole match cleaned (best evidence).
FIELD_PATTERNS = {
    "mrp": [
        r"(?i)\bm[\.\s]*r[\.\s]*p\b(?:\s*\(?incl\.?\s*of\s*all\s*taxes\)?)?[\s:.-]*(?:maximum retail price)?[\s:.-]*(?:rs\.?|inr|₹)?\s*\d[\d,]*\.?\d{0,2}",
        r"(?i)maximum\s*retail\s*price[\s:.-]*(?:rs\.?|inr|₹)?\s*\d[\d,]*\.?\d{0,2}",
        r"₹\s*\d[\d,]*\.?\d{0,2}",
        r"(?i)\brs\.?\s*\d[\d,]*\.?\d{0,2}",
        r"(?i)\binr\s*\d[\d,]*\.?\d{0,2}",
    ],
    "net_quantity": [
        r"(?i)net\s*(quantity|qty\.?|wt\.?|weight|contents?)\s*[:.]?\s*\d[\d,.]*\s*(kg|g|gm|gms|grams?|ml|l|ltr|litre?s?|millilitre?s?)\b",
        r"(?i)\bnet\s*\d[\d,.]*\s*(kg|g|gm|gms|grams?|ml|l|ltr|litre?s?|millilitre?s?)\b",
        r"(?i)\b\d[\d,.]*\s*(kilograms?|grams?|millilitre?s?|litre?s?)\b",
        r"(?i)\b\d[\d,.]*\s*(kg|g|gm|gms|ml|ltr|l)\b",
    ],
    "manufacturer": [
        r"(?i)(manufactured|mfd\.?|packed|pkd\.?|imported|marketed|mkt\.?|mfg\.?)\s*\.?\s*by\b",
        r"(?i)\b(manufacturer|packer|importer|marketer)\b",
    ],
    "manufacturing_date": [
        r"(?i)\b(mfg|mfd|manufactured|packed|pkd|p\.?d\.?|exp|expiry|use\s*by|best\s*before)\b[\s:./-]*(?:date)?[\s:./-]*\d{1,2}[\s./-]+\d{1,2}[\s./-]+\d{2,4}",
        r"(?i)\b(mfg|mfd|manufactured|packed|pkd|p\.?d\.?|exp|expiry|use\s*by|best\s*before)\b[\s:./-]*(?:date)?[\s:./-]*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s./-]+\d{2,4}",
        r"(?i)\b(mfg|mfd|manufactured|packed|pkd|exp|expiry|best\s*before)\b[\s:./-]*\d{1,2}[\s./-]+\d{2,4}",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{1,2}[/-]\d{2,4}\b",
    ],
    "consumer_care": [
        r"(?i)(consumer\s*cares?|customer\s*cares?|helpline|toll\s*free|for\s*feedback|feedback|complaint|contact\s*us|email|e-mail|phone|tel)[\s:.-]*[\w\s@.+()-]{3,}",
        r"(?i)\bcares?\b[\s:.-]*[\w\s@.+()-]{3,}",
        r"(?i)\b(?:1800|1860|080|022|011)[\d\s-]{6,}\b",
        r"(?i)[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
    ],
}

MFR_KEYWORDS = ("manufactured by", "mfd by", "packed by", "pkd by", "imported by",
                "marketed by", "mkt by", "mfg by", "manufacturer", "packer", "importer")

# Lines looking like this are never the brand name.
NAME_BLOCKLIST = ("proprietary", "ingredient", "nutrition", "information", "manufactured",
                  "imported", "feedback", "complaint", "contact", "care", "fssai",
                  "lic ", "lic.", "licence", "license", "address", "bengaluru",
                  "gurgaon", "gurugram", "mumbai", "contains", "allergen", "marketed",
                  "table", "approx", "values", "protein", "carbohydrate", "trans fat")


class FieldExtractor:
    def __init__(self, min_confidence: float = 0.35):
        self.min_confidence = min_confidence
        self.compiled = {f: [re.compile(p) for p in ps] for f, ps in FIELD_PATTERNS.items()}

    def _ordered(self, ocr_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = [r for r in ocr_results if r.get("text", "").strip()]
        # Row-aware reading order: lines whose tops are within ~25px belong
        # to the same visual row (e.g. "MRP" + "120" split into two boxes),
        # sorted left-to-right inside the row. Plain y-sort put "120"
        # (y=74) before "MRP" (y=76) and broke "MRP 120" joins.
        rows.sort(key=lambda r: (((r["bbox"][1] + r["bbox"][3]) // 2) // 25, r["bbox"][0]))
        return rows

    def _window_text(self, window: List[Dict[str, Any]]) -> str:
        return _ocr_normalize(" ".join(w["text"] for w in window))

    def _nearby_value_window(self, label_patterns: List[str], value_pattern: str, rows: List[Dict[str, Any]]):
        """Pair split labels with nearby values, e.g. `MRP` + `Rs 120`."""
        label_res = [re.compile(p, re.I) for p in label_patterns]
        value_re = re.compile(value_pattern, re.I)
        best = None
        for i, row in enumerate(rows):
            if row["confidence"] < self.min_confidence:
                continue
            row_text = _ocr_normalize(row["text"])
            if not any(p.search(row_text) for p in label_res):
                continue
            candidates = rows[i:i + 5]
            for width in range(1, min(5, len(candidates)) + 1):
                window = candidates[:width]
                if any(w["confidence"] < self.min_confidence for w in window):
                    continue
                if width > 1 and window[-1]["bbox"][1] - window[0]["bbox"][3] > 140:
                    continue
                text = self._window_text(window)
                hit = value_re.search(text)
                if not hit:
                    continue
                value = _clean(text)
                conf = sum(w["confidence"] for w in window) / len(window)
                score = conf - (0.02 * width) + min(len(hit.group(0)), 30) * 0.002
                if best is None or score > best[0]:
                    best = (score, value, conf, _union_bbox([w["bbox"] for w in window]), text)
        if best:
            return best[1], best[2], best[3], best[4]
        return None

    def _match_windows(self, field: str, rows: List[Dict[str, Any]]):
        """Try 1-line, then 2-line and 3-line consecutive joins.

        Returns (value, avg_conf, bbox, source_text) or None.
        Joins fix the common split: 'MRP' in one box, 'Rs 20.00' in next.
        """
        best = None  # (score, value, conf, bbox, source)
        for width in (1, 2, 3):
            for i in range(len(rows) - width + 1):
                window = rows[i:i + width]
                if any(w["confidence"] < self.min_confidence for w in window):
                    continue
                # don't join lines far apart vertically (different blocks)
                if width > 1:
                    gap = window[-1]["bbox"][1] - window[0]["bbox"][3]
                    if gap > 120:
                        continue
                text = self._window_text(window)
                for pat in self.compiled[field]:
                    m = pat.search(text)
                    if not m:
                        continue
                    value = _clean(m.group(0))
                    if len(value) < 2:
                        continue
                    conf = sum(w["confidence"] for w in window) / len(window)
                    # prefer tight single-line hits over sprawling joins
                    score = conf - 0.03 * (width - 1) + min(len(value), 30) * 0.001
                    if best is None or score > best[0]:
                        best = (score, value, conf,
                                _union_bbox([w["bbox"] for w in window]), text.strip())
        if best:
            return best[1], best[2], best[3], best[4]
        return None

    def _manufacturer_value(self, rows: List[Dict[str, Any]]):
        """Keyword line + up to 2 following lines as the address block."""
        for i, r in enumerate(rows):
            if r["confidence"] < self.min_confidence:
                continue
            low = _ocr_normalize(r["text"]).lower().replace(".", "")
            if not any(k in low for k in MFR_KEYWORDS):
                continue
            block = [r]
            for nxt in rows[i + 1:i + 5]:
                t = nxt["text"].strip()
                if len(t) < 3 or nxt["confidence"] < self.min_confidence:
                    break
                # stop if next block is a different declaration
                if re.search(r"(?i)\b(mrp|net\s*(wt|quantity|weight)|mfg|exp|1800|1860|helpline|care|cares|fssai|lic\.?\s*no|ingredients?|nutrition)", t):
                    break
                block.append(nxt)
                if len(" ".join(b["text"] for b in block)) > 200:
                    break
            value = _clean(" ".join(b["text"] for b in block))
            conf = sum(b["confidence"] for b in block) / len(block)
            return value, conf, _union_bbox([b["bbox"] for b in block]), " | ".join(b["text"] for b in block)
        return None

    _NAME_SINGLETONS = {"mrp", "net", "wt", "quantity", "weight", "mfg", "pkd",
                         "exp", "consumer", "care", "customer", "helpline", "contact",
                         "feedback", "rs", "inr", "price", "retail", "maximum",
                         "incl", "taxes", "tax", "taxes"}

    def _product_name(self, rows: List[Dict[str, Any]]):
        best, best_score = None, 0.0
        for r in rows:
            t = r["text"].strip()
            low = t.lower()
            if len(t) < 2 or r["confidence"] < 0.4:
                continue
            if any(b in low for b in NAME_BLOCKLIST):
                continue
            if low in self._NAME_SINGLETONS:
                continue  # fragment of a split declaration, e.g. "Consumer" / "MRP"
            tokens = set(re.findall(r"[a-z]+", low))
            if tokens & self._NAME_SINGLETONS:
                continue
            if any(k in low for k in ("mrp", "net wt", "net quantity", "mfg", "pkd", "exp", "1800", "₹", " rs")):
                continue
            digits = sum(c.isdigit() for c in t)
            if digits / max(1, len(t)) > 0.4:  # nutrition table junk
                continue
            x1, y1, x2, y2 = r["bbox"]
            h = max(1, y2 - y1)
            score = len(t) * (1 + h / 40.0) * r["confidence"]
            if re.match(r"^[A-Z][A-Z!&' ]{2,14}$", t):  # BRAND-like: BINGO!
                score *= 2.0
            if score > best_score:
                best_score, best = score, r
        if best:
            return _clean(best["text"], 60), best["confidence"], best["bbox"], best["text"]
        return None

    def extract_fields(self, ocr_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = self._ordered(ocr_results)
        extracted: List[Dict[str, Any]] = []
        seen = set()

        def add(name, hit):
            if not hit:
                return
            if name in seen:
                return
            value, conf, bbox, source = hit
            if not value:
                return
            seen.add(name)
            extracted.append({
                "name": name, "value": value, "confidence": float(conf),
                "bbox": [int(v) for v in bbox], "source_text": source,
            })
            logger.info(f"Extracted {name}: {value} (conf {conf:.2f})")

        name_hit = self._product_name(rows)
        add("product_name", name_hit)
        add("manufacturer", self._manufacturer_value(rows))
        add("mrp", self._match_windows("mrp", rows) or self._nearby_value_window(
            [r"\bmrp\b", r"maximum\s*retail\s*price"],
            r"(?:rs\.?|inr|₹)?\s*\d[\d,]*\.?\d{0,2}",
            rows,
        ))
        add("net_quantity", self._match_windows("net_quantity", rows) or self._nearby_value_window(
            [r"net\s*(quantity|qty|wt|weight|contents?)"],
            r"\d[\d,.]*\s*(kg|g|gm|gms|grams?|ml|l|ltr|litre?s?|millilitre?s?)\b",
            rows,
        ))
        add("manufacturing_date", self._match_windows("manufacturing_date", rows) or self._nearby_value_window(
            [r"\b(mfg|mfd|manufactured|packed|pkd|exp|expiry|best\s*before)\b"],
            r"(\d{1,2}[\s./-]+\d{1,2}[\s./-]+\d{2,4}|\d{1,2}[\s./-]+\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s./-]+\d{2,4})",
            rows,
        ))
        add("consumer_care", self._match_windows("consumer_care", rows) or self._nearby_value_window(
            [r"(consumer|customer)\s*cares?", r"\bcares?\b", r"helpline", r"contact", r"complaint", r"feedback"],
            r"([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|(?:1800|1860|080|022|011)[\d\s-]{6,}|[\w\s@.+()-]{6,})",
            rows,
        ))
        return extracted


def get_field_extractor() -> FieldExtractor:
    return FieldExtractor()
