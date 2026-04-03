"""
Authentication — session management, auth dependencies, and secure cookie handling.
"""

import secrets
import logging

from fastapi import Request, HTTPException

from config import COOKIE_SECURE, COOKIE_HTTPONLY, COOKIE_SAMESITE, COOKIE_MAX_AGE
from database import get_session_user_id, get_user, save_session, delete_session as db_delete_session

logger = logging.getLogger("ytcloner.auth")

# In-memory session cache (also persisted to DB for restart survival)
SESSIONS: dict[str, int] = {}

# Routes that don't require authentication
PUBLIC_PATHS = {"/login", "/docs", "/openapi.json", "/api/health"}


def check_auth(request: Request) -> dict | None:
    """Returns user dict or None. Checks cookie, header, and query param."""
    token = _extract_token(request)
    if not token:
        return None

    # Check in-memory cache first
    if token in SESSIONS:
        user = get_user(SESSIONS[token])
        if user and user.get("active"):
            return user
        # Stale cache entry
        SESSIONS.pop(token, None)

    # Fallback: check DB (survives restarts)
    user_id = get_session_user_id(token)
    if user_id:
        SESSIONS[token] = user_id  # re-populate cache
        user = get_user(user_id)
        if user and user.get("active"):
            return user

    return None


def create_session(user_id: int) -> str:
    """Create a new session and persist to DB."""
    token = secrets.token_hex(32)
    SESSIONS[token] = user_id
    save_session(token, user_id)
    logger.info(f"Session created for user_id={user_id}")
    return token


def destroy_session(token: str):
    """Remove session from cache and DB."""
    SESSIONS.pop(token, None)
    db_delete_session(token)


def set_session_cookie(response, token: str):
    """Set session cookie with secure flags."""
    response.set_cookie(
        key="session",
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=COOKIE_HTTPONLY,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )
    return response


def clear_session_cookie(response):
    """Clear session cookie."""
    response.delete_cookie(key="session", path="/")
    return response


def _extract_token(request: Request) -> str:
    """Extract session token from cookie, header, or query param."""
    # Cookie first
    token = request.cookies.get("session", "")
    # Authorization header
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    # X-Session header
    if not token:
        token = request.headers.get("x-session", "")
    # Query param (last resort, for SSE etc.)
    if not token:
        token = request.query_params.get("_token", "")
    return token


def get_session_token(request: Request) -> str:
    """Get the session token for the current request (for CSRF etc.)."""
    return _extract_token(request)


# ── FastAPI Dependencies ─────────────────────────────────

def optional_auth(request: Request) -> dict | None:
    """Returns user dict or None."""
    return check_auth(request)


def require_auth(request: Request) -> dict:
    """Returns user dict or raises 401."""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def require_admin(request: Request) -> dict:
    """Returns admin user or raises 403."""
    user = require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return user
