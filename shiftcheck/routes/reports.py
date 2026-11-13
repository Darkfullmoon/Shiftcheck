"""End-of-day shift reports: staffing, visitor counts, notes, photos and sign-offs."""

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)

from ..db import execute, from_json, query_all, query_one, to_json
from ..security import admin_required, is_admin, login_required
from ..services import ai, analytics, branches, media, pdf
from ..formatting import fmt_date
from . import common

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")
PAGE_SIZE = 25


def _linked_audit(report):
    return query_one(
        "SELECT id, payload FROM site_audits WHERE branch_id = %s AND audit_date = %s ORDER BY id DESC LIMIT 1",
        (report["branch_id"], report["report_date"]),
    )


def _load(report_id):
    report = query_one(
        "SELECT r.*, b.name AS branch_name, b.code AS branch_code FROM shift_reports r "
        "JOIN branches b ON b.id = r.branch_id WHERE r.id = %s", (report_id,)
    )
    common.ensure_can_view(report)
    for key, default in (("briefing", []), ("summary", []), ("staffing", {}), ("visitor_stats", {}),
                         ("signoffs", []), ("photos", [])):
        report[key] = from_json(report[key], default) or default
    report["photo_check"] = from_json(report["photo_check"])

    # Reports can lean on the same day's audit for staffing, briefing and photos.
    report["from_audit"] = []
    audit = _linked_audit(report)
    report["linked_audit_id"] = audit["id"] if audit else None
    if audit:
        payload = from_json(audit["payload"], {}) or {}
        if not any((v or {}).get("qty") for v in report["staffing"].values()) and payload.get("staffing"):
            report["staffing"] = payload["staffing"]
            report["from_audit"].append("staffing")
        if not report["briefing"] and payload.get("briefing"):
            report["briefing"] = payload["briefing"]
            report["from_audit"].append("briefing")
        if not report["photos"] and payload.get("photos"):
            report["photos"] = payload["photos"]
            report["from_audit"].append("photos")
    report["visitor_total"] = sum(analytics.to_int(report["visitor_stats"].get(k)) for k, _ in analytics.VISITOR_FIELDS)
    return report


def _existing(branch_id, report_date):
    return query_one(
        "SELECT id, submitted_by, created_at FROM shift_reports WHERE branch_id = %s AND report_date = %s "
        "ORDER BY id DESC LIMIT 1", (branch_id, report_date)
    )


