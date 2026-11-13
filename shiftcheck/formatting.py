"""Template filters and small text helpers (Thai locale, Buddhist Era years)."""

import re
from datetime import date, datetime

from flask import request
from markupsafe import Markup, escape

MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
          "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
MONTHS_SHORT = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
DAYS_SHORT = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]


def thai_strftime(value, pattern):
    """strftime with Thai names and Buddhist Era years (%Y → 2569). %d drops the leading zero."""
    tokens = {
        "%d": str(value.day),
        "%B": MONTHS[value.month],
        "%b": MONTHS_SHORT[value.month],
        "%A": DAYS[value.weekday()],
        "%a": DAYS_SHORT[value.weekday()],
        "%Y": str(value.year + 543),
        "%m": f"{value.month:02d}",
    }
    if isinstance(value, datetime):
        tokens["%H"] = f"{value.hour:02d}"
        tokens["%M"] = f"{value.minute:02d}"
    return re.sub(r"%[dBbAaYmHM]", lambda m: tokens.get(m.group(0), m.group(0)), pattern)


def fmt_date(value, pattern="%d %b %Y"):
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return thai_strftime(value, pattern)
    return str(value)


def fmt_datetime(value):
    if not value:
        return "—"
    return thai_strftime(value, "%d %b %Y %H:%M น.") if isinstance(value, datetime) else str(value)


def fmt_time(value):
    return value.strftime("%H:%M น.") if isinstance(value, datetime) else "—"


def media_url(path):
    """Prefixes a stored '/static/...' path with the app's URL prefix, if any."""
    if isinstance(path, str) and path.startswith("/") and not path.startswith("//"):
        return request.script_root + path
    return path


def initials(name):
    parts = [p for p in re.split(r"[\s._-]+", str(name or "")) if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _inline(text):
    text = str(escape(text))
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def markdown(text):
    """Very small Markdown subset (headings, lists, bold, italics) rendered safely."""
    html, list_tag = [], None

    def close_list():
        nonlocal list_tag
        if list_tag:
            html.append(f"</{list_tag}>")
            list_tag = None

    for raw in str(text or "").splitlines():
        line = raw.strip()
        heading = re.match(r"^(#{1,4})\s+(.*)", line)
        bullet = re.match(r"^[-*•]\s+(.*)", line)
        numbered = re.match(r"^\d+[.)]\s+(.*)", line)
        if heading:
            close_list()
            level = min(4, len(heading.group(1)) + 1)
            html.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif bullet or numbered:
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                html.append(f"<{tag}>")
                list_tag = tag
            html.append(f"<li>{_inline((bullet or numbered).group(1))}</li>")
        elif line:
            close_list()
            html.append(f"<p>{_inline(line)}</p>")
        else:
            close_list()
    close_list()
    return Markup("\n".join(html))


STATUS_LABELS = {
    "ON_TIME": ("ตรงเวลา", "success"),
    "LATE": ("ส่งช้า", "warning"),
    "MISSING": ("ยังไม่ส่ง", "danger"),
    "PENDING": ("ยังไม่ถึงกำหนด", "neutral"),
    "PASS": ("ผ่าน", "success"),
    "FAIL": ("ไม่ผ่าน", "danger"),
    "NA": ("ไม่เกี่ยวข้อง", "neutral"),
    "WARN": ("ควรตรวจสอบ", "warning"),
    "NO_STAFF": ("ไม่พบบุคคล", "neutral"),
    "APPROVED": ("อนุมัติแล้ว", "success"),
    "REJECTED": ("ไม่อนุมัติ", "danger"),
}


def status_label(value):
    return STATUS_LABELS.get(value, (str(value).replace("_", " ").title(), "neutral"))[0]


def status_tone(value):
    return STATUS_LABELS.get(value, ("", "neutral"))[1]


def register(app):
    app.add_template_filter(fmt_date, "date")
    app.add_template_filter(fmt_datetime, "datetime")
    app.add_template_filter(fmt_time, "time")
    app.add_template_filter(media_url, "media")
    app.add_template_filter(initials, "initials")
    app.add_template_filter(markdown, "markdown")
    app.add_template_filter(status_label, "status_label")
    app.add_template_filter(status_tone, "status_tone")
