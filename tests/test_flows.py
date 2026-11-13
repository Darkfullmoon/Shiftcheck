"""End-to-end flows through the HTTP layer against the test database."""

import json
import os
from datetime import date, datetime, timedelta

from conftest import audit_form, db_one, png_data_url
from shiftcheck.db import execute, to_json
from shiftcheck.services import media, retention, submissions


def _submit_audit(client, app, **kw):
    response = client.post("/audits/new", audit_form(app, **kw))
    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    return int(response.headers["Location"].rstrip("/").split("/")[-1])


def test_audit_submission_end_to_end(app, nora, sid, admin):
    audit_id = _submit_audit(nora, app)
    row = db_one(app, "SELECT * FROM site_audits WHERE id=%s", (audit_id,))
    assert (row["passed_items"], row["failed_items"], row["total_items"]) == (2, 1, 3)
    payload = json.loads(row["payload"])
    assert payload["sections"][0]["items"][0]["evidence"][0]["value"] == "Fingerprints on glass"
    assert payload["photos"][0].startswith("/static/uploads/photos/")
    with app.test_request_context():
        assert media.local_path(payload["photos"][0])
        assert media.local_path(payload["signoffs"][0]["signature"])

    page = nora.get(f"/audits/{audit_id}").get_data(as_text=True)
    assert "Fingerprints on glass" in page and "ต้องแก้ไข" in page

    pdf = nora.get(f"/audits/{audit_id}/pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"

    summary = nora.get(f"/audits/{audit_id}/summary").get_data(as_text=True)
    assert "Door is clean" in summary and "สร้างจากผลการตรวจ" in summary

    # Same location, same day: a second audit by a team member is redirected to the first.
    again = nora.post("/audits/new", audit_form(app))
    assert again.headers["Location"].endswith(f"/audits/{audit_id}")
    # Another location's user cannot see it.
    assert sid.get(f"/audits/{audit_id}").status_code == 404

    verify = admin.post_json(f"/audits/{audit_id}/verify", {"is_verified": True, "headcount_ok": True})
    assert verify.get_json()["is_verified"] is True
    assert nora.post_json(f"/audits/{audit_id}/verify", {"is_verified": False}).status_code == 403

    assert admin.post(f"/audits/{audit_id}/delete").status_code == 302
    with app.test_request_context():
        assert media.local_path(payload["photos"][0]) is None  # files removed with the record


def test_audit_requires_minimum_photos(app, nora):
    response = nora.post("/audits/new", audit_form(app, photos=0))
    assert response.status_code == 200
    assert "กรุณาแนบรูปอย่างน้อย 1 รูป" in response.get_data(as_text=True)
    assert db_one(app, "SELECT COUNT(*) AS n FROM site_audits")["n"] == 0


def test_user_cannot_submit_for_another_location(app, nora):
    audit_id = _submit_audit(nora, app, branch_key="south")
    # The branch is silently corrected to the user's own location.
    assert db_one(app, "SELECT branch_id FROM site_audits WHERE id=%s", (audit_id,))["branch_id"] == app.test_ids["north"]


def test_template_edits_do_not_change_past_audits(app, nora, admin):
    audit_id = _submit_audit(nora, app)
    bad = admin.post_json("/admin/templates/save", {"id": app.test_ids["template"], "name": "", "sections": []})
    assert bad.status_code == 400
    new_payload = {"id": app.test_ids["template"], "name": "Opening v2", "photo_min": 0, "photo_max": 7,
                   "sections": [{"title": "Only", "items": [{"title": "Brand new item"}]}]}
    assert admin.post_json("/admin/templates/save", new_payload).get_json()["success"]
    page = nora.get(f"/audits/{audit_id}").get_data(as_text=True)
    assert "Door is clean" in page and "Brand new item" not in page
    # Templates with audits cannot be deleted.
    admin.post(f"/admin/templates/{app.test_ids['template']}/action", {"action": "delete"})
    assert db_one(app, "SELECT COUNT(*) AS n FROM checklist_templates")["n"] == 1


def test_photo_upload_endpoint(app, nora, sid):
    bad = nora.post_json("/uploads/photo", {"photo": "data:image/png;base64,bm90IGFuIGltYWdl"})
    assert bad.status_code == 400
    ok = nora.post_json("/uploads/photo", {"photo": png_data_url(), "kind": "audit"}).get_json()
    assert ok["path"].endswith(".webp")
    # Sid may not attach a file Nora uploaded.
    with app.test_request_context():
        assert media.save_photo(ok["path"], "sid") is None
        assert media.save_photo(ok["path"], "nora") == ok["path"]


def test_shift_report_uses_morning_audit_and_feeds_analytics(app, nora, admin):
    _submit_audit(nora, app)
    response = nora.post("/reports/new", {
        "branch": app.test_ids["north"], "date": date.today().isoformat(), "team": "Early",
        "visit_walk_ins": "12", "visit_bookings": "2", "sum_who": "NN", "sum_note": "Two bookings", "photos_json": "[]"})
    assert response.status_code == 302
    report_id = int(response.headers["Location"].split("/")[-1])
    page = nora.get(f"/reports/{report_id}").get_data(as_text=True)
    assert "จากการตรวจเช้า" in page  # staffing borrowed from the audit
    assert "Two bookings" in page
    assert nora.get(f"/reports/{report_id}/pdf").data[:4] == b"%PDF"
    analytics = admin.get("/admin/analytics").get_data(as_text=True)
    assert ">14<" in analytics.replace(" ", "")


def test_item_request_approval(app, nora, admin):
    nora.post("/requests/new", {"item_code": "abc-1", "item_name": "Brochures", "category": "วัสดุสิ้นเปลือง",
                                "quantity": "20", "branch": app.test_ids["north"]})
    row = db_one(app, "SELECT * FROM item_requests")
    assert row["item_code"] == "ABC-1" and row["status"] == "PENDING"
    assert nora.post(f"/requests/{row['id']}/decide", {"decision": "APPROVED"}).status_code == 403
    admin.post(f"/requests/{row['id']}/decide", {"decision": "REJECTED", "note": "Use old stock"})
    row = db_one(app, "SELECT * FROM item_requests")
    assert row["status"] == "REJECTED" and row["reviewed_by"] == "admin"
    assert "Use old stock" in nora.get("/requests").get_data(as_text=True)


def test_admin_user_safeguards(app, admin):
    me = db_one(app, "SELECT id FROM users WHERE username='admin'")["id"]
    admin.post(f"/admin/users/{me}/delete")
    assert db_one(app, "SELECT COUNT(*) AS n FROM users WHERE username='admin'")["n"] == 1
    admin.post(f"/admin/users/{me}", {"role": "USER"})  # would leave no administrator
    assert db_one(app, "SELECT role FROM users WHERE id=%s", (me,))["role"] == "ADMIN"
    admin.post("/admin/users", {"username": "Bad Name"})
    assert db_one(app, "SELECT COUNT(*) AS n FROM users")["n"] == 3


def test_archived_location_disappears_from_forms(app, admin):
    admin.post(f"/admin/locations/{app.test_ids['south']}/archive", {"action": "archive"})
    page = admin.get("/audits/new").get_data(as_text=True)
    assert "South Store" not in page and "North Store" in page


def test_cleaning_schedule_save(app, nora, sid):
    execute_task = "INSERT INTO cleaning_tasks (title, frequency) VALUES ('Sweep', 'DAILY')"
    with app.app_context():
        task_id = execute(execute_task)
    day = date.today().day
    sheet = {"daily": {f"{task_id}:{day}": True}, "done_by": {str(day): "nn"}, "weekly": {}}
    response = nora.post("/cleaning", {"branch": app.test_ids["north"], "month": date.today().strftime("%Y-%m"),
                                       "sheet_json": json.dumps(sheet)})
    assert response.status_code == 302
    data = json.loads(db_one(app, "SELECT data FROM cleaning_schedules")["data"])
    assert data["daily"] == {f"{task_id}:{day}": True} and data["done_by"] == {str(day): "NN"}
    assert sid.get("/cleaning").status_code == 403  # cleaning is not enabled for South Store


def test_submission_status_deadlines(app):
    north, south = app.test_ids["north"], app.test_ids["south"]
    today = date.today()
    with app.app_context():
        for branch_id, at in ((north, "08:30"), (south, "10:05")):
            execute("INSERT INTO site_audits (branch_id, template_name, audit_date, submitted_by, payload, created_at) "
                    "VALUES (%s, 'T', %s, 'x', '{}', %s)", (branch_id, today, f"{today} {at}:00"))
    with app.test_request_context():
        summary, rows = submissions.daily_status(today, now=datetime.combine(today, datetime.min.time()) + timedelta(hours=18))
        by_name = {r["branch"]["name"]: r for r in rows}
        assert by_name["North Store"]["audit"]["status"] == "ON_TIME"
        assert by_name["South Store"]["audit"]["status"] == "LATE"
        assert by_name["North Store"]["report"]["status"] == "MISSING"
        early, _ = submissions.daily_status(today, now=datetime.combine(today, datetime.min.time()) + timedelta(hours=7))
        assert early["report"]["PENDING"] == 2


def test_db_timestamps_use_local_time(app, nora):
    audit_id = _submit_audit(nora, app)
    created = db_one(app, "SELECT created_at FROM site_audits WHERE id=%s", (audit_id,))["created_at"]
    assert abs((datetime.now() - created).total_seconds()) < 120


def test_retention_removes_old_records_and_files(app, nora):
    audit_id = _submit_audit(nora, app)
    old = date.today() - timedelta(days=200)
    with app.app_context():
        execute("UPDATE site_audits SET audit_date = %s WHERE id = %s", (old, audit_id))
    payload = json.loads(db_one(app, "SELECT payload FROM site_audits WHERE id=%s", (audit_id,))["payload"])
    with app.test_request_context():
        stats = retention.run_cleanup(4)
        assert stats["audits"] == 1 and stats["files"] >= 2
        assert media.local_path(payload["photos"][0]) is None
