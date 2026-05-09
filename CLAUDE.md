# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Smart Brief** — internal Hebrew-RTL web app for Selected Digital Marketing Agency. Replaces a paper-based client onboarding (printed PPTX → handwritten notes → manual typing → managerial approval → PDF) with a digital flow that runs in under 10 minutes.

**Deployed:** `https://selected-smart-brief.onrender.com` (Basic Auth gated; password lives in Render env)
**GitHub:** `https://github.com/selectedsem-stack/selected-smart-brief` (private)
**Spec:** [אפיון-smart-brief.md](./אפיון-smart-brief.md) · **Project summary:** [PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md)

Sprints 1–4 done and deployed. Sprint 5 (custom domain + custom email sender) is gated by DNS work and is optional polish.

---

## Common commands

```powershell
# Setup (Windows / PowerShell)
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run dev server (http://localhost:5000)
python run.py

# Render the brief output template against full sample data and open in browser
python dev_preview.py
# → writes data/preview-local.html and launches default browser

# Inspect SQLite (manager tokens, statuses, AI logs)
python -c "import sqlite3; c=sqlite3.connect('data/briefs.db'); c.row_factory=sqlite3.Row; [print(dict(r)) for r in c.execute('SELECT id, client_name, status, manager_token FROM briefs ORDER BY created_at DESC LIMIT 5')]"
```

DB migrations run automatically on `init_db()` (idempotent — safe to redeploy). To add a new migration, append to `_MIGRATIONS` in `app/db.py` with a `(table, column, ALTER SQL)` tuple.

`build_brief.py` is the legacy hardcoded reference output; the live renderer is `brief_renderer.py` driven by `brief_templates/seo-ppc-brief/output.html.j2`.

---

## Architecture — flow

The app has **two audiences and three URL spaces**:

| URL space | Audience | Auth |
|---|---|---|
| `/` `/new` `/b/<id>` `/b/<id>/pick` `/b/<id>/<dept>` | Operator + participants (in-meeting) | Basic Auth (demo gate) |
| `/m/<token>/...` | Manager (remote) | Token in URL is the auth — Basic Auth bypassed |
| `/healthz` | Render health check | Always open |

**Brief status lifecycle:**

```
draft → reviewed → ready_for_manager → final
        (AI ran)   (operator accepted)   (manager finalized)
```

There's also a fallback path for when AI is unavailable: `draft → submitted → final` (operator opens the manager link manually and finalizes).

**Where each route lives:**
- [app/routes/public.py](./app/routes/public.py) — operator + participant routes (dashboard, picker, form, submit, review, accept)
- [app/routes/manager.py](./app/routes/manager.py) — manager routes (`/m/<token>/{view,edit,prompt,finalize,preview}`)
- Auth bypass for `/m/*` paths is in [app/auth.py](./app/auth.py:36).

---

## Architecture — data

**SQLite schema (3 tables):**

- `briefs` — id (UUID), client_name, template_id, departments (JSON array), status, manager_token (separate UUID for /m/ auth), timestamps, `consistency_warnings` (JSON), `manager_email_sent_at`, `ai_status`
- `sections` — `(brief_id, dept)` PK; stores `data` (original JSON) and `data_polished` (Claude-edited JSON) — manager edits **overwrite `data_polished`**, never `data`. The renderer overlays polished onto data per-field.
- `ai_log` — append-only log of every Claude call: action, tokens in/out, timestamp.

**Field schemas** are NOT in the DB — they live in `brief_templates/<template_id>/fields.json`. To add a brief type (e.g., a "web design" brief), drop a new folder with its own `fields.json` + `output.html.j2`. No code changes needed; the system walks departments dynamically.

---

## Architecture — services

