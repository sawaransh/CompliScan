from __future__ import annotations
import json
import logging
from pathlib import Path

from .config import CLOUDINARY_URL, CLOUDINARY_FOLDER

log = logging.getLogger("compliscan.storage")

_enabled: bool | None = None

def is_cloudinary_enabled() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    if not CLOUDINARY_URL:
        _enabled = False
        return False
    try:
        import cloudinary
        cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)
        # quick validation — parsing fails if URL malformed
        cfg = cloudinary.config()
        _enabled = bool(cfg.cloud_name)
        if not _enabled:
            log.warning("CLOUDINARY_URL malformed — falling back to local /files")
        return _enabled
    except Exception as exc:
        log.warning("Cloudinary init failed (%s) — falling back to local", exc)
        _enabled = False
        return False

def upload_image(local_path: Path, run_id: str, filename: str) -> str | None:
    """Upload one evidence image to Cloudinary. Returns secure_url or None on failure."""
    if not is_cloudinary_enabled():
        return None
    try:
        import cloudinary.uploader
        public_id = f"{CLOUDINARY_FOLDER}/{run_id}/{Path(filename).stem}"
        # Use image resource, keep original format, folder per run for easy cleanup
        res = cloudinary.uploader.upload(
            str(local_path),
            public_id=public_id,
            folder=CLOUDINARY_FOLDER,
            overwrite=True,
            resource_type="image",
            type="upload",
        )
        url = res.get("secure_url")
        if url:
            log.info("cloudinary upload %s -> %s", local_path.name, url[:80])
        return url
    except Exception as exc:
        log.warning("cloudinary image upload failed %s: %s", local_path, exc)
        return None

def upload_result_json(local_path: Path, run_id: str) -> str | None:
    """Upload result.json as raw; returns secure_url or None."""
    if not is_cloudinary_enabled():
        return None
    try:
        import cloudinary.uploader
        public_id = f"{CLOUDINARY_FOLDER}/{run_id}/result"
        res = cloudinary.uploader.upload(
            str(local_path),
            public_id=public_id,
            folder=CLOUDINARY_FOLDER,
            overwrite=True,
            resource_type="raw",
        )
        return res.get("secure_url")
    except Exception as exc:
        log.warning("cloudinary result upload failed %s: %s", local_path, exc)
        return None

def fetch_result_json(run_id: str) -> dict | None:
    """If local result.json missing (ephemeral disk), fetch from MongoDB fallback or Cloudinary."""
    # Primary fallback is MongoDB-stored result if we ever store it there.
    # For now try Cloudinary raw download via URL stored in scan doc (not yet).
    # This is a no-op placeholder — caller should fall back to 404 if local missing.
    return None
