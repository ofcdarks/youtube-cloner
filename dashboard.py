"""
Dashboard Web — YouTube Channel Cloner
FastAPI server with project history, visualization, and team management.

Refactored: routes split into modules, centralized config, proper auth and middleware.
"""

import json
import os
import re
import logging
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import (
    PROJECT_DIR, OUTPUT_DIR, PROJECTS_DIR,
    ALLOWED_ORIGINS, PORT, LOG_LEVEL,
    MAX_TOKENS_LARGE, MAX_TOKENS_MEDIUM, MAX_IDEAS_PER_REQUEST,
    validate_startup, print_startup_banner,
)
from middleware import CSRFMiddleware, SafeErrorMiddleware, RequestLogMiddleware, SecurityHeadersMiddleware, generate_csrf_token
from auth import (
    require_auth, require_admin, optional_auth, check_auth,
    get_session_token, SESSIONS,
)
from services import (
    get_filesystem_projects, get_project_files, get_output_files,
    build_categories, load_ideas, validate_file_path, validate_project_id,
    analyze_via_transcripts,
    sanitize_niche_name, validate_url, generate_mindmap_html,
)

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ytcloner")

# ── App Creation ─────────────────────────────────────────
app = FastAPI(title="YT Channel Cloner Dashboard", docs_url=None, redoc_url=None)

# Rate limiting
from rate_limit import limiter
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"error": "Muitas requisicoes. Tente novamente em alguns minutos."}, status_code=429)


# ── Middleware (order matters: last added = first executed) ──
app.add_middleware(SafeErrorMiddleware)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
# SECURITY: Never combine ["*"] with allow_credentials=True
_cors_origins = ALLOWED_ORIGINS if ALLOWED_ORIGINS else []
if not _cors_origins:
    logger.warning("ALLOWED_ORIGINS not set — CORS will reject cross-origin credentialed requests")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["x-csrf-token"],
)

# ── Templates & Static ──────────────────────────────────
templates = Jinja2Templates(directory=str(PROJECT_DIR / "templates"))

# Jinja filter: fromjson — parse JSON string to dict/list (used in card checklist)
def _fromjson_filter(value):
    import json as _json
    if not value:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return _json.loads(value)
    except Exception:
        return {}
templates.env.filters["fromjson"] = _fromjson_filter

# Mount static files — but NOT the output directory root (contains DB)
app.mount("/static", StaticFiles(directory=str(PROJECT_DIR / "static")), name="static")

# Only serve specific output subdirectories and file patterns — NOT the DB
# We'll handle output file serving through a protected route instead


def render(request: Request, template_name: str, ctx: dict | None = None, status_code: int = 200):
    """Render template with session and CSRF context."""
    context = ctx or {}
    context["request"] = request

    # Inject session token and CSRF token
    token = get_session_token(request)
    context["session_token"] = token
    context["csrf_token"] = generate_csrf_token(token) if token else ""

    try:
        return templates.TemplateResponse(request, template_name, context, status_code=status_code)
    except TypeError:
        return templates.TemplateResponse(template_name, context, status_code=status_code)


