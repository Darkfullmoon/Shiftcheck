"""Optional AI features using the Google Gemini REST API.

Everything here degrades gracefully: with no API key the audit summary falls back to a
rule-based report and the photo check is simply not offered.
"""

import base64
import io
import json
import logging
import os
import re
import urllib.error
import urllib.request

from flask import current_app
from PIL import Image

from . import checklists, media

log = logging.getLogger(__name__)
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def enabled():
    return bool(current_app.config.get("AI_ENABLED"))


def _generate(system_text, parts, json_mode=False, timeout=30, temperature=0.2):
    """Calls Gemini with each configured model/key until one succeeds. Returns text or None."""
    cfg = current_app.config
    if not enabled():
        return None
    generation = {"temperature": temperature}
    if json_mode:
        generation["responseMimeType"] = "application/json"
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"parts": parts}],
        "generationConfig": generation,
    }).encode("utf-8")

    for model in cfg["GEMINI_MODELS"]:
        for key in cfg["GEMINI_API_KEYS"]:
            req = urllib.request.Request(
                API_URL.format(model=model), data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                parts_out = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts_out).strip()
                if text:
                    return text
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
                log.warning("Gemini call failed (model=%s, key=...%s): %s", model, key[-4:], exc)
    return None


# ---------------------------------------------------------------- audit summary

SUMMARY_PROMPT = """คุณคือนักวิเคราะห์คุณภาพการปฏิบัติงาน เขียนรายงานสรุปสั้น ๆ สำหรับผู้บริหารจากผลการตรวจสาขา 1 ครั้ง
ตอบเป็นภาษาไทย ใช้ Markdown และใช้หัวข้อต่อไปนี้เท่านั้น:
### สรุปภาพรวม
### สถานะ
### ปัญหาที่พบ
### ข้อเสนอแนะ
### สิ่งที่ต้องติดตาม
เขียนกระชับ ใช้เฉพาะข้อมูลที่ให้มา และเริ่มต้นที่ "### สรุปภาพรวม" ทันที"""


def _status_line(rate, failed_count):
    if failed_count == 0:
        return "**ปกติ** — ทุกรายการที่ให้คะแนนผ่านเกณฑ์"
    if rate >= 85:
        return "**เฝ้าระวัง** — มีข้อบกพร่องเล็กน้อยที่ต้องแก้ไข"
    return "**ต้องแก้ไขด่วน** — สาขาต่ำกว่าเกณฑ์มาตรฐาน 85%"


def rule_based_summary(audit, sections):
    from ..formatting import fmt_date

    rate = checklists.pass_rate(audit["passed_items"], audit["failed_items"])
    failed = checklists.failed_items(sections)
    issues = "\n".join(
        f"- **ข้อ {f['no']} {f['title']}** ({f['section']})" + (f" — {f['notes']}" if f["notes"] else "")
        for f in failed
    ) or "- ไม่พบปัญหา"
    actions = (
        "1. มอบหมายผู้รับผิดชอบแต่ละรายการที่ไม่ผ่าน และกำหนดวันแก้ไขให้ชัดเจน\n"
        "2. ตรวจซ้ำรายการที่แก้ไขแล้วในการตรวจครั้งถัดไป"
        if failed else
        "1. รักษามาตรฐานการทำงานแบบเดิมต่อไป\n2. แบ่งปันแนวทางที่ได้ผลให้สาขาอื่น"
    )
    follow_up = ("ยืนยันว่าแก้ไขปัญหาข้างต้นเสร็จภายใน 24 ชั่วโมง"
                 if failed else "ไม่มีประเด็นที่ต้องติดตาม")
    return (
        f"### สรุปภาพรวม\nสาขา {audit['branch_name']} ผ่านเกณฑ์ **{rate}%** เมื่อวันที่ {fmt_date(audit['audit_date'])} "
        f"(ผ่าน {audit['passed_items']} ไม่ผ่าน {audit['failed_items']} ไม่เกี่ยวข้อง {audit['na_items']} รายการ) "
        f"ตามเช็กลิสต์ *{audit['template_name']}*\n\n"
        f"### สถานะ\n{_status_line(rate, len(failed))}\n\n"
        f"### ปัญหาที่พบ\n{issues}\n\n"
        f"### ข้อเสนอแนะ\n{actions}\n\n"
        f"### สิ่งที่ต้องติดตาม\n{follow_up}"
    )


