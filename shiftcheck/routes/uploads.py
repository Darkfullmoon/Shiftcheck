"""Photo pre-upload endpoint used by the camera widget."""

from flask import Blueprint, jsonify, request

from ..security import login_required
from ..services import media
from .common import username

uploads_bp = Blueprint("uploads", __name__)


@uploads_bp.post("/uploads/photo")
@login_required
def upload_photo():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind") if data.get("kind") in ("audit", "report") else "photo"
    path = media.save_photo(data.get("photo"), username(), prefix=kind)
    if not path:
        return jsonify(success=False, error="ไฟล์นี้ไม่ใช่รูปภาพที่รองรับ"), 400
    return jsonify(success=True, path=path)
