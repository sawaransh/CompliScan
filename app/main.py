from __future__ import annotations
import json, shutil, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from . import db
from . import storage as cloud_store
from .compliance import evaluate, load_rules
from .config import RULES_PATH, RUN_DIR, STATIC_DIR, UPLOAD_DIR
from .evidence import annotate
from .declarations.extractor import extract_fields
from .declarations.gemini import GeminiSemanticResolver
from .finetuneocr import PROVIDER_NAME as OCR_PROVIDER_NAME, recognize_image as recognize_via_ocr_service, service_health as ocr_service_health
from .ocr import image_quality, prepare_upload, assess_readability

app = FastAPI(title="CompliScan", version="0.2.0")
# Render/Vercel origins + local dev — allow the deployed frontend to call this API.
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
except Exception:
    pass
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/files", StaticFiles(directory=str(RUN_DIR)), name="files")

# DB is lazy — don't crash Render startup if Atlas is temporarily unreachable / IP not whitelisted.
# First request will retry.
try:
    db.init_db()
    db.backfill_runs()
    if db.ensure_default_supervisor():
        print(f"[auth] default supervisor login: SUP001 / admin123  (change after first login)")
except Exception as _e:
    print(f"[db] Atlas not reachable at startup (will retry on first request): {_e}")

@app.on_event("startup")
def _db_startup():
    try:
        db.init_db()
    except Exception as e:
        print(f"[db] startup retry failed: {e}")

SUPERVISE_DIR = STATIC_DIR / "supervise"

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page():
    return (STATIC_DIR / "landing.html").read_text()

@app.get("/inspect", response_class=HTMLResponse)
def inspect():
    return (STATIC_DIR / "index.html").read_text()

@app.get("/supervise", response_class=HTMLResponse)
def supervise():
    return (SUPERVISE_DIR / "index.html").read_text()

@app.get("/api/health")
def health():
    return {"status":"ok", "ocr_service":ocr_service_health(), "rule_set":load_rules(RULES_PATH)}

