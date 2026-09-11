#!/bin/bash
set -e
cd "$(dirname "$0")"

# ---- OCR service (finetuneocr backend, :8001) ----
echo "Starting finetuneocr OCR service..."
# Prefer the vendored finetuneocr venv; fall back to the canonical Downloads copy
OCR_VENV=""
for cand in "finetuneocr/project/backend/venv/bin/python" "/Users/sawaransh/Downloads/kalatutta-main/project/backend/venv/bin/python"; do
  if [ -x "$cand" ]; then OCR_VENV="$cand"; break; fi
done
if [ -z "$OCR_VENV" ]; then
  echo "OCR venv not found — creating finetuneocr/project/backend/venv..."
  python3 -m venv "finetuneocr/project/backend/venv"
  "finetuneocr/project/backend/venv/bin/python" -m pip install -q -r "finetuneocr/project/backend/requirements.txt"
  OCR_VENV="finetuneocr/project/backend/venv/bin/python"
fi
OCR_APP_DIR="$(dirname "$OCR_VENV")/../../.."
# Resolve to absolute so uvicorn --app-dir works regardless of cwd
OCR_APP_DIR="$(cd "$OCR_APP_DIR" && pwd)"
# Restart OCR service on :8001
pkill -f "uvicorn app.main:app --host 127.0.0.1 --port 8001" 2>/dev/null || true
sleep 1
FINETUNEOCR_URL="http://127.0.0.1:8001" nohup "$OCR_VENV" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --app-dir "$OCR_APP_DIR" > /tmp/finetuneocr.log 2>&1 &
echo "OCR service starting on http://127.0.0.1:8001 (log: /tmp/finetuneocr.log)"
# Wait for it
for i in 1 2 3 4 5 6 8 10 15; do
  sleep "$i"
  if curl -s http://127.0.0.1:8001/health | grep -q "healthy"; then echo "OCR service ready."; break; fi
done

# ---- Main app (:8000) ----
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
FINETUNEOCR_URL="http://127.0.0.1:8001" python -m app.main