# ── Startup ──────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Validate config, init database, setup credentials."""
    errors, warnings = validate_startup()
    print_startup_banner(errors, warnings)

    try:
        from database import init_db, create_default_admin, get_users
        init_db()
        create_default_admin()
        users = get_users()
        logger.info(f"DB OK. Users: {len(users)}")
    except Exception as e:
        logger.error(f"Startup DB error: {e}")

    # Seed data if output is empty
    try:
        import shutil
        seed_dir = PROJECT_DIR / "seed_output"
        if seed_dir.exists():
            db_path = OUTPUT_DIR / "ytcloner.db"
            seed_db = seed_dir / "ytcloner.db"
            if seed_db.exists() and (not db_path.exists() or db_path.stat().st_size < 1000):
                shutil.copy2(str(seed_db), str(db_path))
                logger.info(f"Seeded DB from build ({seed_db.stat().st_size} bytes)")
            for f in seed_dir.glob("mindmap_*.html"):
                shutil.copy2(str(f), str(OUTPUT_DIR / f.name))
    except Exception as e:
        logger.debug(f"Seed: {e}")

    # One-time project imports from output/import_*.json or seed_output/import_*.json
    try:
        _import_paths = list(OUTPUT_DIR.glob("import_*.json"))
        _seed_dir = PROJECT_DIR / "seed_output"
        if _seed_dir.exists():
            _import_paths += list(_seed_dir.glob("import_*.json"))
        for _imp_file in sorted(_import_paths):
            _imp_data = json.loads(_imp_file.read_text(encoding="utf-8"))
            _imp_name = _imp_data["project"]["name"]
            # Check if project already exists (by name)
            from database import get_db
            with get_db() as _conn:
                _existing = _conn.execute(
                    "SELECT id FROM projects WHERE name=?", (_imp_name,)
                ).fetchone()
            if _existing:
                logger.info(f"Import skip: project '{_imp_name}' already exists")
                continue
            from database import create_project, save_niche, save_idea, save_file, log_activity
            _p = _imp_data["project"]
            _pid = create_project(
                name=_p["name"], channel_original=_p.get("channel_original", ""),
                niche_chosen=_p.get("niche_chosen", ""),
                meta=json.loads(_p["meta"]) if isinstance(_p["meta"], str) else _p.get("meta", {}),
                language=_p.get("language", "en"),
            )
            # SOP
            if _imp_data.get("sop"):
                save_file(_pid, "analise", f"SOP Completo - {_p['name']}",
                          f"sop_{_p['name'].lower().replace(' ', '_')}.md", _imp_data["sop"])
            # Niches
            for _n in _imp_data.get("niches", []):
                save_niche(_pid, _n["name"], _n.get("description", ""),
                           rpm_range=_n.get("rpm_range", ""), competition=_n.get("competition", ""),
                           color=_n.get("color", "#7c3aed"), pillars=_n.get("pillars", "[]"))
            # Ideas
            for _t in _imp_data.get("ideas", []):
                save_idea(_pid, _t.get("num", 0), _t["title"],
                          hook=_t.get("hook", ""), pillar=_t.get("pillar", ""),
                          priority=_t.get("priority", "medium"))
            # Mind map
            try:
                from services import generate_mindmap_html as _gmm, get_project_sop as _gsop
                _mm_niches = [{"name": _n["name"]} for _n in _imp_data.get("niches", [])]
                _mm_ideas = [{"title": _t["title"], "hook": _t.get("hook", ""), "score": 0} for _t in _imp_data.get("ideas", [])[:10]]
                _mm = _gmm(_p["name"], "", (_imp_data.get("sop") or "")[:3000], _mm_niches, _mm_ideas)
                (OUTPUT_DIR / f"mindmap_{_pid}.html").write_text(_mm, encoding="utf-8")
            except Exception:
                pass
            log_activity(_pid, "project_imported", f"Projeto importado de {_imp_file.name}")
            logger.info(f"Import OK: '{_imp_name}' → {_pid} ({len(_imp_data.get('niches',[]))} niches, {len(_imp_data.get('ideas',[]))} ideas)")
    except Exception as e:
        logger.debug(f"Import: {e}")

    # Log Google Drive config status
    _gid = os.environ.get("GOOGLE_CLIENT_ID", "")
    _gsec = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    _guri = os.environ.get("GOOGLE_REDIRECT_URI", "")
    if _gid:
        logger.info(f"Google Drive: client_id={_gid[:20]}... redirect={_guri}")
    else:
        logger.info("Google Drive: GOOGLE_CLIENT_ID not set — Drive integration disabled")
        # Try to load from .env directly as last resort
        try:
            from pathlib import Path as _P
            _env_file = _P(__file__).parent / ".env"
            if _env_file.exists():
                for line in _env_file.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
                            if k not in os.environ or not os.environ[k]:
                                os.environ[k] = v
                                logger.info(f"Google Drive: loaded {k} from .env file")
        except Exception as e:
            logger.debug(f"Failed to load Google vars from .env: {e}")


# ── Exception Handlers ───────────────────────────────────

