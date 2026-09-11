import cv2
import numpy as np
import base64
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class EvidenceAnnotator:
    """Create annotated images showing detected fields and compliance results."""
    
    # Colors in BGR format
    COLORS = {
        "COMPLIANT": (0, 255, 0),      # Green
        "NON_COMPLIANT": (0, 0, 255),  # Red
        "REVIEW_REQUIRED": (0, 255, 255),  # Yellow
        "PASS": (0, 255, 0),
        "FAIL": (0, 0, 255),
        "REVIEW": (0, 255, 255),
        "OCR": (255, 0, 0),  # Blue for raw OCR boxes
    }
    
    def __init__(self, line_thickness: int = 2, font_scale: float = 0.6):
        self.line_thickness = line_thickness
        self.font_scale = font_scale
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    def draw_bbox(self, image: np.ndarray, bbox: List[int], color: tuple,
                  label: str = "", confidence: Optional[float] = None) -> np.ndarray:
        """Draw bounding box with optional label, safely clipped to image."""
        h, w = image.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        # clip + fix inverted boxes
        x1, x2 = max(0, min(x1, x2)), min(w - 1, max(x1, x2))
        y1, y2 = max(0, min(y1, y2)), min(h - 1, max(y1, y2))
        if x2 <= x1 or y2 <= y1:
            return image
        # scale thickness with image size so boxes are visible
        thickness = max(2, min(w, h) // 300)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)

        if label:
            label_text = f"{label}"
            if confidence is not None:
                try:
                    label_text += f" ({float(confidence):.0%})"
                except Exception:
                    pass

            scale = max(0.5, min(w, h) / 900.0)
            (text_w, text_h), _ = cv2.getTextSize(label_text, self.font, scale, 2)
            # keep label inside image (draw below box if too close to top)
            ly1 = y1 - text_h - 8
            ly2 = y1
            if ly1 < 0:
                ly1, ly2 = y2, y2 + text_h + 8
            cv2.rectangle(image, (x1, max(0, ly1)), (min(w, x1 + text_w + 8), min(h, ly2)), color, -1)
            cv2.putText(image, label_text, (x1 + 3, min(h - 3, ly2 - 4)),
                        self.font, scale, (255, 255, 255), 2, cv2.LINE_AA)

        return image

    def create_annotated_image(self, original_image: np.ndarray,
                               ocr_results: List[Dict[str, Any]],
                               extracted_fields: List[Dict[str, Any]],
                               checks: List[Dict[str, Any]]) -> np.ndarray:
        """
        Create annotated image showing all detections and compliance results.
        
        Args:
            original_image: Original image
            ocr_results: Raw OCR results
            extracted_fields: Extracted structured fields
            checks: Compliance check results
            
        Returns:
            Annotated image
        """
        annotated = original_image.copy()

        # Draw raw OCR boxes first (thin blue), then field boxes on top.
        for ocr in ocr_results:
            try:
                if float(ocr.get("confidence", 0)) >= 0.3 and ocr.get("text", "").strip():
                    self.draw_bbox(annotated, ocr["bbox"], self.COLORS["OCR"],
                                   f"{ocr['text'][:28]}", ocr["confidence"])
            except Exception:
                continue
        
        # Create lookup for check results by field
        check_by_field = {c["field"]: c for c in checks}
        
        # Draw extracted fields with compliance colors
        for field in extracted_fields:
            check = check_by_field.get(field["name"])
            if check:
                status = check["status"]
                color = self.COLORS.get(status, self.COLORS["REVIEW"])
                label = f"{field['name']}: {field['value'][:40]}"
            else:
                color = self.COLORS["REVIEW"]
                label = f"{field['name']}: {field['value'][:40]} (no rule)"
            
            self.draw_bbox(annotated, field["bbox"], color, label, field["confidence"])
        
        return annotated

    def create_summary_image(self, original_image: np.ndarray,
                             overall_status: str,
                             checks: List[Dict[str, Any]]) -> np.ndarray:
        """Create a summary image with overall compliance status."""
        h, w = original_image.shape[:2]
        summary = original_image.copy()
        
        # Add status banner at top
        banner_height = 80
        banner = np.zeros((banner_height, w, 3), dtype=np.uint8)
        
        status_color = self.COLORS.get(overall_status, (128, 128, 128))
        cv2.rectangle(banner, (0, 0), (w, banner_height), status_color, -1)
        
        status_text = f"COMPLIANCE: {overall_status}"
        (text_w, text_h), _ = cv2.getTextSize(status_text, self.font, 1.5, 3)
        cv2.putText(banner, status_text, ((w - text_w) // 2, 55), 
                   self.font, 1.5, (255, 255, 255), 3)
        
        # Combine banner with image
        summary = np.vstack([banner, summary])
        
        # Add check summary at bottom
        check_text = "Checks: "
        for c in checks:
            icon = "✓" if c["status"] == "PASS" else ("✗" if c["status"] == "FAIL" else "⚠")
            check_text += f" {icon}{c['field']}"
        
        footer_height = 40
        footer = np.zeros((footer_height, w + 0, 3), dtype=np.uint8)
        cv2.putText(footer, check_text, (10, 28), self.font, 0.6, (255, 255, 255), 1)
        summary = np.vstack([summary, footer])
        
        return summary


def encode_image_to_base64(image: np.ndarray) -> str:
    """Encode image to data-URL base64 string for <img src> display."""
    _, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    b64 = base64.b64encode(buffer).decode('utf-8')
    return f"data:image/jpeg;base64,{b64}"


def get_annotator() -> EvidenceAnnotator:
    return EvidenceAnnotator()