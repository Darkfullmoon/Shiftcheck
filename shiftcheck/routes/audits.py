"""Site audits: fill in a checklist template, review, verify, summarise and export."""

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

from ..db import execute, from_json, query_all, query_one, to_json
from ..security import admin_required, is_admin, login_required
from ..services import ai, branches, checklists, media, pdf
from ..formatting import fmt_date
from . import common

audits_bp = Blueprint("audits", __name__, url_prefix="/audits")
PAGE_SIZE = 25


def _load(audit_id):
    audit = query_one(
        "SELECT a.*, b.name AS branch_name, b.code AS branch_code FROM site_audits a "
        "JOIN branches b ON b.id = a.branch_id WHERE a.id = %s", (audit_id,)
    )
    common.ensure_can_view(audit)
    audit["payload"] = from_json(audit["payload"], {}) or {}
    audit["photo_check"] = from_json(audit["photo_check"])
    audit["rate"] = checklists.pass_rate(audit["passed_items"], audit["failed_items"])
    return audit


def _existing(branch_id, audit_date):
    return query_one(
        "SELECT id, submitted_by, created_at FROM site_audits WHERE branch_id = %s AND audit_date = %s "
        "ORDER BY id DESC LIMIT 1", (branch_id, audit_date)
    )


@audits_bp.get("")
@login_required
def index():
    where, params = common.scope_clause("a")
    filters = {
        "branch": request.args.get("branch", type=int),
        "date_from": common.parse_date(request.args.get("from")),
        "date_to": common.parse_date(request.args.get("to")),
        "verified": request.args.get("verified", ""),
        "q": (request.args.get("q") or "").strip(),
    }
    sql = [where]
    if filters["branch"]:
        sql.append("a.branch_id = %s"); params.append(filters["branch"])
    if filters["date_from"]:
        sql.append("a.audit_date >= %s"); params.append(filters["date_from"])
    if filters["date_to"]:
        sql.append("a.audit_date <= %s"); params.append(filters["date_to"])
    if filters["verified"] in ("yes", "no"):
        sql.append("a.is_verified = %s"); params.append(1 if filters["verified"] == "yes" else 0)
    if filters["q"]:
        sql.append("(a.submitted_by LIKE %s OR a.template_name LIKE %s OR b.name LIKE %s)")
        params += [f"%{filters['q']}%"] * 3

    page = max(1, request.args.get("page", 1, type=int))
    base = f"FROM site_audits a JOIN branches b ON b.id = a.branch_id WHERE {' AND '.join(sql)}"
    total = query_one(f"SELECT COUNT(*) AS n {base}", params)["n"]
    rows = query_all(
        f"""SELECT a.id, a.audit_date, a.template_name, a.submitted_by, a.passed_items, a.failed_items,
                   a.na_items, a.is_verified, a.created_at, a.summary_source,
                   JSON_LENGTH(a.payload, '$.photos') AS photo_count, b.name AS branch_name, b.code AS branch_code
            {base} ORDER BY a.audit_date DESC, a.id DESC LIMIT %s OFFSET %s""",
        params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
    )
    for row in rows:
        row["rate"] = checklists.pass_rate(row["passed_items"], row["failed_items"])
    return render_template(
        "audits/index.html", audits=rows, filters=filters, branches=branches.all_branches(),
        page=page, pages=max(1, -(-total // PAGE_SIZE)), total=total,
    )


@audits_bp.get("/check")
@login_required
def check_existing():
    audit_date = common.parse_date(request.args.get("date"))
    branch = branches.resolve_submit_branch(request.args.get("branch"))
    row = _existing(branch["id"], audit_date) if branch and audit_date else None
    if not row:
        return jsonify(exists=False)
    return jsonify(exists=True, id=row["id"], submitted_by=row["submitted_by"],
                   time=row["created_at"].strftime("%H:%M"), url=url_for("audits.detail", audit_id=row["id"]))


@audits_bp.route("/new", methods=["GET", "POST"])
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
    audit_date = common.parse_date(source.get("date"), common.today())
    templates = checklists.list_templates(include_inactive=False)
    template_id = source.get("template", type=int) or checklists.template_for_branch(branch)
    template = checklists.get_template(template_id) if template_id else None
    if not template or not template["is_active"]:
        if not templates:
            flash("ยังไม่มีเทมเพลตเช็กลิสต์ที่เปิดใช้งาน กรุณาให้ผู้ดูแลระบบสร้างก่อน", "warning")
            return redirect(url_for("dashboard.home"))
        template = checklists.get_template(templates[0]["id"])

    existing = _existing(branch["id"], audit_date)
    if existing and not is_admin():
        if request.method == "POST":
            flash(f"สาขา {branch['name']} ส่งรายงานตรวจของวันที่ {fmt_date(audit_date)} แล้ว", "warning")
        return redirect(url_for("audits.detail", audit_id=existing["id"]))

    if request.method == "POST":
        sections, counts = checklists.score_submission(template, request.form)
        photos = media.save_photos(common.read_photo_list(request.form), common.username(), "audit",
                                   template["photo_max"])
        if len(photos) < template["photo_min"]:
            flash(f"กรุณาแนบรูปอย่างน้อย {template['photo_min']} รูปก่อนส่ง "
                  f"(แนบแล้ว {len(photos)} รูป)", "error")
            return render_template("audits/new.html", **_form_context(allowed, branch, audit_date, templates,
                                                                      template, existing, request.form, photos))
        payload = {
            "sections": sections,
            "staffing": common.read_staffing(request.form),
            "briefing": common.read_notes(request.form, "brief_who", "brief_note"),
            "signoffs": common.read_signoffs(request.form, common.AUDIT_SIGNOFFS),
            "photos": photos,
        }
        audit_id = execute(
            """INSERT INTO site_audits (branch_id, template_id, template_name, audit_date, submitted_by,
                   total_items, passed_items, failed_items, na_items, notes, payload)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (branch["id"], template["id"], template["name"], audit_date, common.username(),
             sum(counts.values()), counts["PASS"], counts["FAIL"], counts["NA"],
             (request.form.get("notes") or "").strip()[:2000] or None, to_json(payload)),
        )
        rate = checklists.pass_rate(counts["PASS"], counts["FAIL"])
        flash(f"บันทึกรายงานตรวจสาขา {branch['name']} แล้ว — ผ่านเกณฑ์ {rate}%", "success")
        return redirect(url_for("audits.detail", audit_id=audit_id))

    return render_template("audits/new.html", **_form_context(allowed, branch, audit_date, templates,
                                                              template, existing, None, []))


def _form_context(allowed, branch, audit_date, templates, template, existing, form, photos):
    return dict(
        branches=allowed, branch=branch, audit_date=audit_date, templates=templates, template=template,
        existing=existing, form=form, photos=photos, staffing_fields=common.STAFFING_FIELDS,
        signoff_roles=common.AUDIT_SIGNOFFS, max_photos=template["photo_max"],
    )


@audits_bp.get("/<int:audit_id>")
@login_required
def detail(audit_id):
    audit = _load(audit_id)
    payload = audit["payload"]
    return render_template(
        "audits/detail.html", audit=audit, payload=payload,
        failed=checklists.failed_items(payload.get("sections")),
        staffing_fields=common.STAFFING_FIELDS, on_site=common.on_site_count(payload.get("staffing")),
    )


@audits_bp.get("/<int:audit_id>/summary")
@login_required
def summary(audit_id):
    audit = _load(audit_id)
    refresh = request.args.get("refresh") == "1" and is_admin()
    if not audit["summary_text"] or refresh:
        text, source = ai.audit_summary(audit, audit["payload"].get("sections"))
        execute("UPDATE site_audits SET summary_text = %s, summary_source = %s WHERE id = %s",
                (text, source, audit_id))
        audit["summary_text"], audit["summary_source"] = text, source
    return render_template("audits/summary.html", audit=audit,
                           failed=checklists.failed_items(audit["payload"].get("sections")))


@audits_bp.post("/<int:audit_id>/verify")
@admin_required
def verify(audit_id):
    _load(audit_id)
    verified, headcount_ok, dress_ok = common.verify_payload()
    if verified:
        execute("UPDATE site_audits SET is_verified=1, headcount_ok=%s, dress_code_ok=%s, verified_by=%s, "
                "verified_at=NOW() WHERE id=%s", (headcount_ok, dress_ok, common.username(), audit_id))
    else:
        execute("UPDATE site_audits SET is_verified=0, verified_by=NULL, verified_at=NULL WHERE id=%s", (audit_id,))
    row = query_one("SELECT is_verified, headcount_ok, dress_code_ok, verified_by, verified_at "
                    "FROM site_audits WHERE id=%s", (audit_id,))
    return jsonify(success=True, is_verified=bool(row["is_verified"]), headcount_ok=bool(row["headcount_ok"]),
                   dress_code_ok=bool(row["dress_code_ok"]), verified_by=row["verified_by"],
                   verified_at=row["verified_at"].strftime("%d %b %Y, %H:%M") if row["verified_at"] else None)


@audits_bp.post("/<int:audit_id>/photo-check")
@login_required
def photo_check(audit_id):
    audit = _load(audit_id)
    if not ai.enabled():
        return jsonify(success=False, error="ฟีเจอร์ AI ปิดอยู่"), 400
    refresh = bool((request.get_json(silent=True) or {}).get("refresh"))
    if audit["photo_check"] and not refresh:
        return jsonify(success=True, cached=True, result=audit["photo_check"])
    result = ai.photo_check(audit["payload"].get("photos") or [], common.on_site_count(audit["payload"].get("staffing")))
    if result is None:
        return jsonify(success=False, error="ไม่สามารถวิเคราะห์รูปได้ กรุณาลองใหม่ภายหลัง"), 502
    execute("UPDATE site_audits SET photo_check = %s WHERE id = %s", (to_json(result), audit_id))
    return jsonify(success=True, cached=False, result=result)


@audits_bp.get("/<int:audit_id>/pdf")
@login_required
def export_pdf(audit_id):
    audit = _load(audit_id)
    buffer = pdf.audit_pdf(audit, current_app.config)
    name = f"audit-{audit_id}-{audit['branch_code'] or 'site'}-{audit['audit_date']}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=request.args.get("download") == "1",
                     download_name=name)


@audits_bp.post("/<int:audit_id>/delete")
@admin_required
def delete(audit_id):
    audit = _load(audit_id)
    execute("DELETE FROM site_audits WHERE id = %s", (audit_id,))
    payload = audit["payload"]
    media.delete_files((payload.get("photos") or []) +
                       [s.get("signature") for s in payload.get("signoffs") or [] if s.get("signature")])
    flash(f"ลบรายงานตรวจ #{audit_id} แล้ว", "success")
    return redirect(url_for("audits.index"))
