"""
Google Drive OAuth routes — web-based OAuth flow for Docker/EasyPanel.

Replaces InstalledAppFlow.run_local_server() which doesn't work in containers.
Flow: Admin clicks "Connect Drive" → redirected to Google → callback saves token to DB.
"""

import json
import logging
import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse

from auth import require_admin
from config import GOOGLE_REDIRECT_URI
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.gdrive")

router = APIRouter(prefix="/api/admin/gdrive", tags=["gdrive"])


def _get_redirect_uri(request: Request) -> str:
    """Build redirect URI — prefer env var, fall back to request-based."""
    if GOOGLE_REDIRECT_URI:
        return GOOGLE_REDIRECT_URI
    # Auto-detect from request
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme}://{host}/api/admin/gdrive/callback"


def _has_credentials() -> bool:
    """Check if we have valid Google client credentials configured."""
    # Check at runtime (not import time) in case env vars are loaded late
    from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        return True
    # Also check os.environ directly as fallback
    import os
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def _get_client_config() -> dict:
    """Get Google OAuth client config from config.py or env vars."""
    from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    import os
    cid = GOOGLE_CLIENT_ID or os.environ.get("GOOGLE_CLIENT_ID", "")
    csec = GOOGLE_CLIENT_SECRET or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    return {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


@router.get("/status")
async def gdrive_status(request: Request, user=Depends(require_admin)):
    """Check Google Drive connection status with debug info."""
    import os as _os
    from database import get_setting
    from config import GOOGLE_CLIENT_ID as cfg_cid, GOOGLE_CLIENT_SECRET as cfg_csec

    env_cid = _os.environ.get("GOOGLE_CLIENT_ID", "")
    env_csec = _os.environ.get("GOOGLE_CLIENT_SECRET", "")

    debug = {
        "config_client_id": bool(cfg_cid),
        "config_client_id_preview": (cfg_cid[:15] + "...") if cfg_cid else "",
        "env_client_id": bool(env_cid),
        "env_client_id_preview": (env_cid[:15] + "...") if env_cid else "",
        "has_credentials": _has_credentials(),
        "has_token_in_db": bool(get_setting("google_oauth_token")),
        "has_token_in_env": bool(_os.environ.get("GOOGLE_TOKEN_JSON")),
    }

    if not _has_credentials():
        return JSONResponse({
            "connected": False,
            "configured": False,
            "message": "GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET nao configurados",
            "debug": debug,
        })

    token_json = get_setting("google_oauth_token") or os.environ.get("GOOGLE_TOKEN_JSON", "")
    if not token_json:
        return JSONResponse({
            "connected": False,
            "configured": True,
            "message": "OAuth nao autorizado. Clique em 'Conectar Google Drive'.",
        })

    # Try to validate/refresh the token
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest

        creds = Credentials.from_authorized_user_info(json.loads(token_json), _scopes())

        if creds.expired and creds.refresh_token:
            creds.refresh(GRequest())
            # Save refreshed token
            from database import set_setting
            set_setting("google_oauth_token", creds.to_json())

        if creds.valid:
            # Get account info
            try:
                from googleapiclient.discovery import build
                drive = build("drive", "v3", credentials=creds)
                about = drive.about().get(fields="user").execute()
                email = about["user"].get("emailAddress", "?")
                return JSONResponse({
                    "connected": True,
                    "configured": True,
                    "email": email,
                    "message": f"Conectado como {email}",
                })
            except Exception:
                return JSONResponse({
                    "connected": True,
                    "configured": True,
                    "message": "Token valido",
                })

        return JSONResponse({
            "connected": False,
            "configured": True,
            "message": "Token expirado. Reconecte o Google Drive.",
        })

    except Exception as e:
        logger.warning(f"GDrive token validation failed: {e}")
        return JSONResponse({
            "connected": False,
            "configured": True,
            "message": "Token invalido. Reconecte o Google Drive.",
        })


@router.get("/auth")
async def gdrive_auth(request: Request, user=Depends(require_admin)):
    """Start OAuth flow — redirect to Google consent screen."""
    if not _has_credentials():
        return JSONResponse(
            {"error": "GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET nao configurados"},
            status_code=400,
        )

    import os as _os
    _os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=_scopes(),
        redirect_uri=_get_redirect_uri(request),
    )

    # Generate authorization URL with PKCE code_verifier
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Save state AND code_verifier to DB (needed for token exchange)
    from database import set_setting
    import json as _json
    set_setting("google_oauth_state", state)
    # Store the code_verifier that Flow generated internally
    code_verifier = flow.code_verifier
    set_setting("google_oauth_code_verifier", code_verifier or "")

    logger.info(f"GDrive OAuth: redirecting to Google (state={state[:12]}..., has_verifier={bool(code_verifier)})")
    return RedirectResponse(authorization_url)


