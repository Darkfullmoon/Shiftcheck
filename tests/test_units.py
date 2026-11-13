"""Pure-function tests that need no database."""

from datetime import date

from shiftcheck import formatting, security
from shiftcheck.services import checklists, cleaning, retention


def test_password_rules():
    assert security.validate_password("short") is not None
    assert "อักขระพิเศษ" in security.validate_password("NoSymbols123")
    assert security.validate_password("Good#Pass1") is None
    for _ in range(50):
        assert security.validate_password(security.generate_temp_password()) is None


def test_username_rules():
    assert security.validate_username("jo") is not None
    assert security.validate_username("Jordan") is not None  # uppercase not allowed
    assert security.validate_username("jordan.lee") is None


def test_markdown_is_escaped_and_structured():
    html = str(formatting.markdown("### Title\n- **bold** <script>x</script>\n1. step"))
    assert "<h4>Title</h4>" in html
    assert "<strong>bold</strong>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<ol>" in html and "<ul>" in html


def test_template_validation():
    import pytest
    with pytest.raises(checklists.TemplateError):
        checklists.normalize_payload({"name": "", "sections": []})
    with pytest.raises(checklists.TemplateError):
        checklists.normalize_payload({"name": "X", "sections": [{"title": "", "items": [{"title": "A"}]}]})
    with pytest.raises(checklists.TemplateError):
        checklists.normalize_payload({"name": "X", "photo_min": 5, "photo_max": 2,
                                      "sections": [{"title": "S", "items": [{"title": "A"}]}]})
    clean = checklists.normalize_payload({"name": "  Opening  ", "sections": [
        {"title": "S", "items": [{"title": "A", "evidence_fields": [{"label": "L", "type": "weird"}]}, {"title": "  "}]}]})
    assert clean["name"] == "Opening"
    assert len(clean["sections"][0]["items"]) == 1  # blank items dropped
    assert clean["sections"][0]["items"][0]["evidence_fields"][0]["type"] == "text"


def test_scoring_ignores_na_and_records_evidence():
    template = {"sections": [{"title": "S", "items": [
        {"id": 1, "title": "A", "evidence_fields": [{"label": "Why", "type": "text"}]},
        {"id": 2, "title": "B", "evidence_fields": []},
        {"id": 3, "title": "C", "evidence_fields": []}]}]}
    sections, counts = checklists.score_submission(template, {"status_1": "FAIL", "ev_1_0": "dirty", "status_3": "NA"})
    assert counts == {"PASS": 1, "FAIL": 1, "NA": 1}
    assert sections[0]["items"][0]["evidence"][0]["value"] == "dirty"
    assert checklists.pass_rate(1, 1) == 50.0
    assert checklists.pass_rate(0, 0) == 100.0


TASKS = [
    {"id": 1, "title": "Sweep", "time_slot": None, "frequency": "DAILY", "is_break": False},
    {"id": 2, "title": "Break", "time_slot": None, "frequency": "DAILY", "is_break": True},
    {"id": 3, "title": "Windows", "time_slot": None, "frequency": "WEEKLY", "is_break": False},
    {"id": 4, "title": "Storeroom", "time_slot": None, "frequency": "WEEKLY", "is_break": False},
]


def test_cleaning_layout_rotates_weekly_tasks():
    layout = cleaning.build_layout("2026-03", TASKS, today=date(2026, 3, 11))
    assert len(layout["days"]) == 31
    assert layout["weeks"][0]["start"] == "2026-02-23"  # Monday on or before the 1st
    tasks = [w["task"]["id"] for w in layout["weeks"]]
    assert all(a != b for a, b in zip(tasks, tasks[1:]))  # alternates between the two weekly tasks
    assert sum(w["is_current"] for w in layout["weeks"]) == 1


def test_cleaning_merge_respects_user_scope():
    today = date(2026, 3, 11)
    layout = cleaning.build_layout("2026-03", TASKS, today=today)
    existing = {"daily": {"1:10": True}, "done_by": {"10": "AB"}}
    submitted = {"daily": {"1:9": True, "1:11": True}, "done_by": {"9": "ZZ", "11": "cd"}, "weekly": {}}
    scope = cleaning.editable_scope(layout, is_admin=False, today=today)
    merged = cleaning.merge_sheet(existing, submitted, layout, scope, TASKS)
    assert merged["daily"] == {"1:10": True, "1:11": True}  # day 9 rejected, day 10 untouched
    assert merged["done_by"] == {"10": "AB", "11": "CD"}
    assert cleaning.editable_scope(cleaning.build_layout("2026-02", TASKS, today), False, today) == {"days": set(), "weeks": set()}


def test_retention_cutoff_handles_month_ends():
    assert retention.cutoff_date(4, date(2026, 6, 30)) == date(2026, 2, 28)
    assert retention.cutoff_date(1, date(2026, 1, 15)) == date(2025, 12, 15)
