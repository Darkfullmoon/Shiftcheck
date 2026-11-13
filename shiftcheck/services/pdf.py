"""PDF exports for audits, shift reports and cleaning schedules (ReportLab, Thai font)."""

import io
import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from ..formatting import fmt_date, fmt_datetime, thai_strftime
from . import analytics, media

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
pdfmetrics.registerFont(TTFont("Sarabun", os.path.join(FONT_DIR, "THSarabunNew.ttf")))
pdfmetrics.registerFont(TTFont("Sarabun-Bold", os.path.join(FONT_DIR, "THSarabunNew-Bold.ttf")))
pdfmetrics.registerFontFamily("Sarabun", normal="Sarabun", bold="Sarabun-Bold",
                              italic="Sarabun", boldItalic="Sarabun-Bold")

INK = colors.HexColor("#17201D")
MUTED = colors.HexColor("#5E6A66")
LINE = colors.HexColor("#DCDFD8")
SOFT = colors.HexColor("#F3F4EF")
BRAND = colors.HexColor("#1F6F5C")
PASS = colors.HexColor("#1F7A4D")
FAIL = colors.HexColor("#B3412E")
NA = colors.HexColor("#7A8580")

# TH Sarabun New draws small, so sizes are larger than a Latin font would need.
BASE = ParagraphStyle("base", fontName="Sarabun", fontSize=13, leading=16, textColor=INK)
SMALL = ParagraphStyle("small", parent=BASE, fontSize=11.5, leading=14, textColor=MUTED)
H1 = ParagraphStyle("h1", parent=BASE, fontName="Sarabun-Bold", fontSize=22, leading=26)
H2 = ParagraphStyle("h2", parent=BASE, fontName="Sarabun-Bold", fontSize=16, leading=19, spaceBefore=10, spaceAfter=5)
CELL_B = ParagraphStyle("cellb", parent=BASE, fontName="Sarabun-Bold")
CENTER = ParagraphStyle("center", parent=BASE, alignment=TA_CENTER)


def p(text, style=BASE):
    return Paragraph(escape(str(text if text not in (None, "") else "—")).replace("\n", "<br/>"), style)


def _table(data, widths, header=True, zebra=True, extra=None):
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    if zebra:
        for row in range(2 if header else 1, len(data), 2):
            style.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#FAFAF7")))
    table.setStyle(TableStyle(style + (extra or [])))
    return table


