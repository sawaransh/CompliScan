from __future__ import annotations
import hashlib, secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo import MongoClient, ASCENDING

from .config import MONGODB_URI, MONGODB_DB_NAME

_session_lifetime = timedelta(days=7)
DEFAULT_SUPERVISOR_ID = "SUP001"
DEFAULT_SUPERVISOR_PASSWORD = "admin123"

_mongo_client: Optional[MongoClient] = None
_mongo_db: Optional = None

def _client() -> MongoClient:
    global _mongo_client, _mongo_db
    if _mongo_client is None:
        import certifi
        _mongo_client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=10000,
            tlsCAFile=certifi.where(),
            retryWrites=True,
        )
        _mongo_db = _mongo_client[MONGODB_DB_NAME]
        _ensure_indexes()
    return _mongo_client

def _get_db():
    _client()
    return _mongo_db

def _officers():
    return _get_db()["officers"]

def _scans():
    return _get_db()["scans"]

def _users():
    return _get_db()["users"]

def _sessions():
    return _get_db()["sessions"]

def _ensure_indexes() -> None:
    _sessions().create_index("expires_at", expireAfterSeconds=0)
    _scans().create_index("run_id", unique=True)
    _scans().create_index([("officer_id", ASCENDING)])
    _scans().create_index([("date", ASCENDING)])
    _scans().create_index([("status", ASCENDING)])
    _scans().create_index([("brand", ASCENDING)])
    _scans().create_index([("city", ASCENDING)])

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_db() -> None:
    _ensure_indexes()
    if _users().count_documents({"role": "supervisor"}) == 0:
        _users().insert_one({
            "_id": DEFAULT_SUPERVISOR_ID,
            "name": "Supervisor",
            "role": "supervisor",
            "password_hash": hash_password(DEFAULT_SUPERVISOR_PASSWORD),
            "created_at": now_iso(),
        })

def backfill_runs() -> int:
    return 0

def upsert_officer(officer_id: str, name: str, dept: str = "Legal Metrology Department") -> None:
    if not officer_id:
        return
    _officers().update_one(
        {"_id": officer_id},
        {"$set": {"name": name or officer_id, "dept": dept or "Legal Metrology Department", "last_seen": now_iso()}},
        upsert=True,
    )

def insert_scan(record: dict) -> None:
    doc = {k: v for k, v in record.items()}
    doc["_id"] = record["run_id"]
    doc.setdefault("report_generated", 0)
    doc.setdefault("submitted", 0)
    doc.setdefault("has_result", 1)
    _scans().replace_one({"_id": record["run_id"]}, doc, upsert=True)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${digest}"

def check_password(password: str, stored: str | None) -> bool:
    try:
        algo, salt, digest = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
        return secrets.compare_digest(candidate, digest)
    except Exception:
        return False

def ensure_default_supervisor() -> bool:
    return _users().count_documents({"_id": DEFAULT_SUPERVISOR_ID}) == 0

def verify_officer(officer_id: str, name: str) -> dict | None:
    row = _officers().find_one({"_id": officer_id})
    if not row or row["name"].strip().lower() != (name or "").strip().lower():
        return None
    return {"id": row["_id"], "name": row["name"], "dept": row.get("dept", "Legal Metrology Department")}

def verify_supervisor(supervisor_id: str, password: str) -> dict | None:
    row = _users().find_one({"_id": supervisor_id, "role": "supervisor"})
    if not row or not check_password(password or "", row.get("password_hash")):
        return None
    return {"id": row["_id"], "name": row["name"]}

def create_session(user_id: str, role: str) -> str:
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    _sessions().insert_one({
        "_id": token,
        "user_id": user_id,
        "role": role,
        "created_at": now.isoformat(),
        "expires_at": (now + _session_lifetime).isoformat(),
    })
    return token

def get_session(token: str) -> dict | None:
    row = _sessions().find_one({"_id": token})
    if not row:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            _sessions().delete_one({"_id": token})
            return None
    except Exception:
        return None
    identity = session_identity(row["user_id"], row["role"])
    if not identity:
        return None
    return {"user_id": row["user_id"], "role": row["role"], **identity}

