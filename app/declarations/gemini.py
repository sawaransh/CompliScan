"""Optional Gemini resolver for ambiguous declaration labels only.

It never evaluates a legal rule and is never sent whole package images by default.
"""
from __future__ import annotations
import json
import os
from urllib import request
from .. import config as _config  # loads the local, gitignored .env once

class GeminiSemanticResolver:
    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash") -> None:
        self.api_key, self.model = api_key or os.getenv("GEMINI_API_KEY"), model

    @property
    def enabled(self) -> bool: return bool(self.api_key)

    def classify_label(self, text: str) -> dict | None:
        """Return a semantic label for a short ambiguous OCR line, or None safely."""
        if not self.enabled: return None
        prompt = ("Classify this OCR line as exactly one of manufacturer, manufacturing_date, "
                  "unknown. This is semantic assistance only, not legal compliance. Return JSON "
                  "with keys field and confidence (0..1). OCR line: " + text[:500])
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        try:
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=6) as res: payload = json.loads(res.read())
            text_out = payload["candidates"][0]["content"]["parts"][0]["text"]
            answer = json.loads(text_out)
            return answer if answer.get("field") in {"manufacturer", "manufacturing_date", "unknown"} else None
        except Exception:
            return None
