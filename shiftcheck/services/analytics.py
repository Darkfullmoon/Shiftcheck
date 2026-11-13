"""Visitor analytics built from shift report counts."""

from datetime import date, timedelta

from ..db import from_json, query_all

VISITOR_FIELDS = [
    ("walk_ins", "ลูกค้า Walk-in"),
    ("appointments", "นัดหมาย"),
    ("phone_inquiries", "โทรสอบถาม"),
    ("bookings", "จอง"),
    ("follow_ups", "โทรติดตาม"),
]


def to_int(value):
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return 0


def weekly_visitors(branch_id=None, weeks=8, today=None):
    """Returns newest-first weeks (Mon–Sun) with per-day visitor totals and breakdowns."""
    today = today or date.today()
    current_monday = today - timedelta(days=today.weekday())
    first_monday = current_monday - timedelta(weeks=weeks - 1)

    sql = ("SELECT id, branch_id, report_date, submitted_by, visitor_stats FROM shift_reports "
           "WHERE report_date BETWEEN %s AND %s")
    params = [first_monday, current_monday + timedelta(days=6)]
    if branch_id:
        sql += " AND branch_id = %s"
        params.append(branch_id)

    by_day = {}
    for row in query_all(sql, params):
        stats = from_json(row["visitor_stats"], {}) or {}
        counts = {key: to_int(stats.get(key)) for key, _ in VISITOR_FIELDS}
        bucket = by_day.setdefault(row["report_date"], {"reports": 0, **dict.fromkeys(counts, 0)})
        bucket["reports"] += 1
        for key, value in counts.items():
            bucket[key] += value

    result = []
    for w in range(weeks):
        monday = current_monday - timedelta(weeks=w)
        days = []
        for d in range(7):
            day = monday + timedelta(days=d)
            bucket = by_day.get(day, {})
            breakdown = {key: bucket.get(key, 0) for key, _ in VISITOR_FIELDS}
            days.append({
                "date": day,
                "total": sum(breakdown.values()),
                "breakdown": breakdown,
                "reports": bucket.get("reports", 0),
                "is_future": day > today,
            })
        totals = {key: sum(d["breakdown"][key] for d in days) for key, _ in VISITOR_FIELDS}
        result.append({
            "start": monday,
            "end": monday + timedelta(days=6),
            "days": days,
            "total": sum(totals.values()),
            "totals": totals,
            "reports": sum(d["reports"] for d in days),
        })
    return result
