"""AI integration: validate / polish / consistency check / manager prompt.

All functions are graceful — if ANTHROPIC_API_KEY is empty they return
neutral results so the submit flow keeps working without AI.
"""
import json
from datetime import datetime, timezone

from flask import current_app

from .templates_loader import load_template


# ───────────────────────────────────────────────────────────────────
# Layer 1 — Required-field validation (no AI)
# ───────────────────────────────────────────────────────────────────


def validate_required(brief, db) -> list[dict]:
    """Return a list of required fields that are empty.

    Each entry: {"dept": str, "field_id": str, "label_he": str}.
    """
    template_id = brief["template_id"]
    tpl = load_template(template_id)
    departments = json.loads(brief["departments"])

    missing: list[dict] = []
    for dept in departments:
        dept_def = tpl["departments"].get(dept)
        if not dept_def:
            continue
        sec_row = db.execute(
            "SELECT data FROM sections WHERE brief_id = ? AND dept = ?",
            (brief["id"], dept),
        ).fetchone()
        section_data = json.loads(sec_row["data"]) if sec_row and sec_row["data"] else {}

        for f in dept_def["fields"]:
            if not f.get("required"):
                continue
            value = section_data.get(f["id"], "")
            if not value or not str(value).strip():
                missing.append({
                    "dept": dept,
                    "field_id": f["id"],
                    "label_he": f"{dept_def['label_he']} · {f['label_he']}",
                })
    return missing


# ───────────────────────────────────────────────────────────────────
# Anthropic client + helpers
# ───────────────────────────────────────────────────────────────────


_MODEL = "claude-sonnet-4-6"


