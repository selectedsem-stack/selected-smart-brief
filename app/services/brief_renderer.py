"""Render a Brief row from the DB into the 8-page HTML output."""
import base64
import json
from datetime import datetime
from pathlib import Path
from functools import lru_cache

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .templates_loader import load_template


PRIOR_SEO_LABELS = {
    "no": "לא",
    "yes": "כן",
    "partial": "חלקי",
    "": "—",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=8)
def _asset_data_uri(rel_path: str, mime: str) -> str:
    p = _project_root() / rel_path
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def _split_lines(text: str | None) -> list[str]:
    """Split a textarea/list value into clean non-empty lines."""
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _classify_platforms(platforms: list[str]) -> tuple[str, str]:
    """Group platform list into Google / Meta summary strings for the intro page."""
    google_parts: list[str] = []
    meta_parts: list[str] = []
    for p in platforms:
        low = p.lower()
        if "google" in low or "search" in low or "display" in low or "youtube" in low:
            cleaned = p.replace("Google", "").replace("google", "").strip(" -·")
            google_parts.append(cleaned or p)
        elif "facebook" in low or "instagram" in low or "meta" in low or "fb" in low or "ig" in low:
            cleaned = p.replace("Meta", "").replace("meta", "").strip(" -·")
            meta_parts.append(cleaned or p)
    google_summary = " + ".join(google_parts) if google_parts else ""
    meta_summary = " + ".join(meta_parts) if meta_parts else ""
    return google_summary, meta_summary


def _section_data(db, brief_id: str, dept: str) -> dict:
    """Load section data with polished fields overlaid on top of originals."""
    row = db.execute(
        "SELECT data, data_polished FROM sections WHERE brief_id = ? AND dept = ?",
        (brief_id, dept),
    ).fetchone()
    if not row:
        return {}
    base = json.loads(row["data"]) if row["data"] else {}
    polished_raw = row["data_polished"] if "data_polished" in row.keys() else None
    if polished_raw:
        polished = json.loads(polished_raw)
        base = {**base, **polished}  # polished overrides original per-field
    return base


def _build_data_dict(brief, db) -> dict:
    """Transform DB rows into the dict shape the Jinja2 template expects."""
    template_id = brief["template_id"]
    departments = json.loads(brief["departments"])

    today = datetime.now()
    client_name = brief["client_name"]
    # The cover splits the client name onto multiple lines if it has spaces
    client_lines = client_name.split() if client_name else [""]

    about = _section_data(db, brief["id"], "about")
    seo = _section_data(db, brief["id"], "seo") if "seo" in departments else {}
    ppc = _section_data(db, brief["id"], "ppc") if "ppc" in departments else {}

    # PPC platforms / audience derivation
    ppc_platforms = _split_lines(ppc.get("platforms", ""))
    google_summary, meta_summary = _classify_platforms(ppc_platforms)
    ppc_audience_lines = _split_lines(ppc.get("audience", ""))[:6]

    return {
        "client_name": client_name,
        "client_lines": client_lines,
        "date_he": today.strftime("%d/%m/%Y"),
        "year": today.strftime("%Y"),
        "departments": departments,
        "about": {
            "company_name": about.get("company_name", client_name),
            "contact_name": about.get("contact_name", ""),
            "contact_phone": about.get("contact_phone", ""),
            "contact_email": about.get("contact_email", ""),
            "services": about.get("services", ""),
            "about_lines": _split_lines(about.get("about", "")),
            "audience_lines": _split_lines(about.get("audience", "")),
            "differentiators": _split_lines(about.get("differentiators", "")),
            "current_url": about.get("current_url", ""),
            "current_url_notes": about.get("current_url_notes", ""),
            "competitors": about.get("competitors", ""),
        },
        "seo": {
            "keywords": _split_lines(seo.get("keywords", "")),
            "prior_seo_label": PRIOR_SEO_LABELS.get(seo.get("prior_seo", ""), "—"),
            "prior_seo_notes": seo.get("prior_seo_notes", ""),
            "content_topics": seo.get("content_topics", ""),
            "complementary_services": seo.get("complementary_services", ""),
            "assets_actions": seo.get("assets_actions", ""),
        },
        "ppc": {
            "goal": ppc.get("goal", ""),
            "budget": ppc.get("budget", ""),
            "platforms": ppc_platforms,
            "google_summary": google_summary,
            "meta_summary": meta_summary,
            "existing_campaigns": ppc.get("existing_campaigns", ""),
            "audience": ppc.get("audience", ""),
            "audience_lines": ppc_audience_lines,
            "key_messages": _split_lines(ppc.get("key_messages", "")),
            "geographic_area": ppc.get("geographic_area", ""),
            "availability": ppc.get("availability", ""),
            "additional_notes": _split_lines(ppc.get("additional_notes", "")),
        },
    }


@lru_cache(maxsize=1)
def _env_for_template(template_id: str) -> Environment:
    template_dir = _project_root() / "brief_templates" / template_id
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_brief_html(brief, db, *, show_print_button: bool = True) -> str:
    """Render the 8-page brief HTML for the given brief row."""
    template_id = brief["template_id"]
    data = _build_data_dict(brief, db)

    env = _env_for_template(template_id)
    template = env.get_template("output.html.j2")
    return template.render(
        data=data,
        logo_src=_asset_data_uri("assets/logos/sel-darknb.png", "image/png"),
        full_src=_asset_data_uri("assets/logos/sel-full-black.png", "image/png"),
        icon_src=_asset_data_uri("assets/logos/sel-icon.png", "image/png"),
        show_print_button=show_print_button,
    )
