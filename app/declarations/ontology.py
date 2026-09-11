from __future__ import annotations

# Kept in one vocabulary so aliases never leak through the rule engine.
DECLARATIONS = {
    "manufacturer": {"aliases": ["manufactured by", "manufactured and packed by", "packed by", "imported by", "mfd by"], "negative_cues": ["mfd:", "mfd ", "mfg:"], "type": "text"},
    "address": {"aliases": ["address", "registered office", "plot", "industrial area"], "type": "text", "neighbours": ["manufacturer"]},
    "product_name": {"aliases": [], "type": "text"},
    "net_quantity": {"aliases": ["net quantity", "net qty", "net wt", "net weight", "contents"], "units": ["mg", "g", "kg", "ml", "l", "cl", "pcs", "pieces"], "type": "quantity"},
    "mrp": {"aliases": ["mrp", "maximum retail price", "m.r.p"], "type": "currency"},
    "date": {"aliases": ["mfd", "mfg", "manufacturing date", "packed on", "packing date", "date of packing"], "type": "date"},
    "consumer_care": {"aliases": ["customer care", "consumer care", "helpline", "toll free", "care line"], "type": "contact"},
    "country_of_origin": {"aliases": ["country of origin", "made in", "origin"], "type": "text"},
}
