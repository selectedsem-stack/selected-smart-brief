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
    brief_public_url = f"{base_url}{url_for('public.brief_dashboard', brief_id=brief_id)}"

    return render_template(
        "brief_dashboard.html",
        brief=brief,
        sections_status=sections_status,
        all_filled=all_filled,
        missing_count=missing_count,
        qr_uri=qr_data_uri(brief_public_url),
        share_url=brief_public_url,
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
    brief = _get_brief(brief_id)
    departments = json.loads(brief["departments"])
    db = get_db()

    # Confirm all sections have data
    for dept in departments:
        sec = db.execute(
            "SELECT data FROM sections WHERE brief_id = ? AND dept = ?",
            (brief_id, dept),
        ).fetchone()
        if not sec or sec["data"] in ("{}", "", None):
            flash("לא ניתן לשלוח — יש סקשנים שלא מולאו", "error")
            return redirect(url_for("public.brief_dashboard", brief_id=brief_id))

    # Sprint 4 will replace this placeholder with: AI validate → polish → consistency → email manager.
    db.execute(
        "UPDATE briefs SET status = 'submitted', submitted_at = ? WHERE id = ?",
        (_now_iso(), brief_id),
    )
    db.commit()
    flash("הבריף נשלח לאישור (Sprint 4 בפיתוח — וולידציית AI ואימייל למנהל יחוברו בקרוב)", "success")
    return redirect(url_for("public.brief_dashboard", brief_id=brief_id))


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

    if request.method == "POST":
        data = {}
        for field in dept_def["fields"]:
            fid = field["id"]
            val = request.form.get(fid, "").strip()
            data[fid] = val

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
        return redirect(url_for("public.brief_dashboard", brief_id=brief_id))

    return render_template(
        "participant.html",
        brief=brief,
        dept=dept,
        dept_def=dept_def,
        data=existing_data,
    )


@bp.app_errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="הדף לא נמצא"), 404
