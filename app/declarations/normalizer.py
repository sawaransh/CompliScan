from __future__ import annotations
import re

def normalize(text: str) -> str:
    """Canonical display form. Never destroys the original (kept in OCRBox)."""
    value = re.sub(r"\s+", " ", text or "").strip()
    value = re.sub(r"m\s*\.\s*r\s*\.\s*p\s*\.?", "MRP", value, flags=re.I)
    value = re.sub(r"\b(?:rs\.?|inr)\s*", "₹", value, flags=re.I)
    value = re.sub(r"₹\s*(\d+(?:\.\d+)?)\s*/?-", r"₹\1", value)
    value = re.sub(r"\bnet\s*(?:wt|qty)\b", "NET QUANTITY", value, flags=re.I)
    value = re.sub(r"\b(\d+(?:\.\d+)?)\s*(KG|G|MG|ML|L|CL)\b", lambda m: f"{m.group(1)} {m.group(2).lower()}", value, flags=re.I)
    return value


def normalize_for_match(text: str) -> str:
    """Matching-time cleanup for common OCR spacing/punctuation errors.

    Applied to the working copy used by regex only; evidence keeps `normalize`.
    """
    value = normalize(text)
    value = value.replace("₹", " ₹ ").replace("|", "I")
    value = re.sub(r"\bM\s*R\s*P\b", "MRP", value, flags=re.I)
    value = re.sub(r"\bM\s*F\s*[GD]\b", lambda m: "MFD" if "D" in m.group(0).upper() else "MFG", value)
    value = re.sub(r"\bP\s*K\s*D\b", "PKD", value, flags=re.I)
    value = re.sub(r"\bE\s*X\s*P\b", "EXP", value, flags=re.I)
    value = re.sub(r"\bMRP(\d)", r"MRP \1", value)
    value = re.sub(r"\bRs\.?\s*(\d)", r"Rs \1", value, flags=re.I)
    value = re.sub(r"\bNET\s*WT\.?\s*(\d)", r"NET WT \1", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    return value