# ============================================================
# Auth — single login page, role-routed to /inspect or /supervise
# ============================================================
def session_from_header(authorization: str = Header("")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not signed in")
    sess = db.get_session(authorization[7:].strip())
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    return sess

def require_roles(*roles: str):
    def dep(sess: dict = Depends(session_from_header)) -> dict:
        if sess["role"] not in roles:
            raise HTTPException(status_code=403, detail="Not permitted for this role")
        return sess
    return dep

@app.post("/api/auth/login")
def api_login(payload: dict):
    role = str(payload.get("role", "")).strip()
    user_id = str(payload.get("id", "")).strip()
    secret = str(payload.get("secret", ""))
    try:
        if role == "officer":
            identity = db.verify_officer(user_id, secret)
            if not identity:
                raise HTTPException(status_code=401, detail="Officer ID and name do not match our records")
        elif role == "supervisor":
            row = db.verify_supervisor(user_id, secret)
            if not row:
                raise HTTPException(status_code=401, detail="Supervisor ID or password is incorrect")
            identity = row
        else:
            raise HTTPException(status_code=400, detail="Unknown role")
        token = db.create_session(identity["id"], role)
        return {"status": "ok", "token": token, "role": role, **identity}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database unreachable — allow 0.0.0.0/0 in Atlas Network Access and redeploy. ({exc.__class__.__name__})")

@app.get("/api/auth/me")
def api_me(sess: dict = Depends(session_from_header)):
    return {"status": "ok", **sess}

@app.post("/api/auth/logout")
def api_logout(sess: dict = Depends(session_from_header), authorization: str = Header("")):
    db.delete_session(authorization[7:].strip())
    return {"status": "ok"}

@app.post("/api/auth/change-password")
def api_change_password(payload: dict, sess: dict = Depends(require_roles("supervisor"))):
    new = str(payload.get("new", ""))
    if len(new) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if not db.change_supervisor_password(sess["user_id"], str(payload.get("current", "")), new):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    return {"status": "ok"}

@app.post("/api/scan")
async def scan(
    files: list[UploadFile] = File(...),
    backend: str = Form("paddle"),
    city: str = Form("Unknown"),
    lat: str = Form(""),
    lng: str = Form(""),
    sess: dict = Depends(require_roles("officer", "supervisor")),
):
    run_id = uuid.uuid4().hex[:12]
    upload_dir, out_dir = UPLOAD_DIR/run_id, RUN_DIR/run_id
    upload_dir.mkdir(parents=True, exist_ok=True); out_dir.mkdir(parents=True, exist_ok=True)
    image_results, warnings = [], []
    for idx, upload in enumerate(files, start=1):
        try:
            # Single decode point: EXIF orientation, HEIC and size validation
            # happen here so every later stage sees normalized pixels.
            source_path, image = prepare_upload(await upload.read(), upload.filename or ".jpg", upload_dir, idx)
        except ValueError as exc:
            warnings.append(f"{upload.filename}: {exc}"); continue
        # Keep an immutable source copy beside the rendered evidence. This lets
        # the mobile viewer switch overlays on and off without altering evidence.
        original_name = f"original_{idx}{source_path.suffix}"
        shutil.copy2(source_path, out_dir / original_name)
        quality = image_quality(image)
        if quality["decision"] == "RETAKE_REQUIRED":
            warnings.append(f"{upload.filename}: {quality['guidance']}")
            continue
        try:
            boxes = recognize_via_ocr_service(image, upload.filename or ".jpg", f"image_{idx}")
        except RuntimeError as exc:
            warnings.append(f"{upload.filename}: {exc}"); continue
        used_backend = OCR_PROVIDER_NAME
        fields = extract_fields(boxes, GeminiSemanticResolver())
        quality["readability"] = assess_readability(image, boxes)
        annotated_name = f"annotated_{idx}.jpg"
        annotate(source_path, boxes, out_dir/annotated_name, fields)
        # Cloudinary (web deployment) — upload evidence so every device can see it.
        # Local disk stays as fallback when CLOUDINARY_URL is not set.
        if cloud_store.is_cloudinary_enabled():
            orig_url = cloud_store.upload_image(out_dir / original_name, run_id, original_name) or f"/files/{run_id}/{original_name}"
            ann_url = cloud_store.upload_image(out_dir / annotated_name, run_id, annotated_name) or f"/files/{run_id}/{annotated_name}"
        else:
            orig_url = f"/files/{run_id}/{original_name}"
            ann_url = f"/files/{run_id}/{annotated_name}"
        image_results.append({"filename": upload.filename, "image_id": f"image_{idx}", "backend": used_backend, "quality": quality, "boxes": boxes, "fields": fields, "original_url": orig_url, "annotated_url": ann_url})
    if not image_results:
        return {"error": "No readable images were uploaded.", "warnings": warnings}
    rules = load_rules(RULES_PATH)
    compliance = evaluate(image_results, rules)
    response = {"inspection_id":f"LM-DEMO-{run_id.upper()}", "backend_requested":backend, "rule_set_id":rules["rule_set_id"], "disclaimer":rules["disclaimer"], "legal_notice":rules.get("legal_notice"), "warnings":warnings, "images":[], "compliance":compliance}
    for item in image_results:
        response["images"].append({"filename":item["filename"], "backend":item["backend"], "quality":item["quality"], "boxes":[b.to_dict() for b in item["boxes"]], "fields":{k:v for k,v in item["fields"].items() if not k.startswith("_")}, "original_url":item["original_url"], "annotated_url":item["annotated_url"]})
    (out_dir/"result.json").write_text(json.dumps(response, indent=2, ensure_ascii=False))
    # Mirror result.json to Cloudinary when enabled (survives ephemeral disk)
    if cloud_store.is_cloudinary_enabled():
        cloud_store.upload_result_json(out_dir / "result.json", run_id)
    response["result_file"] = f"/files/{run_id}/result.json"

    # ---- shared database: attribution comes from the signed-in session ----
    officer_id = sess["user_id"]
    officer_name = sess.get("name") or officer_id
    db.upsert_officer(officer_id, officer_name, sess.get("dept") or "Legal Metrology Department")
    try:
        lat_f = float(lat) if str(lat).strip() not in ("", "None") else None
        lng_f = float(lng) if str(lng).strip() not in ("", "None") else None
    except ValueError:
        lat_f, lng_f = None, None
    # If the phone couldn't reverse-geocode, derive city server-side so the
    # heatmap can still group by region.
    city_val = (city or "").strip() or "Unknown"
    if city_val == "Unknown" and lat_f is not None and lng_f is not None:
        try:
            import urllib.request, json as _json
            with urllib.request.urlopen(
                f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat_f}&lon={lng_f}&zoom=10&addressdetails=1",
                timeout=4) as _r:
                _addr = _json.loads(_r.read()).get("address", {})
                city_val = _addr.get("city") or _addr.get("town") or _addr.get("village") or _addr.get("county") or city_val
        except Exception:
            pass
    comp_fields = compliance.get("fields", {}) or {}
    manufacturer = (comp_fields.get("manufacturer") or {}).get("value")
    product = (comp_fields.get("product_name") or {}).get("value")
    db.insert_scan({
        "run_id": run_id,
        "inspection_id": response["inspection_id"],
        "officer_id": officer_id or None,
        "officer_name": officer_name,
        "date": datetime.now(timezone.utc).isoformat(),
        "product": product or "Unnamed product",
        "brand": manufacturer or "Unknown brand",
        "city": city_val,
        "lat": lat_f,
        "lng": lng_f,
        "status": compliance.get("overall_status", "REVIEW"),
        "passed": compliance.get("summary", {}).get("passed", 0),
        "failed": compliance.get("summary", {}).get("failed", 0),
        "review": compliance.get("summary", {}).get("review", 0),
        "image_count": len(response["images"]),
        # Persist slim result in MongoDB so Cloudinary images survive ephemeral disk
        "result": {
            "inspection_id": response["inspection_id"],
            "disclaimer": response["disclaimer"],
            "legal_notice": response.get("legal_notice"),
            "warnings": response["warnings"],
            "compliance": compliance,
            "images": [{"filename": im["filename"], "backend": im["backend"], "quality": im["quality"], "annotated_url": im["annotated_url"], "original_url": im["original_url"], "fields": im["fields"]} for im in response["images"]],
        },
        "has_result": 1,
    })
    return response

