import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Local-only development secrets. .env is gitignored and existing shell values win.
for _line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if _line and not _line.lstrip().startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _value.strip())

RULES_PATH = ROOT / "rules" / "demo_rules.json"
UPLOAD_DIR = ROOT / "data" / "uploads"
RUN_DIR = ROOT / "data" / "runs"
STATIC_DIR = ROOT / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RUN_DIR.mkdir(parents=True, exist_ok=True)
