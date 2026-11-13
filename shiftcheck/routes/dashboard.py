"""Home dashboard."""

from datetime import date, timedelta

from flask import Blueprint, redirect, render_template, session, url_for

from ..db import query_all, query_one
from ..security import login_required
from ..services import checklists, submissions
from .common import scope_clause

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard.home"))
    return redirect(url_for("auth.login"))


@dashboard_bp.route("/dashboard")
@login_required
def home():
    where, params = scope_clause("a")
    since = date.today() - timedelta(days=29)

    audit_stats = query_one(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(passed_items),0) AS passed, COALESCE(SUM(failed_items),0) AS failed "
        f"FROM site_audits a WHERE {where} AND audit_date >= %s", params + [since],
    )
    report_count = query_one(
        f"SELECT COUNT(*) AS n FROM shift_reports a WHERE {where} AND report_date >= %s", params + [since],
    )["n"]
    req_where, req_params = ("1=1", []) if session.get("role") == "ADMIN" else ("submitted_by = %s", [session["username"]])
    open_requests = query_one(
        f"SELECT COUNT(*) AS n FROM item_requests WHERE {req_where} AND status = 'PENDING'", req_params
    )["n"]

    trend = query_all(
        f"""SELECT audit_date AS day, SUM(passed_items) AS passed, SUM(failed_items) AS failed
              FROM site_audits a WHERE {where} AND audit_date >= %s
             GROUP BY audit_date ORDER BY audit_date""",
        params + [date.today() - timedelta(days=13)],
    )
    trend_by_day = {r["day"]: checklists.pass_rate(int(r["passed"]), int(r["failed"])) for r in trend}
    trend_days = []
    for offset in range(13, -1, -1):
        day = date.today() - timedelta(days=offset)
        trend_days.append({"date": day, "rate": trend_by_day.get(day)})

    recent_audits = query_all(
        f"""SELECT a.id, a.audit_date, a.passed_items, a.failed_items, a.submitted_by, a.is_verified,
                   a.template_name, b.name AS branch_name
              FROM site_audits a JOIN branches b ON b.id = a.branch_id
             WHERE {where} ORDER BY a.audit_date DESC, a.id DESC LIMIT 6""", params,
    )
    recent_reports = query_all(
        f"""SELECT a.id, a.report_date, a.team, a.submitted_by, a.is_verified, b.name AS branch_name
              FROM shift_reports a JOIN branches b ON b.id = a.branch_id
             WHERE {where} ORDER BY a.report_date DESC, a.id DESC LIMIT 6""", params,
    )
    for audit in recent_audits:
        audit["rate"] = checklists.pass_rate(audit["passed_items"], audit["failed_items"])

    status_summary, status_rows = submissions.daily_status()
    if session.get("role") != "ADMIN":
        status_rows = [r for r in status_rows if r["branch"]["id"] == session.get("branch_id")]

    return render_template(
        "dashboard.html",
        audit_count=audit_stats["n"],
        avg_rate=checklists.pass_rate(int(audit_stats["passed"]), int(audit_stats["failed"])) if audit_stats["n"] else None,
        report_count=report_count,
        open_requests=open_requests,
        trend_days=trend_days,
        recent_audits=recent_audits,
        recent_reports=recent_reports,
        status_summary=status_summary,
        status_rows=status_rows,
    )
