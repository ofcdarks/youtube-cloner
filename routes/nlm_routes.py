"""
NotebookLM authentication routes — credential management, notebook listing.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from auth import require_auth, require_admin
from config import OUTPUT_DIR

logger = logging.getLogger("ytcloner.routes.nlm")

router = APIRouter(tags=["nlm"])


def _render(request, template, ctx=None):
    from dashboard import render
    return render(request, template, ctx)


@router.get("/admin/notebooklm", response_class=HTMLResponse)
async def admin_nlm_auth_page(request: Request, user=Depends(require_admin)):
    """NotebookLM credential management page."""
    has_credentials = False
    try:
        has_credentials = (Path.home() / ".notebooklm" / "storage_state.json").exists()
    except Exception:
        pass
    return _render(request, "admin_nlm_auth.html", {"user": user, "has_credentials": has_credentials})


@router.get("/admin/nlm-receive", response_class=HTMLResponse)
async def admin_nlm_receive(request: Request, user=Depends(require_auth)):
    """Callback page — receives cookies from bookmarklet via URL hash and auto-saves."""
    return _render(request, "admin_nlm_receive.html", {"user": user})


@router.get("/api/admin/nlm-notebooks")
async def api_nlm_notebooks(request: Request, user=Depends(require_admin)):
    """List notebooks from NotebookLM account."""
    import asyncio, threading

    async def _fetch():
        from notebooklm import NotebookLMClient
        storage_path = Path.home() / ".notebooklm" / "storage_state.json"
        path_arg = str(storage_path) if storage_path.exists() else None
        async with await NotebookLMClient.from_storage(path=path_arg) as client:
            notebooks = await client.notebooks.list()
            return [{"id": nb.id, "title": getattr(nb, "title", getattr(nb, "name", str(nb)))} for nb in notebooks]

    try:
        container = [None, None]
        def run():
            try:
                container[0] = asyncio.run(_fetch())
            except Exception as e:
                container[1] = e
        t = threading.Thread(target=run)
        t.start()
        t.join(timeout=30)
        if container[1]:
            raise container[1]
        notebooks = container[0] or []
        return JSONResponse({"ok": True, "notebooks": notebooks})
    except Exception as e:
        logger.error(f"NLM list notebooks error: {e}")
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


@router.post("/api/admin/nlm-save-credentials")
async def api_nlm_save_credentials(request: Request, user=Depends(require_admin)):
    """Save NotebookLM storage state (cookies + localStorage)."""
    body = await request.json()
    storage_state = body.get("storage_state", "")

    if not storage_state:
        return JSONResponse({"error": "storage_state obrigatorio"}, status_code=400)

    # Validate JSON
    try:
        if isinstance(storage_state, str):
            parsed = json.loads(storage_state)
        else:
            parsed = storage_state
            storage_state = json.dumps(parsed)

        if not isinstance(parsed, dict):
            return JSONResponse({"error": "JSON deve ser um objeto"}, status_code=400)
        if "cookies" not in parsed and "origins" not in parsed:
            return JSONResponse({"error": "JSON deve conter 'cookies' ou 'origins'"}, status_code=400)
    except (json.JSONDecodeError, TypeError) as e:
        return JSONResponse({"error": f"JSON invalido: {str(e)[:100]}"}, status_code=400)

    try:
        import base64

        # Save to file — but DON'T overwrite if existing one has more cookies (is more complete)
        nlm_dir = Path.home() / ".notebooklm"
        nlm_dir.mkdir(parents=True, exist_ok=True)
        nlm_file = nlm_dir / "storage_state.json"

        # Check if new state is better than existing
        should_write = True
        if nlm_file.exists():
            try:
                existing = json.loads(nlm_file.read_text(encoding="utf-8"))
                new_parsed = json.loads(storage_state) if isinstance(storage_state, str) else storage_state
                existing_cookies = len(existing.get("cookies", []))
                new_cookies = len(new_parsed.get("cookies", []))
                has_sid_new = any(c.get("name") == "SID" for c in new_parsed.get("cookies", []))
                has_sid_existing = any(c.get("name") == "SID" for c in existing.get("cookies", []))

                # Don't overwrite complete auth with incomplete bookmarklet cookies
                if has_sid_existing and not has_sid_new:
                    logger.warning(f"NLM save: keeping existing ({existing_cookies} cookies with SID) — new has {new_cookies} cookies WITHOUT SID (bookmarklet limitation)")
                    should_write = False
                elif existing_cookies > new_cookies * 2 and has_sid_existing:
                    logger.warning(f"NLM save: keeping existing ({existing_cookies} cookies) — new only has {new_cookies}")
                    should_write = False
            except Exception:
                pass

        if should_write:
            nlm_file.write_text(storage_state, encoding="utf-8")
            logger.info(f"NotebookLM credentials saved to file: {len(storage_state)} chars")
        else:
            logger.info("NotebookLM: kept existing credentials (more complete)")

        # Backup to volume
        try:
            backup_file = OUTPUT_DIR / ".nlm_storage_state.json"
            best_content = nlm_file.read_text(encoding="utf-8") if nlm_file.exists() else storage_state
            backup_file.write_text(best_content, encoding="utf-8")
        except Exception:
            pass

        # Also try saving to DB (may fail if DB is readonly — that's OK)
        try:
            from database import set_setting
            b64 = base64.b64encode(storage_state.encode()).decode()
            set_setting("notebooklm_storage_state", b64)
            logger.info("NotebookLM credentials also saved to DB")
        except Exception as db_err:
            logger.warning(f"Could not save NLM creds to DB (file save OK): {db_err}")

        return JSONResponse({"ok": True, "cookies": len(parsed.get("cookies", [])), "origins": len(parsed.get("origins", []))})
    except Exception as e:
        logger.error(f"NLM save error: {e}")
        return JSONResponse({"error": "Falha ao salvar credenciais"}, status_code=500)
