"""Helpers shared by the submission blueprints (audits, shift reports)."""

import json
from datetime import date, datetime

from flask import abort, request, session

from ..services import analytics, media

STAFFING_FIELDS = [
    ("rostered", "พนักงานทั้งหมด"),
    ("offsite", "ปฏิบัติงานนอกสถานที่"),
    ("event", "ออกบูธ / อีเวนต์"),
    ("personal_leave", "ลากิจ"),
    ("sick_leave", "ลาป่วย"),
    ("vacation", "ลาพักร้อน"),
    ("day_off", "วันหยุด"),
]
ABSENT_KEYS = ("personal_leave", "sick_leave", "vacation", "day_off")

AUDIT_SIGNOFFS = [("auditor", "ผู้ตรวจ"), ("site_manager", "ผู้จัดการสาขา")]
REPORT_SIGNOFFS = [("shift_lead", "หัวหน้ากะ"), ("site_manager", "ผู้จัดการสาขา")]


def parse_date(value, default=None):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return default


def username():
    return session.get("username", "user")


def scope_clause(alias=""):
    """SQL fragment limiting lists to what a non-admin may see."""
    prefix = f"{alias}." if alias else ""
    if session.get("role") == "ADMIN":
        return "1=1", []
    return f"({prefix}submitted_by = %s OR {prefix}branch_id = %s)", [username(), session.get("branch_id") or 0]


def ensure_can_view(record):
    if not record:
        abort(404)
    if session.get("role") == "ADMIN":
        return
    if record["submitted_by"] == username() or (record["branch_id"] and record["branch_id"] == session.get("branch_id")):
        return
    abort(404)  # Do not reveal that the record exists.


def read_staffing(form):
    data = {}
    for key, _ in STAFFING_FIELDS:
        qty = analytics.to_int(form.get(f"staff_{key}_qty"))
        names = (form.get(f"staff_{key}_names") or "").strip()[:300]
        data[key] = {"qty": qty, "names": names}
    return data


def on_site_count(staffing):
    staffing = staffing or {}
    rostered = analytics.to_int((staffing.get("rostered") or {}).get("qty"))
    absent = sum(analytics.to_int((staffing.get(k) or {}).get("qty")) for k in ABSENT_KEYS)
    return max(0, rostered - absent)


def read_notes(form, who_field, note_field):
    rows = []
    for who, note in zip(form.getlist(who_field), form.getlist(note_field)):
        who, note = who.strip()[:40], note.strip()[:1000]
        if who or note:
            rows.append({"who": who, "note": note})
    return rows


def read_signoffs(form, roles):
    signoffs = []
    for key, label in roles:
        name = (form.get(f"sign_{key}_name") or "").strip()[:100]
        signature = media.save_signature(form.get(f"sign_{key}_sig"), username(), prefix=f"sig_{key}")
        signoffs.append({"role": key, "label": label, "name": name, "signature": signature})
    return signoffs


def read_photo_list(form, field="photos_json"):
    try:
        values = json.loads(form.get(field) or "[]")
    except ValueError:
        return []
    return [v for v in values if isinstance(v, str)] if isinstance(values, list) else []


def verify_payload():
    data = request.get_json(silent=True) or {}
    return bool(data.get("is_verified")), bool(data.get("headcount_ok")), bool(data.get("dress_code_ok"))


def today():
    return date.today()
