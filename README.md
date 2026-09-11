# CompliScan — Legal Metrology Inspection & Supervision

One service, two doors, one shared database:

- **Officer app (mobile web):** http://127.0.0.1:8000/inspect — scan packages, get verdicts, generate reports
- **Supervisor dashboard (desktop web):** http://127.0.0.1:8000/supervise — monitor officers, review all scans, brand/region analytics

(`/` redirects to `/login`, the single sign-in page.) Every scan from the officer app is recorded in the
shared SQLite store (`data/compliscan.db`) with its officer attached, so the
dashboard reads the exact same data — no sync step.

A local prototype for the core of the Legal Metrology packaged-commodity workflow:

**image(s) → preprocessing → OCR → declaration extraction → compliance checks → visual evidence**

This is intentionally focused on the OCR/rule-verification engine. It is not a legal certification system and the included demo rules are an implementation scaffold; before any real enforcement use, map every check to the current official rule text and applicable amendments.

## What is included

- FastAPI backend with a mobile-friendly web UI
- Multi-image package scanning (front/back/side/etc.)
- PaddleOCR primary pass plus a deliberate RapidOCR pass over the enhanced
  variant; boxes are merged deterministically (IoU + text overlap) with
  per-pass provenance in `image_id`, never fallback switching
- 5 OCR variants (enhanced / original / gray-CLAHE / sharpened / adaptive binary)
  with tuned detection thresholds and rotation recovery
- Upload decoding with EXIF orientation, HEIC support (`pillow-heif`) and size validation
- OCR text + bounding boxes
- Declaration extraction with multi-line window joins, so split declarations
  (`MRP` on one line, `Rs 120` on the next) resolve to single fields, plus
  OCR-error normalization (`M.R.P. Rs. 20/-` → MRP `20`)
- Declaration extraction for prototype fields:
  - manufacturer/packer/importer
  - address
  - product/generic name
  - net quantity
  - MRP
  - packing/manufacture/import date
  - consumer care
  - country of origin
- Confidence-aware `PASS / REVIEW / FAIL`
- Readability/image-quality scoring
- Cross-image MRP conflict detection
- Annotated images with evidence boxes
- JSON results saved locally
- Three synthetic sample package images for immediate testing

## Recommended setup

Use Python 3.10–3.13. The current PaddlePaddle macOS documentation lists Python 3.9–3.13 and macOS ARM64/Apple Silicon support via the macOS installation route; exact package availability can vary by environment. PaddleOCR's current docs expose a Python `predict()` OCR pipeline and return text/geometry data. See the official links in `docs/official_sources.md`.

### Option A — PaddleOCR (recommended)

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install the core app:

```bash
python -m pip install -r requirements.txt
```

Then install PaddleOCR + PaddlePaddle:

```bash
python -m pip install paddlepaddle paddleocr
```

If your platform needs a platform-specific PaddlePaddle wheel, follow the current official PaddlePaddle installation instructions rather than forcing a wheel from an old tutorial.

## Run

```bash
source .venv/bin/activate
python -m app.main
```

Open:

http://127.0.0.1:8000/login — sign in (Officer → /inspect, Supervisor → /supervise)
http://127.0.0.1:8000/inspect — officer scanning app
http://127.0.0.1:8000/supervise — supervisor dashboard

Demo logins: officer `OFF1234` + name `R. Sharma`; supervisor `SUP001` + password `admin123`.

Or:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Recommended first test

Open the UI and upload these files from `sample_images/`:

- `sample_compliant.png` — should mostly pass
- `sample_missing_fields.png` — missing declarations intentionally inserted
- `sample_conflicting_mrp.png` — contains two different MRP values on different package faces

You can upload multiple images in one scan to simulate front/back/side inspection.

## API

### Health

`GET /api/health`

### Scan

`POST /api/scan`

Form fields:

- `files`: one or more image files
- `backend`: `paddle` (the only production OCR provider)

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/scan \
  -F 'backend=paddle' \
  -F 'files=@sample_images/sample_conflicting_mrp.png'
```

## Architecture

```text
Mobile Web UI
     |
     v
 FastAPI API
     |
     +--> image quality / preprocessing
     |
     +--> OpenCV variants -> PaddleOCR
     |
     +--> declaration extractor
     |
     +--> normalization
     |
     +--> versioned rule config
     |
     +--> compliance engine
     |
     +--> evidence mapper
     |
     +--> local inspection record
```

## Important implementation principle

**AI/OCR extracts. Deterministic rules decide. Human verifies ambiguous findings.**

This demo therefore does not ask an LLM to make legal decisions.

## Optional Gemini semantic assistance

Set `GEMINI_API_KEY` in the environment to enable Gemini only for unresolved,
ambiguous short labels (for example, an unclear `MFD` line). It receives text
only, returns a declaration meaning, and is never used to determine compliance.
Without the key, the deterministic ontology and spatial extractor remain fully
functional.

## Next steps after this demo works

1. Build a 100–300 image benchmark from real packaged products.
2. Measure field-level extraction accuracy, not just raw OCR accuracy.
3. Add better perspective correction and surface detection.
4. Replace the demo checklist with rule objects mapped to official provisions and amendment dates.
5. Add inspector authentication, inspection history and report generation.
