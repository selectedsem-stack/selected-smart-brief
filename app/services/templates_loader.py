import json
from pathlib import Path
from functools import lru_cache


def _templates_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "brief_templates"


@lru_cache(maxsize=8)
def load_template(template_id: str) -> dict:
    path = _templates_root() / template_id / "fields.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_department(template_id: str, dept: str) -> dict | None:
    tpl = load_template(template_id)
    return tpl.get("departments", {}).get(dept)


def list_department_keys(template_id: str) -> list[str]:
    tpl = load_template(template_id)
    return list(tpl.get("departments", {}).keys())
