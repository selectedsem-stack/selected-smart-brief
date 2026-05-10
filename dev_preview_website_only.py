"""Preview ONLY website-design + about (no SEO, no PPC)."""
import webbrowser
from pathlib import Path

from app.services.brief_renderer import _env_for_template, _asset_data_uri
from dev_preview import SAMPLE


def main() -> None:
    sample = {**SAMPLE, "departments": ["about", "website_design"]}

    env = _env_for_template("seo-ppc-brief")
    template = env.get_template("output.html.j2")
    html = template.render(
        data=sample,
        logo_src=_asset_data_uri("assets/logos/sel-darknb.png", "image/png"),
        full_src=_asset_data_uri("assets/logos/sel-full-black.png", "image/png"),
        icon_src=_asset_data_uri("assets/logos/sel-icon.png", "image/png"),
        show_print_button=True,
    )

    out = Path(__file__).resolve().parent / "data" / "preview-website-only.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    size_kb = out.stat().st_size // 1024
    print(f"Rendered: {out} ({size_kb} KB)")
    print(f"  Departments: {sample['departments']}")
    print(f"  Opening in browser...")
    webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