@router.get("/callback")
async def gdrive_callback(request: Request):
    """OAuth callback — exchange code for token and save."""
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error", "")

    if error:
        logger.warning(f"GDrive OAuth error: {error}")
        return RedirectResponse(f"/admin/panel?gdrive_error={error}")

    if not code:
        return RedirectResponse("/admin/panel?gdrive_error=no_code")

    # Validate state
    from database import get_setting, set_setting
    saved_state = get_setting("google_oauth_state")
    if not saved_state or saved_state != state:
        logger.warning("GDrive OAuth: state mismatch")
        return RedirectResponse("/admin/panel?gdrive_error=state_mismatch")

    # Exchange code for token using direct HTTP (avoids PKCE/code_verifier issues with Flow)
    try:
        import httpx

        config = _get_client_config()["web"]
        redirect_uri = _get_redirect_uri(request)
        code_verifier = get_setting("google_oauth_code_verifier") or ""

        logger.info(f"GDrive callback: exchanging code, redirect_uri={redirect_uri}, has_verifier={bool(code_verifier)}")

        # Direct token exchange via HTTP POST
        token_data = {
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            token_data["code_verifier"] = code_verifier

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data=token_data)
            result = resp.json()

        if "error" in result:
            err_msg = result.get("error_description", result.get("error", "unknown"))
            logger.error(f"GDrive token exchange error: {result}")
            import urllib.parse
            return RedirectResponse(f"/admin/panel?gdrive_error={urllib.parse.quote(err_msg)}")

        # Build credentials JSON compatible with google-auth
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=result["access_token"],
            refresh_token=result.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            scopes=result.get("scope", "").split(),
        )

        # Save token to DB
        token_json = creds.to_json()
        set_setting("google_oauth_token", token_json)

        # Clean up
        set_setting("google_oauth_state", "")
        set_setting("google_oauth_code_verifier", "")

        logger.info("GDrive OAuth: token saved successfully")
        return RedirectResponse("/admin/panel?gdrive_success=1")

    except Exception as e:
        import traceback
        logger.error(f"GDrive OAuth callback error: {type(e).__name__}: {e}")
        logger.error(f"GDrive traceback: {traceback.format_exc()}")
        import urllib.parse
        err_msg = urllib.parse.quote(f"{type(e).__name__}: {str(e)[:150]}")
        return RedirectResponse(f"/admin/panel?gdrive_error={err_msg}")


@router.post("/disconnect")
@limiter.limit("5/minute")
async def gdrive_disconnect(request: Request, user=Depends(require_admin)):
    """Disconnect Google Drive — remove saved token."""
    from database import set_setting
    set_setting("google_oauth_token", "")
    set_setting("google_oauth_state", "")
    logger.info("GDrive OAuth: disconnected")
    return JSONResponse({"ok": True})


def _scopes() -> list[str]:
    return ["https://www.googleapis.com/auth/drive"]


# ── Credentials helper for google_export.py ──────────────

def get_oauth_credentials():
    """Get valid OAuth credentials from DB or env.

    This replaces the InstalledAppFlow approach in google_export.py.
    Returns Credentials or raises if not available.
    """
    from database import get_setting

    token_json = get_setting("google_oauth_token") or os.environ.get("GOOGLE_TOKEN_JSON", "")
    if not token_json:
        raise RuntimeError(
            "Google Drive nao conectado. Va em Admin Panel > Conectar Google Drive."
        )

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest

    creds = Credentials.from_authorized_user_info(json.loads(token_json), _scopes())

    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        # Persist refreshed token
        from database import set_setting
        set_setting("google_oauth_token", creds.to_json())

    if not creds.valid:
        raise RuntimeError("Token do Google Drive expirado. Reconecte em Admin Panel.")

    return creds