@reports_bp.get("")
@login_required
def index():
    where, params = common.scope_clause("r")
    filters = {
        "branch": request.args.get("branch", type=int),
        "date_from": common.parse_date(request.args.get("from")),
        "date_to": common.parse_date(request.args.get("to")),
        "verified": request.args.get("verified", ""),
        "q": (request.args.get("q") or "").strip(),
    }
    sql = [where]
    if filters["branch"]:
        sql.append("r.branch_id = %s"); params.append(filters["branch"])
    if filters["date_from"]:
        sql.append("r.report_date >= %s"); params.append(filters["date_from"])
    if filters["date_to"]:
        sql.append("r.report_date <= %s"); params.append(filters["date_to"])
    if filters["verified"] in ("yes", "no"):
        sql.append("r.is_verified = %s"); params.append(1 if filters["verified"] == "yes" else 0)
    if filters["q"]:
        sql.append("(r.submitted_by LIKE %s OR r.team LIKE %s OR b.name LIKE %s)")
        params += [f"%{filters['q']}%"] * 3

    page = max(1, request.args.get("page", 1, type=int))
    base = f"FROM shift_reports r JOIN branches b ON b.id = r.branch_id WHERE {' AND '.join(sql)}"
    total = query_one(f"SELECT COUNT(*) AS n {base}", params)["n"]
    rows = query_all(
        f"""SELECT r.id, r.report_date, r.team, r.submitted_by, r.is_verified, r.created_at, r.visitor_stats,
                   JSON_LENGTH(r.photos) AS photo_count, b.name AS branch_name, b.code AS branch_code
            {base} ORDER BY r.report_date DESC, r.id DESC LIMIT %s OFFSET %s""",
        params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
    )
    for row in rows:
        stats = from_json(row["visitor_stats"], {}) or {}
        row["visitors"] = sum(analytics.to_int(stats.get(k)) for k, _ in analytics.VISITOR_FIELDS)
    return render_template(
        "reports/index.html", reports=rows, filters=filters, branches=branches.all_branches(),
        page=page, pages=max(1, -(-total // PAGE_SIZE)), total=total,
    )


@reports_bp.get("/check")
@login_required
def check_existing():
    report_date = common.parse_date(request.args.get("date"))
    branch = branches.resolve_submit_branch(request.args.get("branch"))
    row = _existing(branch["id"], report_date) if branch and report_date else None
    if not row:
        return jsonify(exists=False)
    return jsonify(exists=True, id=row["id"], submitted_by=row["submitted_by"],
                   time=row["created_at"].strftime("%H:%M"), url=url_for("reports.detail", report_id=row["id"]))


@reports_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    allowed = branches.allowed_branches()
    if not allowed:
        flash("ยังไม่มีสาขาในระบบ กรุณาติดต่อผู้ดูแลระบบ", "warning")
        return redirect(url_for("dashboard.home"))
    source = request.form if request.method == "POST" else request.args
    branch = branches.resolve_submit_branch(source.get("branch")) or branches.user_branch() or allowed[0]
    if branch["id"] not in {b["id"] for b in allowed}:
        branch = allowed[0]
    report_date = common.parse_date(source.get("date"), common.today())

    existing = _existing(branch["id"], report_date)
    if existing and not is_admin():
        if request.method == "POST":
            flash(f"สาขา {branch['name']} ส่งรายงานประจำวันของวันที่ {fmt_date(report_date)} แล้ว", "warning")
        return redirect(url_for("reports.detail", report_id=existing["id"]))

    audit = query_one(
        "SELECT id, payload FROM site_audits WHERE branch_id = %s AND audit_date = %s ORDER BY id DESC LIMIT 1",
        (branch["id"], report_date),
    )
    audit_payload = from_json(audit["payload"], {}) if audit else {}

    if request.method == "POST":
        max_photos = current_app.config["MAX_PHOTOS"]
        stats = {key: analytics.to_int(request.form.get(f"visit_{key}")) for key, _ in analytics.VISITOR_FIELDS}
        report_id = execute(
            """INSERT INTO shift_reports (branch_id, team, report_date, submitted_by, briefing, summary,
                   extra_tasks, staffing, visitor_stats, signoffs, photos)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (branch["id"], (request.form.get("team") or "").strip()[:100] or None, report_date, common.username(),
             to_json(common.read_notes(request.form, "brief_who", "brief_note")),
             to_json(common.read_notes(request.form, "sum_who", "sum_note")),
             (request.form.get("extra_tasks") or "").strip()[:2000] or None,
             to_json(common.read_staffing(request.form)), to_json(stats),
             to_json(common.read_signoffs(request.form, common.REPORT_SIGNOFFS)),
             to_json(media.save_photos(common.read_photo_list(request.form), common.username(), "report", max_photos))),
        )
        flash(f"บันทึกรายงานประจำวันสาขา {branch['name']} แล้ว", "success")
        return redirect(url_for("reports.detail", report_id=report_id))

    return render_template(
        "reports/new.html", branches=allowed, branch=branch, report_date=report_date, existing=existing,
        audit=audit, audit_staffing=(audit_payload or {}).get("staffing") or {},
        staffing_fields=common.STAFFING_FIELDS, visitor_fields=analytics.VISITOR_FIELDS,
        signoff_roles=common.REPORT_SIGNOFFS, max_photos=current_app.config["MAX_PHOTOS"],
    )


@reports_bp.get("/<int:report_id>")
@login_required
def detail(report_id):
    report = _load(report_id)
    return render_template(
        "reports/detail.html", report=report, staffing_fields=common.STAFFING_FIELDS,
        visitor_fields=analytics.VISITOR_FIELDS, on_site=common.on_site_count(report["staffing"]),
    )


@reports_bp.post("/<int:report_id>/verify")
@admin_required
def verify(report_id):
    _load(report_id)
    verified, headcount_ok, dress_ok = common.verify_payload()
    if verified:
        execute("UPDATE shift_reports SET is_verified=1, headcount_ok=%s, dress_code_ok=%s, verified_by=%s, "
                "verified_at=NOW() WHERE id=%s", (headcount_ok, dress_ok, common.username(), report_id))
    else:
        execute("UPDATE shift_reports SET is_verified=0, verified_by=NULL, verified_at=NULL WHERE id=%s", (report_id,))
    row = query_one("SELECT is_verified, headcount_ok, dress_code_ok, verified_by, verified_at "
                    "FROM shift_reports WHERE id=%s", (report_id,))
    return jsonify(success=True, is_verified=bool(row["is_verified"]), headcount_ok=bool(row["headcount_ok"]),
                   dress_code_ok=bool(row["dress_code_ok"]), verified_by=row["verified_by"],
                   verified_at=row["verified_at"].strftime("%d %b %Y, %H:%M") if row["verified_at"] else None)


@reports_bp.post("/<int:report_id>/photo-check")
@login_required
def photo_check(report_id):
    report = _load(report_id)
    if not ai.enabled():
        return jsonify(success=False, error="ฟีเจอร์ AI ปิดอยู่"), 400
    refresh = bool((request.get_json(silent=True) or {}).get("refresh"))
    if report["photo_check"] and not refresh:
        return jsonify(success=True, cached=True, result=report["photo_check"])
    result = ai.photo_check(report["photos"], common.on_site_count(report["staffing"]))
    if result is None:
        return jsonify(success=False, error="ไม่สามารถวิเคราะห์รูปได้ กรุณาลองใหม่ภายหลัง"), 502
    execute("UPDATE shift_reports SET photo_check = %s WHERE id = %s", (to_json(result), report_id))
    return jsonify(success=True, cached=False, result=result)


@reports_bp.get("/<int:report_id>/pdf")
@login_required
def export_pdf(report_id):
    report = _load(report_id)
    buffer = pdf.report_pdf(report)
    name = f"shift-report-{report_id}-{report['branch_code'] or 'site'}-{report['report_date']}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=request.args.get("download") == "1",
                     download_name=name)


@reports_bp.post("/<int:report_id>/delete")
@admin_required
def delete(report_id):
    row = query_one("SELECT photos, signoffs FROM shift_reports WHERE id = %s", (report_id,))
    if row:
        execute("DELETE FROM shift_reports WHERE id = %s", (report_id,))
        media.delete_files((from_json(row["photos"], []) or []) +
                           [s.get("signature") for s in from_json(row["signoffs"], []) or [] if s.get("signature")])
        flash(f"ลบรายงานประจำวัน #{report_id} แล้ว", "success")
    return redirect(url_for("reports.index"))