def _doc(buffer, title, pagesize=A4):
    def decorate(canvas, doc):
        width, height = pagesize
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, height - 8 * mm, width, 8 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Sarabun-Bold", 13)
        canvas.drawString(12 * mm, height - 5.6 * mm, "SHIFTCHECK")
        canvas.setFont("Sarabun", 12)
        canvas.drawRightString(width - 12 * mm, height - 5.6 * mm, title)
        canvas.setFillColor(MUTED)
        canvas.drawString(12 * mm, 8 * mm, f"สร้างเมื่อ {fmt_datetime(datetime.now())}")
        canvas.drawRightString(width - 12 * mm, 8 * mm, f"หน้า {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=title, author="Shiftcheck")
    return doc, decorate


def _meta_block(rows, width):
    data = [[p(label, SMALL), p(value, CELL_B)] for label, value in rows]
    cells = []
    for i in range(0, len(data), 2):
        cells.append(data[i] + (data[i + 1] if i + 1 < len(data) else [p(""), p("")]))
    col = width / 4
    return _table(cells, [col * 0.7, col * 1.3, col * 0.7, col * 1.3], header=False, zebra=False)


def _image(path, max_w, max_h):
    full = media.local_path(path)
    if not full:
        return p("(ไม่พบรูป)", SMALL)
    try:
        img = Image(full)
        ratio = min(max_w / img.imageWidth, max_h / img.imageHeight)
        img.drawWidth, img.drawHeight = img.imageWidth * ratio, img.imageHeight * ratio
        return img
    except Exception:  # Corrupt files should not break the whole export.
        return p("(เปิดรูปไม่ได้)", SMALL)


def _staffing_table(staffing, fields, width):
    rows = [[p("ประเภท", CELL_B), p("จำนวน", CELL_B), p("รายชื่อ", CELL_B)]]
    for key, label in fields:
        entry = (staffing or {}).get(key) or {}
        rows.append([p(label), p(entry.get("qty") or 0), p(entry.get("names"))])
    return _table(rows, [width * 0.25, width * 0.1, width * 0.65])


def _notes_table(notes, width, empty="ไม่มีบันทึก"):
    if not notes:
        return p(empty, SMALL)
    rows = [[p("ผู้รับผิดชอบ", CELL_B), p("รายละเอียด", CELL_B)]] + [[p(n.get("who")), p(n.get("note"))] for n in notes]
    return _table(rows, [width * 0.18, width * 0.82])


def _signoffs(signoffs, width):
    cells = []
    for s in signoffs or []:
        sig = _image(s["signature"], 45 * mm, 18 * mm) if s.get("signature") else p("ยังไม่ได้ลงชื่อ", SMALL)
        cells.append([sig, p(s.get("name") or "—", CELL_B), p(s.get("label"), SMALL)])
    if not cells:
        return p("ไม่มีการลงชื่อ", SMALL)
    col = width / max(1, len(cells))
    table = Table([[c[0] for c in cells], [c[1] for c in cells], [c[2] for c in cells]], colWidths=[col] * len(cells))
    table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("LINEABOVE", (0, 1), (-1, 1), 0.6, INK),
                               ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    return table


def _photos(photos, width, per_row=3):
    if not photos:
        return p("ไม่มีรูปแนบ", SMALL)
    cell_w = width / per_row
    images = [_image(path, cell_w - 4 * mm, 55 * mm) for path in photos]
    rows = [images[i:i + per_row] + [""] * (per_row - len(images[i:i + per_row])) for i in range(0, len(images), per_row)]
    table = Table(rows, colWidths=[cell_w] * per_row)
    table.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return table


# ---------------------------------------------------------------- audits

def audit_pdf(audit, cfg=None):
    from ..routes.common import STAFFING_FIELDS, on_site_count

    buffer = io.BytesIO()
    title = f"รายงานตรวจสาขา #{audit['id']}"
    doc, decorate = _doc(buffer, title)
    width = doc.width
    payload = audit["payload"]
    story = [
        p(audit["template_name"], H1),
        p(f"สาขา {audit['branch_name']} · วัน{fmt_date(audit['audit_date'], '%A ที่ %d %B %Y')}", SMALL),
        Spacer(1, 6),
        _meta_block([
            ("สาขา", audit["branch_name"]), ("ผู้ส่ง", audit["submitted_by"]),
            ("วันที่ตรวจ", fmt_date(audit["audit_date"])), ("เวลาที่ส่ง", fmt_datetime(audit["created_at"])),
            ("อัตราผ่านเกณฑ์", f"{audit['rate']}%"),
            ("ผลการตรวจ", f"ผ่าน {audit['passed_items']} · ไม่ผ่าน {audit['failed_items']} · ไม่เกี่ยวข้อง {audit['na_items']}"),
            ("การตรวจรับรอง", f"รับรองแล้ว โดย {audit['verified_by']}" if audit["is_verified"] else "ยังไม่ได้ตรวจรับรอง"),
            ("พนักงานในสาขา", f"{on_site_count(payload.get('staffing'))} คน"),
        ], width),
    ]

    status_styles = {
        status: ParagraphStyle(f"status_{status}", parent=CELL_B, textColor=color)
        for status, color in (("PASS", PASS), ("FAIL", FAIL), ("NA", NA))
    }
    status_text = {"PASS": "ผ่าน", "FAIL": "ไม่ผ่าน", "NA": "ไม่เกี่ยวข้อง"}
    for section in payload.get("sections") or []:
        rows = [[p("ข้อ", CELL_B), p("รายการตรวจ", CELL_B), p("ผล", CELL_B)]]
        for item in section["items"]:
            text = escape(item["title"])
            for ev in item.get("evidence") or []:
                if ev.get("value"):
                    value = fmt_date(ev['value']) if ev.get('type') == 'date' else ev['value']
                    text += f"<br/><font color='#5E6A66' size='11.5'>{escape(ev['label'])}: {escape(value)}</font>"
            rows.append([p(item["no"]), Paragraph(text, BASE),
                         p(status_text[item["status"]], status_styles[item["status"]])])
        story += [p(section["title"], H2), _table(rows, [width * 0.06, width * 0.78, width * 0.16])]

    if audit.get("notes"):
        story += [p("บันทึกของผู้ตรวจ", H2), p(audit["notes"])]
    story += [KeepTogether([p("พนักงานประจำวัน", H2), _staffing_table(payload.get("staffing"), STAFFING_FIELDS, width)])]
    story += [p("การประชุมเช้า", H2), _notes_table(payload.get("briefing"), width)]
    story += [KeepTogether([p("ลงชื่อรับรอง", H2), Spacer(1, 4), _signoffs(payload.get("signoffs"), width)])]
    if payload.get("photos"):
        story += [PageBreak(), p("รูปถ่าย", H2), _photos(payload["photos"], width)]

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------- shift reports

def report_pdf(report):
    from ..routes.common import STAFFING_FIELDS, on_site_count

    buffer = io.BytesIO()
    title = f"รายงานประจำวัน #{report['id']}"
    doc, decorate = _doc(buffer, title)
    width = doc.width
    stats = report["visitor_stats"]
    story = [
        p("รายงานประจำวัน", H1),
        p(f"สาขา {report['branch_name']} · วัน{fmt_date(report['report_date'], '%A ที่ %d %B %Y')}", SMALL),
        Spacer(1, 6),
        _meta_block([
            ("สาขา", report["branch_name"]), ("ทีม / กะ", report["team"] or "—"),
            ("วันที่", fmt_date(report["report_date"])), ("ผู้ส่ง", report["submitted_by"]),
            ("จำนวนลูกค้า", f"{report['visitor_total']} คน"), ("พนักงานในสาขา", f"{on_site_count(report['staffing'])} คน"),
            ("การตรวจรับรอง", f"รับรองแล้ว โดย {report['verified_by']}" if report["is_verified"] else "ยังไม่ได้ตรวจรับรอง"),
            ("เวลาที่ส่ง", fmt_datetime(report["created_at"])),
        ], width),
        p("ลูกค้า", H2),
        _table([[p(label, CELL_B) for _, label in analytics.VISITOR_FIELDS],
                [p(analytics.to_int(stats.get(key)), CENTER) for key, _ in analytics.VISITOR_FIELDS]],
               [width / len(analytics.VISITOR_FIELDS)] * len(analytics.VISITOR_FIELDS), zebra=False),
        KeepTogether([p("พนักงานประจำวัน", H2), _staffing_table(report["staffing"], STAFFING_FIELDS, width)]),
        p("การประชุมเช้า", H2), _notes_table(report["briefing"], width),
        p("สรุปผลการทำงาน", H2), _notes_table(report["summary"], width),
    ]
    if report.get("extra_tasks"):
        story += [p("งานอื่น ๆ / ปัญหาที่พบ", H2), p(report["extra_tasks"])]
    story += [KeepTogether([p("ลงชื่อรับรอง", H2), Spacer(1, 4), _signoffs(report["signoffs"], width)])]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------- cleaning schedules

def cleaning_pdf(record, sheet, layout):
    buffer = io.BytesIO()
    title = f"ตารางทำความสะอาด · {layout['label']}"
    doc, decorate = _doc(buffer, title, landscape(A4))
    width = doc.width
    days = layout["days"]
    tiny = ParagraphStyle("tiny", parent=SMALL, fontSize=9.5, leading=10.5, alignment=TA_CENTER)
    task_w = 62 * mm
    day_w = (width - task_w) / len(days)

    header = [p("งาน", CELL_B)] + [Paragraph(f"{d['day']}<br/>{d['weekday']}", tiny) for d in days]
    rows, extra = [header], []
    for task in layout["daily_tasks"]:
        label = f"{task['title']}" + (f" ({task['time_slot']})" if task.get("time_slot") else "")
        row = [p(label, SMALL)]
        for d in days:
            if task.get("is_break"):
                row.append("")
            else:
                done = (sheet.get("daily") or {}).get(f"{task['id']}:{d['day']}")
                # A filled bullet marks done cells (no check-mark glyph is needed in the font).
                row.append(Paragraph("<font color='#1F6F5C' size='14'><b>•</b></font>" if done else "", tiny))
        rows.append(row)
        if task.get("is_break"):
            extra.append(("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), SOFT))
    for label, key in (("ผู้ทำ", "done_by"), ("ผู้ตรวจ", "checked_by")):
        rows.append([p(label, CELL_B)] + [Paragraph((sheet.get(key) or {}).get(str(d["day"]), ""), tiny) for d in days])
    for i, d in enumerate(days, start=1):
        if d["is_weekend"]:
            extra.append(("BACKGROUND", (i, 0), (i, 0), colors.HexColor("#ECEEE7")))

    grid = Table(rows, colWidths=[task_w] + [day_w] * len(days), repeatRows=1)
    grid.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ] + extra))

    weekly_rows = [[p("สัปดาห์", CELL_B), p("งานทำความสะอาดใหญ่", CELL_B), p("วันที่ทำ", CELL_B),
                    p("ผู้ทำ", CELL_B), p("ผู้ตรวจ", CELL_B)]]
    for week in layout["weeks"]:
        entry = (sheet.get("weekly") or {}).get(week["start"]) or {}
        start, end = datetime.fromisoformat(week["start"]), datetime.fromisoformat(week["end"])
        weekly_rows.append([
            p(f"{thai_strftime(start, '%d %b')} – {thai_strftime(end, '%d %b')}"),
            p(week["task"]["title"] if week["task"] else "—"),
            p(fmt_date(entry.get("done_on")) if entry.get("done_on") else "—"),
            p(entry.get("done_by") or "—"), p(entry.get("checked_by") or "—"),
        ])
    story = [
        p(f"ตารางทำความสะอาด — สาขา {record['branch_name']}", H1),
        p(f"เดือน{layout['label']} · แก้ไขล่าสุด {fmt_datetime(record['updated_at'])} โดย {record['submitted_by']}", SMALL),
        Spacer(1, 6), grid,
        p("งานทำความสะอาดใหญ่ประจำสัปดาห์ (หมุนเวียน)", H2),
        _table(weekly_rows, [width * 0.16, width * 0.44, width * 0.14, width * 0.13, width * 0.13]),
    ]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    buffer.seek(0)
    return buffer
