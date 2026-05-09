"""HTTP Basic Auth gate for the demo deploy.

Activated only when ACCESS_PASSWORD is set in the environment. This is a coarse
front-door lock for the public Render URL during the pilot — not a per-user
auth system. It is intentionally simple.
"""
import secrets
from functools import wraps
from flask import request, Response, current_app


def _check(user: str, pw: str) -> bool:
    expected_user = current_app.config.get("ACCESS_USER", "selected")
    expected_pw = current_app.config.get("ACCESS_PASSWORD", "")
    if not expected_pw:
        return True  # auth disabled
    return (
        secrets.compare_digest(user, expected_user)
        and secrets.compare_digest(pw, expected_pw)
    )


def _challenge():
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Smart Brief"'},
    )


def init_basic_auth(app):
    """Register a before_request handler that enforces Basic Auth when ACCESS_PASSWORD is set."""

    @app.before_request
    def require_basic_auth():
        # /healthz must always be reachable — Render uses it for health checks
        if request.path == "/healthz":
            return None
        if not app.config.get("ACCESS_PASSWORD"):
            return None  # auth disabled — allow through (local dev)
        # Always allow static files (CSS) so the login challenge page styles work
        if request.path.startswith("/static/"):
            return None
        auth = request.authorization
        if auth is None or not _check(auth.username or "", auth.password or ""):
            return _challenge()
        return None
