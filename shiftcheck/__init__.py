"""Shiftcheck — daily operations checklists and shift reporting for multi-location teams."""

import mimetypes
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from . import formatting, security
from .config import Config

__version__ = "1.0.0"

# Some platforms (notably Windows) don't map .webp, which would serve photos as octet-stream.
mimetypes.add_type("image/webp", ".webp")


class PrefixMiddleware:
    """Serves the app under a URL prefix (e.g. /shiftcheck) without changing any routes."""

    def __init__(self, wsgi_app, prefix):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path == self.prefix or path.startswith(self.prefix + "/"):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + self.prefix
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
            return self.wsgi_app(environ, start_response)
        start_response("302 Found", [("Location", self.prefix + "/")])
        return [b""]


def create_app(**overrides):
    load_dotenv()
    cfg = Config(**overrides)

    app = Flask(__name__)
    app.config.update(cfg.as_flask_config())
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_PATH=cfg.URL_PREFIX or "/",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg.SESSION_HOURS),
        MAX_CONTENT_LENGTH=64 * 1024 * 1024,
    )

    if cfg.URL_PREFIX:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, cfg.URL_PREFIX)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=0 if cfg.URL_PREFIX else 1)

    formatting.register(app)
    _register_hooks(app)
    _register_errors(app)

    from .routes import register_blueprints
    register_blueprints(app)

    from .cli import register_cli
    register_cli(app)
    return app


def _register_hooks(app):
    @app.before_request
    def enforce_session_age():
        if "user_id" in session:
            started = session.get("login_time", 0)
            if datetime.now().timestamp() - started > app.config["SESSION_HOURS"] * 3600:
                session.clear()
                flash("เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง", "warning")
                return redirect(url_for("auth.login"))

    @app.before_request
    def csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not security.csrf_valid(security.submitted_csrf_token()):
                abort(400, description="แบบฟอร์มหมดอายุหรือไม่ถูกต้อง กรุณาโหลดหน้าใหม่แล้วลองอีกครั้ง")

    @app.context_processor
    def inject_globals():
        from .services import ai, branches
        user = security.current_user()
        pending = 0
        if user and user["is_admin"]:
            try:
                from .db import query_one
                pending = query_one("SELECT COUNT(*) AS n FROM item_requests WHERE status='PENDING'")["n"]
            except Exception:  # The badge must never break page rendering.
                pending = 0
        own_branch = branches.user_branch() if user else None
        return {
            "current_user": user,
            "csrf_token": security.csrf_token,
            "pending_requests": pending,
            "ai_enabled": ai.enabled(),
            "require_live_camera": app.config["REQUIRE_LIVE_CAMERA"],
            "user_branch": own_branch,
            "cleaning_allowed": bool(user and (user["is_admin"] or (own_branch and own_branch["cleaning_schedule_enabled"]))),
            "app_version": __version__,
            "now": datetime.now(),
        }


def _register_errors(app):
    def handler(code, title):
        def render(error):
            # Only show descriptions we wrote ourselves; Werkzeug's defaults are English.
            description = getattr(error, "description", "")
            default = getattr(type(error), "description", None)
            message = description if description and description != default else title
            if security.wants_json():
                return jsonify(success=False, error=message), code
            return render_template("errors/error.html", code=code, title=title, message=message), code
        return render

    app.register_error_handler(400, handler(400, "คำขอไม่ถูกต้อง"))
    app.register_error_handler(401, handler(401, "ต้องเข้าสู่ระบบก่อน"))
    app.register_error_handler(403, handler(403, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้"))
    app.register_error_handler(404, handler(404, "ไม่พบหน้าที่ต้องการ"))
    app.register_error_handler(413, handler(413, "ไฟล์มีขนาดใหญ่เกินไป"))
    app.register_error_handler(500, handler(500, "เกิดข้อผิดพลาดในระบบ"))
