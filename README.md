# Legal Metrology OCR + Compliance Demo

A local prototype for the core of the Legal Metrology packaged-commodity workflow:

**image(s) → preprocessing → OCR → declaration extraction → compliance checks → visual evidence**

This is intentionally focused on the OCR/rule-verification engine. It is not a legal certification system and the included demo rules are an implementation scaffold; before any real enforcement use, map every check to the current official rule text and applicable amendments.

## What is included

- FastAPI backend with a mobile-friendly web UI
- Multi-image package scanning (front/back/side/etc.)
- PaddleOCR adapter (primary, optional)
- Tesseract adapter (fallback, optional)
- OCR text + bounding boxes
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

### Option B — Tesseract fallback

Install the system binary:

```bash
brew install tesseract
```

Then install the Python adapter:

```bash
python -m pip install -r requirements.txt
```

The web app can run with `backend=tesseract`.

## Run

```bash
source .venv/bin/activate
python -m app.main
```

Open:

http://127.0.0.1:8000

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
- `backend`: `auto`, `paddle`, `tesseract`, or `mock`

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/scan \
  -F 'backend=auto' \
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
     +--> OCR adapter
     |       +--> PaddleOCR
     |       +--> Tesseract fallback
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

## Next steps after this demo works

1. Build a 100–300 image benchmark from real packaged products.
2. Measure field-level extraction accuracy, not just raw OCR accuracy.
3. Add better perspective correction and surface detection.
4. Replace the demo checklist with rule objects mapped to official provisions and amendment dates.
5. Add inspector authentication, inspection history and report generation.
