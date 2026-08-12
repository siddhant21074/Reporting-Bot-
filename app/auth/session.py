"""Signed session cookies for the dashboard.

The cookie carries only the user id and an issue timestamp, signed with
``SECRET_KEY``. Role and scope are read from the database on every request, so
changing or deactivating an account takes effect immediately rather than when
the cookie happens to expire.
"""

import logging
import secrets
from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

logger = logging.getLogger("app.auth.session")

COOKIE_NAME = "reportbot_session"
_SALT = "reportbot-admin-session"

_fallback_secret: Optional[str] = None


def _get_secret() -> str:
    """Returns SECRET_KEY if set, otherwise generates a fallback secret in memory."""
    global _fallback_secret
    secret = settings.admin.secret_key
    if not secret:
        if _fallback_secret is None:
            _fallback_secret = secrets.token_urlsafe(48)
            logger.warning(
                "SECRET_KEY is not configured; using a temporary fallback secret for session cookies.",
                extra={"event": "session_fallback_secret_generated"},
            )
        return _fallback_secret
    return secret


def _serializer() -> URLSafeTimedSerializer:
    """Builds the signer from the configured or fallback secret."""
    return URLSafeTimedSerializer(_get_secret(), salt=_SALT)


def issue_session(user_id: int) -> str:
    """Returns a signed cookie value for a login."""
    return _serializer().dumps({"uid": user_id})


def read_session(token: Optional[str]) -> Optional[int]:
    """Validates a cookie and returns the user id it carries.

    Returns ``None`` for a missing, tampered or expired cookie.
    """
    if not token:
        return None

    try:
        data = _serializer().loads(token, max_age=settings.admin.session_max_age)
    except SignatureExpired:
        logger.info("Session cookie expired.", extra={"event": "session_expired"})
        return None
    except BadSignature:
        logger.warning("Session cookie failed signature check.", extra={"event": "session_bad_signature"})
        return None
    except RuntimeError:
        return None

    user_id = data.get("uid") if isinstance(data, dict) else None
    return int(user_id) if isinstance(user_id, int) else None


def cookie_params() -> dict:
    """Cookie attributes shared by login and logout.

    ``secure`` is on outside development because the dashboard is served over
    HTTPS in production; setting it locally would stop the cookie working on
    plain HTTP.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.app.environment not in ("development", "testing"),
        "path": "/",
    }