def audit_summary(audit, sections):
    """Returns (markdown, source) where source is 'ai' or 'rules'."""
    if enabled():
        failed = checklists.failed_items(sections)
        lines = [
            f"สาขา: {audit['branch_name']}",
            f"วันที่: {audit['audit_date']}",
            f"เช็กลิสต์: {audit['template_name']}",
            f"ผ่าน: {audit['passed_items']}, ไม่ผ่าน: {audit['failed_items']}, ไม่เกี่ยวข้อง: {audit['na_items']}",
            f"อัตราผ่านเกณฑ์: {checklists.pass_rate(audit['passed_items'], audit['failed_items'])}%",
            "รายการที่ไม่ผ่าน:" if failed else "ไม่มีรายการที่ไม่ผ่าน",
        ]
        lines += [f"- #{f['no']} [{f['section']}] {f['title']} — {f['notes'] or 'ไม่มีบันทึก'}" for f in failed]
        if audit.get("notes"):
            lines.append(f"บันทึกของผู้ตรวจ: {audit['notes']}")
        text = _generate(SUMMARY_PROMPT, [{"text": "\n".join(lines)}], timeout=20)
        if text:
            match = re.search(r"###\s*สรุปภาพรวม.*", text, re.DOTALL | re.IGNORECASE)
            return (match.group(0) if match else text).strip(), "ai"
    return rule_based_summary(audit, sections), "rules"


# ---------------------------------------------------------------- photo check

PHOTO_PROMPT = """You check a team photo taken at the start of a shift. Answer in JSON only:
{{
  "is_screen_photo": false,            // true if this is a photo of a screen, print or poster
  "detected_count": 0,                 // real people visible (ignore mannequins, posters, cartoons)
  "is_full_body": true,                // head to shoes visible for the people shown
  "dress_code_status": "PASS",         // PASS, WARN or FAIL
  "dress_code_summary": "สรุป 1 ประโยคเป็นภาษาไทย",
  "observations": ["ข้อสังเกตสั้น ๆ เป็นภาษาไทย"]
}}
Dress code policy: {policy}"""


def _image_part(path):
    full = media.local_path(path) if path.startswith("/static/") else path
    if not full or not os.path.isfile(full):
        return None
    try:
        img = Image.open(full)
        img = img.convert("RGB")
        img.thumbnail((800, 800))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}
    except OSError:
        return None


def _reference_parts():
    folder = current_app.config.get("UNIFORM_REFERENCE_DIR")
    if not folder or not os.path.isdir(folder):
        return []
    parts = []
    for name in sorted(os.listdir(folder))[:3]:
        if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            part = _image_part(os.path.join(folder, name))
            if part:
                parts.append(part)
    return parts


def photo_check(photos, reported_count):
    """Analyses the first (team) photo. Returns a result dict, or None if AI is unavailable."""
    if not enabled() or not photos:
        return None
    team_photo = _image_part(photos[0])
    if not team_photo:
        return None

    parts = []
    references = _reference_parts()
    if references:
        parts.append({"text": "ตัวอย่างชุดยูนิฟอร์มที่ถูกต้อง:"})
        parts += references
    parts.append({"text": f"รูปที่ต้องตรวจ รายงานระบุว่ามีพนักงานในกะ {reported_count} คน"})
    parts.append(team_photo)

    prompt = PHOTO_PROMPT.format(policy=current_app.config["DRESS_CODE_POLICY"])
    text = _generate(prompt, parts, json_mode=True, timeout=40, temperature=0.1)
    if not text:
        return None
    try:
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())
        if isinstance(data, list):
            data = data[0] if data else {}
    except ValueError:
        return None

    detected = int(data.get("detected_count") or 0)
    is_screen = bool(data.get("is_screen_photo"))
    dress = str(data.get("dress_code_status") or "WARN").upper()
    if is_screen or detected == 0:
        dress = "FAIL" if is_screen else "NO_STAFF"
    observations = [str(o) for o in (data.get("observations") or [])][:6]
    if is_screen:
        observations.insert(0, "รูปนี้น่าจะถ่ายจากหน้าจอหรือภาพพิมพ์ ไม่ใช่การถ่ายจริง")
    return {
        "is_screen_photo": is_screen,
        "detected_count": detected,
        "reported_count": reported_count,
        "count_matches": reported_count > 0 and detected >= reported_count,
        "is_full_body": bool(data.get("is_full_body")) and detected > 0,
        "dress_code_status": dress if dress in ("PASS", "WARN", "FAIL", "NO_STAFF") else "WARN",
        "dress_code_summary": str(data.get("dress_code_summary") or "")[:300],
        "observations": observations,
    }
