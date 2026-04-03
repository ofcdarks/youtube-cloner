"""
NotebookLM Auth — Remote browser authentication via Playwright.

Manages a headless Chromium instance that the admin interacts with
through screenshots + click/type events from the frontend.

Flow:
  1. Admin clicks "Conectar NotebookLM"
  2. Backend launches Playwright browser → Google login page
  3. Frontend polls /api/admin/nlm-screenshot every 500ms
  4. Admin clicks/types via the screenshot viewer
  5. After login, backend captures storage_state.json
  6. Saves encrypted to DB for future NotebookLM API calls
"""

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from io import BytesIO

logger = logging.getLogger("ytcloner.nlm_auth")

# Browser session state
_browser = None
_context = None
_page = None
_last_screenshot: bytes = b""
_last_screenshot_time: float = 0
_session_active = False
_auth_complete = False
_status_message = "Idle"

NOTEBOOKLM_URL = "https://notebooklm.google.com/"
GOOGLE_LOGIN_URL = "https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Fnotebooklm.google.com%2F&flowName=GlifWebSignIn"
STORAGE_DIR = Path.home() / ".notebooklm"
STORAGE_PATH = STORAGE_DIR / "storage_state.json"

# Screenshot dimensions
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800


async def start_session() -> dict:
    """Start a new Playwright browser session for NotebookLM auth."""
    global _browser, _context, _page, _session_active, _auth_complete, _status_message

    if _session_active:
        return {"ok": True, "message": "Sessao ja ativa"}

    try:
        from playwright.async_api import async_playwright

        _status_message = "Iniciando navegador..."
        _auth_complete = False

        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        # Check if we have existing storage state
        storage_state = None
        if STORAGE_PATH.exists():
            try:
                storage_state = str(STORAGE_PATH)
                logger.info("Loading existing storage state")
            except Exception:
                storage_state = None

        _context = await _browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            storage_state=storage_state,
            locale="pt-BR",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        _page = await _context.new_page()
        _session_active = True

        _status_message = "Navegando para NotebookLM..."
        await _page.goto(NOTEBOOKLM_URL, wait_until="domcontentloaded", timeout=30000)

        # Wait a bit for redirects
        await asyncio.sleep(2)

        # Check if we landed on login or on NotebookLM
        current_url = _page.url
        if "accounts.google.com" in current_url:
            _status_message = "Faca login com sua conta Google"
        elif "notebooklm.google.com" in current_url:
            _status_message = "Ja autenticado! Capturando sessao..."
            await _save_storage_state()
            _auth_complete = True
            _status_message = "Autenticado com sucesso!"

        return {"ok": True, "message": _status_message, "url": current_url}

    except ImportError:
        _status_message = "Playwright nao instalado"
        return {"ok": False, "error": "Playwright nao instalado. Execute: pip install playwright && playwright install chromium"}
    except Exception as e:
        _status_message = f"Erro: {str(e)[:100]}"
        logger.error(f"NLM auth start failed: {e}")
        await stop_session()
        return {"ok": False, "error": str(e)[:200]}


async def take_screenshot() -> bytes:
    """Take a screenshot of the current page."""
    global _last_screenshot, _last_screenshot_time

    if not _page or not _session_active:
        return b""

    try:
        now = time.time()
        # Rate limit screenshots to every 300ms
        if now - _last_screenshot_time < 0.3 and _last_screenshot:
            return _last_screenshot

        _last_screenshot = await _page.screenshot(type="jpeg", quality=70)
        _last_screenshot_time = now

        # Check if auth completed (landed on NotebookLM)
        current_url = _page.url
        if "notebooklm.google.com" in current_url and not _auth_complete:
            # Check if it's the actual app (not a redirect back to login)
            content = await _page.content()
            if "notebook" in content.lower() and "signin" not in current_url:
                global _status_message, _auth_complete
                _status_message = "Login detectado! Salvando sessao..."
                await _save_storage_state()
                _auth_complete = True
                _status_message = "NotebookLM conectado com sucesso!"

        return _last_screenshot
    except Exception as e:
        logger.debug(f"Screenshot error: {e}")
        return _last_screenshot or b""


async def click(x: int, y: int) -> dict:
    """Click at coordinates on the page."""
    if not _page or not _session_active:
        return {"ok": False, "error": "Sessao nao ativa"}

    try:
        await _page.mouse.click(x, y)
        await asyncio.sleep(0.3)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


async def type_text(text: str) -> dict:
    """Type text into the currently focused element."""
    if not _page or not _session_active:
        return {"ok": False, "error": "Sessao nao ativa"}

    try:
        await _page.keyboard.type(text, delay=50)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


async def press_key(key: str) -> dict:
    """Press a special key (Enter, Tab, Backspace, etc)."""
    if not _page or not _session_active:
        return {"ok": False, "error": "Sessao nao ativa"}

    try:
        await _page.keyboard.press(key)
        await asyncio.sleep(0.3)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


async def navigate(url: str) -> dict:
    """Navigate to a URL."""
    if not _page or not _session_active:
        return {"ok": False, "error": "Sessao nao ativa"}

    try:
        await _page.goto(url, wait_until="domcontentloaded", timeout=20000)
        return {"ok": True, "url": _page.url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


async def _save_storage_state():
    """Save browser storage state for future use."""
    global _status_message

    if not _context:
        return

    try:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        state = await _context.storage_state()

        # Save to file
        STORAGE_PATH.write_text(json.dumps(state), encoding="utf-8")
        logger.info(f"Storage state saved: {len(json.dumps(state))} chars")

        # Also save to DB as admin setting (encrypted)
        try:
            from database import set_setting, _encrypt_api_key
            state_json = json.dumps(state)
            b64 = base64.b64encode(state_json.encode()).decode()
            set_setting("notebooklm_storage_state", b64)
            logger.info("Storage state saved to DB")
        except Exception as e:
            logger.warning(f"Could not save to DB: {e}")

        # Save context.json if there's notebook info on the page
        try:
            # Try to extract notebook IDs from the page
            page_content = await _page.content()
            if "notebook" in page_content.lower():
                context_info = {
                    "url": _page.url,
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "authenticated": True,
                }
                (STORAGE_DIR / "context.json").write_text(
                    json.dumps(context_info), encoding="utf-8"
                )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Save storage state failed: {e}")
        _status_message = f"Erro ao salvar: {str(e)[:100]}"


async def stop_session() -> dict:
    """Close the browser session."""
    global _browser, _context, _page, _session_active, _status_message

    try:
        if _page:
            await _page.close()
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
    except Exception:
        pass

    _browser = None
    _context = None
    _page = None
    _session_active = False
    _status_message = "Sessao encerrada"

    return {"ok": True}


def get_status() -> dict:
    """Get current session status."""
    return {
        "active": _session_active,
        "authenticated": _auth_complete,
        "message": _status_message,
        "url": _page.url if _page else "",
        "has_existing_credentials": STORAGE_PATH.exists(),
    }
