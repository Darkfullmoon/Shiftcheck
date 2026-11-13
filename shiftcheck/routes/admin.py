"""Administration: people, locations, checklist templates, cleaning tasks, monitoring, data."""

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import generate_password_hash

from ..db import execute, query_all, query_one, transaction
from ..security import admin_required, generate_temp_password, validate_password, validate_username
from ..services import analytics, branches, checklists, retention, submissions
from ..formatting import fmt_date
from .common import parse_date

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ================================================================= people

@admin_bp.get("/users")
@admin_required
def users():
    q = (request.args.get("q") or "").strip().lower()
    role = request.args.get("role", "")
    branch_id = request.args.get("branch", type=int)
    sql, params = ["1=1"], []
    if q:
        sql.append("(u.username LIKE %s OR u.full_name LIKE %s)"); params += [f"%{q}%"] * 2
    if role in ("ADMIN", "USER"):
        sql.append("u.role = %s"); params.append(role)
    if branch_id:
        sql.append("u.branch_id = %s"); params.append(branch_id)
    rows = query_all(
        f"""SELECT u.id, u.username, u.full_name, u.role, u.branch_id, u.must_change_password,
                   u.last_login_at, u.created_at, b.name AS branch_name
              FROM users u LEFT JOIN branches b ON b.id = u.branch_id
             WHERE {' AND '.join(sql)} ORDER BY u.role, u.username""", params,
    )
    return render_template("admin/users.html", users=rows, branches=branches.all_branches(),
                           q=q, role=role, branch_id=branch_id)