def _client():
    """Lazily create an Anthropic client using the configured API key.

    Raises RuntimeError if no key is set — callers should check
    current_app.config['AI_AVAILABLE'] first.
    """
    from anthropic import Anthropic

    key = current_app.config.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return Anthropic(api_key=key)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_call(db, brief_id: str, action: str, usage) -> None:
    db.execute(
        """INSERT INTO ai_log (brief_id, action, input_tokens, output_tokens, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (brief_id, action,
         getattr(usage, "input_tokens", 0),
         getattr(usage, "output_tokens", 0),
         _now_iso()),
    )
    db.commit()


def _parse_json_response(text: str) -> dict:
    """Robustly extract a JSON object from a Claude response.

    Tolerates code fences (```json ... ```) and leading/trailing prose.
    """
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence (```json or ```)
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    # If the response has prose before the JSON, find the first `{` and `}`
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _load_all_sections(db, brief_id: str) -> dict:
    """Return {dept: {field_id: value}} for all non-empty fields."""
    rows = db.execute(
        "SELECT dept, data FROM sections WHERE brief_id = ?",
        (brief_id,),
    ).fetchall()
    out: dict = {}
    for r in rows:
        if not r["data"]:
            continue
        data = json.loads(r["data"])
        cleaned = {k: v for k, v in data.items() if v and str(v).strip()}
        if cleaned:
            out[r["dept"]] = cleaned
    return out


# ───────────────────────────────────────────────────────────────────
# Layer 2 — Polish (Claude call #1)
# ───────────────────────────────────────────────────────────────────


_POLISH_SYSTEM = """אתה עורך תוכן שיווקי בעברית עבור Selected Digital Marketing Agency.
המשימה: לקבל טקסטים שאיש צוות מילא בפגישת בריף ולשפר אותם.

עקרונות:
- שפה מקצועית ועברית תקנית
- ללא שינוי המשמעות
- ללא הוספת מידע חדש שלא נכתב במקור
- ללא הסרת פרטים מהותיים
- טון מקצועי-ידידותי (לא קר-תאגידי, לא עממי)
- שמור על המבנה: רשימות נשארות רשימות (שורה אחת לכל פריט), טקסטים חופשיים נשארים פסקאות
- שדות שכבר תקינים — דלג עליהם, אל תכלול בתשובה

חשוב מאוד — מה לא לעשות:
- אם השדה מכיל ג'יבריש (אותיות אקראיות, "asdf", "לחדעכדגע", הקלדות מבחן) — אל תנסה לליטוש. השאר אותו ריק בתשובה. סקירת המומחה תסמן את זה.
- אם השדה מכיל מילה אחת או שתיים בלבד שאין מה לליטוש — דלג.
- אל תהפוך תוכן דליל למשהו עשיר באופן מלאכותי.

החזר JSON בלבד עם שדות ששופרו (השאר ריק שדות שאסור לליטוש):
{
  "about": { "field_id": "טקסט מלוטש" },
  "seo":   { "field_id": "..." },
  "ppc":   { "field_id": "..." }
}
"""


def polish_brief(brief, db) -> dict | None:
    """Run Claude polish on all non-empty fields. Stores result in
    `sections.data_polished` and returns the polished dict."""
    if not current_app.config.get("AI_AVAILABLE"):
        return None

    sections_data = _load_all_sections(db, brief["id"])
    if not sections_data:
        return {}

    user_msg = "להלן הבריף בפורמט JSON. שפר רק שדות שדורשים זאת:\n\n" + json.dumps(
        sections_data, ensure_ascii=False, indent=2
    )

    client = _client()
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=[{
            "type": "text",
            "text": _POLISH_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = resp.content[0].text
    polished = _parse_json_response(raw)

    # Store polished fields per dept
    for dept, fields in polished.items():
        if not isinstance(fields, dict):
            continue
        db.execute(
            "UPDATE sections SET data_polished = ? WHERE brief_id = ? AND dept = ?",
            (json.dumps(fields, ensure_ascii=False), brief["id"], dept),
        )
    db.commit()

    _log_call(db, brief["id"], "polish", resp.usage)
    return polished


# ───────────────────────────────────────────────────────────────────
# Layer 3 — Consistency check (Claude call #2)
# ───────────────────────────────────────────────────────────────────


_CONSISTENCY_SYSTEM = """אתה בודק עקביות פנימית של בריפי לקוח עבור Selected Digital Marketing Agency.

המשימה: לקבל בריף עם 3 סקשנים אפשריים (about, seo, ppc) ולמצוא:
- סתירות בין סקשנים (קהל יעד שונה ב-SEO לעומת PPC, מסרים סותרים)
- אי-התאמות (מסרים שלא תואמים את הקהל המוצהר)
- חוסרים מהותיים שלא נתפסו בולידציה הבסיסית (תקציב מינימלי, אזור גאוגרפי לא ברור)

הנחיות לאיכות:
- התמקד בבעיות עסקיות אמיתיות, לא ב-nitpicks ניסוחיים
- אם הכל עקבי — החזר רשימה ריקה
- כל אזהרה תכלול הסבר תמציתי + הצעת פתרון

החזר JSON בלבד:
{
  "warnings": [
    {
      "severity": "error" | "warning" | "info",
      "title": "כותרת קצרה בעברית",
      "message": "הסבר ההתנגשות + הצעת פתרון",
      "related_fields": ["seo.audience", "ppc.audience"]
    }
  ]
}
severity: error = חייב לתקן · warning = מומלץ לבדוק · info = להעיר.
"""


def check_consistency(brief, db) -> list[dict]:
    """Returns a list of warning dicts. Empty list if all consistent or AI off."""
    if not current_app.config.get("AI_AVAILABLE"):
        return []

    sections_data = _load_all_sections(db, brief["id"])
    if not sections_data:
        return []

    user_msg = "להלן הבריף לבדיקת עקביות:\n\n" + json.dumps(
        sections_data, ensure_ascii=False, indent=2
    )

    client = _client()
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=[{
            "type": "text",
            "text": _CONSISTENCY_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = resp.content[0].text
    parsed = _parse_json_response(raw)
    warnings = parsed.get("warnings", []) if isinstance(parsed, dict) else []

    _log_call(db, brief["id"], "consistency", resp.usage)
    return warnings


# ───────────────────────────────────────────────────────────────────
# Layer 4 — Manager prompt routing (Sprint 3 dependency, defined but unused)
# ───────────────────────────────────────────────────────────────────


_MANAGER_PROMPT_SYSTEM = """אתה עוזר עריכה למנהל הסוכנות. המנהל יכתוב בעברית
חופשית מה הוא רוצה לשנות בבריף — אתה מחליט לאיזה סקשן ושדה זה הולך,
ומחזיר את הערך החדש.

החזר JSON בלבד:
{
  "dept": "about|seo|ppc",
  "field_id": "field_id_מהסכמה",
  "action": "append" | "replace",
  "new_value": "הטקסט החדש או המוסף"
}
"""


def manager_prompt(brief, db, prompt: str) -> dict | None:
    """Route a free-text manager edit to a specific field+action.

    NOT WIRED to UI yet — Sprint 3 (manager screen) will use this.
    """
    if not current_app.config.get("AI_AVAILABLE"):
        return None

    schema = load_template(brief["template_id"])
    sections_data = _load_all_sections(db, brief["id"])

    user_msg = (
        f"מבנה הסכמה (departments+fields): {json.dumps(schema, ensure_ascii=False)}\n\n"
        f"הבריף הנוכחי: {json.dumps(sections_data, ensure_ascii=False)}\n\n"
        f"בקשת המנהל: {prompt}"
    )

    client = _client()
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": _MANAGER_PROMPT_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    parsed = _parse_json_response(resp.content[0].text)
    _log_call(db, brief["id"], "manager_prompt", resp.usage)
    return parsed


# ───────────────────────────────────────────────────────────────────
# Layer 5 — Expert review (Claude call #3)
# ───────────────────────────────────────────────────────────────────


_EXPERT_REVIEW_SYSTEM = """אתה אסטרטג בכיר בסוכנות שיווק דיגיטלי ישראלית בעלת ניסיון של 15+ שנים.
עברת על אלפי בריפי לקוח ב-SEO ו-PPC. אתה מבין מצוין:
- איך נראה בריף בריא לעומת בריף שמכין את המנהל לקמפיין כושל
- איזה שדות אופציונליים הופכים לקריטיים בהקשר מסוים (B2B vs B2C, תקציב גבוה vs נמוך, שירות לוקאלי vs ארצי)
- מתי משתתף מילא ג'יבריש או טקסט-בדיקה (תוצאה: צריך למלא מחדש)
- מתי יש סתירה אסטרטגית בין הצהרות (יעד CPA נמוך + קהל פרימיום, או "ארצי" + "תקציב 1500₪")

המשימה: לקבל את כל הבריף (כולל שדות אופציונליים שלא מולאו) ולהציף בעיות אמיתיות.

זהה במיוחד את אלה — בסדר חשיבות:

1. **תוכן בלתי שמיש (severity: critical):**
   - ג'יבריש או אותיות אקראיות (לחדעכדגע, asdf, qwerty, 12345)
   - הקלדות בדיקה (test, בדיקה, אאא, שגגג)
   - מילה אחת בודדת בשדה textarea שמבקש פסקה (למשל "אנשים" כקהל יעד)
   - תאריכים/מספרים לא הגיוניים

2. **שדות אופציונליים שדילגו עליהם והם קריטיים בהקשר (severity: critical/warning):**
   - prior_seo='yes' אבל prior_seo_notes ריק → critical (חייבים להבין מה היה)
   - platforms כולל פלטפורמה אמיתית אבל existing_campaigns ריק → warning
   - budget גבוה (>5,000₪) ו-availability ריק → suggestion
   - competitors ריק לעסק שאינו בנישה ייחודית → warning
   - current_url ריק וגם current_url_notes ריק → critical (הסוכנות צריכה לדעת אם יש אתר)

3. **תוכן דליל (severity: warning):**
   - שדה textarea/list עם 1-3 מילים בלבד שלא מוסיפות ערך אמיתי
   - תיאור גנרי מאוד שלא מבדל את הלקוח

4. **סתירות אסטרטגיות (severity: critical/warning):**
   - יעדים מנוגדים, קהל יעד שלא מתאים לתקציב/פלטפורמה
   - אזור גאוגרפי שלא תואם את התקציב

5. **חוסר ספציפיות (severity: warning):**
   - "אנשים", "כולם", "מי שצריך", "המון" כקהל יעד
   - תקציב ללא מטבע

החזר JSON בלבד:
{
  "findings": [
    {
      "severity": "critical" | "warning" | "suggestion",
      "title": "כותרת קצרה (3-6 מילים)",
      "field_ref": "{dept}.{field_id}" או null אם זה כללי,
      "issue": "מה הבעיה — משפט אחד תכליתי",
      "suggestion": "מה כדאי לעשות — משפט אחד מעשי"
    }
  ]
}

אם הבריף מצוין ואין מה להעיר — החזר {"findings": []}.
חשוב: דבר אל הקוראת/הקורא ישירות בעברית, בטון מקצועי-חברי. בלי משפטים מליציים.
"""


def expert_review(brief, db) -> list[dict]:
    """Senior agency strategist scrutinizes the entire brief — including
    empty optional fields — and surfaces issues. Returns a list of finding dicts.
    Empty list if AI off or no issues."""
    if not current_app.config.get("AI_AVAILABLE"):
        return []

    template_id = brief["template_id"]
    tpl = load_template(template_id)
    departments = json.loads(brief["departments"])

    # Build a representation that includes EMPTY optional fields with their hints,
    # so the model can decide if they should have been filled given the context.
    brief_repr: dict = {}
    for dept in departments:
        dept_def = tpl["departments"].get(dept)
        if not dept_def:
            continue
        sec_row = db.execute(
            "SELECT data FROM sections WHERE brief_id = ? AND dept = ?",
            (brief["id"], dept),
        ).fetchone()
        sec_data = json.loads(sec_row["data"]) if sec_row and sec_row["data"] else {}

        fields_repr = []
        for f in dept_def["fields"]:
            value = sec_data.get(f["id"], "")
            fields_repr.append({
                "id": f["id"],
                "label": f["label_he"],
                "type": f["type"],
                "required": f.get("required", False),
                "hint": f.get("hint", ""),
                "value": value if value else None,
            })
        brief_repr[dept] = {
            "label": dept_def["label_he"],
            "fields": fields_repr,
        }

    user_msg = (
        f"לקוח: {brief['client_name']}\n\n"
        f"הבריף המלא (כולל שדות אופציונליים שלא מולאו — value=null):\n\n"
        f"{json.dumps(brief_repr, ensure_ascii=False, indent=2)}"
    )

    client = _client()
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=3072,
        system=[{
            "type": "text",
            "text": _EXPERT_REVIEW_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = resp.content[0].text
    parsed = _parse_json_response(raw)
    findings = parsed.get("findings", []) if isinstance(parsed, dict) else []

    _log_call(db, brief["id"], "expert_review", resp.usage)
    return findings