def session_identity(user_id: str, role: str) -> dict | None:
    if role == "officer":
        row = _officers().find_one({"_id": user_id})
    else:
        row = _users().find_one({"_id": user_id, "role": "supervisor"})
    if not row:
        return None
    identity = {"id": row["_id"], "name": row["name"]}
    if role == "officer":
        identity["dept"] = row.get("dept", "Legal Metrology Department")
    return identity

def delete_session(token: str) -> None:
    _sessions().delete_one({"_id": token})

def change_supervisor_password(supervisor_id: str, current: str, new: str) -> bool:
    row = _users().find_one({"_id": supervisor_id, "role": "supervisor"})
    if not row or not check_password(current or "", row.get("password_hash", "")):
        return False
    _users().update_one({"_id": supervisor_id}, {"$set": {"password_hash": hash_password(new)}})
    _sessions().delete_many({"user_id": supervisor_id})
    return True

def flag_scan(run_id: str, column: str) -> dict:
    if column not in ("report_generated", "submitted"):
        raise ValueError("Unknown flag")
    result = _scans().update_one({"_id": run_id}, {"$set": {column: 1}})
    if result.matched_count == 0:
        raise RuntimeError("Inspection not found")
    return {"status": "ok", column: 1}

def get_scan(run_id: str) -> dict | None:
    row = _scans().find_one({"_id": run_id})
    if not row:
        return None
    row = dict(row)
    row["run_id"] = row.pop("_id")
    return row

def scan_exists(run_id: str) -> bool:
    return _scans().find_one({"_id": run_id}) is not None

def get_scans(status: str = "all", q: str = "", limit: int = 200) -> list[dict]:
    query = {}
    if status.upper() in ("COMPLIANT", "NON-COMPLIANT", "REVIEW"):
        query["status"] = status.upper()
    if q.strip():
        query["$or"] = [
            {"product": {"$regex": q.strip(), "$options": "i"}},
            {"brand": {"$regex": q.strip(), "$options": "i"}},
            {"officer_name": {"$regex": q.strip(), "$options": "i"}},
            {"city": {"$regex": q.strip(), "$options": "i"}},
            {"inspection_id": {"$regex": q.strip(), "$options": "i"}},
        ]
    rows = list(_scans().find(query).sort("date", -1).limit(max(1, min(500, limit))))
    out = []
    for r in rows:
        doc = dict(r)
        doc["run_id"] = doc.pop("_id")
        out.append(doc)
    return out

def get_scan_detail(run_id: str) -> dict | None:
    row = _scans().find_one({"_id": run_id})
    if not row:
        return None
    doc = dict(row)
    doc["run_id"] = doc.pop("_id")
    return doc

def get_map_pins() -> list[dict]:
    rows = list(_scans().find({"lat": {"$ne": None}, "lng": {"$ne": None}}).sort("date", -1).limit(500))
    out = []
    for r in rows:
        doc = dict(r)
        doc["run_id"] = doc.pop("_id")
        out.append(doc)
    return out

def get_brands(limit: int = 10) -> list[dict]:
    pipeline = [
        {"$group": {"_id": "$brand", "total": {"$sum": 1}, "violations": {"$sum": {"$cond": [{"$eq": ["$status", "NON-COMPLIANT"]}, 1, 0]}}}},
        {"$sort": {"violations": -1, "total": -1}},
        {"$limit": max(1, min(50, limit))},
    ]
    rows = list(_scans().aggregate(pipeline))
    return [{"brand": r["_id"], "total": r["total"], "violations": r["violations"]} for r in rows]

def get_locations() -> list[dict]:
    pipeline = [
        {"$group": {"_id": "$city", "total": {"$sum": 1}, "violations": {"$sum": {"$cond": [{"$eq": ["$status", "NON-COMPLIANT"]}, 1, 0]}}}},
        {"$sort": {"violations": -1}},
    ]
    rows = list(_scans().aggregate(pipeline))
    return [{"city": r["_id"], "total": r["total"], "violations": r["violations"]} for r in rows]

