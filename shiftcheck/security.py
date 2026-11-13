"""Authentication helpers: CSRF, access decorators, password rules."""

import hmac
import re
import secrets
from datetime import datetime
from functools import wraps

from flask import abort, current_app, flash, redirect, request, session, url_for

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


# ---------------------------------------------------------------- CSRF

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(32)
    return session["_csrf"]


def csrf_valid(token):
    expected = session.get("_csrf")
    return bool(expected and token) and hmac.compare_digest(str(expected), str(token).strip())


def submitted_csrf_token():
    token = request.form.get("csrf_token")
    if not token and request.is_json:
        token = (request.get_json(silent=True) or {}).get("csrf_token")
    return token or request.headers.get("X-CSRF-Token")


# ---------------------------------------------------------------- session / roles

def current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "username": session.get("username"),
        "full_name": session.get("full_name") or session.get("username"),
        "role": session.get("role", "USER"),
        "branch_id": session.get("branch_id"),
        "is_admin": session.get("role") == "ADMIN",
    }


def is_admin():
    return session.get("role") == "ADMIN"


def wants_json():
    return request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" \
        or request.accept_mimetypes.best == "application/json"


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if wants_json():
                abort(401)
            flash("กรุณาเข้าสู่ระบบก่อนใช้งาน", "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        if session.get("must_change_password"):
            return redirect(url_for("auth.change_password"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not is_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- passwords

def validate_username(username):
    if not username:
        return "กรุณากรอกชื่อผู้ใช้"
    if not USERNAME_RE.match(username):
        return "ชื่อผู้ใช้ต้องเป็นอักษรภาษาอังกฤษพิมพ์เล็ก ตัวเลข จุด ขีด หรือขีดล่าง ยาว 3–32 ตัว"
    return None


def validate_password(password):
    """Returns an error message, or None when the password is strong enough."""
    if not password or len(password) < 8:
        return "รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร"
    checks = [
        (r"[A-Z]", "ตัวพิมพ์ใหญ่"),
        (r"[a-z]", "ตัวพิมพ์เล็ก"),
        (r"[0-9]", "ตัวเลข"),
        (r"[^A-Za-z0-9]", "อักขระพิเศษ"),
    ]
    missing = [label for pattern, label in checks if not re.search(pattern, password)]
    if missing:
        return "รหัสผ่านต้องมี " + ", ".join(missing)
    return None


def generate_temp_password(length=10):
    """Readable random password that always satisfies validate_password()."""
    pools = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789", "!@#$%&*?"]
    chars = [secrets.choice(pool) for pool in pools]
    everything = "".join(pools)
    chars += [secrets.choice(everything) for _ in range(max(0, length - len(chars)))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def password_expired(changed_at):
    max_age = current_app.config.get("PASSWORD_MAX_AGE_DAYS", 0)
    if not max_age:
        return False
    if not changed_at:
        return True
    return (datetime.now() - changed_at).days >= max_age
