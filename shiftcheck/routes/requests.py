"""Item requests: staff ask for supplies or equipment, admins approve or reject."""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..db import execute, query_all, query_one
from ..security import admin_required, is_admin, login_required
from ..services import branches

requests_bp = Blueprint("requests", __name__, url_prefix="/requests")

CATEGORIES = ["วัสดุสิ้นเปลือง", "สื่อการตลาด", "อุปกรณ์", "เฟอร์นิเจอร์และของตกแต่ง", "ไอที", "อื่น ๆ"]
STATUSES = ("PENDING", "APPROVED", "REJECTED")


@requests_bp.get("")
@login_required
def index():
    status = request.args.get("status", "ALL")
    q = (request.args.get("q") or "").strip()
    sql = ["1=1"] if is_admin() else ["r.submitted_by = %s"]
    params = [] if is_admin() else [session["username"]]
    if status in STATUSES:
        sql.append("r.status = %s"); params.append(status)
    if q:
        sql.append("(r.item_code LIKE %s OR r.item_name LIKE %s OR r.submitted_by LIKE %s)")
        params += [f"%{q}%"] * 3
    rows = query_all(
        f"""SELECT r.*, b.name AS branch_name FROM item_requests r LEFT JOIN branches b ON b.id = r.branch_id
             WHERE {' AND '.join(sql)} ORDER BY r.created_at DESC LIMIT 200""", params,
    )
    counts = {s: 0 for s in STATUSES}
    count_sql = "SELECT status, COUNT(*) AS n FROM item_requests" + ("" if is_admin() else " WHERE submitted_by = %s")
    for row in query_all(count_sql + " GROUP BY status", [] if is_admin() else [session["username"]]):
        counts[row["status"]] = row["n"]
    return render_template("requests/index.html", items=rows, status=status, q=q, counts=counts)


@requests_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = {}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in ("item_code", "item_name", "category", "quantity", "reason", "branch")}
        errors = []
        if not form["item_code"] or not form["item_name"]:
            errors.append("กรุณากรอกรหัสและชื่อรายการ")
        if form["category"] not in CATEGORIES:
            errors.append("กรุณาเลือกหมวดหมู่")
        try:
            quantity = int(form["quantity"])
            if not 1 <= quantity <= 10000:
                raise ValueError
        except ValueError:
            errors.append("จำนวนต้องเป็นจำนวนเต็มระหว่าง 1 ถึง 10,000")
            quantity = 1
        branch = branches.resolve_submit_branch(form["branch"]) or branches.user_branch()
        if errors:
            for error in errors:
                flash(error, "error")
        else:
            execute(
                "INSERT INTO item_requests (branch_id, item_code, item_name, category, quantity, reason, submitted_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (branch["id"] if branch else None, form["item_code"].upper()[:50], form["item_name"][:255],
                 form["category"], quantity, form["reason"][:500] or None, session["username"]),
            )
            flash(f"ส่งคำขอ “{form['item_name']}” เพื่อรออนุมัติแล้ว", "success")
            return redirect(url_for("requests.index"))
    return render_template("requests/new.html", form=form, categories=CATEGORIES,
                           branches=branches.allowed_branches())


@requests_bp.get("/queue")
@admin_required
def queue():
    rows = query_all(
        "SELECT r.*, b.name AS branch_name FROM item_requests r LEFT JOIN branches b ON b.id = r.branch_id "
        "WHERE r.status = 'PENDING' ORDER BY r.created_at"
    )
    return render_template("requests/queue.html", items=rows)


@requests_bp.post("/<int:request_id>/decide")
@admin_required
def decide(request_id):
    decision = request.form.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        flash("กรุณาเลือกอนุมัติหรือไม่อนุมัติ", "error")
        return redirect(url_for("requests.queue"))
    row = query_one("SELECT id, item_name, status FROM item_requests WHERE id = %s", (request_id,))
    if not row:
        flash("ไม่พบคำขอ", "error")
    elif row["status"] != "PENDING":
        flash("คำขอนี้ได้รับการพิจารณาไปแล้ว", "warning")
    else:
        execute(
            "UPDATE item_requests SET status=%s, reviewer_note=%s, reviewed_by=%s, reviewed_at=NOW() WHERE id=%s",
            (decision, (request.form.get("note") or "").strip()[:1000] or None, session["username"], request_id),
        )
        flash(f"“{row['item_name']}” {'อนุมัติแล้ว' if decision == 'APPROVED' else 'ไม่อนุมัติ'}", "success")
    return redirect(url_for("requests.queue"))
