from __future__ import annotations
import json, shutil, uuid
from pathlib import Path
import cv2
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from .compliance import evaluate, load_rules
from .config import RULES_PATH, RUN_DIR, STATIC_DIR, UPLOAD_DIR
from .evidence import annotate
from .extract import extract_fields
from .ocr import image_quality, run_ocr

app = FastAPI(title="Legal Metrology OCR Demo", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/files", StaticFiles(directory=str(RUN_DIR)), name="files")

@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC_DIR / "index.html").read_text()

@app.get("/api/health")
def health():
    checks = {"paddleocr": False, "tesseract": False}
    try:
        import paddleocr
        checks["paddleocr"] = True
    except Exception:
        pass
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        checks["tesseract"] = True
    except Exception:
        pass
    return {"status":"ok", "ocr_engines":checks, "rule_set":load_rules(RULES_PATH)}

@app.post("/api/scan")
async def scan(files: list[UploadFile] = File(...), backend: str = Form("auto")):
    run_id = uuid.uuid4().hex[:12]
    upload_dir, out_dir = UPLOAD_DIR/run_id, RUN_DIR/run_id
    upload_dir.mkdir(parents=True, exist_ok=True); out_dir.mkdir(parents=True, exist_ok=True)
    image_results, warnings = [], []
    for idx, upload in enumerate(files, start=1):
        suffix = Path(upload.filename or ".jpg").suffix.lower() or ".jpg"
        source_path = upload_dir / f"image_{idx}{suffix}"
        with source_path.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        image = cv2.imread(str(source_path))
        if image is None:
            warnings.append(f"Could not decode {upload.filename}"); continue
        quality = image_quality(image)
        used_backend, boxes, warning = run_ocr(source_path, backend)
        if warning: warnings.append(warning)
        annotated_name = f"annotated_{idx}.jpg"
        annotate(source_path, boxes, out_dir/annotated_name)
        fields = extract_fields(boxes)
        image_results.append({"filename": upload.filename, "backend": used_backend, "quality": quality, "boxes": boxes, "fields": fields, "annotated_url": f"/files/{run_id}/{annotated_name}"})
    if not image_results:
        return {"error":"No readable images were uploaded."}
    rules = load_rules(RULES_PATH)
    compliance = evaluate(image_results, rules)
    response = {"inspection_id":f"LM-DEMO-{run_id.upper()}", "backend_requested":backend, "rule_set_id":rules["rule_set_id"], "disclaimer":rules["disclaimer"], "warnings":warnings, "images":[], "compliance":compliance}
    for item in image_results:
        response["images"].append({"filename":item["filename"], "backend":item["backend"], "quality":item["quality"], "boxes":[b.to_dict() for b in item["boxes"]], "fields":{k:v for k,v in item["fields"].items() if not k.startswith("_")}, "annotated_url":item["annotated_url"]})
    (out_dir/"result.json").write_text(json.dumps(response, indent=2, ensure_ascii=False))
    response["result_file"] = f"/files/{run_id}/result.json"
    return response

@app.get("/api/result/{run_id}")
def get_result(run_id: str):
    return FileResponse(RUN_DIR/run_id/"result.json")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
