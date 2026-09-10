from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "rules" / "demo_rules.json"
UPLOAD_DIR = ROOT / "data" / "uploads"
RUN_DIR = ROOT / "data" / "runs"
STATIC_DIR = ROOT / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RUN_DIR.mkdir(parents=True, exist_ok=True)
