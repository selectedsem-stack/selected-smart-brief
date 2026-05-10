"""Render the brief output template against full sample data, open in browser.

Usage:
    python dev_preview.py

What it does:
    Renders brief_templates/seo-ppc-brief/output.html.j2 with a fully-populated
    sample (מדגה עין המפרץ), writes to data/preview-local.html, opens browser.

When to use:
    Iterate on the brief design without running the Flask server or filling
    out forms in the UI. Edit the template → run this → refresh browser.

Live alternative:
    `python run.py` + http://localhost:5000/b/<id>/preview also works (Jinja2
    auto-reloads on template changes), but requires having a brief in the DB.
"""
import webbrowser
from pathlib import Path

from app.services.brief_renderer import _env_for_template, _asset_data_uri


SAMPLE = {
    "client_name": "מדגה עין המפרץ",
    "client_lines": ["מדגה", "עין המפרץ"],
    "date_he": "09/05/2026",
    "year": "2026",
    "departments": ["about", "seo", "ppc", "website_design"],
    "about": {
        "company_name": "מדגה עין המפרץ",
        "contact_name": "חיים",
        "contact_phone": "052-3967330",
        "contact_email": "haim@ein.co.il",
        "services": "שיווק ומכירת דגים טריים וקפואים, מטבלים ויין",
        "about_lines": ["גידול ושיווק דגים", "36+ שנות ניסיון", "עין המפרץ"],
        "audience_lines": ["נשים וגברים", "גילאי 25+", 'אזור ת"א, חיפה, בית אלפא'],
        "differentiators": [
            "מגדלים את הדגים בעצמם",
            "מתמחים בדגי ים מלוחים: דניס, מושט, סלמון",
            "מחירים אטרקטיביים — נטו מהמגדל",
            "חקלאות ישראלית מקומית",
        ],
        "current_url": "Denis-iaraeli.co.il",
        "current_url_notes": "חיים יחזיר תשובה לגבי דומיין חדש",
        "competitors": "קיבוץ דן · פורל המתגלגל · דגת הארץ · מאסטר פוד",
    },
    "seo": {
        "keywords": [
            "דגים טריים",
            "דגים קפואים",
            "דגים טחונים",
            'וריאציות לוקאליות (עין המפרץ, ת"א, חיפה)',
        ],
        "prior_seo_label": "לא",
        "prior_seo_notes": "הלקוח צריך לעדכן לגבי הדומיין הקיים או חדש",
        "content_topics": (
            "דגים טריים, קפואים וטחונים; ממרחים ויין; "
            "מידע על המדגה וחקלאות ישראלית מקומית"
        ),
        "complementary_services": (
            "ממרחים, שמנים, יין וכו' — מוצרים נלווים שיקבלו חשיפה דיגיטלית בצד הדגים"
        ),
        "assets_actions": (
            "Selected תקים את כלל הנכסים: Google Business Profile, Search Console, Analytics. "
            "לאחר מכן יתחיל מחקר הביטויים ובניית אסטרטגיית תוכן."
        ),
    },
    "ppc": {
        "goal": "הגדלת מכירות אונליין",
        "budget": "6,000 ₪ לחודש",
        "platforms": ["Google Search", "Google Display", "Facebook", "Instagram"],
        "google_summary": "Search + Display",
        "meta_summary": "Facebook + Instagram",
        "existing_campaigns": "גוגל — לא\nפייסבוק — מעט\nגישה: עמרי שניידר 054-7472411",
        "audience": (
            'מתעניינים ברכישת דגים אונליין — ת"א, חיפה, בית אלפא (7 ק"מ)'
        ),
        "audience_lines": [
            "נשים וגברים גילאי 25+",
            'אזור ת"א ואזור חיפה',
            'בית אלפא — רדיוס 7 ק"מ',
            "מתעניינים ברכישת דגים אונליין",
            "מחירים אטרקטיביים כמסר מרכזי",
            "זמינות: א'–ו' (משלוח ג'–ה')",
        ],
        "key_messages": [
            "מחירים אטרקטיביים",
            "דגים טריים ישר מהמדגה",
            "כלל המוצרים באתר",
        ],
        "geographic_area": 'ת"א + חיפה\nבית אלפא — 7 ק"מ רדיוס',
        "availability": "כל ימות השבוע\nמשלוחים: ג', ד', ה' בלבד",
        "additional_notes": [
            "תקציב: 6,000 ₪ חודשי לכל פלטפורמה (200 ₪ יומי)",
            "דומיין — חיים יעדכן אם מעדיף דומיין קיים או שנציע אפשרויות חדשות",
            "הטבת משלוח חינם לרכישות מעל סכום — לעדכן לפני השקת הקמפיין",
            "Selected תספק 2-3 קונספטים לסרטונים לאישור הלקוח לפני צילום",
        ],
    },
    "website_design": {
        "project_type": "store",
        "project_type_label": "חנות אונליין",
        "branding_kit": (
            "קיים לוגו וקטור (פורמטים: AI, SVG, PNG). צבעוניות מותג: כחול עמוק "
            "#0a3d62 + נחושת חמה #c98856. פונט ראשי: Heebo (כל המשקלים)."
        ),
        "site_impression": (
            "מודרני, נקי, עם נגיעה כפרית-אותנטית. דגש על תמונות ענק של דגים טריים, "
            "תחושת חוף ים מלאה אור. רושם: מקצועי, ביתי, מזמין למשפחה."
        ),
        "liked_websites": [
            "https://farmers.org.il",
            "https://thymeandtable.co.uk",
            "https://stripe.com",
            "https://linear.app",
        ],
        "materials_ready": (
            "תמונות מקצועיות של 28 דגים (זמינים). טקסטי תיאור — חיים יכין החודש. "
            "וידאו: צילום עין המפרץ קיים (4K, 6 דקות). דמואים: לא נדרש."
        ),
        "navigation": (
            "תפריט ראשי: דף הבית · המוצרים שלנו (drop-down: דגים טריים / קפואים / "
            "ממרחים / יין) · המדגה · בלוג · צרו קשר. תפריט עליון fixed עם לוגו "
            "בצד שמאל ו-CTA כתום 'הזמן עכשיו' מימין. תפריט תחתון: מדיניות + שירות."
        ),
        "homepage_layout": (
            "Hero (וידאו ברקע + כותרת 'דגים ישר מהמדגה' + 2 CTAs) ← 3 קטגוריות "
            "מובילות (דגים טריים / קפואים / ממרחים) ← סרטון על המדגה (60 שניות) ← "
            "המלצות לקוחות ← הטבת משלוח חינם ← טופס הצטרפות לדיוור ← פוטר."
        ),
        "additional_notes": (
            "אינטגרציה עם מערכת הזמנות קיימת. שילוב WhatsApp Click-to-Chat "
            "בכל עמוד מוצר. סליקה: מימון ישיר. שילוב Google Maps לעין המפרץ."
        ),
    },
}


def main() -> None:
    env = _env_for_template("seo-ppc-brief")
    template = env.get_template("output.html.j2")
    html = template.render(
        data=SAMPLE,
        logo_src=_asset_data_uri("assets/logos/sel-darknb.png", "image/png"),
        full_src=_asset_data_uri("assets/logos/sel-full-black.png", "image/png"),
        icon_src=_asset_data_uri("assets/logos/sel-icon.png", "image/png"),
        show_print_button=True,
    )

    out = Path(__file__).resolve().parent / "data" / "preview-local.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    size_kb = out.stat().st_size // 1024
    print(f"✓ Rendered: {out} ({size_kb} KB)")
    print(f"  Opening in browser…")
    webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