@app.post("/api/inspection/{run_id}/verify-field")
def verify_field(run_id: str, payload: dict, sess: dict = Depends(require_roles("officer", "supervisor"))):
    """Preserve AI evidence and attach an officer correction; never overwrite it."""
    result_path = RUN_DIR / run_id / "result.json"
    if not result_path.exists(): return {"error": "Inspection not found"}
    data = json.loads(result_path.read_text())
    field_name = str(payload.get("field", "")).strip()
    field = data.get("compliance", {}).get("fields", {}).get(field_name)
    if not field: return {"error": "Declaration field not found"}
    field["ai_value"] = field.get("value")
    field["officer_value"] = payload.get("value")
    field["officer_verified"] = True
    field["officer_id"] = sess["user_id"]
    field["verified_at"] = datetime.now(timezone.utc).isoformat()
    result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return {"status": "ok", "field": field}

@app.get("/api/result/{run_id}")
def get_result(run_id: str, sess: dict = Depends(require_roles("officer", "supervisor"))):
    return FileResponse(RUN_DIR/run_id/"result.json")

def _flag_scan(run_id: str, sess: dict, column: str) -> dict:
    if column not in ("report_generated", "submitted"):
        raise HTTPException(status_code=400, detail="Unknown flag")
    row = db.get_scan(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Inspection not found")
    if sess["role"] == "officer" and row.get("officer_id") != sess["user_id"]:
        raise HTTPException(status_code=403, detail="Not your inspection")
    try:
        return db.flag_scan(run_id, column)
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Inspection not found")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update scan")

@app.post("/api/inspection/{run_id}/report")
def api_mark_report(run_id: str, sess: dict = Depends(require_roles("officer", "supervisor"))):
    """Officer generated the PDF report — visible on the supervisor dashboard."""
    return _flag_scan(run_id, sess, "report_generated")

@app.post("/api/inspection/{run_id}/submit")
def api_mark_submitted(run_id: str, sess: dict = Depends(require_roles("officer", "supervisor"))):
    """Officer submitted the case to their supervisor."""
    return _flag_scan(run_id, sess, "submitted")


# ============================================================
# Officer — per-officer history synced to MongoDB
# ============================================================
@app.get("/api/officer/scans")
def api_officer_scans(status: str = "all", q: str = "", limit: int = 200, sess: dict = Depends(require_roles("officer"))):
    return {"scans": db.get_officer_scans(sess["user_id"], status, q, limit)}

@app.get("/api/officer/overview")
def api_officer_overview(sess: dict = Depends(require_roles("officer"))):
    return db.get_officer_overview(sess["user_id"])

