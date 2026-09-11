from __future__ import annotations
import json, shutil, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from . import db
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

db.init_db()
db.backfill_runs()
if db.ensure_default_supervisor():
    print(f"[auth] default supervisor login: {db.DEFAULT_SUPERVISOR_ID} / {db.DEFAULT_SUPERVISOR_PASSWORD}  (change after first login)")

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
        image_results.append({"filename": upload.filename, "image_id": f"image_{idx}", "backend": used_backend, "quality": quality, "boxes": boxes, "fields": fields, "original_url": f"/files/{run_id}/{original_name}", "annotated_url": f"/files/{run_id}/{annotated_name}"})
    if not image_results:
        return {"error": "No readable images were uploaded.", "warnings": warnings}
    rules = load_rules(RULES_PATH)
    compliance = evaluate(image_results, rules)
    response = {"inspection_id":f"LM-DEMO-{run_id.upper()}", "backend_requested":backend, "rule_set_id":rules["rule_set_id"], "disclaimer":rules["disclaimer"], "legal_notice":rules.get("legal_notice"), "warnings":warnings, "images":[], "compliance":compliance}
    for item in image_results:
        response["images"].append({"filename":item["filename"], "backend":item["backend"], "quality":item["quality"], "boxes":[b.to_dict() for b in item["boxes"]], "fields":{k:v for k,v in item["fields"].items() if not k.startswith("_")}, "original_url":item["original_url"], "annotated_url":item["annotated_url"]})
    (out_dir/"result.json").write_text(json.dumps(response, indent=2, ensure_ascii=False))
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
    conn = db._connect()
    row = conn.execute("SELECT run_id, officer_id FROM scans WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")
    if sess["role"] == "officer" and row["officer_id"] != sess["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Not your inspection")
    conn.execute(f"UPDATE scans SET {column} = 1 WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()
    return {"status": "ok", column: 1}

@app.post("/api/inspection/{run_id}/report")
def api_mark_report(run_id: str, sess: dict = Depends(require_roles("officer", "supervisor"))):
    """Officer generated the PDF report — visible on the supervisor dashboard."""
    return _flag_scan(run_id, sess, "report_generated")

@app.post("/api/inspection/{run_id}/submit")
def api_mark_submitted(run_id: str, sess: dict = Depends(require_roles("officer", "supervisor"))):
    """Officer submitted the case to their supervisor."""
    return _flag_scan(run_id, sess, "submitted")


# ============================================================
# Supervisor dashboard APIs — same database the officers write to
# ============================================================
@app.get("/api/dashboard/overview")
def api_overview(_sup: dict = Depends(require_roles("supervisor"))):
    conn = db._connect()
    total = conn.execute("SELECT COUNT(*) c FROM scans").fetchone()["c"]
    violations = conn.execute("SELECT COUNT(*) c FROM scans WHERE status = 'NON-COMPLIANT'").fetchone()["c"]
    compliant = conn.execute("SELECT COUNT(*) c FROM scans WHERE status = 'COMPLIANT'").fetchone()["c"]
    officials = conn.execute("SELECT COUNT(*) c FROM officers").fetchone()["c"]
    conn.close()
    return {"total_scans": total, "violations": violations, "compliant": compliant, "officials": officials}


@app.get("/api/dashboard/trends")
def api_trends(days: int = 7, _sup: dict = Depends(require_roles("supervisor"))):
    from datetime import timedelta
    days = max(1, min(30, days))
    today = datetime.now(timezone.utc).date()
    labels, comp, noncomp = [], [], []
    conn = db._connect()
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.isoformat()
        labels.append(day.strftime("%d %b"))
        comp.append(conn.execute(
            "SELECT COUNT(*) c FROM scans WHERE date LIKE ? AND status = 'COMPLIANT'", (day_str + "%",)).fetchone()["c"])
        noncomp.append(conn.execute(
            "SELECT COUNT(*) c FROM scans WHERE date LIKE ? AND status = 'NON-COMPLIANT'", (day_str + "%",)).fetchone()["c"])
    conn.close()
    return {"labels": labels, "compliant": comp, "non_compliant": noncomp}


@app.get("/api/dashboard/scans")
def api_scans(status: str = "all", q: str = "", limit: int = 200, _sup: dict = Depends(require_roles("supervisor"))):
    query = "SELECT * FROM scans WHERE 1=1"
    params: list = []
    if status.upper() in ("COMPLIANT", "NON-COMPLIANT", "REVIEW"):
        query += " AND status = ?"
        params.append(status.upper())
    if q.strip():
        query += " AND (product LIKE ? OR brand LIKE ? OR officer_name LIKE ? OR city LIKE ? OR inspection_id LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like] * 5)
    query += " ORDER BY date DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    conn = db._connect()
    rows = db.dicts(conn.execute(query, params))
    conn.close()
    return {"scans": rows}


@app.get("/api/dashboard/scans/{run_id}")
def api_scan_detail(run_id: str, _sup: dict = Depends(require_roles("supervisor"))):
    conn = db._connect()
    row = conn.execute("SELECT * FROM scans WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": "Scan not found"}
    detail = dict(row)
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
                    {k: img.get(k) for k in ("filename", "backend", "quality", "annotated_url", "fields")}
                    for img in full.get("images", [])
                ],
            }
            # similar past violations: same brand flagged before, excluding self
            conn = db._connect()
            similar = db.dicts(conn.execute(
                """SELECT run_id, inspection_id, date, product, city, officer_name, status
                   FROM scans WHERE brand = ? AND status = 'NON-COMPLIANT' AND run_id != ?
                   ORDER BY date DESC LIMIT 5""",
                (detail["brand"], run_id)))
            conn.close()
            detail["similar"] = similar
        except Exception:
            detail["result"] = None
            detail["similar"] = []
    else:
        detail["result"] = None
        detail["similar"] = []
    return detail


