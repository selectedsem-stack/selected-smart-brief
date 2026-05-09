# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Smart Brief** — internal web system for Selected Digital Marketing Agency. Replaces a paper-based client onboarding process (printed PPTX + handwritten notes → typed manually → passed between colleagues → manager approves → PDF via WhatsApp) with a digital workflow that goes from meeting end to PDF in under 10 minutes.

Full spec: `אפיון-smart-brief.md`

---

## Current State

**Design/prototype phase — no application code yet.** What exists:

| File | What it is |
|------|-----------|
| `build_brief.py` | Python script that generates `brief-sample.html` — the reference design for what the output document looks like |
| `brief-sample.html` | Generated output — 8-page A4-landscape HTML brief for client מדגה עין המפרץ (real sample data) |
| `smart-brief-presentation.html` | 6-slide HTML pitch deck for manager approval of the project |
| `אפיון-smart-brief.md` | Full product spec in Hebrew |

### Regenerating the sample brief

```bash
python build_brief.py
# Output: brief-sample.html (~1.2MB, self-contained)
```

Requires `.pptx-extract/` (team photo asset). If it's missing:

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory(
  "C:\Users\SEMSELECTED\Desktop\טמפלייטים ומדריכים\טמפלייט סיכום בריף.pptx",
  ".pptx-extract"
)
```

Then run `python build_brief.py` again.

---

## Logo Assets

All official Selected logos are at `Q:\selected logo\`. Key files:

| Variable in `build_brief.py` | File | Use |
|---|---|---|
| `darknb_src` | `לוגו-חדש\sel-darknb.png` | Dark wordmark, transparent bg — for orange/light surfaces (apply CSS `filter: brightness(0) invert(1)` to get white version on dark surfaces) |
| `full_src` | `SELECTED LOGO\0 FINAL MATERIALS\LOGO-2020-SELECTED-BLACK.png` | Full logo with "Digital Marketing Agency" — for white/light footers |
| `icon_src` | `2020 BRAND\LOGO VECTOR\LOGO 2020 SELECTED-01.png` | Round S icon — decorative watermark use |

**Logo placement rule in the brief:**
- Dark header bars → `darknb_src` + `filter: brightness(0) invert(1)` = white logo
- Orange panels (cover, intro pages) → `darknb_src` + `filter: brightness(0) invert(1)` = white logo  
- White footers → `full_src`, no filter

---

## Output Document Design

The brief is a self-contained HTML file with all assets base64-embedded. Pages are A4 landscape (297mm × 210mm). Print to PDF via browser Ctrl+P.

**Page structure (8 pages):**
1. Cover — split panel: team photo left, orange panel right with client name
2. About client — contact row + 3-column info card grid
3. SEO Intro — full-bleed split: orange brand panel + dark facts panel
4. SEO Fields — 2-column card grid
5. SEO Process — 2-column numbered steps grid
6. PPC Intro — full-bleed split: same structure as SEO Intro
7. PPC Fields — 3-column card grid + dark notes box
8. PPC Process — 2-column numbered steps grid

**CSS design tokens:**
- `--orange: #E06820` / `--dark: #141414`
- Font: Heebo (Google Fonts), weights 300/400/500/700/900
- Spacing: mm units throughout (for print accuracy)

---

## Planned Application Stack

```
smart_brief/
  app.py              ← Flask entry point
  brief_manager.py    ← SQLite session management
  validator.py        ← Claude API: validate + polish text
  sender.py           ← Email to manager
  templates/          ← Jinja2 HTML (form, manager review)

templates/
  seo-ppc-brief/
    fields.json       ← Field definitions per department
  web-brief/          ← Phase 2

data/briefs.db        ← SQLite
.env                  ← ANTHROPIC_API_KEY, SMTP_USER, SMTP_PASS, MANAGER_EMAIL, SECRET_KEY
```

**`fields.json` schema:**
```json
{
  "section": "ppc",
  "fields": [
    { "id": "ppc_budget", "label_he": "תקציב לכל פלטפורמה", "required": true, "type": "text" }
  ]
}
```

Adding a new brief type = new folder + `fields.json`. No code changes.

---

## Key Design Decisions

- **HTML output, not PPTX** — RTL Hebrew in CSS is reliable; python-pptx RTL is not. Manager opens HTML in browser → Ctrl+P → PDF.
- **Claude does 3 things:** (1) validate required fields, (2) polish informal Hebrew text to professional copywriting standard, (3) check cross-section consistency (e.g., audience described in SEO matches PPC targeting).
- **Manager has two edit modes:** direct field editing OR Claude prompt ("add to the SEO section that the client has never done SEO before") → Claude writes to the correct field.
- **Phone numbers stored from day one** — not needed in Phase 1, but collected now for the Phase 2 WhatsApp API integration.
- **No user auth in Phase 1** — session URL is the access mechanism. Manager link is a separate long-lived UUID.

---

## Phase 2 (out of scope now)

- WhatsApp API: auto-create group with meeting participants + send PDF
- Web/UX design brief template (different field set)
- Client credential retrieval via WhatsApp agent