def get_officer_scans(officer_id: str, status: str = "all", q: str = "", limit: int = 200) -> list[dict]:
    query: dict = {"officer_id": officer_id}
    if status.upper() in ("COMPLIANT", "NON-COMPLIANT", "REVIEW"):
        query["status"] = status.upper()
    if q.strip():
        qr = {"$regex": q.strip(), "$options": "i"}
        query["$or"] = [{"product": qr}, {"brand": qr}, {"city": qr}, {"inspection_id": qr}]
        # $or must be at top level with officer_id – use $and
        query = {"$and": [{"officer_id": officer_id}, {"$or": [{"product": qr}, {"brand": qr}, {"city": qr}, {"inspection_id": qr}]}]}
        if status.upper() in ("COMPLIANT", "NON-COMPLIANT", "REVIEW"):
            query["$and"].append({"status": status.upper()})
    rows = list(_scans().find(query).sort("date", -1).limit(max(1, min(500, limit))))
    out = []
    for r in rows:
        doc = dict(r)
        doc["run_id"] = doc.pop("_id")
        out.append(doc)
    return out

def get_officer_overview(officer_id: str) -> dict:
    total = _scans().count_documents({"officer_id": officer_id})
    violations = _scans().count_documents({"officer_id": officer_id, "status": "NON-COMPLIANT"})
    compliant = _scans().count_documents({"officer_id": officer_id, "status": "COMPLIANT"})
    pending = _scans().count_documents({"officer_id": officer_id, "submitted": {"$ne": 1}})
    return {"total_scans": total, "violations": violations, "compliant": compliant, "pending": pending}

def get_officers() -> list[dict]:
    pipeline = [
        {"$lookup": {"from": "scans", "localField": "_id", "foreignField": "officer_id", "as": "scans"}},
        {"$addFields": {
            "scans_count": {"$size": "$scans"},
            "violations": {"$sum": {"$cond": [{"$eq": ["$scans.status", "NON-COMPLIANT"]}, 1, 0]}},
            "compliant": {"$sum": {"$cond": [{"$eq": ["$scans.status", "COMPLIANT"]}, 1, 0]}},
        }},
        {"$project": {"scans": 0}},
        {"$sort": {"scans_count": -1}},
    ]
    rows = list(_officers().aggregate(pipeline))
    out = []
    for r in rows:
        doc = dict(r)
        doc["id"] = doc.pop("_id")
        out.append(doc)
    return out

def officer_exists(officer_id: str) -> bool:
    return _officers().find_one({"_id": officer_id}) is not None

def add_officer(officer_id: str, name: str, dept: str = "Legal Metrology Department") -> None:
    upsert_officer(officer_id, name, dept)

def remove_officer(officer_id: str) -> None:
    _officers().delete_one({"_id": officer_id})
    _scans().update_many({"officer_id": officer_id}, {"$set": {"officer_id": None}})

def get_dashboard_overview() -> dict:
    total = _scans().count_documents({})
    violations = _scans().count_documents({"status": "NON-COMPLIANT"})
    compliant = _scans().count_documents({"status": "COMPLIANT"})
    officials = _officers().count_documents({})
    return {"total_scans": total, "violations": violations, "compliant": compliant, "officials": officials}

def get_dashboard_trends(days: int = 7) -> dict:
    from datetime import timedelta
    days = max(1, min(30, days))
    today = datetime.now(timezone.utc).date()
    labels, comp, noncomp = [], [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.isoformat()
        labels.append(day.strftime("%d %b"))
        comp.append(_scans().count_documents({"date": {"$gte": day_str, "$lt": (day + timedelta(days=1)).isoformat()}, "status": "COMPLIANT"}))
        noncomp.append(_scans().count_documents({"date": {"$gte": day_str, "$lt": (day + timedelta(days=1)).isoformat()}, "status": "NON-COMPLIANT"}))
    return {"labels": labels, "compliant": comp, "non_compliant": noncomp}
