"""Email sending via Resend. Graceful — no key/recipient = no-op.

Free tier: 3,000 emails/month, 100/day. Sender defaults to
onboarding@resend.dev (Resend's test address that works without DNS setup).
"""
import requests
from flask import current_app, render_template


RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_manager_link(brief, link_url: str) -> tuple[bool, str | None]:
    """Send the approval-link email to MANAGER_EMAIL.

    Returns (sent, error_message). sent=False is not necessarily an error —
    it can mean the feature is intentionally disabled (no key set).
    """
    api_key = current_app.config.get("RESEND_API_KEY", "")
    manager_email = current_app.config.get("MANAGER_EMAIL", "")
    if not api_key:
        current_app.logger.info("Email skipped: RESEND_API_KEY not set")
        return False, None
    if not manager_email:
        current_app.logger.info("Email skipped: MANAGER_EMAIL not set")
        return False, None

    sender = current_app.config.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    html = render_template(
        "email_manager_link.html",
        client_name=brief["client_name"],
        link=link_url,
    )
    text_fallback = (
        f"בריף חדש לאישור — {brief['client_name']}.\n"
        f"לפתיחה: {link_url}"
    )

    try:
        resp = requests.post(
            RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"Smart Brief · Selected <{sender}>",
                "to": [manager_email],
                "subject": f"בריף חדש לאישור — {brief['client_name']}",
                "html": html,
                "text": text_fallback,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        current_app.logger.exception("Resend request failed")
        return False, str(e)

    if resp.status_code >= 400:
        current_app.logger.warning("Resend returned %s: %s", resp.status_code, resp.text[:200])
        return False, f"Resend HTTP {resp.status_code}: {resp.text[:200]}"

    return True, None
