"""Manager flow — token-protected screens for the brief approver.

The manager_token is a UUID created at brief-creation time and stored in
briefs.manager_token. Anyone with the token can act as the manager: edit
fields, send Claude prompts, and finalize. The token IS the auth — no
Basic Auth challenge for /m/* paths (see app/auth.py).
"""
import json
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    abort, jsonify, current_app, flash,
)

from ..db import get_db
from ..services.templates_loader import load_template
from ..services.brief_renderer import render_brief_html
from ..services import validator


bp = Blueprint("manager", __name__, url_prefix="/m")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_brief_by_token(token: str):
    row = get_db().execute(
        "SELECT * FROM briefs WHERE manager_token = ?",
        (token,),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _section(db, brief_id: str, dept: str):
    return db.execute(
        "SELECT data, data_polished FROM sections WHERE brief_id = ? AND dept = ?",
        (brief_id, dept),
    ).fetchone()


def _merged_values(sec) -> dict:
    """Original data with polished/edited fields overlaid on top."""
    if sec is None:
        return {}
    base = json.loads(sec["data"]) if sec["data"] else {}
    polished_raw = sec["data_polished"] if "data_polished" in sec.keys() else None
    if polished_raw:
        polished = json.loads(polished_raw)
        base = {**base, **polished}
    return base


@bp.route("/<token>")
def manager_view(token):
    brief = _get_brief_by_token(token)
    db = get_db()
    tpl = load_template(brief["template_id"])
    departments = json.loads(brief["departments"])

    sections_data = []
    for dept in departments:
        dept_def = tpl["departments"].get(dept)
        if not dept_def:
            continue
        sec = _section(db, brief["id"], dept)
        sections_data.append({
            "dept": dept,
            "label_he": dept_def["label_he"],
            "fields": dept_def["fields"],
            # Use a non-dict-method name — Jinja2 resolves `obj.values` as the
            # dict.values() bound method, not the dictionary key.
            "field_values": _merged_values(sec),
        })

    return render_template(
        "manager.html",
        brief=brief,
        sections_data=sections_data,
    )


@bp.route("/<token>/edit", methods=["POST"])
def manager_edit(token):
    """AJAX: persist a single-field edit into sections.data_polished."""
    brief = _get_brief_by_token(token)
    db = get_db()

    payload = request.get_json(force=True, silent=True) or {}
    dept = (payload.get("dept") or "").strip()
    field_id = (payload.get("field_id") or "").strip()
    value = payload.get("value", "")
    if not dept or not field_id:
        return jsonify({"ok": False, "error": "missing dept or field_id"}), 400

    sec = _section(db, brief["id"], dept)
    if sec is None:
        return jsonify({"ok": False, "error": "section not found"}), 404

    polished = json.loads(sec["data_polished"]) if sec["data_polished"] else {}
    polished[field_id] = value
    db.execute(
        "UPDATE sections SET data_polished = ? WHERE brief_id = ? AND dept = ?",
        (json.dumps(polished, ensure_ascii=False), brief["id"], dept),
    )
    db.commit()
    return jsonify({"ok": True})


@bp.route("/<token>/prompt", methods=["POST"])
def manager_claude_prompt(token):
    """AJAX: route a free-text Hebrew prompt through Claude → applied edit."""
    brief = _get_brief_by_token(token)
    db = get_db()

    payload = request.get_json(force=True, silent=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "empty"}), 400

    if not current_app.config.get("AI_AVAILABLE"):
        return jsonify({"error": "ai_unavailable",
                        "message": "Claude API לא מחובר. הוסף ANTHROPIC_API_KEY."}), 503

    try:
        suggestion = validator.manager_prompt(brief, db, prompt)
    except Exception as e:
        current_app.logger.exception("manager_prompt failed")
        return jsonify({"error": "claude_failed", "message": str(e)}), 502

    if not suggestion or "dept" not in suggestion or "field_id" not in suggestion:
        return jsonify({"error": "claude_failed",
                        "message": "Claude לא הצליח לזהות שדה רלוונטי"}), 502

    dept = suggestion["dept"]
    field_id = suggestion["field_id"]
    action = suggestion.get("action", "replace")
    new_value = suggestion.get("new_value", "")

    sec = _section(db, brief["id"], dept)
    if sec is None:
        return jsonify({"error": "claude_invalid_dept",
                        "message": f"Claude הפנה ל-{dept} שלא קיים בבריף"}), 502

    base = json.loads(sec["data"]) if sec["data"] else {}
    polished = json.loads(sec["data_polished"]) if sec["data_polished"] else {}
    if action == "append":
        existing = polished.get(field_id) or base.get(field_id, "")
        merged = (existing + "\n" + new_value).strip() if existing else new_value
    else:
        merged = new_value
    polished[field_id] = merged

    db.execute(
        "UPDATE sections SET data_polished = ? WHERE brief_id = ? AND dept = ?",
        (json.dumps(polished, ensure_ascii=False), brief["id"], dept),
    )
    db.commit()

    return jsonify({
        "applied": {
            "dept": dept,
            "field_id": field_id,
            "action": action,
            "new_value": merged,
        }
    })


@bp.route("/<token>/finalize", methods=["POST"])
def manager_finalize(token):
    brief = _get_brief_by_token(token)
    db = get_db()
    db.execute(
        "UPDATE briefs SET status = 'final', approved_at = ? WHERE id = ?",
        (_now_iso(), brief["id"]),
    )
    db.commit()
    return redirect(url_for("manager.manager_preview", token=token))


@bp.route("/<token>/preview")
def manager_preview(token):
    """Same render as /b/<id>/preview, but reachable via the manager token
    (so it works without the Basic Auth password)."""
    brief = _get_brief_by_token(token)
    db = get_db()
    html = render_brief_html(brief, db, show_print_button=True)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}
