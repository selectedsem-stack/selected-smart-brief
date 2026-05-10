import json
import uuid
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    abort, current_app, flash, jsonify
)

from ..db import get_db
from ..services.qr import qr_data_uri
from ..services.templates_loader import load_template, get_department, list_department_keys
from ..services.brief_renderer import render_brief_html
from ..services import validator
from ..services import mailer


bp = Blueprint("public", __name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_brief(brief_id: str):
    row = get_db().execute(
        "SELECT * FROM briefs WHERE id = ?", (brief_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _get_section(brief_id: str, dept: str):
    return get_db().execute(
        "SELECT * FROM sections WHERE brief_id = ? AND dept = ?",
        (brief_id, dept),
    ).fetchone()


@bp.route("/")
def home():
    return render_template("home.html")


@bp.route("/healthz")
def healthz():
    """Health check endpoint — bypasses Basic Auth so Render can ping it."""
    return "ok", 200, {"Content-Type": "text/plain"}


@bp.route("/new", methods=["GET", "POST"])
def new_brief():
    template_id = current_app.config["DEFAULT_TEMPLATE"]
    tpl = load_template(template_id)

    if request.method == "POST":
        client_name = (request.form.get("client_name") or "").strip()
        if not client_name:
            flash("חסר שם לקוח", "error")
            return redirect(url_for("public.new_brief"))

        # "about" is always selected. Other departments come from form.
        chosen = ["about"]
        for dept in tpl["departments"]:
            if dept == "about":
                continue
            if request.form.get(f"dept_{dept}"):
                chosen.append(dept)

        brief_id = uuid.uuid4().hex
        manager_token = uuid.uuid4().hex
        now = _now_iso()

        db = get_db()
        db.execute(
            """INSERT INTO briefs (id, client_name, template_id, departments,
                 status, created_at, manager_token)
               VALUES (?,?,?,?,?,?,?)""",
            (brief_id, client_name, template_id, json.dumps(chosen),
             "draft", now, manager_token),
        )
        for dept in chosen:
            db.execute(
                "INSERT INTO sections (brief_id, dept, data) VALUES (?,?,?)",
                (brief_id, dept, "{}"),
            )
        db.commit()

        return redirect(url_for("public.brief_dashboard", brief_id=brief_id))

    # GET
    return render_template(
        "new_brief.html",
        template=tpl,
        non_about_depts=[(k, v) for k, v in tpl["departments"].items() if k != "about"],
    )


@bp.route("/b/<brief_id>")
def brief_dashboard(brief_id):
    brief = _get_brief(brief_id)
    template_id = brief["template_id"]
    tpl = load_template(template_id)
    departments = json.loads(brief["departments"])

    sections_status = []
    db = get_db()
    for dept in departments:
        sec = db.execute(
            "SELECT * FROM sections WHERE brief_id = ? AND dept = ?",
            (brief_id, dept),
        ).fetchone()
        sections_status.append({
            "dept": dept,
            "label_he": tpl["departments"][dept]["label_he"],
            "filled_by": sec["filled_by_name"] if sec else None,
            "filled_at": sec["filled_at"] if sec else None,
            "has_data": bool(sec and sec["data"] not in ("{}", "", None)),
        })

    all_filled = all(s["has_data"] for s in sections_status)
    missing_count = sum(1 for s in sections_status if not s["has_data"])

    base_url = current_app.config["BASE_URL"].rstrip("/")
    # QR points to the participant picker — operators land here on the dashboard
    # via direct URL, but team members scanning a phone get a clean "who are you?"
    # screen instead of all this dashboard chrome.
    brief_public_url = f"{base_url}{url_for('public.brief_picker', brief_id=brief_id)}"
    manager_link = f"{base_url}{url_for('manager.manager_view', token=brief['manager_token'])}"

    return render_template(
        "brief_dashboard.html",
        brief=brief,
        sections_status=sections_status,
        all_filled=all_filled,
        missing_count=missing_count,
        qr_uri=qr_data_uri(brief_public_url),
        share_url=brief_public_url,
        manager_link=manager_link,
    )


@bp.route("/b/<brief_id>/pick")
def brief_picker(brief_id):
    """Participant landing page — what the QR opens on a phone."""
    brief = _get_brief(brief_id)
    template_id = brief["template_id"]
    tpl = load_template(template_id)
    departments = json.loads(brief["departments"])

    db = get_db()
    sections_status = []
    for dept in departments:
        sec = db.execute(
            "SELECT * FROM sections WHERE brief_id = ? AND dept = ?",
            (brief_id, dept),
        ).fetchone()
        sections_status.append({
            "dept": dept,
            "label_he": tpl["departments"][dept]["label_he"],
            "has_data": bool(sec and sec["data"] not in ("{}", "", None)),
            "filled_at": sec["filled_at"] if sec else None,
        })

    completed = sum(1 for s in sections_status if s["has_data"])
    total = len(sections_status)
    progress_pct = int(round(completed / total * 100)) if total else 0

    return render_template(
        "pick.html",
        brief=brief,
        sections_status=sections_status,
        completed=completed,
        total=total,
        progress_pct=progress_pct,
    )


@bp.route("/b/<brief_id>/preview")
def brief_preview(brief_id):
    """Render the 8-page brief HTML for download/preview."""
    brief = _get_brief(brief_id)
    db = get_db()
    html = render_brief_html(brief, db, show_print_button=True)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/b/<brief_id>/submit", methods=["POST"])
def submit_for_approval(brief_id):
    """Save and mark the brief as submitted. No Claude calls in the live path —
    sync AI was timing out gunicorn (60s) during live meetings. Re-enable later
    via CLAUDE_ENABLED + an async worker."""
    brief = _get_brief(brief_id)
    db = get_db()

    missing = validator.validate_required(brief, db)
    if missing:
        labels = " · ".join(m["label_he"] for m in missing[:5])
        more = f" (ועוד {len(missing) - 5})" if len(missing) > 5 else ""
        flash(f"חסרים שדות חובה: {labels}{more}", "error")
        return redirect(url_for("public.brief_dashboard", brief_id=brief_id))

    db.execute(
        "UPDATE briefs SET status = 'submitted', submitted_at = ? WHERE id = ?",
        (_now_iso(), brief_id),
    )
    db.commit()

    if current_app.config.get("CLAUDE_ENABLED") and current_app.config.get("AI_AVAILABLE"):
        # Future hook: run polish + consistency + expert_review here only when
        # an async worker exists. Direct synchronous calls block gunicorn for
        # 15-30s and have caused production crashes — do NOT re-enable inline.
        current_app.logger.info("CLAUDE_ENABLED is true but inline AI is disabled until async path lands")

    flash("הבריף נשלח. שתף את הקישור למנהל מהדאשבורד.", "success")
    return redirect(url_for("public.brief_dashboard", brief_id=brief_id))


@bp.route("/b/<brief_id>/<dept>/autosave", methods=["POST"])
def autosave_section(brief_id, dept):
    """Partial save during typing. No required-field validation, no format
    validation, no status change. Merges submitted fields into sections.data.
    Accepts JSON body or sendBeacon form-encoded payload."""
    brief = _get_brief(brief_id)
    if dept not in json.loads(brief["departments"]):
        abort(404)

    payload = request.get_json(silent=True)
    if payload is None:
        # sendBeacon may arrive as form-encoded or text/plain blob — try raw body
        raw = request.get_data(as_text=True)
        try:
            payload = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            payload = {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad_payload"}), 400

    db = get_db()
    sec = _get_section(brief_id, dept)
    existing = json.loads(sec["data"]) if sec and sec["data"] else {}

    cleaned = {k: str(v).strip() for k, v in payload.items() if v is not None}
    merged = {**existing, **cleaned}

    db.execute(
        "UPDATE sections SET data = ?, filled_at = ? WHERE brief_id = ? AND dept = ?",
        (json.dumps(merged, ensure_ascii=False), _now_iso(), brief_id, dept),
    )
    db.commit()
    return jsonify({"ok": True, "saved_at": _now_iso()})


@bp.route("/b/<brief_id>/review")
def brief_review(brief_id):
    """Show AI polish diff + consistency warnings for operator approval."""
    brief = _get_brief(brief_id)
    db = get_db()
    tpl = load_template(brief["template_id"])
    departments = json.loads(brief["departments"])

    review_data = []
    for dept in departments:
        dept_def = tpl["departments"].get(dept)
        if not dept_def:
            continue
        sec = db.execute(
            "SELECT data, data_polished FROM sections WHERE brief_id = ? AND dept = ?",
            (brief_id, dept),
        ).fetchone()
        original = json.loads(sec["data"]) if sec and sec["data"] else {}
        polished = json.loads(sec["data_polished"]) if sec and sec["data_polished"] else {}
        review_data.append({
            "dept": dept,
            "label_he": dept_def["label_he"],
            "fields": dept_def["fields"],
            "original": original,
            "polished": polished,
        })

    warnings_raw = brief["consistency_warnings"] if "consistency_warnings" in brief.keys() else None
    warnings = json.loads(warnings_raw) if warnings_raw else []

    findings_raw = brief["expert_findings"] if "expert_findings" in brief.keys() else None
    findings = json.loads(findings_raw) if findings_raw else []

    return render_template(
        "review.html",
        brief=brief,
        review_data=review_data,
        warnings=warnings,
        findings=findings,
    )


@bp.route("/b/<brief_id>/accept", methods=["POST"])
def accept_review(brief_id):
    """Operator confirms the AI polish — brief becomes ready_for_manager
    and an email goes out to MANAGER_EMAIL with the manager-token link."""
    brief = _get_brief(brief_id)
    db = get_db()
    db.execute(
        "UPDATE briefs SET status = 'ready_for_manager' WHERE id = ?",
        (brief_id,),
    )
    db.commit()

    # Build the manager link (also shown on the dashboard as fallback)
    base_url = current_app.config["BASE_URL"].rstrip("/")
    manager_link = f"{base_url}{url_for('manager.manager_view', token=brief['manager_token'])}"

    sent, error = mailer.send_manager_link(brief, manager_link)
    if sent:
        db.execute(
            "UPDATE briefs SET manager_email_sent_at = ? WHERE id = ?",
            (_now_iso(), brief_id),
        )
        db.commit()
        flash("הבריף אושר ונשלח אימייל למנהל.", "success")
    elif error:
        flash(
            f"הבריף אושר. שליחת האימייל נכשלה ({error}) — שתף את הלינק ידנית מהדאשבורד.",
            "warning",
        )
    else:
        # Email intentionally disabled (no key/recipient yet)
        flash(
            "הבריף אושר. שליחת אימייל לא מוגדרת כרגע — שתף את הלינק ידנית מהדאשבורד.",
            "info",
        )
    return redirect(url_for("public.brief_dashboard", brief_id=brief_id))


import re as _re

_EMAIL_RE = _re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_URL_RE = _re.compile(r"^(https?://)?([\w\-]+\.)+[\w\-]{2,}(/[^\s]*)?$", _re.IGNORECASE)


def _is_valid_il_phone(value: str) -> bool:
    """Israeli phone — accepts 050-1234567, 0501234567, 03-1234567, +972501234567, etc."""
    digits = _re.sub(r"[\s\-\(\)]", "", value.strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        return False
    # Local: 0 + 8 digits (mobile, 05X) or 0 + 8 digits (landline, 02-04, 06-09)
    if digits.startswith("0") and len(digits) in (9, 10):
        return digits[1] in "234589" or digits[1:3] in ("50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "72", "73", "74", "76", "77", "78")
    # International with country code 972
    if digits.startswith("972") and len(digits) in (11, 12):
        rest = digits[3:]
        return rest[0] in "234589" or rest[0:2].startswith("5")
    return False


def _validate_field_format(field_type: str, value: str) -> str | None:
    """Return error message in Hebrew if value violates the type's format, else None."""
    if not value:
        return None
    v = value.strip()
    if field_type == "tel" and not _is_valid_il_phone(v):
        return "מספר טלפון לא תקין (דוגמה: 050-1234567 או 03-1234567)"
    if field_type == "email" and not _EMAIL_RE.match(v):
        return "כתובת אימייל לא תקינה"
    if field_type == "url" and not _URL_RE.match(v):
        return "כתובת אתר לא תקינה (דוגמה: example.co.il או https://example.co.il)"
    return None


def _form_back_url(brief_id: str, status: str) -> str:
    """During draft phase, back goes to picker (participants).
    Post-draft, back goes to dashboard (operators only)."""
    if status == "draft":
        return url_for("public.brief_picker", brief_id=brief_id)
    return url_for("public.brief_dashboard", brief_id=brief_id)


@bp.route("/b/<brief_id>/<dept>", methods=["GET", "POST"])
def participant_form(brief_id, dept):
    brief = _get_brief(brief_id)
    template_id = brief["template_id"]
    dept_def = get_department(template_id, dept)
    if dept_def is None:
        abort(404)

    departments = json.loads(brief["departments"])
    if dept not in departments:
        abort(404)

    tpl = load_template(template_id)
    section = _get_section(brief_id, dept)
    existing_data = json.loads(section["data"]) if section and section["data"] else {}
    back_url = _form_back_url(brief_id, brief["status"])

    if request.method == "POST":
        data = {}
        field_errors: dict[str, str] = {}
        for field in dept_def["fields"]:
            fid = field["id"]
            val = request.form.get(fid, "").strip()
            data[fid] = val
            err = _validate_field_format(field.get("type", "text"), val)
            if err:
                field_errors[fid] = err

        # Required field validation (server-side last line of defense)
        missing = [
            field["label_he"]
            for field in dept_def["fields"]
            if field.get("required") and not data.get(field["id"])
        ]
        if missing:
            flash("חסרים שדות חובה: " + ", ".join(missing), "error")
            return render_template(
                "participant.html",
                brief=brief,
                dept=dept,
                dept_def=dept_def,
                data=data,
                back_url=back_url,
                field_errors=field_errors,
            )
        if field_errors:
            flash("יש שדות עם פורמט לא תקין — תקן והמשך.", "error")
            return render_template(
                "participant.html",
                brief=brief,
                dept=dept,
                dept_def=dept_def,
                data=data,
                back_url=back_url,
                field_errors=field_errors,
            )

        # For the "about" section, derive filled_by from the client contact fields.
        # For other sections, leave them null — we don't track per-section filler.
        filled_by_name = data.get("contact_name", "") if dept == "about" else None
        filled_by_phone = data.get("contact_phone", "") if dept == "about" else None

        db = get_db()
        db.execute(
            """UPDATE sections
               SET data = ?, filled_by_name = ?, filled_by_phone = ?, filled_at = ?
               WHERE brief_id = ? AND dept = ?""",
            (json.dumps(data, ensure_ascii=False), filled_by_name,
             filled_by_phone, _now_iso(), brief_id, dept),
        )
        db.commit()
        flash("נשמר בהצלחה", "success")
        return redirect(back_url)

    return render_template(
        "participant.html",
        brief=brief,
        dept=dept,
        dept_def=dept_def,
        data=existing_data,
        back_url=back_url,
        field_errors={},
    )


@bp.app_errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="הדף לא נמצא"), 404
