"""Monthly cleaning schedule: daily task grid plus a rotating weekly deep-clean task."""

import calendar
import re
from datetime import date, datetime, timedelta

from ..db import query_all
from ..formatting import DAYS_SHORT, MONTHS

ROTATION_ANCHOR = date(2024, 1, 1)  # a Monday; weekly tasks rotate every 7 days from here
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
INITIALS_RE = re.compile(r"[^A-Z0-9]")


def active_tasks():
    rows = query_all(
        "SELECT id, title, time_slot, frequency, is_break FROM cleaning_tasks "
        "WHERE is_active = 1 ORDER BY frequency, position, id"
    )
    return [dict(r, is_break=bool(r["is_break"])) for r in rows]


def all_tasks():
    return query_all("SELECT * FROM cleaning_tasks ORDER BY frequency, position, id")


def valid_month(value):
    return bool(value and MONTH_RE.match(value))


def parse_month(value):
    year, month = value.split("-")
    return int(year), int(month)


def month_label(value):
    if not valid_month(value):
        return value or ""
    year, month = parse_month(value)
    return f"{MONTHS[month]} {year + 543}"


def shift_month(value, delta):
    year, month = parse_month(value)
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return f"{year:04d}-{month:02d}"


def weekly_task_for(week_start, weekly_tasks):
    if not weekly_tasks:
        return None
    index = ((week_start - ROTATION_ANCHOR).days // 7) % len(weekly_tasks)
    return weekly_tasks[index]


def build_layout(month, tasks, today=None):
    """Days and Monday-based weeks of a month, each week tagged with its rotating task."""
    today = today or date.today()
    year, mon = parse_month(month)
    days_in_month = calendar.monthrange(year, mon)[1]
    weekly = [t for t in tasks if t["frequency"] == "WEEKLY"]

    days = []
    for d in range(1, days_in_month + 1):
        day_date = date(year, mon, d)
        days.append({
            "day": d,
            "date": day_date,
            "weekday": DAYS_SHORT[day_date.weekday()],
            "is_today": day_date == today,
            "is_weekend": day_date.weekday() >= 5,
        })

    weeks = []
    start = date(year, mon, 1)
    start -= timedelta(days=start.weekday())
    while start <= date(year, mon, days_in_month):
        in_month = [d for d in range(1, days_in_month + 1)
                    if start <= date(year, mon, d) <= start + timedelta(days=6)]
        weeks.append({
            "start": start.isoformat(),
            "end": (start + timedelta(days=6)).isoformat(),
            "days": in_month,
            "task": weekly_task_for(start, weekly),
            "is_current": start <= today <= start + timedelta(days=6),
        })
        start += timedelta(days=7)

    return {
        "month": month,
        "label": month_label(month),
        "days": days,
        "weeks": weeks,
        "daily_tasks": [t for t in tasks if t["frequency"] == "DAILY"],
        "weekly_tasks": weekly,
        "is_current_month": (today.year, today.month) == (year, mon),
    }


def editable_scope(layout, is_admin, today=None):
    """Which days and weeks the current user may change."""
    today = today or date.today()
    if is_admin:
        return {"days": {d["day"] for d in layout["days"]}, "weeks": {w["start"] for w in layout["weeks"]}}
    if not layout["is_current_month"]:
        return {"days": set(), "weeks": set()}
    return {
        "days": {today.day},
        "weeks": {w["start"] for w in layout["weeks"] if w["is_current"]},
    }


def _initials(value):
    return INITIALS_RE.sub("", str(value or "").upper())[:4]


def _iso_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def empty_sheet():
    return {"tasks": [], "daily": {}, "done_by": {}, "checked_by": {}, "weekly": {}}


def merge_sheet(existing, submitted, layout, scope, tasks):
    """Applies submitted changes, but only inside the user's editable scope."""
    result = empty_sheet()
    existing = existing or {}
    for key in ("daily", "done_by", "checked_by", "weekly"):
        result[key] = dict(existing.get(key) or {})

    daily_ids = {t["id"] for t in layout["daily_tasks"]}
    submitted_daily = submitted.get("daily") or {}
    for day in scope["days"]:
        for task_id in daily_ids:
            key = f"{task_id}:{day}"
            if submitted_daily.get(key):
                result["daily"][key] = True
            else:
                result["daily"].pop(key, None)
        for field in ("done_by", "checked_by"):
            value = _initials((submitted.get(field) or {}).get(str(day)))
            if value:
                result[field][str(day)] = value
            else:
                result[field].pop(str(day), None)

    weeks = {w["start"]: w for w in layout["weeks"]}
    submitted_weekly = submitted.get("weekly") or {}
    for week_start in scope["weeks"]:
        week = weeks.get(week_start)
        entry = submitted_weekly.get(week_start) or {}
        done_on = _iso_date(entry.get("done_on"))
        if week and week["task"] and (done_on or entry.get("done_by")):
            result["weekly"][week_start] = {
                "task_id": week["task"]["id"],
                "done_on": done_on,
                "done_by": _initials(entry.get("done_by")),
                "checked_by": _initials(entry.get("checked_by")),
            }
        else:
            result["weekly"].pop(week_start, None)

    # Keep a snapshot of task titles so old months still render after tasks are edited.
    known = {t["id"]: t for t in (existing.get("tasks") or [])}
    for task in tasks:
        known[task["id"]] = {k: task[k] for k in ("id", "title", "time_slot", "frequency", "is_break")}
    result["tasks"] = list(known.values())
    return result


def completion(sheet, layout):
    """Share of daily task cells ticked up to today (or the whole month if it is over)."""
    today = date.today()
    tickable = [t for t in layout["daily_tasks"] if not t.get("is_break")]
    days = [d for d in layout["days"] if d["date"] <= today]
    total = len(tickable) * len(days)
    if not total:
        return 0.0
    done = sum(1 for t in tickable for d in days if (sheet.get("daily") or {}).get(f"{t['id']}:{d['day']}"))
    return round(done / total * 100, 1)


def tasks_for_sheet(sheet):
    """Task list for rendering a saved month: current tasks plus any retired ones it used."""
    current = active_tasks()
    ids = {t["id"] for t in current}
    used = set()
    for key in (sheet.get("daily") or {}):
        used.add(int(key.split(":")[0]))
    retired = [dict(t, is_break=bool(t.get("is_break"))) for t in (sheet.get("tasks") or [])
               if t["id"] in used and t["id"] not in ids]
    return current + retired
