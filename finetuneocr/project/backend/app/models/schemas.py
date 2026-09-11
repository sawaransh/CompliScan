from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"


class OCRResult(BaseModel):
    text: str
    bbox: List[int] = Field(..., description="[x1, y1, x2, y2] bounding box coordinates")
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractedField(BaseModel):
    name: str
    value: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: List[int] = Field(..., description="[x1, y1, x2, y2] bounding box coordinates")
    source_text: str
    rule_id: Optional[str] = None
    source_image: Optional[int] = None
    source_filename: Optional[str] = None


class ComplianceCheck(BaseModel):
    rule_id: str
    field: str
    status: CheckStatus
    message: str
    bbox: Optional[List[int]] = None
    confidence: Optional[float] = None


class Violation(BaseModel):
    rule_id: str
    field: str
    requirement: str
    reason: str
    evidence: str
    bbox: Optional[List[int]] = None


class ReviewItem(BaseModel):
    rule_id: str
    field: str
    requirement: str
    reason: str
    evidence: str
    bbox: Optional[List[int]] = None
    confidence: float


class AnalysisResponse(BaseModel):
    status: ComplianceStatus
    fields: List[ExtractedField]
    checks: List[ComplianceCheck]
    violations: List[Violation]
    review_items: List[ReviewItem]
    annotated_image: Optional[str] = None
    original_image: Optional[str] = None
    ocr_results: List[OCRResult]
    processing_steps: List[str] = []
    quality: Optional[Dict[str, Any]] = None


class SingleImageResult(BaseModel):
    index: int
    filename: str
    width: int
    height: int
    ocr_regions: int
    fields: List[ExtractedField]
    ocr_results: List[OCRResult]
    annotated_image: Optional[str] = None
    original_image: Optional[str] = None
    quality: Optional[Dict[str, Any]] = None


class MultiAnalysisResponse(BaseModel):
    status: ComplianceStatus
    fields: List[ExtractedField]
    checks: List[ComplianceCheck]
    violations: List[Violation]
    review_items: List[ReviewItem]
    images: List[SingleImageResult]
    processing_steps: List[str] = []
    quality: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str