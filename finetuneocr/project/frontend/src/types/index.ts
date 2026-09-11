export type ComplianceStatus = 'COMPLIANT' | 'NON_COMPLIANT' | 'REVIEW_REQUIRED';
export type CheckStatus = 'PASS' | 'FAIL' | 'REVIEW';

export interface OCRResult {
  text: string;
  bbox: number[];
  confidence: number;
}

export interface ExtractedField {
  name: string;
  value: string;
  confidence: number;
  bbox: number[];
  source_text: string;
  rule_id?: string;
  source_image?: number;
  source_filename?: string;
}

export interface SingleImageResult {
  index: number;
  filename: string;
  width: number;
  height: number;
  ocr_regions: number;
  fields: ExtractedField[];
  ocr_results: OCRResult[];
  annotated_image?: string;
  original_image?: string;
  quality?: ImageQuality;
}

export interface MultiAnalysisResponse {
  status: ComplianceStatus;
  fields: ExtractedField[];
  checks: ComplianceCheck[];
  violations: Violation[];
  review_items: ReviewItem[];
  images: SingleImageResult[];
  processing_steps: string[];
  quality?: ImageQuality;
}

export interface ComplianceCheck {
  rule_id: string;
  field: string;
  status: CheckStatus;
  message: string;
  bbox?: number[];
  confidence?: number;
}

export interface Violation {
  rule_id: string;
  field: string;
  requirement: string;
  reason: string;
  evidence: string;
  bbox?: number[];
}

export interface ReviewItem {
  rule_id: string;
  field: string;
  requirement: string;
  reason: string;
  evidence: string;
  bbox?: number[];
  confidence: number;
}

export interface ImageQuality {
  blur_score: number;
  blurry: boolean;
  median_text_height_px: number;
  tiny_text: boolean;
  suspicious_layout?: boolean;
  ocr_regions: number;
}

export interface AnalysisResponse {
  status: ComplianceStatus;
  fields: ExtractedField[];
  checks: ComplianceCheck[];
  violations: Violation[];
  review_items: ReviewItem[];
  annotated_image?: string;
  original_image?: string;
  ocr_results: OCRResult[];
  processing_steps: string[];
  quality?: ImageQuality;
}

export interface ProcessingStep {
  step: number;
  name: string;
  description: string;
  completed: boolean;
  active: boolean;
}