@app.exception_handler(401)
async def custom_401(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return render(request, "login.html", {"error": "Sessao expirada. Faca login novamente."}, status_code=401)


from fastapi import HTTPException

@app.exception_handler(HTTPException)
async def custom_http_exception(request: Request, exc):
    if exc.status_code == 401:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return render(request, "login.html", {"error": "Sessao expirada."}, status_code=401)
    if exc.status_code in (403, 404):
        return JSONResponse({"error": exc.detail or "forbidden"}, status_code=exc.status_code)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Erro interno"}, status_code=exc.status_code)
    raise exc


# ── Include Route Modules ────────────────────────────────
from routes.auth_routes import router as auth_router
app.include_router(auth_router)

from routes.gdrive_routes import router as gdrive_router
app.include_router(gdrive_router)

from routes.api_routes import router as api_router
app.include_router(api_router)

from routes.student_routes import router as student_router
app.include_router(student_router)

from routes.admin_routes import router as admin_router
app.include_router(admin_router)

from routes.drive_admin_routes import router as drive_admin_router
app.include_router(drive_admin_router)

from routes.pipeline_routes import router as pipeline_router
app.include_router(pipeline_router)

from routes.mockup_routes import router as mockup_router
app.include_router(mockup_router)

from routes.import_routes import router as import_router
app.include_router(import_router)

# ── M17: Health Check ────────────────────────────────────
import time as _time
_cloner_start_time = _time.time()

@app.get("/api/health")
async def api_health():
    """Health check endpoint para monitoramento externo (EasyPanel, uptime robot, etc.)."""
    try:
        from database import get_db
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        db_ok = True
        db_projects_count = count
    except Exception as e:
        db_ok = False
        db_projects_count = 0

    # Disk space check
    import shutil
    disk = shutil.disk_usage(str(OUTPUT_DIR))
    disk_free_gb = round(disk.free / (1024**3), 1)

    return JSONResponse({
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "db_ok": db_ok,
        "db_projects": db_projects_count,
        "uptime_s": int(_time.time() - _cloner_start_time),
        "disk_free_gb": disk_free_gb,
    })


# ── SSE Progress Endpoint ────────────────────────────────

from fastapi.responses import StreamingResponse

@app.get("/api/admin/pipeline-progress")
async def api_pipeline_progress(request: Request, niche: str = "", user=Depends(require_admin)):
    """SSE endpoint for real-time pipeline progress."""
    import asyncio
    from progress_store import get_progress

    async def event_stream():
        key = f"pipeline_{niche}"
        last_step = -1
        no_update_count = 0

        while True:
            if await request.is_disconnected():
                break

            progress = get_progress(key)
            if progress and progress.get("step", 0) != last_step:
                last_step = progress["step"]
                no_update_count = 0
                import json
                yield f"data: {json.dumps(progress)}\n\n"

                # Pipeline complete
                if progress.get("step", 0) >= progress.get("total", 12):
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break
            else:
                no_update_count += 1
                # Send keepalive every 15 seconds to prevent proxy timeouts (nginx, etc.)
                if no_update_count % 15 == 0:
                    yield ": keepalive\n\n"

            # Timeout after 10 minutes of no updates
            if no_update_count > 600:
                yield f"data: {json.dumps({'error': 'timeout'})}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ══════════════════════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, project: str = "", user=Depends(require_auth)):
    """Main dashboard — admin sees full dashboard, student redirects."""
    if user.get("must_change_password"):
        return RedirectResponse("/change-password?first=1", status_code=302)
    if user.get("role") == "student":
        return RedirectResponse("/student", status_code=302)

    from database import get_projects as db_projects, get_ideas, get_niches, get_scripts, get_stats, get_files

    projects = db_projects()
    current_project = None
    ideas = []
    niches = []
    scripts = []
    files = []

    if project:
        current_project = next((p for p in projects if p["id"] == project), None)
    if not current_project and projects:
        current_project = projects[0]

    if current_project:
        pid = current_project["id"]
        ideas = get_ideas(pid)
        niches = get_niches(pid)
        scripts = get_scripts(pid)
        files = get_files(pid)

    stats = get_stats()

    # Build categories from DB files ONLY (per-project, not global)
    categories = {}
    cat_config = {
        "analise": {"label": "Analise / SOP", "icon": "&#128200;", "color": "#7c3aed"},
        "seo": {"label": "SEO Pack", "icon": "&#128269;", "color": "#06b6d4"},
        "roteiro": {"label": "Roteiros", "icon": "&#128221;", "color": "#eab308"},
        "roteiros": {"label": "Roteiros", "icon": "&#128221;", "color": "#eab308"},
        "narracao": {"label": "Narracoes", "icon": "&#127908;", "color": "#ff6e40"},
        "visual": {"label": "Mind Map / Visual", "icon": "&#127912;", "color": "#e040fb"},
        "outro": {"label": "Outros", "icon": "&#128196;", "color": "#64748b"},
    }
    if files:
        for f in files:
            cat_key = f.get("category", "outro")
            if cat_key not in categories:
                cfg = cat_config.get(cat_key, cat_config["outro"])
                categories[cat_key] = {"label": cfg["label"], "icon": cfg["icon"], "color": cfg["color"], "files": []}
            categories[cat_key]["files"].append({
                "name": f.get("label", f.get("filename", "")),
                "path": f.get("filename", ""),
                "size": len(f.get("content", "") or ""),
                "label": f.get("label", f.get("filename", "")),
                "id": f.get("id", 0),
                "visible": f.get("visible_to_students", 0),
            })

    # Mind map path
    mindmap_path = ""
    if current_project:
        mm = OUTPUT_DIR / f"mindmap_{current_project['id']}.html"
        fname = f"mindmap_{current_project['id']}.html"
        if mm.exists():
            mindmap_path = f"/output-file?name={fname}"
        else:
            # Check DB fallback (file content saved there)
            try:
                with get_db() as conn:
                    row = conn.execute("SELECT filename FROM files WHERE project_id=? AND category='visual' AND content != '' LIMIT 1", (current_project['id'],)).fetchone()
                    if row:
                        mindmap_path = f"/output-file?name={row[0]}"
            except Exception:
                pass

    # Drive links from project
    drive_links = []
    sop_source = ""
    if current_project:
        drive_url = current_project.get("drive_folder_url", "") or ""
        if drive_url:
            drive_links.append({"url": drive_url, "label": "Pasta do Projeto", "type": "Folder", "icon": "&#128193;"})
        for f in files:
            fu = f.get("drive_url", "") or ""
            if fu:
                drive_links.append({"url": fu, "label": f.get("label", f.get("filename", "")), "type": f.get("category", ""), "icon": "&#128196;"})
        # SOP source from meta (safely parse — old DB may have unexpected formats)
        raw_meta = current_project.get("meta", None)
        meta = {}
        if isinstance(raw_meta, dict):
            meta = raw_meta
        elif isinstance(raw_meta, str) and raw_meta:
            try:
                parsed = json.loads(raw_meta)
                if isinstance(parsed, dict):
                    meta = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        sop_source = meta.get("sop_source", "") if isinstance(meta, dict) else ""

    # Extract recommended flag from pillars JSON for template rendering
    for n in niches:
        n["recommended"] = False
        n["recommended_reason"] = ""
        try:
            pillars_raw = n.get("pillars", "[]")
            if isinstance(pillars_raw, str):
                pillars_raw = json.loads(pillars_raw)
            if isinstance(pillars_raw, list):
                for p in pillars_raw:
                    if isinstance(p, dict) and p.get("__recommended"):
                        n["recommended"] = True
                        n["recommended_reason"] = p.get("__reason", "")
                        break
        except (json.JSONDecodeError, TypeError):
            pass

    return render(request, "dashboard.html", {
        "user": user,
        "all_projects": projects,
        "projects": projects,
        "current_project": current_project,
        "current_project_id": current_project["id"] if current_project else "",
        "ideas": ideas,
        "niches": niches,
        "nichos": niches,
        "scripts": scripts,
        "files": files,
        "stats": stats,
        "categories": categories,
        "mindmap_path": mindmap_path,
        "drive_links": drive_links,
        "sop_source": sop_source,
        "nichos_escolhidos": [n for n in niches if n.get("chosen")],
    })


@app.get("/output-file")
async def serve_output_file(request: Request, name: str = "", user=Depends(require_auth)):
    """Serve files from output directory — checks disk first, then DB.
    Students can only access files from their assigned projects.
    """
    if not name:
        return JSONResponse({"error": "nome obrigatorio"}, status_code=400)

    blocked = [".db", ".db-wal", ".db-shm", ".key", ".pem"]
    if any(name.lower().endswith(ext) for ext in blocked):
        return JSONResponse({"error": "Acesso negado"}, status_code=403)

    # Student access control: verify file belongs to an assigned project
    if user.get("role") != "admin":
        try:
            from database import get_db
            filename = Path(name).name
            with get_db() as conn:
                # Check if file is in a project the student is assigned to AND visible
                allowed = conn.execute("""
                    SELECT f.id FROM files f
                    JOIN assignments a ON a.project_id = f.project_id AND a.student_id = ?
                    WHERE f.filename = ? AND f.visible_to_students = 1
                    LIMIT 1
                """, (user["id"], filename)).fetchone()

                # Also allow student-specific filesystem files
                is_student_file = filename.startswith(f"roteiro_student_{user['id']}_")

                if not allowed and not is_student_file:
                    return JSONResponse({"error": "Acesso negado"}, status_code=403)
        except Exception as e:
            # SECURITY: Fail closed — if DB check fails, deny access for non-admin
            logger.error(f"File access control check failed: {e}")
            return JSONResponse({"error": "Acesso negado"}, status_code=403)

    # Determine content type
    suffix = Path(name).suffix.lower()
    content_types = {".html": "text/html", ".md": "text/plain", ".txt": "text/plain"}
    ct = content_types.get(suffix, "text/plain")

    # Try filesystem first
    resolved = validate_file_path(name)
    if resolved:
        try:
            content = resolved.read_text(encoding="utf-8")
            return PlainTextResponse(content, media_type=ct)
        except Exception:
            pass

    # Fallback: try DB by filename
    try:
        from database import get_db
        filename = Path(name).name
        with get_db() as conn:
            row = conn.execute("SELECT content FROM files WHERE filename=? AND content != '' ORDER BY created_at DESC LIMIT 1", (filename,)).fetchone()
            if row and row[0]:
                return PlainTextResponse(row[0], media_type=ct)
    except Exception:
        pass

    return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)


