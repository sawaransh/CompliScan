import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Rule:
    rule_id: str
    field: str
    requirement: str
    severity: str
    legal_reference: str
    validation: Dict[str, Any]


@dataclass
class Category:
    name: str
    description: str
    applicable_rules: List[str]


class RuleEngine:
    def __init__(self, rules_path: str = None):
        if rules_path is None:
            # Default to rules file in project root
            rules_path = Path(__file__).parent.parent.parent.parent / "rules" / "packaged_commodities_rules.json"
        self.rules_path = Path(rules_path)
        self.rules: Dict[str, Rule] = {}
        self.categories: Dict[str, Category] = {}
        self.confidence_thresholds: Dict[str, float] = {}
        self._load_rules()

    def _load_rules(self):
        """Load rules from JSON configuration."""
        with open(self.rules_path, 'r') as f:
            config = json.load(f)
        
        for rule_data in config.get("rules", []):
            rule = Rule(
                rule_id=rule_data["rule_id"],
                field=rule_data["field"],
                requirement=rule_data["requirement"],
                severity=rule_data["severity"],
                legal_reference=rule_data.get("legal_reference", ""),
                validation=rule_data.get("validation", {})
            )
            self.rules[rule.rule_id] = rule
        
        for cat_id, cat_data in config.get("categories", {}).items():
            self.categories[cat_id] = Category(
                name=cat_data["name"],
                description=cat_data["description"],
                applicable_rules=cat_data["applicable_rules"]
            )
        
        self.confidence_thresholds = config.get("confidence_thresholds", {
            "compliant": 0.7,
            "review_required": 0.5,
            "non_compliant": 0.5
        })
        
        logger.info(f"Loaded {len(self.rules)} rules and {len(self.categories)} categories")

    def get_applicable_rules(self, category: str = "general_retail_packaged_commodity") -> List[Rule]:
        """Get rules applicable to a product category."""
        cat = self.categories.get(category)
        if not cat:
            logger.warning(f"Unknown category: {category}, using default")
            cat = self.categories.get("general_retail_packaged_commodity")
        
        applicable = []
        for rule_id in cat.applicable_rules:
            if rule_id in self.rules:
                applicable.append(self.rules[rule_id])
        return applicable

    def evaluate_field(
        self,
        rule: Rule,
        extracted_fields: List[Dict[str, Any]],
        ocr_quality: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a single rule against extracted fields.
        
        Returns:
            Dict with status, message, confidence, bbox
        """
        # Find matching extracted field
        field_data = None
        for f in extracted_fields:
            if f["name"] == rule.field:
                field_data = f
                break
        
        validation = rule.validation
        min_conf = validation.get("min_confidence", 0.5)
        pattern = validation.get("pattern", "")
        
        ocr_quality = ocr_quality or {}
        readable_regions = int(ocr_quality.get("readable_regions", 0))
        avg_confidence = float(ocr_quality.get("avg_confidence", 0.0))
        had_ocr_errors = bool(ocr_quality.get("had_errors", False))
        photo_quality = ocr_quality.get("photo_quality") or {}
        weak_photo = bool(
            photo_quality.get("blurry")
            or photo_quality.get("tiny_text")
            or photo_quality.get("suspicious_layout")
        )

        if not field_data:
            # Missing field on a sharp, confident read = clear violation.
            # Missing field with weak evidence = ask for a better photo,
            # never a false NON_COMPLIANT.
            if (readable_regions < 4 or avg_confidence < 0.6
                    or had_ocr_errors or weak_photo):
                return {
                    "status": "REVIEW",
                    "message": (
                        f"{rule.requirement} - not detected, but OCR evidence is weak "
                        f"({readable_regions} readable regions, avg confidence {avg_confidence:.2f})"
                    ),
                    "confidence": avg_confidence,
                    "bbox": None
                }
            return {
                "status": "FAIL",
                "message": f"{rule.requirement} - field not detected",
                "confidence": 0.0,
                "bbox": None
            }
        
        confidence = field_data["confidence"]
        value = field_data["value"]
        
        # Check confidence threshold
        if confidence < min_conf:
            return {
                "status": "REVIEW",
                "message": f"{rule.field} detected but confidence too low ({confidence:.2f} < {min_conf})",
                "confidence": confidence,
                "bbox": field_data["bbox"]
            }
        
        # Validate pattern if provided
        if pattern:
            evidence_text = f"{field_data.get('source_text', '')} {value}"
            if not re.search(pattern, evidence_text, re.IGNORECASE):
                return {
                    "status": "REVIEW",
                    "message": f"{rule.field} value format doesn't match expected pattern",
                    "confidence": confidence,
                    "bbox": field_data["bbox"]
                }
        
        return {
            "status": "PASS",
            "message": f"{rule.requirement} - detected: {value}",
            "confidence": confidence,
            "bbox": field_data["bbox"]
        }

    def evaluate_compliance(
        self,
        extracted_fields: List[Dict[str, Any]],
        category: str = "general_retail_packaged_commodity",
        ocr_results: Optional[List[Dict[str, Any]]] = None,
        ocr_errors: Optional[List[str]] = None,
        photo_quality: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate full compliance for a category.
        
        Returns:
            Dict with overall status, checks, violations, review_items
        """
        applicable_rules = self.get_applicable_rules(category)
        ocr_results = ocr_results or []
        confidences = [
            float(r.get("confidence", 0.0))
            for r in ocr_results
            if r.get("text", "").strip() and float(r.get("confidence", 0.0)) >= 0.25
        ]
        ocr_quality = {
            "readable_regions": len(confidences),
            "avg_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "had_errors": bool(ocr_errors),
            "photo_quality": photo_quality or {},
        }
        
        checks = []
        violations = []
        review_items = []
        
        for rule in applicable_rules:
            result = self.evaluate_field(rule, extracted_fields, ocr_quality)
            
            check = {
                "rule_id": rule.rule_id,
                "field": rule.field,
                "status": result["status"],
                "message": result["message"],
                "bbox": result["bbox"],
                "confidence": result["confidence"]
            }
            checks.append(check)
            
            if result["status"] == "FAIL":
                violations.append({
                    "rule_id": rule.rule_id,
                    "field": rule.field,
                    "requirement": rule.requirement,
                    "reason": result["message"],
                    "evidence": f"Field '{rule.field}' not detected or confidence too low",
                    "bbox": result["bbox"]
                })
            elif result["status"] == "REVIEW":
                review_items.append({
                    "rule_id": rule.rule_id,
                    "field": rule.field,
                    "requirement": rule.requirement,
                    "reason": result["message"],
                    "evidence": f"Field '{rule.field}' detected but needs verification",
                    "bbox": result["bbox"],
                    "confidence": result["confidence"]
                })
        
        # Determine overall status
        has_failures = len(violations) > 0
        has_reviews = len(review_items) > 0
        all_passed = len(checks) > 0 and not has_failures and not has_reviews
        
        if has_failures:
            overall_status = "NON_COMPLIANT"
        elif has_reviews:
            overall_status = "REVIEW_REQUIRED"
        elif all_passed:
            overall_status = "COMPLIANT"
        else:
            overall_status = "REVIEW_REQUIRED"
        
        return {
            "status": overall_status,
            "checks": checks,
            "violations": violations,
            "review_items": review_items
        }


def get_rule_engine() -> RuleEngine:
    return RuleEngine()
