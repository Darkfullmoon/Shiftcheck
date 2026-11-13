"""Daily submission compliance: did each location submit its audit and shift report on time?"""

from datetime import date, datetime

from flask import current_app

from ..db import query_all
from . import branches as branch_service


def _status(record, deadline, target, now):
    if record:
        created = record["created_at"]
        on_time = created.date() < target or (created.date() == target and created.time() <= deadline)
        return "ON_TIME" if on_time else "LATE"
    if target > now.date() or (target == now.date() and now.time() < deadline):
        return "PENDING"
    return "MISSING"


def _record_view(record, status):
    return {
        "id": record["id"] if record else None,
        "status": status,
        "submitted_by": record["submitted_by"] if record else None,
        "time": record["created_at"].strftime("%H:%M") if record else None,
        "is_verified": bool(record and record["is_verified"]),
    }


def daily_status(target=None, now=None):
    now = now or datetime.now()
    if isinstance(target, str):
        try:
            target = datetime.strptime(target, "%Y-%m-%d").date()
        except ValueError:
            target = None
    target = target or now.date()
    cfg = current_app.config

    audits = {}
    for row in query_all(
        "SELECT id, branch_id, submitted_by, is_verified, created_at FROM site_audits "
        "WHERE audit_date = %s ORDER BY created_at", (target,)
    ):
        audits.setdefault(row["branch_id"], row)
    reports = {}
    for row in query_all(
        "SELECT id, branch_id, submitted_by, is_verified, created_at FROM shift_reports "
        "WHERE report_date = %s ORDER BY created_at", (target,)
    ):
        reports.setdefault(row["branch_id"], row)

    keys = ("ON_TIME", "LATE", "MISSING", "PENDING")
    summary = {"audit": dict.fromkeys(keys, 0), "report": dict.fromkeys(keys, 0), "complete": 0}
    rows = []
    for branch in branch_service.all_branches():
        audit = audits.get(branch["id"])
        report = reports.get(branch["id"])
        a_status = _status(audit, cfg["AUDIT_DEADLINE"], target, now)
        r_status = _status(report, cfg["REPORT_DEADLINE"], target, now)
        summary["audit"][a_status] += 1
        summary["report"][r_status] += 1
        if audit and report:
            summary["complete"] += 1
        rows.append({
            "branch": branch,
            "audit": _record_view(audit, a_status),
            "report": _record_view(report, r_status),
        })

    slots = len(rows) * 2
    submitted = sum(summary[k]["ON_TIME"] + summary[k]["LATE"] for k in ("audit", "report"))
    summary["rate"] = round(submitted / slots * 100, 1) if slots else 0.0
    summary["branches"] = len(rows)
    summary["date"] = target
    summary["is_today"] = target == now.date()
    summary["audit_deadline"] = cfg["AUDIT_DEADLINE"].strftime("%H:%M")
    summary["report_deadline"] = cfg["REPORT_DEADLINE"].strftime("%H:%M")
    return summary, rows


def serialize(summary, rows):
    """JSON-friendly copy for the live monitor endpoint."""
    out = dict(summary, date=summary["date"].isoformat())
    return out, [
        {"branch": {"id": r["branch"]["id"], "name": r["branch"]["name"], "code": r["branch"]["code"]},
         "audit": r["audit"], "report": r["report"]}
        for r in rows
    ]


def today():
    return date.today()
