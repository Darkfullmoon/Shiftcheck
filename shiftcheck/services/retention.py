"""Data retention: removes old records together with the photos and signatures they reference."""

import calendar
from datetime import date

from ..db import from_json, query_all, transaction
from . import media


def cutoff_date(months, today=None):
    today = today or date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def _files_from_audit(row):
    payload = from_json(row["payload"], {}) or {}
    files = list(payload.get("photos") or [])
    files += [s.get("signature") for s in payload.get("signoffs") or [] if s.get("signature")]
    return files


def _files_from_report(row):
    files = list(from_json(row["photos"], []) or [])
    files += [s.get("signature") for s in from_json(row["signoffs"], []) or [] if s.get("signature")]
    return files


def run_cleanup(months, today=None):
    """Deletes audits, shift reports and cleaning sheets older than `months`. Returns counts."""
    if not months or months <= 0:
        return {"skipped": True}
    cut = cutoff_date(months, today)
    stats = {"cutoff": cut, "audits": 0, "reports": 0, "schedules": 0, "files": 0}

    audits = query_all("SELECT id, payload FROM site_audits WHERE audit_date < %s", (cut,))
    reports = query_all("SELECT id, photos, signoffs FROM shift_reports WHERE report_date < %s", (cut,))
    with transaction() as cur:
        stats["audits"] = cur.execute("DELETE FROM site_audits WHERE audit_date < %s", (cut,))
        stats["reports"] = cur.execute("DELETE FROM shift_reports WHERE report_date < %s", (cut,))
        stats["schedules"] = cur.execute(
            "DELETE FROM cleaning_schedules WHERE month < %s", (cut.strftime("%Y-%m"),)
        )
    for row in audits:
        stats["files"] += media.delete_files(_files_from_audit(row))
    for row in reports:
        stats["files"] += media.delete_files(_files_from_report(row))
    return stats


def clear_all():
    """Deletes every audit, report, cleaning sheet and request, plus uploaded files."""
    audits = query_all("SELECT payload FROM site_audits")
    reports = query_all("SELECT photos, signoffs FROM shift_reports")
    with transaction() as cur:
        for table in ("site_audits", "shift_reports", "cleaning_schedules", "item_requests"):
            cur.execute(f"DELETE FROM {table}")
    removed = sum(media.delete_files(_files_from_audit(r)) for r in audits)
    removed += sum(media.delete_files(_files_from_report(r)) for r in reports)
    return removed
