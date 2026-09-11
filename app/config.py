import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for _line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if _line and not _line.lstrip().startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        _value = _value.strip().strip('"').strip("'")
        os.environ.setdefault(_key.strip(), _value)

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "compliscan")
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "").strip().strip('"').strip("'")
CLOUDINARY_FOLDER = os.environ.get("CLOUDINARY_FOLDER", "compliscan")
RULES_PATH = ROOT / "rules" / "demo_rules.json"
UPLOAD_DIR = ROOT / "data" / "uploads"
RUN_DIR = ROOT / "data" / "runs"
STATIC_DIR = ROOT / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RUN_DIR.mkdir(parents=True, exist_ok=True)
