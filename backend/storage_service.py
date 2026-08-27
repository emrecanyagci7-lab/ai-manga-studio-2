"""Local filesystem storage — Emergent Object Storage'ın yerine geçen ücretsiz alternatif."""
import os
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/app/backend/uploads"))
APP_NAME = os.environ.get("APP_NAME", "ai-manga-studio")

_CT_MAP = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def init_storage(force: bool = False):
    """No-op for local storage; ensures root exists."""
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info(f"Local storage root: {STORAGE_ROOT}")
    return "local"


def _safe_path(relative_path: str) -> Path:
    """Resolve relative_path under STORAGE_ROOT, reject traversal."""
    candidate = (STORAGE_ROOT / relative_path).resolve()
    root = STORAGE_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Invalid storage path")
    return candidate


def put_object(path: str, data: bytes, content_type: str) -> dict:
    target = _safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": path, "size": len(data), "content_type": content_type}


def get_object(path: str) -> tuple[bytes, str]:
    target = _safe_path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(path)
    data = target.read_bytes()
    ext = target.suffix.lstrip(".").lower()
    return data, _CT_MAP.get(ext, "application/octet-stream")


def upload_image(image_bytes: bytes, folder: str, ext: str = "png") -> str:
    """Save image and return storage path."""
    path = f"{APP_NAME}/{folder}/{uuid.uuid4().hex}.{ext}"
    ct = _CT_MAP.get(ext.lower(), "image/png")
    put_object(path, image_bytes, ct)
    return path
