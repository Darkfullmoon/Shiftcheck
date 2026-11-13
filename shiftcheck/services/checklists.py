"""Checklist templates: admin-editable sections, items and evidence fields."""

from ..db import from_json, query_all, query_one, to_json, transaction

FIELD_TYPES = ("text", "number", "date")
STATUSES = ("PASS", "FAIL", "NA")
MAX_SECTIONS = 30
MAX_ITEMS_PER_SECTION = 60
MAX_FIELDS_PER_ITEM = 5


class TemplateError(ValueError):
    pass


def list_templates(include_inactive=True):
    rows = query_all(
        """
        SELECT t.*,
               (SELECT COUNT(*) FROM checklist_sections s WHERE s.template_id = t.id) AS section_count,
               (SELECT COUNT(*) FROM checklist_items i
                  JOIN checklist_sections s ON s.id = i.section_id
                 WHERE s.template_id = t.id) AS item_count,
               (SELECT COUNT(*) FROM site_audits a WHERE a.template_id = t.id) AS audit_count
          FROM checklist_templates t
         ORDER BY t.is_default DESC, t.is_active DESC, t.name
        """
    )
    return [r for r in rows if include_inactive or r["is_active"]]


def get_template(template_id):
    template = query_one("SELECT * FROM checklist_templates WHERE id = %s", (template_id,))
    if not template:
        return None
    sections = query_all(
        "SELECT id, title, position FROM checklist_sections WHERE template_id = %s ORDER BY position, id",
        (template_id,),
    )
    items = query_all(
        """
        SELECT i.id, i.section_id, i.title, i.guidance, i.position, i.evidence_fields
          FROM checklist_items i JOIN checklist_sections s ON s.id = i.section_id
         WHERE s.template_id = %s ORDER BY i.position, i.id
        """,
        (template_id,),
    )
    by_section = {s["id"]: {**s, "items": []} for s in sections}
    for item in items:
        item["evidence_fields"] = from_json(item["evidence_fields"], [])
        by_section[item["section_id"]]["items"].append(item)
    template["sections"] = list(by_section.values())
    template["item_count"] = len(items)
    return template


def default_template_id():
    row = query_one(
        "SELECT id FROM checklist_templates WHERE is_active = 1 ORDER BY is_default DESC, id LIMIT 1"
    )
    return row["id"] if row else None


def template_for_branch(branch):
    """The branch's assigned template if it is active, otherwise the default one."""
    if branch and branch.get("template_id"):
        row = query_one(
            "SELECT id FROM checklist_templates WHERE id = %s AND is_active = 1", (branch["template_id"],)
        )
        if row:
            return row["id"]
    return default_template_id()


def _clean_text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def normalize_payload(data):
    """Validates editor JSON and returns a clean structure, raising TemplateError on problems."""
    if not isinstance(data, dict):
        raise TemplateError("ข้อมูลเทมเพลตไม่ถูกต้อง")
    name = _clean_text(data.get("name"), 120)
    if not name:
        raise TemplateError("กรุณาตั้งชื่อเทมเพลต")
    try:
        photo_min = max(0, min(7, int(data.get("photo_min") or 0)))
        photo_max = max(0, min(7, int(data.get("photo_max") if data.get("photo_max") is not None else 7)))
    except (TypeError, ValueError):
        raise TemplateError("จำนวนรูปต้องเป็นจำนวนเต็มระหว่าง 0 ถึง 7")
    if photo_min > photo_max:
        raise TemplateError("จำนวนรูปขั้นต่ำต้องไม่มากกว่าจำนวนสูงสุด")

    sections = []
    for raw_section in (data.get("sections") or [])[:MAX_SECTIONS]:
        title = _clean_text(raw_section.get("title"), 200)
        items = []
        for raw_item in (raw_section.get("items") or [])[:MAX_ITEMS_PER_SECTION]:
            item_title = _clean_text(raw_item.get("title"), 500)
            if not item_title:
                continue
            fields = []
            for raw_field in (raw_item.get("evidence_fields") or [])[:MAX_FIELDS_PER_ITEM]:
                label = _clean_text(raw_field.get("label"), 120)
                ftype = raw_field.get("type") if raw_field.get("type") in FIELD_TYPES else "text"
                if label:
                    fields.append({"label": label, "type": ftype})
            items.append({
                "title": item_title,
                "guidance": _clean_text(raw_item.get("guidance"), 500) or None,
                "evidence_fields": fields,
            })
        if items:
            if not title:
                raise TemplateError("ทุกหมวดต้องมีชื่อ")
            sections.append({"title": title, "items": items})
    if not sections:
        raise TemplateError("ต้องมีอย่างน้อย 1 หมวด และแต่ละหมวดต้องมีอย่างน้อย 1 รายการ")

    return {
        "name": name,
        "description": _clean_text(data.get("description"), 500) or None,
        "is_active": 1 if data.get("is_active", True) else 0,
        "photo_min": photo_min,
        "photo_max": photo_max,
        "sections": sections,
    }


