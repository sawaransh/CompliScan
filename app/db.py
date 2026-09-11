from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT, RUN_DIR

DB_PATH = ROOT / "data" / "compliscan.db"
SESSION_DAYS = 7
DEFAULT_SUPERVISOR_ID = "SUP001"
DEFAULT_SUPERVISOR_PASSWORD = "admin123"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS officers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dept TEXT NOT NULL DEFAULT 'Legal Metrology Department',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scans (
            run_id TEXT PRIMARY KEY,
            inspection_id TEXT NOT NULL,
            officer_id TEXT,
            officer_name TEXT NOT NULL DEFAULT 'Unknown',
            date TEXT NOT NULL,
            product TEXT NOT NULL DEFAULT 'Unnamed product',
            brand TEXT NOT NULL DEFAULT 'Unknown brand',
            city TEXT NOT NULL DEFAULT 'Unknown',
            lat REAL,
            lng REAL,
            status TEXT NOT NULL DEFAULT 'REVIEW',
            passed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            review INTEGER NOT NULL DEFAULT 0,
            image_count INTEGER NOT NULL DEFAULT 0,
            has_result INTEGER NOT NULL DEFAULT 0,
            report_generated INTEGER NOT NULL DEFAULT 0,
            submitted INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_scans_date ON scans(date);
        CREATE INDEX IF NOT EXISTS idx_scans_officer ON scans(officer_id);
        CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('officer', 'supervisor')),
            password_hash TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        """
    )
    conn.commit()
    # Columns added after the first release (idempotent on existing databases).
    for ddl in (
        "ALTER TABLE scans ADD COLUMN report_generated INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE scans ADD COLUMN submitted INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.commit()
    conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_officer(officer_id: str, name: str, dept: str = "Legal Metrology Department") -> None:
    if not officer_id:
        return
    conn = _connect()
    row = conn.execute("SELECT id FROM officers WHERE id = ?", (officer_id,)).fetchone()
    if row:
        conn.execute(
            "UPDATE officers SET name = ?, dept = ?, last_seen = ? WHERE id = ?",
            (name or officer_id, dept or "Legal Metrology Department", now_iso(), officer_id),
        )
    else:
        conn.execute(
            "INSERT INTO officers (id, name, dept, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
            (officer_id, name or officer_id, dept or "Legal Metrology Department", now_iso(), now_iso()),
        )
    conn.commit()
    conn.close()


def insert_scan(record: dict) -> None:
    conn = _connect()
    conn.execute(
        """INSERT OR REPLACE INTO scans
           (run_id, inspection_id, officer_id, officer_name, date, product, brand,
            city, lat, lng, status, passed, failed, review, image_count, has_result)
           VALUES (:run_id, :inspection_id, :officer_id, :officer_name, :date, :product, :brand,
                   :city, :lat, :lng, :status, :passed, :failed, :review, :image_count, :has_result)""",
        record,
    )
    conn.commit()
    conn.close()


def backfill_runs() -> int:
    """Import pre-database data/runs/*/result.json files. Returns count imported."""
    if not RUN_DIR.exists():
        return 0
    conn = _connect()
    existing = {r["run_id"] for r in conn.execute("SELECT run_id FROM scans")}
    conn.close()
    imported = 0
    for result_file in sorted(RUN_DIR.glob("*/result.json")):
        run_id = result_file.parent.name
        if run_id in existing:
            continue
        try:
            data = json.loads(result_file.read_text())
        except Exception:
            continue
        c = data.get("compliance", {})
        fields = c.get("fields", {}) or {}
        summary = c.get("summary", {}) or {}
        manufacturer = (fields.get("manufacturer") or {}).get("value")
        product = (fields.get("product_name") or {}).get("value")
        try:
            date = datetime.fromtimestamp(result_file.stat().st_mtime, tz=timezone.utc).isoformat()
        except Exception:
            date = now_iso()
        insert_scan({
            "run_id": run_id,
            "inspection_id": data.get("inspection_id", f"LM-DEMO-{run_id.upper()}"),
            "officer_id": None,
            "officer_name": "Unknown",
            "date": date,
            "product": product or "Unnamed product",
            "brand": manufacturer or "Unknown brand",
            "city": "Unknown",
            "lat": None,
            "lng": None,
            "status": c.get("overall_status", "REVIEW"),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "review": summary.get("review", 0),
            "image_count": len(data.get("images", [])),
            "has_result": 1,
        })
        imported += 1
    return imported


def dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ============================================================
# Auth: password hashing, users, sessions
# ============================================================
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
    """Create the initial supervisor login. Returns True on first creation."""
    conn = _connect()
    row = conn.execute("SELECT id FROM users WHERE id = ?", (DEFAULT_SUPERVISOR_ID,)).fetchone()
    if row:
        conn.close()
        return False
    conn.execute(
        "INSERT INTO users (id, name, role, password_hash, created_at) VALUES (?, ?, 'supervisor', ?, ?)",
        (DEFAULT_SUPERVISOR_ID, "Supervisor", hash_password(DEFAULT_SUPERVISOR_PASSWORD), now_iso()),
    )
    conn.commit()
    conn.close()
    return True


def verify_officer(officer_id: str, name: str) -> dict | None:
    """Officers authenticate with registry ID + full name (field-device friendly)."""
    conn = _connect()
    row = conn.execute("SELECT id, name, dept FROM officers WHERE id = ?", (officer_id,)).fetchone()
    conn.close()
    if not row or row["name"].strip().lower() != (name or "").strip().lower():
        return None
    return {"id": row["id"], "name": row["name"], "dept": row["dept"]}


def verify_supervisor(supervisor_id: str, password: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT id, name, password_hash FROM users WHERE id = ? AND role = 'supervisor'", (supervisor_id,)).fetchone()
    conn.close()
    if not row or not check_password(password or "", row["password_hash"]):
        return None
    return {"id": row["id"], "name": row["name"]}


def create_session(user_id: str, role: str) -> str:
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    conn = _connect()
    conn.execute(
        "INSERT INTO sessions (token, user_id, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (token, user_id, role, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def get_session(token: str) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT token, user_id, role, expires_at FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            delete_session(token)
            return None
    except Exception:
        return None
    identity = session_identity(row["user_id"], row["role"])
    if not identity:
        return None
    return {"user_id": row["user_id"], "role": row["role"], **identity}


def session_identity(user_id: str, role: str) -> dict | None:
    """Fresh display identity for a session owner (dept included for officers)."""
    conn = _connect()
    if role == "officer":
        row = conn.execute("SELECT id, name, dept FROM officers WHERE id = ?", (user_id,)).fetchone()
    else:
        row = conn.execute("SELECT id, name FROM users WHERE id = ? AND role = 'supervisor'", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    identity = {"id": row["id"], "name": row["name"]}
    if role == "officer":
        identity["dept"] = row["dept"]
    return identity


def delete_session(token: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def change_supervisor_password(supervisor_id: str, current: str, new: str) -> bool:
    """Returns True on success; False when the current password is wrong."""
    conn = _connect()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id = ? AND role = 'supervisor'", (supervisor_id,)).fetchone()
    if not row or not check_password(current or "", row["password_hash"]):
        conn.close()
        return False
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), supervisor_id))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (supervisor_id,))
    conn.commit()
    conn.close()
    return True
