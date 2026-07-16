"""
Coach authentication: single-user session-cookie auth.

Environment variables
---------------------
HITE_COACH_PASSWORD_HASH  – bcrypt hash of the coach password.
                            If unset, the dev fallback password "devcoach" is accepted
                            and a loud warning is logged at startup.
HITE_SESSION_SECRET        – secret key for signing session cookies.
                            Falls back to a random value (sessions won't survive restarts).
"""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer

log = logging.getLogger("hite.auth")

# ── Configuration helpers ──────────────────────────────────────────────

_DEV_PASSWORD = "devcoach"
_SESSION_COOKIE = "hite_session"
_SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


@lru_cache(maxsize=1)
def _session_secret() -> str:
    secret = os.environ.get("HITE_SESSION_SECRET", "")
    if not secret:
        secret = secrets.token_hex(32)
        log.warning("HITE_SESSION_SECRET not set – using random secret (sessions lost on restart)")
    return secret


@lru_cache(maxsize=1)
def _password_hash() -> bytes | None:
    """Return the stored bcrypt hash, or None for dev-mode fallback."""
    raw = os.environ.get("HITE_COACH_PASSWORD_HASH", "")
    if raw:
        return raw.encode()
    log.warning(
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  WARNING: HITE_COACH_PASSWORD_HASH is not set!             ║\n"
        "║  Accepting dev password 'devcoach' — NOT FOR PRODUCTION.   ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
    )
    return None


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret())


# ── Password verification ──────────────────────────────────────────────


def verify_password(plain: str) -> bool:
    """Check *plain* against the configured bcrypt hash (or dev fallback)."""
    stored = _password_hash()
    if stored is None:
        return plain == _DEV_PASSWORD
    return bcrypt.checkpw(plain.encode(), stored)


def hash_password(plain: str) -> str:
    """Return a bcrypt hash suitable for HITE_COACH_PASSWORD_HASH."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ── Session cookie helpers ─────────────────────────────────────────────


def create_session_cookie(response, username: str = "coach") -> None:
    """Set a signed session cookie on *response*."""
    token = _get_serializer().dumps({"u": username})
    response.set_cookie(
        _SESSION_COOKIE,
        token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        # secure=True in prod — but we can't know here; leave it to reverse proxy
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(_SESSION_COOKIE)


def get_current_coach(request: Request) -> str | None:
    """Return the coach username from the session cookie, or None."""
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _get_serializer().loads(token, max_age=_SESSION_MAX_AGE)
        return data.get("u")
    except Exception:
        return None


# ── FastAPI dependency ─────────────────────────────────────────────────


def require_coach(request: Request) -> str:
    """Dependency: raises 302 redirect to login if not authenticated."""
    coach = get_current_coach(request)
    if coach is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/coach/login"},
        )
    return coach


# ── Startup hook (call from main to warm caches & show warnings) ──────


def init_auth() -> None:
    """Call at startup to eagerly validate config and emit warnings."""
    _password_hash()
    _session_secret()


# ── CSRF helpers (new functions — do not modify above) ─────────────────

_CSRF_SALT = "hite-csrf-v1"
_CSRF_MAX_AGE = 60 * 60  # 1 hour


def generate_csrf_token() -> str:
    """Return a signed, time-limited CSRF token (stateless double-submit style).

    Embed in every admin POST form as a hidden field named ``csrf_token``.
    Verify with :func:`verify_csrf_token` on POST handlers.
    """
    return _get_serializer().dumps({"t": "csrf"}, salt=_CSRF_SALT)


def verify_csrf_token(token: str) -> bool:
    """Return True if *token* is a valid, unexpired CSRF token."""
    if not token:
        return False
    try:
        data = _get_serializer().loads(token, salt=_CSRF_SALT, max_age=_CSRF_MAX_AGE)
        return data.get("t") == "csrf"
    except Exception:
        return False