@app.get("/api/officer/scans/{run_id}")
def api_officer_scan_detail(run_id: str, sess: dict = Depends(require_roles("officer"))):
    row = db.get_scan(run_id)
    if not row or row.get("officer_id") != sess["user_id"]:
        raise HTTPException(status_code=404, detail="Scan not found")
    detail = db.get_scan_detail(run_id)
    if not detail:
        return {"error": "Scan not found"}
    result_file = RUN_DIR / run_id / "result.json"
    if result_file.exists():
        try:
            full = json.loads(result_file.read_text())
            detail["result"] = {
                "inspection_id": full.get("inspection_id"),
                "disclaimer": full.get("disclaimer"),
                "legal_notice": full.get("legal_notice"),
                "warnings": full.get("warnings", []),
                "compliance": full.get("compliance"),
                "images": [{k: img.get(k) for k in ("filename", "backend", "quality", "annotated_url", "original_url", "fields")} for img in full.get("images", [])],
            }
        except Exception:
            detail["result"] = detail.get("result")
    else:
        # Fallback to MongoDB-persisted result (survives Cloudinary/ephemeral disk)
        detail["result"] = detail.get("result")
    return detail

# ============================================================
# Supervisor dashboard APIs — same database the officers write to
# ============================================================
@app.get("/api/dashboard/overview")
def api_overview(_sup: dict = Depends(require_roles("supervisor"))):
    return db.get_dashboard_overview()


@app.get("/api/dashboard/trends")
def api_trends(days: int = 7, _sup: dict = Depends(require_roles("supervisor"))):
    return db.get_dashboard_trends(days)


@app.get("/api/dashboard/scans")
def api_scans(status: str = "all", q: str = "", limit: int = 200, _sup: dict = Depends(require_roles("supervisor"))):
    return {"scans": db.get_scans(status, q, limit)}


@app.get("/api/dashboard/scans/{run_id}")
def api_scan_detail(run_id: str, _sup: dict = Depends(require_roles("supervisor"))):
    detail = db.get_scan_detail(run_id)
    if not detail:
        return {"error": "Scan not found"}
    result_file = RUN_DIR / run_id / "result.json"
    if result_file.exists():
        try:
            full = json.loads(result_file.read_text())
            detail["result"] = {
                "inspection_id": full.get("inspection_id"),
                "disclaimer": full.get("disclaimer"),
                "legal_notice": full.get("legal_notice"),
                "warnings": full.get("warnings", []),
                "compliance": full.get("compliance"),
                "images": [
                    {k: img.get(k) for k in ("filename", "backend", "quality", "annotated_url", "original_url", "fields")}
                    for img in full.get("images", [])
                ],
            }
        except Exception:
            detail["result"] = detail.get("result")
    else:
        detail["result"] = detail.get("result")
    # Always compute similar from MongoDB (works even when file missing)
    try:
        detail["similar"] = [s for s in db.get_scans("NON-COMPLIANT") if s.get("brand") == detail.get("brand") and s.get("run_id") != run_id][:5]
    except Exception:
        detail["similar"] = detail.get("similar") or []
    return detail


@app.get("/api/dashboard/map-pins")
def api_map_pins(_sup: dict = Depends(require_roles("supervisor"))):
    return {"pins": db.get_map_pins()}


@app.get("/api/dashboard/brands")
def api_brands(limit: int = 10, _sup: dict = Depends(require_roles("supervisor"))):
    return {"brands": db.get_brands(limit)}


@app.get("/api/dashboard/locations")
def api_locations(_sup: dict = Depends(require_roles("supervisor"))):
    return {"locations": db.get_locations()}


@app.get("/api/dashboard/officers")
def api_officers(_sup: dict = Depends(require_roles("supervisor"))):
    return {"officers": db.get_officers()}


@app.post("/api/dashboard/officers")
def api_officer_add(payload: dict, _sup: dict = Depends(require_roles("supervisor"))):
    officer_id = str(payload.get("id", "")).strip()
    if not officer_id:
        return {"error": "Officer ID is required"}
    db.add_officer(officer_id, str(payload.get("name", "")).strip() or officer_id,
                    str(payload.get("dept", "") or "Legal Metrology Department"))
    return {"status": "ok"}


@app.delete("/api/dashboard/officers/{officer_id}")
def api_officer_remove(officer_id: str, _sup: dict = Depends(require_roles("supervisor"))):
    db.remove_officer(officer_id)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