@app.get("/output/{filename}")
async def serve_output_legacy(request: Request, filename: str, user=Depends(require_auth)):
    """Legacy route — redirect /output/filename to /output-file?name=filename."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/output-file?name={filename}")


@app.get("/file")
async def read_file(request: Request, path: str = "", id: int = 0, user=Depends(require_auth)):
    """Read a file content — by path or by DB id. Supports role-based access."""
    # ID-based lookup (used by copyNarration, scoreScript, etc.)
    if id:
        try:
            from database import get_db
            with get_db() as conn:
                row = conn.execute("SELECT * FROM files WHERE id=?", (id,)).fetchone()
                if row and row["content"]:
                    # Students can only access visible files from their assigned projects
                    if user.get("role") != "admin":
                        assigned = conn.execute(
                            "SELECT 1 FROM assignments WHERE student_id=? AND project_id=?",
                            (user["id"], row["project_id"]),
                        ).fetchone()
                        if not assigned or not row["visible_to_students"]:
                            return JSONResponse({"error": "Acesso negado"}, status_code=403)
                    return PlainTextResponse(row["content"])
        except Exception as e:
            logger.error(f"File ID lookup error: {e}")
        return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)

    if not path:
        return JSONResponse({"error": "path obrigatorio"}, status_code=400)

    # Students cannot access SOP/analysis files
    filename_lower = Path(path).name.lower()
    if user.get("role") != "admin":
        if "sop" in filename_lower or "analise" in filename_lower:
            return JSONResponse({"error": "Acesso restrito"}, status_code=403)

    # Try filesystem (within output/ only)
    resolved = validate_file_path(path)
    if resolved:
        try:
            return PlainTextResponse(resolved.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Try loading from database by filename
    try:
        from database import get_db
        filename = Path(path).name
        with get_db() as conn:
            row = conn.execute(
                "SELECT content FROM files WHERE filename=? AND content IS NOT NULL AND content != '' LIMIT 1",
                (filename,),
            ).fetchone()
        if row and row["content"]:
            return PlainTextResponse(row["content"])
    except Exception:
        pass

    return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)


@app.get("/project")
async def read_project(request: Request, id: str = "", user=Depends(require_auth)):
    """Read project files concatenated.

    Projects can exist in two places:
    1. Filesystem: PROJECTS_DIR/<id>/*.md (legacy, pipeline-generated)
    2. Database: files table with project_id=<id> and content column populated
       (reusable niche templates assignable to any student — no channel required)

    This route reads from whichever source has content. If both exist, filesystem wins.
    If neither has content, returns 404.
    """
    if not validate_project_id(id):
        return JSONResponse({"error": "ID invalido"}, status_code=400)

    content = ""

    # 1. Try filesystem first (legacy pipeline projects)
    project_dir = PROJECTS_DIR / id
    if project_dir.exists():
        for f in sorted(project_dir.glob("*.md")):
            content += f"{'=' * 60}\n{f.stem.upper()}\n{'=' * 60}\n\n"
            content += f.read_text(encoding="utf-8") + "\n\n"

    # 2. Fallback/merge: read files stored in DB (template projects, no channel)
    if not content.strip():
        try:
            from database import get_project as db_get_project, get_files as db_get_files
            project = db_get_project(id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

            files = db_get_files(id)
            if not files:
                # Project exists in DB but has no files yet — return friendly empty state
                return PlainTextResponse(
                    f"{'=' * 60}\n"
                    f"PROJETO: {project.get('name', id)}\n"
                    f"{'=' * 60}\n\n"
                    f"Este projeto ainda nao tem arquivos.\n\n"
                    f"Voce pode adicionar arquivos via pipeline, upload manual, "
                    f"ou importar SOPs de outro projeto.\n"
                )

            # Sort by category then created_at for stable ordering
            def _sort_key(f):
                return (str(f.get("category") or ""), str(f.get("created_at") or ""))

            last_category = None
            for f in sorted(files, key=_sort_key):
                fname = f.get("filename") or f.get("label") or f"file_{f.get('id')}"
                fcontent = f.get("content") or ""
                if not fcontent.strip():
                    continue
                # Section header with category break
                category = f.get("category") or "geral"
                if category != last_category:
                    content += f"\n{'#' * 60}\n# CATEGORIA: {category.upper()}\n{'#' * 60}\n\n"
                    last_category = category
                content += f"{'=' * 60}\n{Path(fname).stem.upper()}\n{'=' * 60}\n\n"
                content += fcontent + "\n\n"
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("read_project DB fallback failed for id=%s: %s", id, exc)
            raise HTTPException(status_code=500, detail="Erro ao ler projeto do banco")

    if not content.strip():
        raise HTTPException(status_code=404, detail="Project not found")

    return PlainTextResponse(content)


# ══════════════════════════════════════════════════════════
# API ROUTES — moved to routes/api_routes.py
# ══════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/admin/students", response_class=HTMLResponse)
async def admin_students(request: Request, user=Depends(require_admin)):
    from database import get_admin_overview, get_projects as db_projects, get_niches
    overview = get_admin_overview()
    projects = db_projects()

    # Collect all niches from all active projects for the create-student form
    all_niches = []
    seen_names = set()
    for p in projects:
        for n in get_niches(p["id"]):
            if n["name"] not in seen_names:
                all_niches.append(n)
                seen_names.add(n["name"])

    return render(request, "admin_students.html", {
        "user": user,
        "students": overview,
        "projects": projects,
        "nichos": all_niches,
    })


@app.get("/admin/student/{student_id}", response_class=HTMLResponse)
async def admin_student_detail(request: Request, student_id: int, user=Depends(require_admin)):
    from database import get_user, get_assignments, get_student_ideas
    student = get_user(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Aluno nao encontrado")
    assignments = get_assignments(student_id)

    # Status display config
    status_labels = {"pending": "Pendente", "writing": "Escrevendo", "recording": "Gravando",
                     "editing": "Editando", "published": "Publicado"}
    status_colors = {"pending": "#ffd740", "writing": "#448aff", "recording": "#e040fb",
                     "editing": "#ff6e40", "published": "#4caf50"}

    for a in assignments:
        ideas = get_student_ideas(a["id"])
        a["ideas"] = ideas
        total = len(ideas)
        completed = sum(1 for i in ideas if i.get("status") == "published")
        a["pct"] = round(completed / total * 100) if total else 0

    has_api = bool(student.get("api_key_encrypted"))

    from database import get_student_channels, get_projects, get_db
    channels = get_student_channels(student_id)

    # All projects for assignment dropdown
    all_projects = get_projects()
    projects_by_id = {p["id"]: p for p in all_projects}

    # Enrich channels with linked project info
    for ch in channels:
        proj = projects_by_id.get(ch.get("project_id", ""))
        ch["project_name"] = proj["name"] if proj else ""
        ch["project_niche"] = proj.get("niche_chosen", "") if proj else ""

    # Enrich assignments with project info
    for a in assignments:
        proj = projects_by_id.get(a.get("project_id"))
        a["project_name"] = proj["name"] if proj else "Sem projeto"
        a["project_channel"] = proj.get("channel_original", "") if proj else ""
        a["project_language"] = proj.get("language", "pt-BR") if proj else ""

    # Get resources for this student
    # target_student_id semantics: NULL (or legacy 0) = all students | <int> = specific student
    student_resources = []
    try:
        with get_db() as conn:
            student_resources = [dict(r) for r in conn.execute(
                "SELECT * FROM admin_resources WHERE active=1 AND (target_student_id IS NULL OR target_student_id=0 OR target_student_id=?) ORDER BY created_at DESC",
                (student_id,),
            ).fetchall()]
    except Exception:
        pass

    return render(request, "admin_student_detail.html", {
        "user": user,
        "student": student,
        "assignments": assignments,
        "has_api": has_api,
        "status_labels": status_labels,
        "status_colors": status_colors,
        "channels": channels,
        "all_projects": all_projects,
        "resources": student_resources,
    })


@app.get("/admin/projects", response_class=HTMLResponse)
async def admin_projects(request: Request, user=Depends(require_admin)):
    from database import get_projects as db_projects, get_db

    projects = db_projects()

    # Enrich with counts — single GROUP BY query instead of N+1
    with get_db() as conn:
        counts = {row["id"]: row for row in conn.execute("""
            SELECT p.id,
                   COALESCE(i.cnt, 0) as idea_count,
                   COALESCE(n.cnt, 0) as niche_count,
                   COALESCE(s.cnt, 0) as script_count
            FROM projects p
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM ideas GROUP BY project_id) i ON i.project_id = p.id
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM niches GROUP BY project_id) n ON n.project_id = p.id
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM scripts GROUP BY project_id) s ON s.project_id = p.id
        """).fetchall()}
        for p in projects:
            c = counts.get(p["id"])
            p["idea_count"] = c["idea_count"] if c else 0
            p["niche_count"] = c["niche_count"] if c else 0
            p["script_count"] = c["script_count"] if c else 0

    return render(request, "admin_projects.html", {"user": user, "projects": projects})


@app.get("/admin/bent-ideas", response_class=HTMLResponse)
async def admin_bent_ideas(request: Request, project: str = "", user=Depends(require_admin)):
    """Dedicated page to view and manage saved bent ideas (niche bender history)."""
    from database import get_bent_ideas, get_projects as db_projects

    items = get_bent_ideas(limit=200, project_id=project)
    projects = db_projects()

    # Enrich items with project name lookup
    project_map = {p["id"]: p["name"] for p in projects}
    for it in items:
        it["source_project_name"] = project_map.get(it.get("source_project_id", ""), "")

    return render(request, "admin_bent_ideas.html", {
        "user": user,
        "items": items,
        "projects": projects,
        "filter_project": project,
        "total": len(items),
    })


@app.post("/api/admin/delete-bent-idea")
async def api_delete_bent_idea(request: Request, user=Depends(require_admin)):
    """Delete a saved bent idea."""
    from database import get_db
    body = await request.json()
    bent_id = body.get("bent_id")
    if not bent_id:
        return JSONResponse({"error": "bent_id obrigatorio"}, status_code=400)
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM bent_ideas WHERE id=?", (int(bent_id),))
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.exception(f"delete-bent-idea error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.post("/api/admin/star-bent-variation")
async def api_star_bent_variation(request: Request, user=Depends(require_admin)):
    """Mark a specific variation within a bent idea as 'starred' for later formalization.

    Stores in the variations_json by setting starred=true on the variation at index N.
    """
    import json as _json
    from database import get_db
    body = await request.json()
    bent_id = body.get("bent_id")
    var_idx = body.get("variation_idx")
    starred = bool(body.get("starred", True))
    if bent_id is None or var_idx is None:
        return JSONResponse({"error": "bent_id e variation_idx obrigatorios"}, status_code=400)
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT variations_json FROM bent_ideas WHERE id=?",
                (int(bent_id),),
            ).fetchone()
            if not row:
                return JSONResponse({"error": "Bent idea nao encontrada"}, status_code=404)
            try:
                variations = _json.loads(row["variations_json"] or "[]")
            except Exception:
                variations = []
            if not isinstance(variations, list) or int(var_idx) >= len(variations):
                return JSONResponse({"error": "variation_idx fora do range"}, status_code=400)
            variations[int(var_idx)]["starred"] = starred
            conn.execute(
                "UPDATE bent_ideas SET variations_json=? WHERE id=?",
                (_json.dumps(variations, ensure_ascii=False), int(bent_id)),
            )
        return JSONResponse({"ok": True, "starred": starred})
    except Exception as e:
        logger.exception(f"star-bent-variation error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.get("/admin/niches-lab", response_class=HTMLResponse)
async def admin_niches_lab(request: Request, user=Depends(require_admin)):
    """Niches Lab — Top Niches playbook + Deep Dive turbinado com DataForSEO."""
    from protocols.niches_lab import TOP_NICHES
    return render(request, "admin_niches_lab.html", {
        "user": user,
        "top_niches": TOP_NICHES,
    })


@app.post("/api/admin/niches-lab/enrich")
async def api_niches_lab_enrich(request: Request, user=Depends(require_admin)):
    """Enriquece a lista curada de Top Niches com dados ao vivo do DataForSEO."""
    from protocols.niches_lab import enrich_top_niches
    body = await request.json()
    country = (body.get("country") or "us").lower()
    language = (body.get("language") or "en").lower()
    try:
        enriched = enrich_top_niches(country=country, language=language)
        has_live = any(n.get("live", {}).get("has_data") for n in enriched)
        return JSONResponse({
            "ok": True,
            "country": country,
            "language": language,
            "niches": enriched,
            "live_data_available": has_live,
        })
    except Exception as e:
        logger.exception(f"niches-lab/enrich error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.post("/api/admin/niches-lab/regional")
async def api_niches_lab_regional(request: Request, user=Depends(require_admin)):
    """
    Generate validated regional niches per (country, language) via AI.
    Enriches with real YouTube channel URLs. Cached in memory.
    First call ~30s. Subsequent instant.
    """
    from protocols.niches_lab import get_regional_niches
    body = await request.json()
    country = (body.get("country") or "us").lower()
    language = (body.get("language") or "en").lower()
    force = bool(body.get("force_refresh", False))
    try:
        niches = get_regional_niches(country, language, force_refresh=force)
        return JSONResponse({
            "ok": True,
            "country": country,
            "language": language,
            "niches": niches,
            "count": len(niches),
        })
    except Exception as e:
        logger.exception(f"niches-lab/regional error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.post("/api/admin/niches-lab/clear-cache")
async def api_niches_lab_clear_cache(request: Request, user=Depends(require_admin)):
    """Clear the regional niches cache (useful if AI generated bad data)."""
    from protocols.niches_lab import clear_regional_cache
    body = await request.json()
    country = body.get("country")
    language = body.get("language")
    try:
        cleared = clear_regional_cache(country, language)
        return JSONResponse({"ok": True, "cleared": cleared})
    except Exception as e:
        logger.exception(f"niches-lab/clear-cache error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.post("/api/admin/niches-lab/deep-dive")
async def api_niches_lab_deep_dive(request: Request, user=Depends(require_admin)):
    """Deep Dive de um nicho — sub-niches reais via DataForSEO Labs + plano 30 dias."""
    from protocols.niches_lab import deep_dive_niche
    body = await request.json()
    niche = (body.get("niche") or "").strip()
    country = (body.get("country") or "us").lower()
    language = (body.get("language") or "en").lower()
    if not niche:
        return JSONResponse({"error": "niche obrigatorio"}, status_code=400)
    try:
        result = deep_dive_niche(niche, country=country, language=language)
        return JSONResponse(result)
    except Exception as e:
        logger.exception(f"niches-lab/deep-dive error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.get("/admin/radar", response_class=HTMLResponse)
async def admin_radar(request: Request, project: str = "", user=Depends(require_admin)):
    """Dedicated Radar page — trend analysis for a project."""
    from database import get_project, get_files
    proj = get_project(project)
    if not proj:
        return RedirectResponse("/")

    # Get existing radar reports
    existing = [dict(f) for f in get_files(project) if "radar" in f.get("filename", "").lower() or "tendencia" in f.get("label", "").lower()]

    return render(request, "admin_radar.html", {
        "user": user,
        "project": proj,
        "existing_reports": existing,
    })


@app.get("/admin/sop-analysis", response_class=HTMLResponse)
async def admin_sop_analysis(request: Request, project: str = "", mode: str = "canal", user=Depends(require_admin)):
    """Dedicated SOP Analysis page — canal or alunos mode."""
    from database import get_project, get_files
    proj = get_project(project)
    if not proj:
        return RedirectResponse("/")

    if mode not in ("canal", "alunos"):
        mode = "canal"

    # Get existing SOP evolution reports
    existing = [dict(f) for f in get_files(project) if "evolucao" in f.get("label", "").lower() or "evolve" in f.get("filename", "").lower()]

    return render(request, "admin_sop_analysis.html", {
        "user": user,
        "project": proj,
        "mode": mode,
        "existing_reports": existing,
    })


@app.get("/admin/panel", response_class=HTMLResponse)
async def admin_panel(request: Request, user=Depends(require_admin)):
    """Admin control panel with stats, API status, users, and activity."""
    from database import get_db, get_projects as db_projects

    with get_db() as conn:
        # Stats — single query instead of 5 separate COUNTs
        stat_row = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM projects) as projects,
                (SELECT COUNT(*) FROM users) as users,
                (SELECT COUNT(*) FROM files) as files,
                (SELECT COUNT(*) FROM ideas) as ideas,
                (SELECT COUNT(*) FROM scripts) as scripts
        """).fetchone()
        stats = {
            "projects": stat_row["projects"],
            "users": stat_row["users"],
            "files": stat_row["files"],
            "ideas": stat_row["ideas"],
            "scripts": stat_row["scripts"],
            "db_size_mb": round(os.path.getsize(OUTPUT_DIR / "ytcloner.db") / 1024 / 1024, 1) if (OUTPUT_DIR / "ytcloner.db").exists() else 0,
        }

        users = [dict(r) for r in conn.execute("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC").fetchall()]

        # Project counts — single GROUP BY query instead of N+1
        projects = db_projects()
        pcounts = {row["id"]: row for row in conn.execute("""
            SELECT p.id,
                   COALESCE(n.cnt, 0) as niches_count,
                   COALESCE(i.cnt, 0) as ideas_count,
                   COALESCE(s.cnt, 0) as scripts_count,
                   COALESCE(f.cnt, 0) as files_count
            FROM projects p
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM niches GROUP BY project_id) n ON n.project_id = p.id
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM ideas GROUP BY project_id) i ON i.project_id = p.id
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM scripts GROUP BY project_id) s ON s.project_id = p.id
            LEFT JOIN (SELECT project_id, COUNT(*) as cnt FROM files GROUP BY project_id) f ON f.project_id = p.id
        """).fetchall()}
        for p in projects:
            c = pcounts.get(p["id"])
            p["niches_count"] = c["niches_count"] if c else 0
            p["ideas_count"] = c["ideas_count"] if c else 0
            p["scripts_count"] = c["scripts_count"] if c else 0
            p["files_count"] = c["files_count"] if c else 0

        activity = [dict(r) for r in conn.execute(
            "SELECT action, details, created_at FROM activity_log ORDER BY created_at DESC LIMIT 30"
        ).fetchall()]

    # API keys status
    from config import GOOGLE_CLIENT_ID as _gci
    gdrive_configured = bool(_gci or os.environ.get("GOOGLE_CLIENT_ID"))
    gdrive_connected = False
    gdrive_email = ""
    try:
        from database import get_setting
        gdrive_token = get_setting("google_oauth_token")
        if gdrive_token:
            gdrive_connected = True
            try:
                import json as _json
                token_data = _json.loads(gdrive_token)
                gdrive_email = token_data.get("client_id", "")[:20] + "..."
            except Exception:
                pass
    except Exception:
        pass

    api_keys = {
        "laozhang": bool(os.environ.get("LAOZHANG_API_KEY")),
        "laozhang_masked": (os.environ.get("LAOZHANG_API_KEY", "")[:8] + "...") if os.environ.get("LAOZHANG_API_KEY") else "",
        "youtube": False,
        "youtube_masked": "",
        "gdrive": gdrive_connected,
        "gdrive_configured": gdrive_configured,
        "gdrive_status": "Conectado" if gdrive_connected else ("OAuth configurado" if gdrive_configured else "Nao configurado"),
    }
    # Check YouTube API key from DB
    try:
        from database import get_setting
        yt_key = get_setting("youtube_api_key") or ""
        api_keys["youtube"] = bool(yt_key)
        api_keys["youtube_masked"] = (yt_key[:8] + "...") if yt_key else ""
    except Exception:
        pass

    # Check DataForSEO credentials
    try:
        from database import get_setting as _gs
        dfs_login = _gs("dataforseo_login") or os.environ.get("DATAFORSEO_LOGIN", "")
        dfs_pass = _gs("dataforseo_password") or os.environ.get("DATAFORSEO_PASSWORD", "")
        api_keys["dataforseo"] = bool(dfs_login and dfs_pass)
        api_keys["dataforseo_masked"] = (dfs_login[:8] + "...") if dfs_login else ""
    except Exception:
        api_keys["dataforseo"] = False
        api_keys["dataforseo_masked"] = ""

    # Check ImageFX cookie (Fernet-encrypted in admin_settings)
    try:
        from protocols.imagefx_client import get_imagefx_cookie
        ifx_cookie = get_imagefx_cookie()
        api_keys["imagefx"] = bool(ifx_cookie)
        api_keys["imagefx_masked"] = ("•" * 20) if ifx_cookie else ""
    except Exception:
        api_keys["imagefx"] = False
        api_keys["imagefx_masked"] = ""

    # AI Usage stats
    ai_usage = {"total_tokens": 0, "total_cost": 0, "total_calls": 0, "by_project": [], "by_operation": []}
    try:
        from database import get_ai_usage_summary
        ai_usage = get_ai_usage_summary()
    except Exception:
        pass

    from database import get_setting
    admin_ai_model = get_setting("admin_ai_model") or "claude-sonnet-4-6"

    return render(request, "admin_panel.html", {
        "user": user,
        "stats": stats,
        "users": users,
        "projects": projects[:10],
        "activity": activity,
        "api_keys": api_keys,
        "ai_usage": ai_usage,
        "admin_ai_model": admin_ai_model,
    })


# ══════════════════════════════════════════════════════════
# STUDENT ROUTES — moved to routes/student_routes.py
# ══════════════════════════════════════════════════════════


# ── Entry point ──────────────────────────────────────────

def run_dashboard(port: int = PORT):
    import uvicorn
    logger.info(f"Dashboard: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=LOG_LEVEL)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_dashboard(port)
