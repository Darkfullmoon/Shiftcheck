"""Sign-in, sign-out and password changes."""

from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import execute, query_one
from ..security import password_expired, validate_password

auth_bp = Blueprint("auth", __name__)


def _safe_next(target):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return None
    return target


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session and not session.get("must_change_password"):
        return redirect(url_for("dashboard.home"))

    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = query_one("SELECT * FROM users WHERE username = %s", (username,)) if username else None

        if not user or not check_password_hash(user["password_hash"], password):
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
            return render_template("auth/login.html", username=username), 401

        session.clear()
        session.permanent = True
        session.update(
            user_id=user["id"],
            username=user["username"],
            full_name=user["full_name"] or user["username"],
            role=user["role"],
            branch_id=user["branch_id"],
            login_time=datetime.now().timestamp(),
        )
        execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (user["id"],))

        if user["must_change_password"]:
            session["must_change_password"] = True
            session["password_reason"] = "first"
            return redirect(url_for("auth.change_password"))
        if user["role"] != "ADMIN" and password_expired(user["password_changed_at"]):
            session["must_change_password"] = True
            session["password_reason"] = "expired"
            return redirect(url_for("auth.change_password"))

        flash(f"ยินดีต้อนรับ {session['full_name']}", "success")
        return redirect(_safe_next(request.args.get("next")) or url_for("dashboard.home"))

    return render_template("auth/login.html", username=username)


@auth_bp.route("/account/password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    forced = bool(session.get("must_change_password"))
    reason = session.get("password_reason")

    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        user = query_one("SELECT id, password_hash FROM users WHERE id = %s", (session["user_id"],))

        error = None
        if not user:
            session.clear()
            return redirect(url_for("auth.login"))
        if not check_password_hash(user["password_hash"], current):
            error = "รหัสผ่านปัจจุบันไม่ถูกต้อง"
        elif new != confirm:
            error = "รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน"
        elif check_password_hash(user["password_hash"], new):
            error = "กรุณาตั้งรหัสผ่านที่ไม่ซ้ำกับรหัสผ่านเดิม"
        else:
            error = validate_password(new)

        if error:
            flash(error, "error")
        else:
            execute(
                "UPDATE users SET password_hash = %s, password_changed_at = NOW(), must_change_password = 0 "
                "WHERE id = %s",
                (generate_password_hash(new), user["id"]),
            )
            session.pop("must_change_password", None)
            session.pop("password_reason", None)
            flash("เปลี่ยนรหัสผ่านเรียบร้อยแล้ว", "success")
            return redirect(url_for("dashboard.home"))

    return render_template("auth/change_password.html", forced=forced, reason=reason)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("ออกจากระบบเรียบร้อยแล้ว", "info")
    return redirect(url_for("auth.login"))
