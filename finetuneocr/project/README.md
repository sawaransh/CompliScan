# CompliScan - Packaged Commodity Compliance Scanner

A prototype system for checking compliance of Packaged Commodities under Legal Metrology (Packaged Commodities) Rules, 2011.

## Project Structure

```
project/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI application entry point
│   │   ├── api/                    # API routes (future)
│   │   ├── ocr/
│   │   │   └── paddle_ocr.py       # PaddleOCR wrapper
│   │   ├── preprocessing/
│   │   │   └── image_processing.py # Image preprocessing with OpenCV
│   │   ├── extraction/
│   │   │   └── field_extractor.py  # Field extraction from OCR results
│   │   ├── compliance/
│   │   │   └── rule_engine.py      # Deterministic rule engine
│   │   ├── evidence/
│   │   │   └── annotator.py        # Evidence annotation on images
│   │   └── models/
│   │       └── schemas.py          # Pydantic models
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/             # React components
│   │   ├── pages/                  # Page components (future)
│   │   ├── services/               # API services
│   │   ├── types/                  # TypeScript types
│   │   ├── App.tsx                 # Main app component
│   │   └── main.tsx                # Entry point
│   └── package.json
├── rules/
│   └── packaged_commodities_rules.json  # Legal Metrology rules configuration
└── README.md
```

## Architecture - Four Layer Separation

1. **LAYER 1 - OCR** (`backend/app/ocr/paddle_ocr.py`): PaddleOCR reads text, returns text + bbox + confidence
2. **LAYER 2 - FIELD EXTRACTION** (`backend/app/extraction/field_extractor.py`): Identifies MRP, net quantity, manufacturer, dates, consumer care
3. **LAYER 3 - RULE ENGINE** (`backend/app/compliance/rule_engine.py`): Deterministically checks extracted info against configured Legal Metrology requirements
4. **LAYER 4 - EVIDENCE** (`backend/app/evidence/annotator.py`): Shows what was detected, where, confidence, why it passed/failed, rule reference

## Features Implemented

- ✅ Image upload (JPG, JPEG, PNG, WEBP)
- ✅ Image preprocessing (resize, denoise, enhance contrast, sharpen)
- ✅ PaddleOCR integration (text + bounding boxes + confidence)
- ✅ Field extraction (MRP, net quantity, manufacturer, manufacturing date, consumer care)
- ✅ Configurable rule engine (JSON-based rules)
- ✅ Three compliance outcomes: COMPLIANT, NON-COMPLIANT, REVIEW REQUIRED
- ✅ Evidence annotation (color-coded bounding boxes)
- ✅ Interactive result viewer (highlight fields on hover)
- ✅ Processing steps visualization
- ✅ No database, no authentication (MVP)

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- PaddleOCR dependencies (will be installed via pip)

### Backend Setup

```bash
cd project/backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

The API will be available at `http://localhost:8000`

### Frontend Setup

```bash
cd project/frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`

### Test the API

```bash
curl -X POST "http://localhost:8000/api/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "image=@test_image.jpg"
```

## Rules Configuration

Rules are defined in `rules/packaged_commodities_rules.json`:

- Each rule has: rule_id, field, requirement, severity, legal_reference, validation
- Categories define which rules apply to which product types
- Confidence thresholds control COMPLIANT/REVIEW/NON_COMPLIANT decisions
- Pattern-based validation for each field

## API Response Format

```json
{
  "status": "COMPLIANT|NON_COMPLIANT|REVIEW_REQUIRED",
  "fields": [
    {
      "name": "mrp",
      "value": "₹120",
      "confidence": 0.98,
      "bbox": [100, 200, 400, 250],
      "source_text": "MRP ₹120 (Incl. of all taxes)"
    }
  ],
  "checks": [
    {
      "rule_id": "PC-MRP-001",
      "field": "mrp",
      "status": "PASS|FAIL|REVIEW",
      "message": "MRP declaration detected",
      "bbox": [100, 200, 400, 250],
      "confidence": 0.98
    }
  ],
  "violations": [],
  "review_items": [],
  "annotated_image": "base64...",
  "original_image": "base64...",
  "ocr_results": [...],
  "processing_steps": [...]
}
```

## Development Approach (Incremental)

1. ✅ Create project structure
2. ✅ Backend with FastAPI + PaddleOCR
3. ✅ Image preprocessing
4. ✅ Field extraction
5. ✅ Rule engine with JSON config
6. ✅ Evidence annotation
7. ✅ Frontend with React + Vite + Tailwind
8. ✅ Upload & analysis UI
9. ✅ Connect frontend to backend
10. ✅ Result display with evidence highlighting
11. 🔄 Test complete pipeline

## Test Cases

1. **Clear compliant image** → 🟢 COMPLIANT
2. **Clear image with missing declaration** → 🔴 NON-COMPLIANT
3. **Blurry/poor quality image** → 🟡 REVIEW REQUIRED

## Important Principles

- **No LLM for legal decisions** - Rule engine is deterministic
- **Evidence preservation** - Every field links to OCR bbox + confidence
- **Separate legal rules from code** - JSON config allows rule updates without code changes
- **Applicability layer** - Not all rules apply to all products
- **Uncertainty ≠ Non-compliance** - REVIEW REQUIRED for low confidence

## Future Phases (Not in MVP)

- Camera capture, multiple package sides
- Barcode/GTIN support
- PDF reports, database, history
- Authentication, role-based access
- Dashboard, search, analytics

## License

MIT License - Built for SIH 2026