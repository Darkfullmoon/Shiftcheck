"""Test fixtures. Tests run against a separate MySQL database (TEST_DB_NAME, default shiftcheck_test)."""

import base64
import io
import os
import re
import shutil
import sys

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shiftcheck import create_app  # noqa: E402
from shiftcheck.db import connect, execute, init_db, query_one  # noqa: E402
from shiftcheck.services import branches, checklists  # noqa: E402

ADMIN_PW = "Admin#Test1"
USER_PW = "User#Test1"
TABLES = ["item_requests", "cleaning_schedules", "site_audits", "shift_reports", "users", "branches",
          "cleaning_tasks", "checklist_sections", "checklist_items", "checklist_templates"]


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    app = create_app(
        DB_NAME=os.getenv("TEST_DB_NAME", "shiftcheck_test"),
        ADMIN_USERNAME="admin", ADMIN_PASSWORD=ADMIN_PW, TESTING=True,
        GEMINI_API_KEYS=[], AI_ENABLED=False, RETENTION_MONTHS=4,
    )
    app.static_folder = str(tmp_path_factory.mktemp("static"))
    with app.app_context():
        conn = connect(app.config)
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in TABLES:
                cur.execute(f"DROP TABLE IF EXISTS {table}")
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.close()
        init_db(log=lambda *_: None)
    yield app
    shutil.rmtree(app.static_folder, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_data(app):
    """Each test starts with: admin, two locations, one user per location, one template."""
    with app.app_context():
        conn = connect(app.config)
        with conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in TABLES:
                if table == "users":
                    cur.execute("DELETE FROM users WHERE username <> 'admin'")
                else:
                    cur.execute(f"DELETE FROM {table}")
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            cur.execute("UPDATE users SET must_change_password = 0, password_hash = %s WHERE username='admin'",
                        (generate_password_hash(ADMIN_PW),))
        conn.close()
        north = execute("INSERT INTO branches (name, code, cleaning_schedule_enabled) VALUES ('North Store', 'NTH', 1)")
        south = execute("INSERT INTO branches (name, code) VALUES ('South Store', 'STH')")
        for username, branch_id in (("nora", north), ("sid", south)):
            execute("INSERT INTO users (username, full_name, password_hash, role, branch_id, must_change_password) "
                    "VALUES (%s, %s, %s, 'USER', %s, 0)",
                    (username, username.title(), generate_password_hash(USER_PW), branch_id))
        branches.invalidate()
        template_id = checklists.save_template(SAMPLE_TEMPLATE, username="admin")
        checklists.set_default(template_id)
        app.test_ids = {"north": north, "south": south, "template": template_id}
    yield


SAMPLE_TEMPLATE = {
    "name": "Opening checklist",
    "description": "Test template",
    "photo_min": 1,
    "photo_max": 3,
    "sections": [
        {"title": "Front", "items": [
            {"title": "Door is clean", "evidence_fields": [{"label": "What is wrong", "type": "text"}]},
            {"title": "Sign is lit", "evidence_fields": []},
        ]},
        {"title": "Safety", "items": [{"title": "Exit is clear", "evidence_fields": [{"label": "Fix by", "type": "date"}]}]},
    ],
}


def png_data_url(color=(30, 120, 90), size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class Client:
    """Test client that knows the CSRF token of its session."""

    def __init__(self, app):
        self.c = app.test_client()
        self.token = None

    def refresh_token(self):
        page = self.c.get("/login", follow_redirects=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True))
        self.token = match.group(1)

    def login(self, username, password):
        self.refresh_token()
        return self.c.post("/login", data={"username": username, "password": password, "csrf_token": self.token})

    def get(self, *a, **kw):
        return self.c.get(*a, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token)
        return self.c.post(url, data=data, **kw)

    def post_json(self, url, payload=None):
        return self.c.post(url, json=payload or {}, headers={"X-CSRF-Token": self.token})


@pytest.fixture
def admin(app):
    client = Client(app)
    assert client.login("admin", ADMIN_PW).status_code == 302
    client.refresh_token()
    return client


@pytest.fixture
def nora(app):
    client = Client(app)
    assert client.login("nora", USER_PW).status_code == 302
    client.refresh_token()
    return client


@pytest.fixture
def sid(app):
    client = Client(app)
    assert client.login("sid", USER_PW).status_code == 302
    client.refresh_token()
    return client


def audit_form(app, branch_key="north", fail_first=True, photos=1):
    template = checklists_get(app)
    items = [i for s in template["sections"] for i in s["items"]]
    form = {"branch": app.test_ids[branch_key], "date": "", "template": template["id"],
            "photos_json": "[" + ",".join(f'"{png_data_url()}"' for _ in range(photos)) + "]",
            "sign_auditor_name": "Nora North", "sign_auditor_sig": png_data_url((0, 0, 0), (120, 40)),
            "staff_rostered_qty": "4", "staff_sick_leave_qty": "1", "brief_who": "NN", "brief_note": "Opens the store"}
    for item in items:
        form[f"status_{item['id']}"] = "PASS"
    if fail_first:
        form[f"status_{items[0]['id']}"] = "FAIL"
        form[f"ev_{items[0]['id']}_0"] = "Fingerprints on glass"
    return form


def checklists_get(app):
    with app.app_context():
        return checklists.get_template(app.test_ids["template"])


def db_one(app, sql, params=None):
    with app.app_context():
        return query_one(sql, params)