def save_template(data, template_id=None, username=None):
    """Creates or replaces a template. Past audits keep their own snapshot, so replacing is safe."""
    clean = normalize_payload(data)
    with transaction() as cur:
        if template_id:
            cur.execute("SELECT id FROM checklist_templates WHERE id = %s FOR UPDATE", (template_id,))
            if not cur.fetchone():
                raise TemplateError("ไม่พบเทมเพลต")
            cur.execute(
                "UPDATE checklist_templates SET name=%s, description=%s, is_active=%s, photo_min=%s, "
                "photo_max=%s WHERE id=%s",
                (clean["name"], clean["description"], clean["is_active"], clean["photo_min"],
                 clean["photo_max"], template_id),
            )
            cur.execute("DELETE FROM checklist_sections WHERE template_id = %s", (template_id,))
        else:
            cur.execute("SELECT COUNT(*) AS n FROM checklist_templates")
            is_first = cur.fetchone()["n"] == 0
            cur.execute(
                "INSERT INTO checklist_templates (name, description, is_active, is_default, photo_min, "
                "photo_max, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (clean["name"], clean["description"], clean["is_active"], 1 if is_first else 0,
                 clean["photo_min"], clean["photo_max"], username),
            )
            template_id = cur.lastrowid

        for s_pos, section in enumerate(clean["sections"]):
            cur.execute(
                "INSERT INTO checklist_sections (template_id, title, position) VALUES (%s, %s, %s)",
                (template_id, section["title"], s_pos),
            )
            section_id = cur.lastrowid
            for i_pos, item in enumerate(section["items"]):
                cur.execute(
                    "INSERT INTO checklist_items (section_id, title, guidance, position, evidence_fields) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (section_id, item["title"], item["guidance"], i_pos, to_json(item["evidence_fields"])),
                )
        if not clean["is_active"]:
            cur.execute("UPDATE checklist_templates SET is_default = 0 WHERE id = %s", (template_id,))
    return template_id


def set_default(template_id):
    with transaction() as cur:
        cur.execute("SELECT is_active FROM checklist_templates WHERE id = %s", (template_id,))
        row = cur.fetchone()
        if not row:
            raise TemplateError("ไม่พบเทมเพลต")
        if not row["is_active"]:
            raise TemplateError("กรุณาเปิดใช้งานเทมเพลตก่อนตั้งเป็นค่าเริ่มต้น")
        cur.execute("UPDATE checklist_templates SET is_default = (id = %s)", (template_id,))


def set_active(template_id, active):
    with transaction() as cur:
        cur.execute(
            "UPDATE checklist_templates SET is_active = %s, is_default = IF(%s, is_default, 0) WHERE id = %s",
            (1 if active else 0, 1 if active else 0, template_id),
        )


def duplicate(template_id, username=None):
    template = get_template(template_id)
    if not template:
        raise TemplateError("ไม่พบเทมเพลต")
    payload = {
        "name": f"{template['name']} (สำเนา)"[:120],
        "description": template["description"],
        "is_active": False,
        "photo_min": template["photo_min"],
        "photo_max": template["photo_max"],
        "sections": [
            {"title": s["title"], "items": [
                {"title": i["title"], "guidance": i["guidance"], "evidence_fields": i["evidence_fields"]}
                for i in s["items"]
            ]}
            for s in template["sections"]
        ],
    }
    return save_template(payload, username=username)


def delete(template_id):
    """Deletes a template that no audit references; otherwise archive it instead."""
    row = query_one("SELECT COUNT(*) AS n FROM site_audits WHERE template_id = %s", (template_id,))
    if row and row["n"]:
        raise TemplateError("เทมเพลตนี้มีรายงานตรวจอ้างอิงอยู่ ให้ปิดใช้งานแทนการลบ")
    with transaction() as cur:
        cur.execute("DELETE FROM checklist_templates WHERE id = %s", (template_id,))


# ---------------------------------------------------------------- audit scoring

def score_submission(template, form):
    """Builds the audit snapshot from a submitted form. Returns (sections, counts)."""
    counts = {"PASS": 0, "FAIL": 0, "NA": 0}
    sections = []
    number = 0
    for section in template["sections"]:
        snap_items = []
        for item in section["items"]:
            number += 1
            status = form.get(f"status_{item['id']}", "PASS")
            if status not in STATUSES:
                status = "PASS"
            counts[status] += 1
            evidence = []
            if status == "FAIL":
                for idx, field in enumerate(item["evidence_fields"]):
                    value = (form.get(f"ev_{item['id']}_{idx}") or "").strip()[:500]
                    evidence.append({"label": field["label"], "type": field["type"], "value": value})
            snap_items.append({
                "id": item["id"],
                "no": number,
                "title": item["title"],
                "guidance": item.get("guidance"),
                "status": status,
                "evidence": evidence,
            })
        sections.append({"title": section["title"], "items": snap_items})
    return sections, counts


def _fmt_evidence(entry):
    if entry.get("type") == "date":
        from ..formatting import fmt_date
        return fmt_date(entry["value"])
    return entry["value"]


def failed_items(sections):
    out = []
    for section in sections or []:
        for item in section.get("items", []):
            if item.get("status") == "FAIL":
                notes = [f"{e['label']}: {_fmt_evidence(e)}" for e in item.get("evidence", []) if e.get("value")]
                out.append({
                    "no": item.get("no"),
                    "title": item.get("title"),
                    "section": section.get("title"),
                    "notes": "; ".join(notes),
                })
    return out


def pass_rate(passed, failed):
    scored = (passed or 0) + (failed or 0)
    return round(passed / scored * 100, 1) if scored else 100.0