@admin_bp.post("/users")
@admin_required
def create_user():
    username = (request.form.get("username") or "").strip().lower()
    full_name = (request.form.get("full_name") or "").strip()[:100] or None
    role = "ADMIN" if request.form.get("role") == "ADMIN" else "USER"
    branch = branches.get(request.form.get("branch_id"))
    password = (request.form.get("password") or "").strip()

    error = validate_username(username)
    if not error and query_one("SELECT id FROM users WHERE username = %s", (username,)):
        error = f"ชื่อผู้ใช้ “{username}” มีอยู่แล้ว"
    if not error and password:
        error = validate_password(password)
    if error:
        flash(error, "error")
        return redirect(url_for("admin.users"))

    temp = password or generate_temp_password()
    execute(
        "INSERT INTO users (username, full_name, password_hash, role, branch_id, must_change_password) "
        "VALUES (%s, %s, %s, %s, %s, 1)",
        (username, full_name, generate_password_hash(temp), role, branch["id"] if branch else None),
    )
    session["reveal_password"] = {"username": username, "password": temp}
    flash(f"สร้างบัญชี “{username}” แล้ว แจ้งรหัสผ่านชั่วคราวด้านล่างให้ผู้ใช้ ซึ่งต้องเปลี่ยนเมื่อเข้าสู่ระบบครั้งแรก", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>")
@admin_required
def update_user(user_id):
    user = query_one("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
    if not user:
        flash("ไม่พบผู้ใช้", "error")
        return redirect(url_for("admin.users"))
    role = "ADMIN" if request.form.get("role") == "ADMIN" else "USER"
    if user["role"] == "ADMIN" and role != "ADMIN" and _admin_count() <= 1:
        flash("ต้องมีผู้ดูแลระบบอย่างน้อย 1 คน", "error")
        return redirect(url_for("admin.users"))
    branch = branches.get(request.form.get("branch_id"))
    full_name = (request.form.get("full_name") or "").strip()[:100] or None
    execute("UPDATE users SET full_name=%s, role=%s, branch_id=%s WHERE id=%s",
            (full_name, role, branch["id"] if branch else None, user_id))
    if user_id == session.get("user_id"):
        session.update(role=role, branch_id=branch["id"] if branch else None, full_name=full_name or user["username"])
    flash(f"อัปเดตข้อมูล “{user['username']}” แล้ว", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/reset-password")
@admin_required
def reset_password(user_id):
    user = query_one("SELECT id, username FROM users WHERE id = %s", (user_id,))
    if not user:
        flash("ไม่พบผู้ใช้", "error")
        return redirect(url_for("admin.users"))
    temp = generate_temp_password()
    execute("UPDATE users SET password_hash=%s, must_change_password=1, password_changed_at=NOW() WHERE id=%s",
            (generate_password_hash(temp), user_id))
    session["reveal_password"] = {"username": user["username"], "password": temp}
    flash(f"รีเซ็ตรหัสผ่านของ “{user['username']}” แล้ว", "success")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/delete")
@admin_required
def delete_user(user_id):
    user = query_one("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
    if not user:
        flash("ไม่พบผู้ใช้", "error")
    elif user_id == session.get("user_id"):
        flash("ไม่สามารถลบบัญชีของตัวเองได้", "error")
    elif user["role"] == "ADMIN" and _admin_count() <= 1:
        flash("ต้องมีผู้ดูแลระบบอย่างน้อย 1 คน", "error")
    else:
        execute("DELETE FROM users WHERE id = %s", (user_id,))
        flash(f"ลบ “{user['username']}” แล้ว (รายงานเดิมยังคงอยู่)", "success")
    return redirect(url_for("admin.users"))


def _admin_count():
    return query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'ADMIN'")["n"]


# ================================================================= locations

@admin_bp.get("/locations", endpoint="branches")
@admin_required
def branches_page():
    rows = query_all(
        """SELECT b.*, t.name AS template_name,
                  (SELECT COUNT(*) FROM users u WHERE u.branch_id = b.id) AS user_count,
                  (SELECT MAX(audit_date) FROM site_audits a WHERE a.branch_id = b.id) AS last_audit
             FROM branches b LEFT JOIN checklist_templates t ON t.id = b.template_id
            ORDER BY b.is_active DESC, b.name"""
    )
    return render_template("admin/branches.html", rows=rows,
                           templates=checklists.list_templates(include_inactive=False))


def _branch_form():
    name = " ".join((request.form.get("name") or "").split())[:100]
    code = (request.form.get("code") or "").strip().upper()[:20] or None
    template_id = request.form.get("template_id", type=int) or None
    cleaning_on = 1 if request.form.get("cleaning_schedule_enabled") else 0
    return name, code, template_id, cleaning_on


@admin_bp.post("/locations")
@admin_required
def create_branch():
    name, code, template_id, cleaning_on = _branch_form()
    if not name:
        flash("กรุณากรอกชื่อสาขา", "error")
    elif query_one("SELECT id FROM branches WHERE name = %s", (name,)):
        flash(f"มีสาขา “{name}” อยู่แล้ว", "warning")
    else:
        execute("INSERT INTO branches (name, code, template_id, cleaning_schedule_enabled) VALUES (%s, %s, %s, %s)",
                (name, code, template_id, cleaning_on))
        branches.invalidate()
        flash(f"เพิ่มสาขา “{name}” แล้ว", "success")
    return redirect(url_for("admin.branches"))


@admin_bp.post("/locations/<int:branch_id>")
@admin_required
def update_branch(branch_id):
    name, code, template_id, cleaning_on = _branch_form()
    clash = query_one("SELECT id FROM branches WHERE name = %s AND id <> %s", (name, branch_id))
    if not name or clash:
        flash("ชื่อสาขาต้องไม่ว่างและไม่ซ้ำกับสาขาอื่น", "error")
    else:
        execute("UPDATE branches SET name=%s, code=%s, template_id=%s, cleaning_schedule_enabled=%s WHERE id=%s",
                (name, code, template_id, cleaning_on, branch_id))
        branches.invalidate()
        flash(f"บันทึกสาขา “{name}” แล้ว", "success")
    return redirect(url_for("admin.branches"))


@admin_bp.post("/locations/<int:branch_id>/archive")
@admin_required
def archive_branch(branch_id):
    active = 0 if request.form.get("action") == "archive" else 1
    execute("UPDATE branches SET is_active = %s WHERE id = %s", (active, branch_id))
    branches.invalidate()
    flash("ปิดใช้งานสาขาแล้ว ประวัติยังคงอยู่" if not active else "เปิดใช้งานสาขาอีกครั้งแล้ว", "success")
    return redirect(url_for("admin.branches"))


# ================================================================= checklist templates

@admin_bp.get("/templates")
@admin_required
def templates():
    return render_template("admin/templates.html", templates=checklists.list_templates())


@admin_bp.get("/templates/new")
@admin_required
def new_template():
    blank = {"id": None, "name": "", "description": "", "is_active": 1, "photo_min": 0, "photo_max": 7,
             "sections": [{"title": "", "items": [{"title": "", "guidance": "", "evidence_fields": []}]}]}
    return render_template("admin/template_edit.html", template=blank)


@admin_bp.get("/templates/<int:template_id>")
@admin_required
def edit_template(template_id):
    template = checklists.get_template(template_id)
    if not template:
        flash("Template not found.", "error")
        return redirect(url_for("admin.templates"))
    return render_template("admin/template_edit.html", template=template)


@admin_bp.post("/templates/save")
@admin_required
def save_template():
    data = request.get_json(silent=True) or {}
    template_id = data.get("id")
    try:
        saved_id = checklists.save_template(data, int(template_id) if template_id else None, session["username"])
    except checklists.TemplateError as exc:
        return jsonify(success=False, error=str(exc)), 400
    flash("บันทึกเทมเพลตแล้ว", "success")
    return jsonify(success=True, id=saved_id, url=url_for("admin.edit_template", template_id=saved_id))


@admin_bp.post("/templates/<int:template_id>/action")
@admin_required
def template_action(template_id):
    action = request.form.get("action")
    try:
        if action == "default":
            checklists.set_default(template_id)
            flash("ตั้งเป็นเทมเพลตเริ่มต้นแล้ว", "success")
        elif action in ("activate", "deactivate"):
            checklists.set_active(template_id, action == "activate")
            flash("เปิดใช้งานเทมเพลตแล้ว" if action == "activate" else "ปิดใช้งานเทมเพลตแล้ว", "success")
        elif action == "duplicate":
            new_id = checklists.duplicate(template_id, session["username"])
            flash("สร้างสำเนาแล้ว (ยังไม่เปิดใช้งาน เพื่อให้แก้ไขก่อน)", "success")
            return redirect(url_for("admin.edit_template", template_id=new_id))
        elif action == "delete":
            checklists.delete(template_id)
            flash("ลบเทมเพลตแล้ว", "success")
    except checklists.TemplateError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.templates"))


# ================================================================= cleaning tasks

@admin_bp.route("/cleaning-tasks", methods=["GET", "POST"])
@admin_required
def cleaning_tasks():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        tasks = data.get("tasks") or []
        clean, kept = [], set()
        for pos, task in enumerate(tasks[:80]):
            title = " ".join(str(task.get("title") or "").split())[:200]
            if not title:
                continue
            clean.append({
                "id": task.get("id") if isinstance(task.get("id"), int) else None,
                "title": title,
                "time_slot": str(task.get("time_slot") or "").strip()[:40] or None,
                "frequency": "WEEKLY" if task.get("frequency") == "WEEKLY" else "DAILY",
                "is_break": 1 if task.get("is_break") else 0,
                "position": pos,
            })
        with transaction() as cur:
            for task in clean:
                if task["id"]:
                    cur.execute("UPDATE cleaning_tasks SET title=%s, time_slot=%s, frequency=%s, is_break=%s, "
                                "position=%s, is_active=1 WHERE id=%s",
                                (task["title"], task["time_slot"], task["frequency"], task["is_break"],
                                 task["position"], task["id"]))
                    kept.add(task["id"])
                else:
                    cur.execute("INSERT INTO cleaning_tasks (title, time_slot, frequency, is_break, position) "
                                "VALUES (%s, %s, %s, %s, %s)",
                                (task["title"], task["time_slot"], task["frequency"], task["is_break"], task["position"]))
                    kept.add(cur.lastrowid)
            # Removed tasks are deactivated, not deleted, so old schedules still show their titles.
            if kept:
                placeholders = ",".join(["%s"] * len(kept))
                cur.execute(f"UPDATE cleaning_tasks SET is_active = 0 WHERE id NOT IN ({placeholders})", list(kept))
            else:
                cur.execute("UPDATE cleaning_tasks SET is_active = 0")
        flash("บันทึกงานทำความสะอาดแล้ว", "success")
        return jsonify(success=True)
    tasks = query_all("SELECT * FROM cleaning_tasks WHERE is_active = 1 ORDER BY frequency, position, id")
    return render_template("admin/cleaning_tasks.html", tasks=tasks)


# ================================================================= monitoring & analytics

@admin_bp.get("/monitor")
@admin_required
def monitor():
    target = parse_date(request.args.get("date"))
    summary, rows = submissions.daily_status(target)
    return render_template("admin/monitor.html", summary=summary, rows=rows)


@admin_bp.get("/monitor/data")
@admin_required
def monitor_data():
    summary, rows = submissions.daily_status(parse_date(request.args.get("date")))
    summary_json, rows_json = submissions.serialize(summary, rows)
    return jsonify(success=True, summary=summary_json, rows=rows_json)


@admin_bp.get("/analytics")
@admin_required
def visitor_analytics():
    branch_id = request.args.get("branch", type=int)
    weeks = request.args.get("weeks", 8, type=int)
    weeks = weeks if weeks in (4, 8, 12, 16) else 8
    data = analytics.weekly_visitors(branch_id, weeks)
    return render_template("admin/analytics.html", weeks=data, branches=branches.all_branches(),
                           branch_id=branch_id, week_count=weeks, fields=analytics.VISITOR_FIELDS)


# ================================================================= data & settings

@admin_bp.get("/settings")
@admin_required
def settings():
    cfg = current_app.config
    counts = {
        table: query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
        for table in ("site_audits", "shift_reports", "cleaning_schedules", "item_requests", "users", "branches")
    }
    months = cfg["RETENTION_MONTHS"]
    return render_template("admin/settings.html", counts=counts, retention_months=months,
                           cutoff=retention.cutoff_date(months) if months else None, cfg=cfg)


@admin_bp.post("/settings/retention")
@admin_required
def run_retention():
    stats = retention.run_cleanup(current_app.config["RETENTION_MONTHS"])
    if stats.get("skipped"):
        flash("ปิดการลบข้อมูลตามระยะเวลาอยู่ (RETENTION_MONTHS=0)", "info")
    else:
        flash(f"ลบรายงานตรวจ {stats['audits']} รายการ รายงานประจำวัน {stats['reports']} รายการ ตาราง {stats['schedules']} รายการ "
              f"และไฟล์ {stats['files']} ไฟล์ ที่เก่ากว่า {fmt_date(stats['cutoff'])}", "success")
    return redirect(url_for("admin.settings"))


@admin_bp.post("/settings/clear")
@admin_required
def clear_data():
    if request.form.get("confirm") != "DELETE":
        flash("กรุณาพิมพ์ DELETE เพื่อยืนยัน", "error")
        return redirect(url_for("admin.settings"))
    removed = retention.clear_all()
    flash(f"ลบรายงานทั้งหมดแล้ว (ลบไฟล์ {removed} ไฟล์) ผู้ใช้ สาขา และเทมเพลตยังคงอยู่", "success")
    return redirect(url_for("admin.settings"))