@app.get("/api/dashboard/map-pins")
def api_map_pins(_sup: dict = Depends(require_roles("supervisor"))):
    """Every scan with GPS → pin on the real map. Supports dashboard filters."""
    conn = db._connect()
    rows = db.dicts(conn.execute(
        """SELECT run_id, inspection_id, product, brand, city, lat, lng, status, date, officer_name
           FROM scans WHERE lat IS NOT NULL AND lng IS NOT NULL
           ORDER BY date DESC LIMIT 500"""))
    conn.close()
    return {"pins": rows}


@app.get("/api/dashboard/brands")
def api_brands(limit: int = 10, _sup: dict = Depends(require_roles("supervisor"))):
    conn = db._connect()
    rows = db.dicts(conn.execute(
        """SELECT brand, COUNT(*) total,
                  SUM(CASE WHEN status = 'NON-COMPLIANT' THEN 1 ELSE 0 END) violations
           FROM scans GROUP BY brand ORDER BY violations DESC, total DESC LIMIT ?""",
        (max(1, min(50, limit)),)))
    conn.close()
    return {"brands": rows}


@app.get("/api/dashboard/locations")
def api_locations(_sup: dict = Depends(require_roles("supervisor"))):
    conn = db._connect()
    rows = db.dicts(conn.execute(
        """SELECT city, COUNT(*) total,
                  SUM(CASE WHEN status = 'NON-COMPLIANT' THEN 1 ELSE 0 END) violations,
                  AVG(lat) lat, AVG(lng) lng
           FROM scans GROUP BY city ORDER BY violations DESC"""))
    conn.close()
    return {"locations": rows}


@app.get("/api/dashboard/officers")
def api_officers(_sup: dict = Depends(require_roles("supervisor"))):
    conn = db._connect()
    rows = db.dicts(conn.execute(
        """SELECT o.id, o.name, o.dept, o.last_seen,
                  COUNT(s.run_id) scans,
                  SUM(CASE WHEN s.status = 'NON-COMPLIANT' THEN 1 ELSE 0 END) violations,
                  SUM(CASE WHEN s.status = 'COMPLIANT' THEN 1 ELSE 0 END) compliant
           FROM officers o LEFT JOIN scans s ON s.officer_id = o.id
           GROUP BY o.id ORDER BY scans DESC"""))
    conn.close()
    return {"officers": rows}


@app.post("/api/dashboard/officers")
def api_officer_add(payload: dict, _sup: dict = Depends(require_roles("supervisor"))):
    officer_id = str(payload.get("id", "")).strip()
    if not officer_id:
        return {"error": "Officer ID is required"}
    db.upsert_officer(officer_id, str(payload.get("name", "")).strip() or officer_id,
                      str(payload.get("dept", "") or "Legal Metrology Department"))
    return {"status": "ok"}


@app.delete("/api/dashboard/officers/{officer_id}")
def api_officer_remove(officer_id: str, _sup: dict = Depends(require_roles("supervisor"))):
    conn = db._connect()
    conn.execute("DELETE FROM officers WHERE id = ?", (officer_id,))
    conn.execute("UPDATE scans SET officer_id = NULL WHERE officer_id = ?", (officer_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
