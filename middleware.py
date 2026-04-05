"""
Middleware — CSRF protection, CORS, error handling, and request logging.
"""

import os
import hmac
import hashlib
import secrets
import time
import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("ytcloner.middleware")

# ── CSRF ─────────────────────────────────────────────────

CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT_PATHS = {"/login", "/api/health"}

# SECURITY: Module-level fallback so tokens generated in one request can be verified in the next.
# This is only used when CSRF_SECRET env var is missing (dev mode).
_CSRF_SECRET_FALLBACK = secrets.token_hex(32)


def _get_csrf_secret() -> str:
    """Get CSRF secret — env var or stable fallback (never per-call random)."""
    return os.environ.get("CSRF_SECRET", "") or _CSRF_SECRET_FALLBACK


def generate_csrf_token(session_token: str) -> str:
    """Generate CSRF token tied to a session."""
    secret = _get_csrf_secret()
    timestamp = str(int(time.time()))
    payload = f"{session_token}:{timestamp}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


def verify_csrf_token(token: str, session_token: str) -> bool:
    """Verify a CSRF token."""
    if not token:
        return False
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        timestamp, signature = parts
        # Token valid for 24 hours
        if abs(time.time() - int(timestamp)) > 86400:
            return False
        secret = _get_csrf_secret()
        payload = f"{session_token}:{timestamp}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection for state-changing requests."""

    async def dispatch(self, request: Request, call_next):
        if request.method in CSRF_SAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        if path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Check CSRF token for non-safe methods
        session_token = request.cookies.get("session", "")
        if not session_token:
            session_token = request.headers.get("x-session", "")

        csrf_token = request.headers.get("x-csrf-token", "")
        if not csrf_token:
            # Also check form data for traditional form submissions
            content_type = request.headers.get("content-type", "")
            if "form" in content_type:
                try:
                    form = await request.form()
                    csrf_token = form.get("_csrf", "")
                except Exception:
                    pass

        # SECURITY: Always enforce CSRF for state-changing requests, even without session.
        # Without session_token, verify_csrf_token will fail (as expected — no valid token possible).
        if not verify_csrf_token(csrf_token, session_token):
            if path.startswith("/api/"):
                return JSONResponse({"error": "CSRF token invalido"}, status_code=403)
            return HTMLResponse("<h1>Erro 403</h1><p>Token de seguranca invalido. Recarregue a pagina.</p>", status_code=403)

        return await call_next(request)


# ── Error Handling ───────────────────────────────────────

# Generic error messages — never leak internals
GENERIC_ERRORS = {
    400: "Requisicao invalida",
    401: "Nao autorizado",
    403: "Acesso negado",
    404: "Nao encontrado",
    429: "Muitas requisicoes. Tente novamente em alguns minutos.",
    500: "Erro interno do servidor",
}


class SafeErrorMiddleware(BaseHTTPMiddleware):
    """Catch all exceptions and return safe error messages."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            error_id = secrets.token_hex(4)
            logger.error(f"[{error_id}] {request.method} {request.url.path}: {e}")
            logger.debug(traceback.format_exc())

            is_api = request.url.path.startswith("/api/")
            safe_msg = f"Erro interno (ref: {error_id})"

            if is_api:
                return JSONResponse({"error": safe_msg}, status_code=500)
            return HTMLResponse(
                f"<h1>Erro interno</h1><p>{safe_msg}</p><p>Entre em contato com o administrador.</p>",
                status_code=500,
            )


# ── Security Headers ────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS only when running behind HTTPS (COOKIE_SECURE=true)
        if os.environ.get("COOKIE_SECURE", "true").lower() == "true":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP: allow inline scripts/styles (needed for Jinja2 templates) but block everything else
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response


# ── Request Logging ──────────────────────────────────────

class RequestLogMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = round((time.time() - start) * 1000, 1)

        # Only log non-static requests
        path = request.url.path
        if not path.startswith(("/static/", "/output/mindmap_")):
            logger.info(f"{request.method} {path} -> {response.status_code} ({duration}ms)")

        return response
