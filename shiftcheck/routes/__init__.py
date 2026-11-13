from .admin import admin_bp
from .audits import audits_bp
from .auth import auth_bp
from .cleaning import cleaning_bp
from .dashboard import dashboard_bp
from .reports import reports_bp
from .requests import requests_bp
from .uploads import uploads_bp


def register_blueprints(app):
    for bp in (auth_bp, dashboard_bp, uploads_bp, audits_bp, reports_bp, cleaning_bp, requests_bp, admin_bp):
        app.register_blueprint(bp)