Four services in `app/services/` — each is **graceful by design** (returns a neutral value, doesn't raise, when its dependency is missing):

| Service | Role | Graceful fallback |
|---|---|---|
| [validator.py](./app/services/validator.py) | Claude AI: validate / polish / consistency / manager_prompt | Returns `None`/`[]` if `ANTHROPIC_API_KEY` empty |
| [brief_renderer.py](./app/services/brief_renderer.py) | DB → 8-page HTML via Jinja2 (overlays `data_polished` on top of `data`) | Always works (no external deps at render time) |
| [mailer.py](./app/services/mailer.py) | Resend API: send manager-link email | Returns `(False, None)` if `RESEND_API_KEY` or `MANAGER_EMAIL` empty |
| [qr.py](./app/services/qr.py) | Generate QR code as `data:image/png;base64,...` | n/a |

**Design rule:** when a feature degrades, the user sees an explicit flash message explaining what happened and how to proceed manually. Never silently swallow.

---

## Key design decisions

- **HTML output, not PPTX.** RTL Hebrew in Jinja2/CSS is reliable; python-pptx RTL was not. Manager opens HTML → Ctrl+P → PDF. Print colors preserved with `print-color-adjust: exact !important` (line ~63 of `output.html.j2`).
- **Two separate UUIDs per brief.** `briefs.id` for operators (URL: `/b/<id>`), `briefs.manager_token` for managers (URL: `/m/<token>`). The manager token is the auth — bypasses Basic Auth — so the email link works without a password.
- **`data_polished` overlays `data`.** The renderer merges them per-field with polished overriding original. This is why `manager_edit` writes to `data_polished` (preserves original input).
- **Single-call Claude per layer.** Polish sends the entire brief in one Claude call (returns JSON of polished fields); consistency sends the brief in another single call (returns warnings). Keeps total latency under 15s and works inside Render's 60s gunicorn timeout.
- **Prompt caching on system prompts.** All four `validator.py` functions use `cache_control: {"type": "ephemeral"}` on the system prompt → ~80% cost reduction on follow-up calls within 5 min.
- **No participant tracking.** `participant_meta` was removed from `fields.json` — the team contact (name + phone) lives in the `about` section. Other sections don't ask "who are you" because it adds friction without value.
- **Picker switches to a celebration screen** when `brief.status >= submitted`. The picker isn't just a section selector — it's the participant's natural home, so it shows them the right state for whatever phase the brief is in.

---

## Pending — what's needed to reach 100%

These are env vars on Render (and locally in `.env`); the code is already wired:

| Variable | Purpose | Status |
|---|---|---|
| `ANTHROPIC_API_KEY` | Activates polish + consistency + manager prompt | **Pending** — Mor's $20 top-up |
| `RESEND_API_KEY` | Activates auto-emails to manager | User has the key (not yet set on Render) |
| `MANAGER_EMAIL` | Recipient address for approval emails | Will be `mor@selected.co.il` once tested |
| `RESEND_FROM_EMAIL` | Sender — defaults to `onboarding@resend.dev`; later `brief@selected.co.il` | Default works for pilot |
| `BASE_URL` | Used in QR codes and email links | Already set on Render |
| `ACCESS_PASSWORD` | Demo gate password | Already set on Render |

The app handles every combination of these missing/present gracefully — the dashboard banner explains what's active.

**Hosting decision (out of scope for code — env-level):** stay on Render Free (sleeps after 15 min), upgrade to Render Starter ($7/m), or migrate to Selected's own server ($0 extra, IT setup needed). The user has not committed yet.

---

## Branding

Selected logos live in **two locations** for two purposes:
- `assets/logos/` — used by `brief_renderer.py` to base64-embed in the brief output HTML
- `app/static/logos/` — served by Flask for the in-app header (`base.html`) and any other UI references

Both folders are populated and committed. If updating brand assets, update both.

The HTML brief output uses the dark wordmark with `filter: brightness(0) invert(1)` to render white on dark. The web app header does the same.

---

## Related docs / artifacts

- [PRODUCT.md](./PRODUCT.md) — brand voice, audience, anti-references
- [אפיון-smart-brief.md](./אפיון-smart-brief.md) — full Hebrew product spec
- [PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md) — Hebrew presentation summary (for humans)
- [summary-presentation.html](./summary-presentation.html) — 11-slide HTML deck for showing Mor
- [smart-brief-presentation.html](./smart-brief-presentation.html) — original pitch deck (pre-build approval)
- [build_brief.py](./build_brief.py) — legacy hardcoded sample renderer; **don't edit** unless needed for visual reference

The `/skills/project-summary` skill (in user's `~/.claude/skills/`) was updated with the design rules learned here: strict RTL, leftward flow arrows, RTL nav with swapped buttons, copyright in every artifact, brand logos in 3 places minimum, Heebo font with full weight range, WCAG AA contrast on dark backgrounds.

---

## Deploying

```bash
# All deploys are auto-triggered by git push to main
git add .
git commit -m "..."
git push
# → Render auto-deploys within 3 min, watching the main branch
```

The Render config is in [render.yaml](./render.yaml) (Blueprint format). It defines the web service, build/start commands, region (Frankfurt — closest to IL), and which env vars are auto-generated vs. manually-set.

Health check: Render polls `/healthz` every 30s; that route bypasses Basic Auth (see `app/auth.py`).
