"""Application settings, read from environment variables (see .env.example)."""

import os
import secrets
from datetime import time


def _bool(name, default=False):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _time(name, default):
    raw = (os.getenv(name) or default).strip()
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        hours, minutes = default.split(":")
        return time(int(hours), int(minutes))


def _prefix(raw):
    raw = (raw or "").strip().strip("/")
    return f"/{raw}" if raw else ""


class Config:
    def __init__(self, **overrides):
        self.SECRET_KEY = os.getenv("SECRET_KEY") or ""
        self.SECRET_KEY_GENERATED = not self.SECRET_KEY
        if not self.SECRET_KEY:
            # Sessions will not survive a restart; fine for local development only.
            self.SECRET_KEY = secrets.token_hex(32)

        self.DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
        self.DB_PORT = _int("DB_PORT", 3306)
        self.DB_NAME = os.getenv("DB_NAME", "shiftcheck")
        self.DB_USER = os.getenv("DB_USER", "shiftcheck")
        self.DB_PASSWORD = os.getenv("DB_PASSWORD", "")
        # e.g. +07:00; defaults to the app server's local offset
        self.DB_TIMEZONE = os.getenv("DB_TIMEZONE", "").strip()

        self.DEBUG = _bool("FLASK_DEBUG", False)
        self.PORT = _int("PORT", 8000)
        self.URL_PREFIX = _prefix(os.getenv("URL_PREFIX"))
        self.SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME") or "shiftcheck_session"

        self.ADMIN_USERNAME = (os.getenv("ADMIN_USERNAME") or "admin").strip().lower()
        self.ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") or ""

        self.AUDIT_DEADLINE = _time("AUDIT_DEADLINE", "09:15")
        self.REPORT_DEADLINE = _time("REPORT_DEADLINE", "17:00")
        self.RETENTION_MONTHS = _int("RETENTION_MONTHS", 4)
        self.PASSWORD_MAX_AGE_DAYS = _int("PASSWORD_MAX_AGE_DAYS", 90)
        self.SESSION_HOURS = _int("SESSION_HOURS", 24)
        self.REQUIRE_LIVE_CAMERA = _bool("REQUIRE_LIVE_CAMERA", False)
        self.MAX_PHOTOS = 7

        keys = os.getenv("GEMINI_API_KEY", "")
        self.GEMINI_API_KEYS = [k.strip() for k in keys.split(",") if k.strip()]
        self.GEMINI_MODELS = [
            m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-2.5-flash").split(",") if m.strip()
        ]
        self.AI_ENABLED = bool(self.GEMINI_API_KEYS) and _bool("AI_FEATURES", True)
        self.DRESS_CODE_POLICY = os.getenv("DRESS_CODE_POLICY") or (
            "Staff wear a clean collared company shirt or a dark blazer over a light shirt, "
            "smart trousers or skirt, and closed shoes."
        )
        self.UNIFORM_REFERENCE_DIR = os.getenv("UNIFORM_REFERENCE_DIR") or ""

        self.TESTING = False
        for key, value in overrides.items():
            setattr(self, key, value)

    def as_flask_config(self):
        return {k: v for k, v in vars(self).items() if k.isupper()}
