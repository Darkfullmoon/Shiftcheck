"""Saving uploaded photos and signatures to disk."""

import base64
import binascii
import io
import os
import re
from datetime import datetime

from flask import current_app
from PIL import Image, UnidentifiedImageError

PHOTO_DIR = "photos"
SIGNATURE_DIR = "signatures"
MAX_BYTES = 12 * 1024 * 1024


def uploads_root():
    return os.path.join(current_app.static_folder, "uploads")


def _safe(text):
    return re.sub(r"[^A-Za-z0-9_-]", "", text or "")[:40] or "x"


def _decode_data_url(data_url):
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or "," not in data_url:
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > MAX_BYTES:
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img
    except (UnidentifiedImageError, OSError):
        return None


def _filename(prefix, username, ext):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{_safe(prefix)}_{_safe(username)}_{stamp}.{ext}"


def is_stored_upload(path, kind=PHOTO_DIR):
    """True if `path` points at an existing file we saved earlier (prevents arbitrary paths)."""
    prefix = f"/static/uploads/{kind}/"
    if not isinstance(path, str) or not path.startswith(prefix):
        return False
    name = path[len(prefix):]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        return False
    return os.path.isfile(os.path.join(uploads_root(), kind, name))


def local_path(url_path):
    """Maps a stored '/static/uploads/...' URL to a filesystem path, or None."""
    if not isinstance(url_path, str) or not url_path.startswith("/static/uploads/"):
        return None
    rel = url_path[len("/static/"):]
    full = os.path.normpath(os.path.join(current_app.static_folder, rel))
    if not full.startswith(os.path.normpath(uploads_root())):
        return None
    return full if os.path.isfile(full) else None


def save_photo(value, username, prefix="photo", max_dim=1280, quality=80):
    """Accepts a data URL (or an already stored path) and returns the stored URL path."""
    if is_stored_upload(value, PHOTO_DIR):
        # Only accept pre-uploaded files that this user uploaded (the name embeds the uploader).
        return value if f"_{_safe(username)}_" in value else None
    img = _decode_data_url(value)
    if img is None:
        return None
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    folder = os.path.join(uploads_root(), PHOTO_DIR)
    os.makedirs(folder, exist_ok=True)
    name = _filename(prefix, username, "webp")
    img.save(os.path.join(folder, name), "WEBP", quality=quality, method=4)
    return f"/static/uploads/{PHOTO_DIR}/{name}"


def save_photos(values, username, prefix, limit):
    saved = []
    for value in values or []:
        path = save_photo(value, username, prefix)
        if path:
            saved.append(path)
        if len(saved) >= limit:
            break
    return saved


def save_signature(value, username, prefix="sig"):
    if not value:
        return ""
    if is_stored_upload(value, SIGNATURE_DIR):
        return value
    img = _decode_data_url(value)
    if img is None:
        return ""
    folder = os.path.join(uploads_root(), SIGNATURE_DIR)
    os.makedirs(folder, exist_ok=True)
    name = _filename(prefix, username, "png")
    img.save(os.path.join(folder, name), "PNG", optimize=True)
    return f"/static/uploads/{SIGNATURE_DIR}/{name}"


def delete_files(paths):
    removed = 0
    for path in paths or []:
        full = local_path(path)
        if full:
            try:
                os.remove(full)
                removed += 1
            except OSError:
                pass
    return removed
