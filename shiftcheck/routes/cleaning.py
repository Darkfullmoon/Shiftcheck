"""Monthly cleaning schedules per location."""

import json
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from ..db import execute, from_json, query_all, query_one, to_json
from ..security import is_admin, login_required
from ..services import branches, cleaning, pdf

cleaning_bp = Blueprint("cleaning", __name__, url_prefix="/cleaning")


def _allowed_branches():
    if is_admin():
        return branches.cleaning_branches()
    own = branches.user_branch()
    return [own] if own and own["is_active"] and own["cleaning_schedule_enabled"] else []


def _guard():
    if not _allowed_branches() and not is_admin():
        abort(403, description="สาขาของคุณยังไม่ได้เปิดใช้ตารางทำความสะอาด")


@cleaning_bp.route("", methods=["GET", "POST"])
@login_required
def sheet():
    _guard()
    allowed = _allowed_branches()
    if not allowed:
        flash("กรุณาเปิดใช้ตารางทำความสะอาดให้อย่างน้อย 1 สาขาก่อน", "warning")
        return redirect(url_for("admin.branches"))

    source = request.form if request.method == "POST" else request.args
    branch = next((b for b in allowed if str(b["id"]) == str(source.get("branch"))), allowed[0])
    month = source.get("month") or date.today().strftime("%Y-%m")
    if not cleaning.valid_month(month):
        month = date.today().strftime("%Y-%m")

    record = query_one("SELECT * FROM cleaning_schedules WHERE branch_id = %s AND month = %s", (branch["id"], month))
    sheet_data = from_json(record["data"], cleaning.empty_sheet()) if record else cleaning.empty_sheet()
    tasks = cleaning.tasks_for_sheet(sheet_data)
    layout = cleaning.build_layout(month, tasks)
    scope = cleaning.editable_scope(layout, is_admin())

    if request.method == "POST":
        if not scope["days"] and not scope["weeks"]:
            flash("แก้ไขได้เฉพาะเดือนปัจจุบันเท่านั้น", "error")
            return redirect(url_for("cleaning.sheet", branch=branch["id"], month=month))
        try:
            submitted = json.loads(request.form.get("sheet_json") or "{}")
        except ValueError:
            submitted = {}
        merged = cleaning.merge_sheet(sheet_data, submitted if isinstance(submitted, dict) else {},
                                      layout, scope, cleaning.active_tasks())
        execute(
            """INSERT INTO cleaning_schedules (branch_id, month, submitted_by, data) VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE data = VALUES(data), submitted_by = VALUES(submitted_by)""",
            (branch["id"], month, session["username"], to_json(merged)),
        )
        flash(f"บันทึกตารางทำความสะอาดสาขา {branch['name']} เดือน{cleaning.month_label(month)} แล้ว", "success")
        return redirect(url_for("cleaning.sheet", branch=branch["id"], month=month))

    return render_template(
        "cleaning/sheet.html", branches=allowed, branch=branch, month=month, layout=layout,
        sheet=sheet_data, record=record, scope={k: sorted(v) for k, v in scope.items()},
        completion=cleaning.completion(sheet_data, layout),
        prev_month=cleaning.shift_month(month, -1), next_month=cleaning.shift_month(month, 1),
    )


@cleaning_bp.get("/history")
@login_required
def history():
    _guard()
    allowed = _allowed_branches()
    ids = [b["id"] for b in allowed] or [0]
    branch_id = request.args.get("branch", type=int)
    if branch_id and branch_id in ids:
        ids = [branch_id]
    placeholders = ",".join(["%s"] * len(ids))
    rows = query_all(
        f"""SELECT s.id, s.branch_id, s.month, s.submitted_by, s.updated_at, s.data, b.name AS branch_name
              FROM cleaning_schedules s JOIN branches b ON b.id = s.branch_id
             WHERE s.branch_id IN ({placeholders}) ORDER BY s.month DESC, b.name""", ids,
    )
    for row in rows:
        data = from_json(row.pop("data"), {}) or {}
        layout = cleaning.build_layout(row["month"], cleaning.tasks_for_sheet(data))
        row["label"] = cleaning.month_label(row["month"])
        row["completion"] = cleaning.completion(data, layout)
        row["weekly_done"] = sum(1 for w in (data.get("weekly") or {}).values() if w.get("done_on"))
        row["weeks"] = len(layout["weeks"])
    return render_template("cleaning/history.html", schedules=rows, branches=allowed, branch_id=branch_id)


@cleaning_bp.get("/<int:schedule_id>/pdf")
@login_required
def export_pdf(schedule_id):
    _guard()
    record = query_one(
        "SELECT s.*, b.name AS branch_name FROM cleaning_schedules s JOIN branches b ON b.id = s.branch_id "
        "WHERE s.id = %s", (schedule_id,)
    )
    if not record or record["branch_id"] not in {b["id"] for b in _allowed_branches()}:
        abort(404)
    data = from_json(record["data"], cleaning.empty_sheet())
    layout = cleaning.build_layout(record["month"], cleaning.tasks_for_sheet(data))
    buffer = pdf.cleaning_pdf(record, data, layout)
    return send_file(buffer, mimetype="application/pdf", as_attachment=request.args.get("download") == "1",
                     download_name=f"cleaning-{record['month']}-{record['branch_id']}.pdf")
