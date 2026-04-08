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

    # One-time project imports from output/import_*.json
    try:
        _import_dir = OUTPUT_DIR
        for _imp_file in sorted(PROJECT_DIR.glob("output/import_*.json")):
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


@app.post("/api/admin/link-channel-project")
@limiter.limit("20/minute")
async def api_link_channel_project(request: Request, user=Depends(require_admin)):
    """Link a student channel to a project. Also creates/updates assignment to sync."""
    body = await request.json()
    channel_id = body.get("channel_id")
    project_id = body.get("project_id", "").strip()
    student_id = body.get("student_id")

    if not channel_id or not project_id or not student_id:
        return JSONResponse({"error": "channel_id, project_id e student_id obrigatorios"}, status_code=400)

    from database import get_project, get_db, create_assignment, log_activity
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    niche = proj.get("niche_chosen", proj["name"])

    try:
        # Step 1: Update channel → project link
        with get_db() as conn:
            conn.execute(
                "UPDATE student_channels SET project_id=?, niche=? WHERE id=? AND student_id=?",
                (project_id, niche, int(channel_id), int(student_id)),
            )

        # Step 2: Check/create assignment (separate connection to avoid deadlock)
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
                (int(student_id), project_id),
            ).fetchone()

        if not existing:
            aid = create_assignment(int(student_id), project_id, niche, 5)
            log_activity(project_id, "channel_project_linked",
                         f"Canal {channel_id} vinculado + assignment {aid} criado com 5 titulos")
        else:
            log_activity(project_id, "channel_project_linked",
                         f"Canal {channel_id} vinculado ao projeto (assignment ja existe)")

        return JSONResponse({"ok": True, "project_name": proj["name"]})
    except Exception as e:
        logger.error(f"link-channel-project error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao vincular projeto ao canal."}, status_code=500)


@app.post("/api/admin/assign-project")
@limiter.limit("20/minute")
async def api_assign_project(request: Request, user=Depends(require_admin)):
    """Assign or change the project linked to a student assignment."""
    body = await request.json()
    assignment_id = body.get("assignment_id")
    project_id = body.get("project_id", "").strip()

    if not assignment_id or not project_id:
        return JSONResponse({"error": "assignment_id e project_id obrigatorios"}, status_code=400)

    from database import get_db, get_project
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE assignments SET project_id=?, niche=? WHERE id=?",
                (project_id, proj.get("niche_chosen", proj["name"]), int(assignment_id)),
            )
        from database import log_activity
        log_activity(project_id, "project_assigned", f"Projeto atribuido ao assignment {assignment_id}")
        return JSONResponse({"ok": True, "project_name": proj["name"]})
    except Exception as e:
        logger.error(f"assign-project error: {e}")
        return JSONResponse({"error": "Falha ao atribuir projeto."}, status_code=500)


@app.post("/api/admin/create-assignment")
@limiter.limit("10/minute")
async def api_create_assignment(request: Request, user=Depends(require_admin)):
    """Create a new assignment for a student with a specific project."""
    body = await request.json()
    student_id = body.get("student_id")
    project_id = body.get("project_id", "").strip()
    niche = body.get("niche", "").strip()
    titles_count = int(body.get("titles_count", 5))

    if not student_id or not project_id:
        return JSONResponse({"error": "student_id e project_id obrigatorios"}, status_code=400)

    from database import get_project, create_assignment
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    if not niche:
        niche = proj.get("niche_chosen", proj["name"])

    try:
        aid = create_assignment(int(student_id), project_id, niche, titles_count)
        from database import log_activity
        log_activity(project_id, "assignment_created", f"Aluno {student_id} atribuido com {titles_count} titulos")
        return JSONResponse({"ok": True, "assignment_id": aid})
    except Exception as e:
        logger.error(f"create-assignment error: {e}")
        return JSONResponse({"error": "Falha ao criar atribuicao."}, status_code=500)


@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request, user=Depends(require_auth), first: str = ""):
    """Page where the student (or any user) can change their own password."""
    must = bool(user.get("must_change_password")) or first == "1"
    return render(
        request,
        "change_password.html",
        {"must_change": must, "user_email": user.get("email", "")},
    )


@app.post("/api/change-password")
@limiter.limit("5/minute")
async def api_change_password(request: Request, user=Depends(require_auth)):
    """Change the current user's password. Clears the must_change_password flag."""
    body = await request.json()
    new_pw = (body.get("new_password") or "").strip()
    confirm = (body.get("confirm_password") or "").strip()
    if not new_pw or len(new_pw) < 8:
        return JSONResponse({"error": "Nova senha deve ter no minimo 8 caracteres"}, status_code=400)
    if new_pw != confirm:
        return JSONResponse({"error": "Senhas nao coincidem"}, status_code=400)
    if new_pw == user.get("email", ""):
        return JSONResponse({"error": "A nova senha nao pode ser igual ao email"}, status_code=400)

    from database import change_user_password
    ok = change_user_password(int(user["id"]), new_pw)
    if not ok:
        return JSONResponse({"error": "Falha ao alterar senha"}, status_code=500)

    redirect = "/" if user.get("role") == "admin" else "/student"
    return JSONResponse({"ok": True, "redirect": redirect})


@app.post("/api/admin/create-student")
@limiter.limit("10/minute")
async def api_create_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    password = (body.get("password") or "").strip()
    niche = (body.get("niche") or "").strip()
    project_id = body.get("project_id", "")

    if not name or len(name) < 2:
        return JSONResponse({"error": "Nome deve ter pelo menos 2 caracteres"}, status_code=400)
    if not email or "@" not in email:
        return JSONResponse({"error": "Email invalido"}, status_code=400)

    # Default password = email when admin doesn't supply one. Student is forced
    # to change it on first login (must_change_password=1).
    must_change = False
    if not password:
        password = email
        must_change = True
    elif password == email:
        must_change = True
    elif len(password) < 12:
        return JSONResponse({"error": "Senha deve ter pelo menos 12 caracteres"}, status_code=400)

    from database import create_user, create_assignment
    uid = create_user(
        name,
        email,
        password,
        role="student",
        created_by=user.get("id"),
        must_change_password=must_change,
    )
    if not uid:
        return JSONResponse({"error": "Email ja cadastrado"}, status_code=400)

    assignment_id = None
    if niche and project_id:
        assignment_id = create_assignment(uid, project_id, niche)

    # Welcome notification
    try:
        from database import create_notification
        create_notification(uid, "welcome", "Bem-vindo ao YT Channel Cloner!",
            f"Seu acesso foi criado. Nicho: {niche or 'a definir'}. Configure sua API key para comecar a gerar roteiros.",
            "/student")
    except Exception:
        pass

    # Google Drive folder for student (auto-sync)
    # Uses get_or_create_student_folder which puts "Aluno - {name}" inside
    # the admin root "YT Cloner" folder — consistent with connect-drive flow
    # and prevents duplicate flat folders at Drive root.
    drive_folder_id = ""
    try:
        from protocols.google_export import get_or_create_student_folder, share_folder
        from database import update_user, log_activity
        drive_folder_id = get_or_create_student_folder(name)
        share_folder(drive_folder_id, email, role="writer")
        update_user(uid, drive_folder_id=drive_folder_id)
        log_activity(project_id or "", "drive_student_folder",
                     f"Pasta Drive criada para aluno {name}: {drive_folder_id}")
        logger.info(f"[CREATE-STUDENT] Drive folder {drive_folder_id} (Aluno - {name}) created and shared with {email}")
    except Exception as e:
        logger.warning(f"[CREATE-STUDENT] Drive folder creation failed (student created without Drive): {e}")

    return JSONResponse({"ok": True, "user_id": uid, "assignment_id": assignment_id})


@app.post("/api/admin/analyze-channel")
@limiter.limit("3/minute")
async def api_admin_analyze_channel(request: Request, user=Depends(require_admin)):
    """Full channel analysis pipeline: SOP → Niches → Titles → SEO → Mind Map.

    Two modes:
    - Channel mode (default): requires url — runs transcript analysis, SOP from channel
    - Template mode (template_mode=true): url optional — creates reusable niche template
      that can be assigned to multiple students without a linked YouTube channel
    """
    body = await request.json()
    template_mode = bool(body.get("template_mode", False))
    url = validate_url(body.get("url", "")) if body.get("url") else ""
    niche_name = sanitize_niche_name(body.get("niche_name", ""))
    nlm_sop = (body.get("nlm_sop") or "").strip()
    language = (body.get("language") or "pt-BR").strip()

    # Validate language
    VALID_LANGS = {"pt-BR", "en", "es", "fr", "de", "it", "ja", "ko"}
    if language not in VALID_LANGS:
        language = "pt-BR"

    # Language labels for AI prompts
    from config import LANG_LABELS
    lang_label = LANG_LABELS.get(language, language)
    lang_instruction = f"\n\nIMPORTANTE: Todo o conteudo deve ser gerado em {lang_label}."

    if not template_mode and not url:
        return JSONResponse({"error": "URL invalida"}, status_code=400)
    if not niche_name or len(niche_name) < 2:
        return JSONResponse({"error": "Nome do nicho invalido (min 2 caracteres)"}, status_code=400)

    mode_label = "TEMPLATE" if template_mode else "CHANNEL"
    logger.info(f"[ANALYZE:{mode_label}] {user.get('email')}: url={url[:80] or '(none)'}, niche={niche_name}, lang={language}, nlm_sop={len(nlm_sop)} chars")

    import asyncio

    def _run_pipeline():
        """Run the entire pipeline in a thread so health checks keep responding."""
        from database import create_project, save_niche, save_idea, save_file, log_activity, update_project
        from protocols.ai_client import chat
        from progress_store import update_progress, clear_progress

        TOTAL_STEPS = 12

        def _step(n, label, detail=""):
            update_progress(f"pipeline_{niche_name}", n, TOTAL_STEPS, label, detail)
            logger.info(f"[ANALYZE] Step {n}/{TOTAL_STEPS}: {label}")

        _step(1, "Criando projeto", niche_name)

        # Step 1: Create project
        project_id = create_project(name=niche_name, channel_original=url, niche_chosen=niche_name,
                                     meta={"channel_url": url, "niche": niche_name, "created_by": user["id"], "language": language},
                                     language=language)

        # Step 1b: Google Drive folder
        drive_folder_id = ""
        try:
            from protocols.google_export import get_or_create_project_folder
            drive_folder_id = get_or_create_project_folder(niche_name)
            update_project(project_id, drive_folder_id=drive_folder_id,
                          drive_folder_url=f"https://drive.google.com/drive/folders/{drive_folder_id}")
            logger.info(f"[ANALYZE] Drive folder: {drive_folder_id}")
        except Exception as e:
            logger.warning(f"[ANALYZE] Drive folder creation failed (projeto continua sem Drive): {e}")

        _step(2, 'Gerando SOP', 'Analisando canal e transcricoes...')

        # Step 2: Generate SOP (Manual paste → Transcripts → AI fallback)
        sop_content = ""
        sop_source = "AI"

        # Priority 1: User pasted manual SOP
        if nlm_sop and len(nlm_sop) > 200:
            sop_content = nlm_sop
            sop_source = "Manual"
            logger.info(f"[ANALYZE] Using pasted SOP: {len(sop_content)} chars")

        # Priority 2: Transcripts + AI (skipped in template mode — no URL)
        if not sop_content and url:
            logger.info(f"[ANALYZE] Trying transcript analysis for {url}")
            sop_content = analyze_via_transcripts(url, niche_name)
            if sop_content and len(sop_content) > 200:
                sop_source = "Transcricoes"
                logger.info(f"[ANALYZE] Transcript SOP: {len(sop_content)} chars")

        if not sop_content:
            # Template mode: no URL context, generate pure niche-based SOP
            _url_line = f"URL: {url}\n" if url else ""
            _intro = (
                "Analise o conceito deste canal do YouTube e crie um SOP COMPLETO com as 17 secoes padrao."
                if url else
                f"Crie um SOP COMPLETO com as 17 secoes padrao para um canal faceless do YouTube no nicho '{niche_name}'. "
                f"Este e um TEMPLATE de nicho validado que sera usado por multiplos criadores — nao ha canal de referencia, "
                f"voce deve projetar o canal ideal para este nicho com base nas melhores praticas do segmento."
            )
            sop_prompt = f"""{_intro}

{_url_line}Nicho: {niche_name}

Crie um SOP (Standard Operating Procedure) com TODAS essas 17 secoes, cada uma DETALHADA e especifica para o nicho:

## Parte 1/5 — Autopsia do Canal

### 1. IDENTIDADE PROFUNDA
- Nicho EXATO e sub-nicho
- Publico-alvo (idade/genero, interesses, DORES, DESEJOS)
- Proposta de valor UNICA
- Tom de voz (5 frases reais que exemplificam)
- Persona do narrador
- 10 expressoes/palavras tipicas do canal

### 2. FORMATO E PRODUCAO
- Duracao ideal
- Frequencia ideal
- Estilo visual exato (renderizacao, DOF, iluminacao, camera, movimentos)
- Estrutura de producao (passos concretos)

### 3. ANATOMIA DO ROTEIRO
- Tabela de atos/blocos com tempo e descricao
- Cenas obrigatorias em todo video
- Cenas PROIBIDAS

### 4. PLAYBOOK DE HOOKS
- 8 tipos de ganchos com exemplos e percentual de uso
- Regras dos hooks

### 5. TECNICAS DE STORYTELLING
- Minimo 8 tecnicas numeradas com explicacao detalhada

### 6. REGRAS DE OURO
- 15 regras INVIOLAVEIS numeradas

### 7. PILARES DE CONTEUDO
- 5-7 pilares com percentual de uso e exemplos

### 8. FORMULA DE TITULOS
- 5 templates com 3 exemplos cada
- Keywords obrigatorias
- Palavras capitalizadas de enfase

### 9. THUMBNAIL
- Regras visuais detalhadas
- O que NAO fazer

### 10. SEO E METADADOS
- Tags obrigatorias (20+)
- Descricao template completo
- Categoria YouTube, idioma, captions

### 11. MONETIZACAO E RPM
- RPM/CPM esperados
- 7+ estrategias de monetizacao

### 12. RETENCAO E ENGAJAMENTO
- Estrategias de retencao
- Estrategias de engajamento

### 13. COMPETIDORES E INTELIGENCIA DE MERCADO
- 5+ canais competidores
- Diferenciais do nosso canal
- Tendencias do nicho

### 14. EVOLUCAO DO CANAL
- Plano mes 1-2, 3-4, 5-6, 6-12, ano 1+

### 15. SYSTEM PROMPT COMPLETO
- Prompt pronto para copiar e colar na IA (minimo 300 palavras)
- Contexto do canal, regras invioláveis, estrutura, vocabulario

### 16. TEMPLATE DE ROTEIRO PREENCHIVEL
- Template cena-a-cena pronto para preencher

### 17. CHECKLIST — 15 PERGUNTAS SIM/NAO
- 15 perguntas binarias para validar qualidade antes de publicar

Seja EXTREMAMENTE detalhado. Cada secao deve ter ao menos 200 palavras. SOP total minimo: 4000 palavras. Especifico para o nicho "{niche_name}".{lang_instruction}"""
            sop_content = chat(sop_prompt, system="Voce e um estrategista de canais faceless do YouTube com 10 anos de experiencia. Sua especialidade e criar SOPs (Standard Operating Procedures) ultra detalhados de 17 secoes que servem como DNA para replicar e elevar canais bem-sucedidos.", max_tokens=MAX_TOKENS_LARGE)

        save_file(project_id, "analise", f"SOP - {niche_name}", f"sop_{project_id}.md", sop_content)
        log_activity(project_id, "sop_generated", f"SOP via {sop_source}")

        _step(3, 'Gerando 5 nichos derivados')

        # Step 3: Generate 5 niches
        _channel_ref = f'"{niche_name}" ({url})' if url else f'"{niche_name}" (template de nicho, sem canal de referencia)'
        niche_prompt = f"""Baseado neste canal {_channel_ref}, gere 5 sub-nichos derivados.
SOP: {sop_content[:3000]}
Retorne JSON: [{{"name":"...","description":"...","rpm_range":"$X-Y","competition":"Baixa/Media/Alta","color":"#hex","pillars":["..."]}}]
Retorne APENAS o JSON.{lang_instruction}"""

        niche_response = chat(niche_prompt, max_tokens=2000, temperature=0.7)
        niche_json_match = re.search(r'\[.*\]', niche_response, re.DOTALL)
        niche_colors = ["#e040fb", "#448aff", "#ff5252", "#ffd740", "#00e5ff"]
        niches_generated = 0
        niche_list = []

        if niche_json_match:
            try:
                niche_list = json.loads(niche_json_match.group())
                for i, n in enumerate(niche_list[:5]):
                    save_niche(project_id, n.get("name", f"Nicho {i+1}"), n.get("description", ""),
                              n.get("rpm_range", ""), n.get("competition", ""),
                              n.get("color", niche_colors[i % 5]), chosen=(i == 0), pillars=n.get("pillars", []))
                    niches_generated += 1
            except (json.JSONDecodeError, Exception):
                save_niche(project_id, niche_name, "Nicho principal", chosen=True, color="#e040fb")
                niches_generated = 1
        else:
            save_niche(project_id, niche_name, "Nicho principal", chosen=True, color="#e040fb")
            niches_generated = 1

        log_activity(project_id, "niches_generated", f"{niches_generated} nichos")

        _step(4, 'Pesquisando demanda real + gerando 30 titulos', 'YouTube + Google Trends...')

        # Step 4a: PRE-RESEARCH — collect real demand data
        demand_summary = ""
        try:
            from protocols.trend_research import research_niche_demand
            yt_key = ""
            with get_db() as conn:
                yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
                if yt_row:
                    yt_key = yt_row["value"]
            demand_data = research_niche_demand(niche_name, language, yt_key)
            demand_summary = demand_data.get("summary", "")
            if demand_summary:
                logger.info(f"[PIPELINE] Pre-research: {len(demand_data.get('trending_titles', []))} titles, "
                           f"{len(demand_data.get('rising_searches', []))} trends, "
                           f"{len(demand_data.get('trending_keywords', []))} keywords")
        except Exception as e:
            logger.warning(f"[PIPELINE] Pre-research failed (non-blocking): {e}")

        # Step 4b: Generate 30 titles — based on CHOSEN niches + REAL demand data
        chosen_niches = []
        try:
            db_niches = get_niches(project_id)
            chosen_niches = [{"name": n["name"], "description": n.get("description", "")} for n in db_niches if n.get("chosen")]
        except Exception:
            pass
        if not chosen_niches:
            chosen_niches = niche_list[:2] if niche_list else [{"name": niche_name, "description": ""}]

        chosen_niches_text = "\n".join([
            f"- {n.get('name', '')}: {n.get('description', '')}" for n in chosen_niches
        ])

        titles_prompt = f"""Gere 30 ideias de videos para o canal "{niche_name}".

SUB-NICHOS ESCOLHIDOS (os titulos DEVEM ser sobre estes sub-nichos APENAS):
{chosen_niches_text}

{demand_summary}

IMPORTANTE:
- Todos os 30 titulos EXCLUSIVAMENTE sobre os sub-nichos listados acima
- Use as KEYWORDS DE ALTA FREQUENCIA da pre-pesquisa nos titulos
- Siga os PADROES DE TITULO que funcionam (numeros, perguntas, CAPS, etc)
- Cada titulo deve combinar DEMANDA REAL + estilo do SOP
- Distribua igualmente entre os sub-nichos escolhidos

SOP do canal (referencia de tom e estilo):
{sop_content[:3000]}

REGRAS OBRIGATORIAS DO YOUTUBE:
- CADA titulo DEVE ter no MAXIMO 100 caracteres (incluindo espacos)
- Titulos devem ser impactantes mesmo sendo curtos

Retorne JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"nome do sub-nicho","priority":"ALTA"}}]
O campo "pillar" DEVE ser o nome do sub-nicho correspondente.
Misture: ~10 ALTA, ~12 MEDIA, ~8 BAIXA. Titulos VIRAIS. Retorne APENAS o JSON.{lang_instruction}"""

        titles_response = chat(titles_prompt, max_tokens=6000, temperature=0.8)
        titles_json_match = re.search(r'\[.*\]', titles_response, re.DOTALL)
        titles_generated = 0

        if not titles_json_match:
            retry_prompt = f'Gere 10 ideias de videos para "{niche_name}". Retorne APENAS JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"...","priority":"ALTA"}}]{lang_instruction}'
            titles_response = chat(retry_prompt, max_tokens=MAX_TOKENS_MEDIUM, temperature=0.7)
            titles_json_match = re.search(r'\[.*\]', titles_response, re.DOTALL)

        if titles_json_match:
            try:
                ideas_list = json.loads(titles_json_match.group())
                for i, idea in enumerate(ideas_list[:30]):
                    title = idea.get("title", f"Titulo {i+1}")
                    # save_idea() enforces 100-char limit via enforce_title_limit()
                    save_idea(project_id, i + 1, title,
                             idea.get("hook", ""), idea.get("summary", ""),
                             idea.get("pillar", ""), idea.get("priority", "MEDIA"))
                    titles_generated += 1
            except (json.JSONDecodeError, Exception):
                pass

        log_activity(project_id, "titles_generated", f"{titles_generated} titulos")

        _step(5, 'Gerando SEO + Thumbnails + Music + Teasers', 'Executando 4 tarefas em paralelo...')

        # ── Steps 5-8: SEO, Thumbnails, Music, Teasers (PARALLEL) ──
        import concurrent.futures

        # Pre-compute shared data for parallel tasks
        top5 = json.loads(titles_json_match.group())[:5] if titles_json_match else []
        titles_for_thumb = "\n".join([f'{i+1}. {t.get("title","")}' for i, t in enumerate(top5)])
        seo_generated = 0

        def _gen_seo():
            if not titles_json_match:
                return None
            top_titles = json.loads(titles_json_match.group())[:10]
            titles_block = "\n".join([f'{i+1}. {t.get("title", "")}' for i, t in enumerate(top_titles)])
            seo_prompt = f"""Gere SEO pack para estes 10 videos do canal "{niche_name}":
{titles_block}

SOP DO CANAL (referencia de tom, vocabulario e estilo):
{sop_content[:2000]}

REGRAS OBRIGATORIAS DO YOUTUBE:
- Tags: o TOTAL de TODAS as tags de cada video NAO pode ultrapassar 500 caracteres. Use 10-12 tags relevantes e curtas.
- Titulo: max 100 caracteres.
- Descricao: 150-200 palavras. OBRIGATORIO incluir no FINAL da descricao: "⚠️ Este conteudo foi produzido com auxilio de inteligencia artificial. As narrativas apresentadas sao reconstituicoes ficcionais baseadas em fatos e pesquisas, com fins de entretenimento e educacao."

Para CADA video: 3 variacoes de titulo (max 100 chars cada), descricao YouTube (com disclaimer no final), tags (max 500 chars total), 5 hashtags.{lang_instruction}"""
            return chat(seo_prompt, system="Especialista em YouTube SEO.", max_tokens=MAX_TOKENS_LARGE, temperature=0.7)

        def _gen_thumbnails():
            thumb_prompt = f"""Crie prompts de thumbnail para Midjourney e DALL-E para estes 5 videos do canal "{niche_name}":
{titles_for_thumb}

SOP resumido: {sop_content[:1500]}

Para CADA video gere:
- 1 prompt Midjourney (estilo cinematografico, dark, POV)
- 1 prompt DALL-E (mesmo conceito, adaptado)
- Paleta de cores sugerida (hex)
- Texto overlay sugerido (1-2 palavras max)
- Composicao (descricao do layout){lang_instruction}"""
            return chat(thumb_prompt, system="Especialista em thumbnails virais do YouTube.", max_tokens=4000, temperature=0.7)

        def _gen_music():
            music_prompt = f"""Crie prompts de musica de fundo para videos do canal "{niche_name}" para plataformas Suno AI, Udio e MusicGPT.

SOP resumido: {sop_content[:1500]}

Gere:
- 5 prompts para Suno AI (dark ambient, cinematic tension, suspense)
- 3 prompts para Udio (atmospheric, moody, dramatic)
- Tags de estilo: genero, mood, instrumentos, BPM
- Quando usar cada tipo de musica no video (hook, tensao, climax, reflexao)
- Efeitos sonoros sugeridos (SFX) para momentos-chave{lang_instruction}"""
            return chat(music_prompt, system="Compositor de trilha sonora para YouTube.", max_tokens=3000, temperature=0.7)

        def _gen_teasers():
            teaser_prompt = f"""Crie scripts de Teaser/Shorts para YouTube Shorts, Instagram Reels e TikTok para o canal "{niche_name}".

SOP resumido: {sop_content[:1500]}
Top 5 titulos: {titles_for_thumb if titles_json_match else niche_name}

Para CADA um dos 5 videos:
- Hook de 3 segundos (primeira frase que para o scroll)
- Script completo de 30-60 segundos (150-200 palavras)
- CTA para o video completo ("Video completo no canal")
- Hashtags sugeridas (10)
- Melhor horario para postar
- Formato: vertical 9:16{lang_instruction}"""
            return chat(teaser_prompt, system="Especialista em conteudo short-form viral.", max_tokens=4000, temperature=0.7)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_seo = executor.submit(_gen_seo)
            future_thumb = executor.submit(_gen_thumbnails)
            future_music = executor.submit(_gen_music)
            future_teaser = executor.submit(_gen_teasers)

            # Collect SEO result
            try:
                seo_content = future_seo.result(timeout=240)
                if seo_content and len(seo_content) > 100:
                    save_file(project_id, "seo", "SEO Pack", f"seo_pack_{project_id}.md", seo_content)
                    seo_generated = 10
                    log_activity(project_id, "seo_generated", f"SEO Pack para {seo_generated} videos")
                _step(5, 'SEO Pack concluido', f'{seo_generated} videos')
            except Exception as e:
                logger.error(f"SEO generation failed: {e}")

            # Collect Thumbnail result
            try:
                thumb_content = future_thumb.result(timeout=240)
                if thumb_content and len(thumb_content) > 100:
                    save_file(project_id, "outros", "Thumbnail Prompts - Midjourney DALL-E", f"thumbnail_prompts_{project_id}.md", thumb_content)
                    log_activity(project_id, "thumbnail_prompts", "Thumbnail Prompts gerados")
                _step(6, 'Thumbnail Prompts concluidos', 'Midjourney + DALL-E')
            except Exception as e:
                logger.error(f"Thumbnail prompts failed: {e}")

            # Collect Music result
            try:
                music_content = future_music.result(timeout=240)
                if music_content and len(music_content) > 100:
                    save_file(project_id, "outros", "Music Prompts - Suno Udio MusicGPT", f"music_prompts_{project_id}.md", music_content)
                    log_activity(project_id, "music_prompts", "Music Prompts gerados")
                _step(7, 'Music Prompts concluidos', 'Suno + Udio + MusicGPT')
            except Exception as e:
                logger.error(f"Music prompts failed: {e}")

            # Collect Teaser result
            try:
                teaser_content = future_teaser.result(timeout=240)
                if teaser_content and len(teaser_content) > 100:
                    save_file(project_id, "outros", "Teaser Prompts - Shorts Reels TikTok", f"teaser_prompts_{project_id}.md", teaser_content)
                    log_activity(project_id, "teaser_prompts", "Teaser Prompts gerados")
                _step(8, 'Teaser Prompts concluidos', 'Shorts + Reels + TikTok')
            except Exception as e:
                logger.error(f"Teaser prompts failed: {e}")

        # ── Disclaimer / Aviso Legal ──
        LANG_DISCLAIMERS = {
            "pt-BR": "⚠️ AVISO LEGAL — DISCLAIMER\n\nEste conteudo foi produzido com auxilio de inteligencia artificial.\nAs narrativas apresentadas sao reconstituicoes ficcionais baseadas em fatos reais e pesquisas, com fins de entretenimento e educacao.\nNenhuma informacao deve ser interpretada como conselho profissional, legal, medico ou financeiro.\n\n📋 USAR NA DESCRICAO DE CADA VIDEO:\n\"⚠️ Este conteudo foi produzido com auxilio de inteligencia artificial. As narrativas apresentadas sao reconstituicoes ficcionais baseadas em fatos reais e pesquisas, com fins de entretenimento e educacao.\"\n\n🎙️ FALAR NO FINAL DE CADA VIDEO:\n\"Este conteudo foi produzido com auxilio de inteligencia artificial. As narrativas sao reconstituicoes ficcionais baseadas em fatos reais, com fins de entretenimento e educacao.\"",
            "en": "⚠️ LEGAL DISCLAIMER\n\nThis content was produced with the assistance of artificial intelligence.\nThe narratives presented are fictional reconstructions based on real facts and research, for entertainment and educational purposes only.\nNo information should be interpreted as professional, legal, medical or financial advice.\n\n📋 USE IN EVERY VIDEO DESCRIPTION:\n\"⚠️ This content was produced with the assistance of artificial intelligence. The narratives presented are fictional reconstructions based on real facts and research, for entertainment and educational purposes.\"\n\n🎙️ SAY AT THE END OF EVERY VIDEO:\n\"This content was produced with the assistance of artificial intelligence. The narratives are fictional reconstructions based on real facts, for entertainment and educational purposes.\"",
            "es": "⚠️ AVISO LEGAL — DISCLAIMER\n\nEste contenido fue producido con asistencia de inteligencia artificial.\nLas narrativas presentadas son reconstrucciones ficticias basadas en hechos reales e investigaciones, con fines de entretenimiento y educacion.\nNinguna informacion debe interpretarse como consejo profesional, legal, medico o financiero.\n\n📋 USAR EN LA DESCRIPCION DE CADA VIDEO:\n\"⚠️ Este contenido fue producido con asistencia de inteligencia artificial. Las narrativas presentadas son reconstrucciones ficticias basadas en hechos reales e investigaciones, con fines de entretenimiento y educacion.\"\n\n🎙️ DECIR AL FINAL DE CADA VIDEO:\n\"Este contenido fue producido con asistencia de inteligencia artificial. Las narrativas son reconstrucciones ficticias basadas en hechos reales, con fines de entretenimiento y educacion.\"",
        }
        disclaimer_text = LANG_DISCLAIMERS.get(language, LANG_DISCLAIMERS.get(language[:2], LANG_DISCLAIMERS["en"]))
        save_file(project_id, "outros", "Disclaimer - Aviso Legal (IA)", f"disclaimer_{project_id}.md", disclaimer_text)

        _step(9, 'Gerando 3 roteiros completos', 'Executando 3 roteiros em paralelo...')

        # ── Step 10: Generate 3 Roteiros for top titles (PARALLEL) ──
        roteiros_count = 0
        try:
            top3 = json.loads(titles_json_match.group())[:3] if titles_json_match else []
            valid_titles = [(i, title_data.get("title", "")) for i, title_data in enumerate(top3) if title_data.get("title", "")]

            def _gen_roteiro(idx, t):
                roteiro_prompt = f"""Escreva um roteiro COMPLETO para o video "{t}" do canal "{niche_name}".

SOP DO CANAL:
{sop_content[:3000]}

INSTRUCOES:
- Siga EXATAMENTE o estilo, tom e estrutura do SOP
- Duracao: 15-20 minutos de narracao (~2500-3500 palavras)
- Estrutura em Levels (gamificacao)
- Hook nos primeiros 5 segundos
- Open loops, pattern interrupts, specific spikes
- Sem CTA explicito (imersao total)
- Inclua marcacoes: [MUSICA: tipo], [SFX: descricao], [B-ROLL: descricao]
- Fechamento fatalista e ciclico
- OBRIGATORIO: Inclua no FINAL do roteiro (depois do fechamento) um disclaimer lido pelo narrador:
  "Este conteudo foi produzido com auxilio de inteligencia artificial. As narrativas sao reconstituicoes ficcionais baseadas em fatos reais e pesquisas, com fins de entretenimento e educacao."{lang_instruction}"""
                return chat(roteiro_prompt, system="Roteirista de elite para YouTube faceless.", max_tokens=MAX_TOKENS_LARGE, temperature=0.8)

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                future_to_title = {
                    executor.submit(_gen_roteiro, i, t): (i, t)
                    for i, t in valid_titles
                }
                for future in concurrent.futures.as_completed(future_to_title):
                    i, t = future_to_title[future]
                    try:
                        roteiro = future.result(timeout=240)
                        if roteiro and len(roteiro) > 500:
                            save_file(project_id, "roteiro", f"Roteiro - {t[:50]}", f"roteiro_{project_id}_{i+1}.md", roteiro)

                            # Also generate narration version (clean, no markers)
                            narracao = re.sub(r'\[.*?\]', '', roteiro)  # Remove [MUSICA:], [SFX:], [B-ROLL:] markers
                            narracao = re.sub(r'\n{3,}', '\n\n', narracao).strip()
                            if narracao:
                                save_file(project_id, "narracao", f"Narracao - {t[:50]}", f"narracao_{project_id}_{i+1}.md", narracao)

                            roteiros_count += 1
                            log_activity(project_id, "roteiro_generated", f"Roteiro {i+1}: {t[:40]}")
                    except Exception as e:
                        logger.error(f"Roteiro {i+1} generation failed: {e}")
        except Exception as e:
            logger.error(f"Roteiros generation failed: {e}")

        _step(10, 'Gerando Mind Map interativo')

        # ── Step 11: Generate Mind Map HTML ──
        mindmap_generated = False
        try:
            mindmap_html = generate_mindmap_html(
                niche_name, url, sop_content,
                niche_list if niche_json_match else [{"name": niche_name}],
                json.loads(titles_json_match.group())[:15] if titles_json_match else [],
                scripts_count=0,
            )
            mindmap_filename = f"mindmap_{project_id}.html"

            # Save to disk
            try:
                mindmap_path = OUTPUT_DIR / mindmap_filename
                mindmap_path.write_text(mindmap_html, encoding="utf-8")
                logger.info(f"Mindmap saved to disk: {mindmap_path} ({len(mindmap_html)} chars)")
            except Exception as disk_err:
                logger.warning(f"Mindmap disk write failed: {disk_err}")

            # Always save to DB (reliable — serves as fallback)
            save_file(project_id, "visual", f"Mind Map - {niche_name}", mindmap_filename, mindmap_html)
            log_activity(project_id, "mindmap_generated", "Mind Map gerado")
            mindmap_generated = True
        except Exception as e:
            logger.error(f"Mindmap generation failed: {type(e).__name__}: {e}")

        _step(11, 'Exportando 14 arquivos pro Drive')

        # ── Step 12: Drive Export — 14 arquivos padrao ──
        drive_exported = 0
        if drive_folder_id:
            try:
                from protocols.google_export import create_doc, create_sheet
                from database import get_niches as _gn, get_ideas as _gi

                def _drive_doc(title, doc_content):
                    nonlocal drive_exported
                    if doc_content and len(doc_content) > 50:
                        try:
                            create_doc(title, doc_content, drive_folder_id)
                            drive_exported += 1
                        except Exception as e:
                            logger.warning(f"Drive doc '{title}': {e}")

                def _drive_sheet(title, data):
                    nonlocal drive_exported
                    if data and len(data) > 1:
                        try:
                            create_sheet(title, data, drive_folder_id)
                            drive_exported += 1
                        except Exception as e:
                            logger.warning(f"Drive sheet '{title}': {e}")

                # 1. SOP (Doc)
                _drive_doc(f"SOP - {niche_name}", sop_content)

                # 2. SEO Pack (Doc)
                seo_file = next((f for f in get_files(project_id) if f.get("category") == "seo"), None)
                if seo_file:
                    _drive_doc(f"SEO Pack - {niche_name} ({seo_generated} videos)", seo_file.get("content", ""))

                # 3-5. Roteiros 1-3 (Docs)
                roteiro_files = [f for f in get_files(project_id) if f.get("category") == "roteiro"]
                for i, rf in enumerate(roteiro_files[:3], 1):
                    _drive_doc(f"Roteiro {i} - {rf.get('label', '').replace('Roteiro - ', '')}", rf.get("content", ""))

                # 6. Thumbnail Prompts (Doc)
                thumb_file = next((f for f in get_files(project_id) if "thumbnail" in f.get("filename", "").lower()), None)
                if thumb_file:
                    _drive_doc("Thumbnail Prompts - Midjourney DALL-E", thumb_file.get("content", ""))

                # 7. Music Prompts (Doc)
                music_file = next((f for f in get_files(project_id) if "music" in f.get("filename", "").lower()), None)
                if music_file:
                    _drive_doc("Music Prompts - Suno Udio MusicGPT", music_file.get("content", ""))

                # 8. Teaser Prompts (Doc)
                teaser_file = next((f for f in get_files(project_id) if "teaser" in f.get("filename", "").lower()), None)
                if teaser_file:
                    _drive_doc("Teaser Prompts - Shorts Reels TikTok", teaser_file.get("content", ""))

                # 9. MIND MAP (Doc)
                if mindmap_generated:
                    _drive_doc(f"MIND MAP - Visao Geral do Projeto", mindmap_html)

                # 10. 30 Ideias (Doc)
                all_ideas = _gi(project_id)
                if all_ideas:
                    ideas_text = f"# 30 Ideias de Videos - {niche_name}\n\n"
                    for idx, idea in enumerate(all_ideas, 1):
                        ideas_text += f"## {idx}. {idea.get('title', '')}\n"
                        ideas_text += f"**Hook:** {idea.get('hook', '')}\n"
                        ideas_text += f"**Resumo:** {idea.get('summary', '')}\n"
                        ideas_text += f"**Pilar:** {idea.get('pillar', '')} | **Prioridade:** {idea.get('priority', '')}\n\n"
                    _drive_doc(f"30 Ideias de Videos - {niche_name}", ideas_text)

                # 11. Titulos (Sheet)
                if all_ideas:
                    td = [["#", "Titulo", "Hook", "Pilar", "Prioridade", "Score"]]
                    for idx, idea in enumerate(all_ideas, 1):
                        td.append([str(idx), idea.get("title",""), idea.get("hook","")[:100],
                                  idea.get("pillar",""), idea.get("priority",""), str(idea.get("score",0))])
                    _drive_sheet(f"Titulos - {niche_name}", td)

                # 12. 5 Nichos Derivados (Sheet)
                _niches = _gn(project_id)
                if _niches:
                    nd = [["Nome", "Descricao", "RPM", "Competicao", "Pilares"]]
                    for n in _niches:
                        pillars_str = ""
                        try:
                            p = n.get("pillars", "")
                            if isinstance(p, str): pillars_str = ", ".join(json.loads(p))
                            elif isinstance(p, list): pillars_str = ", ".join(p)
                        except Exception: pass
                        nd.append([n.get("name",""), n.get("description","")[:100],
                                  n.get("rpm_range",""), n.get("competition",""), pillars_str])
                    _drive_sheet(f"5 Nichos Derivados - Niche Bending", nd)

                # 13. SEO Sheet (Sheet)
                if all_ideas:
                    sd = [["#", "Titulo", "Score", "Rating", "Pilar", "Prioridade"]]
                    for idx, idea in enumerate(all_ideas[:15], 1):
                        sd.append([str(idx), idea.get("title",""), str(idea.get("score",0)),
                                  idea.get("rating",""), idea.get("pillar",""), idea.get("priority","")])
                    _drive_sheet(f"SEO Sheet - Titulos e Tags ({len(sd)-1} videos)", sd)

                # 14. Narracoes Completas (Doc)
                narracao_files = [f for f in get_files(project_id) if f.get("category") == "narracao"]
                if narracao_files:
                    narracao_combined = ""
                    for idx, nf in enumerate(narracao_files[:3], 1):
                        narracao_combined += f"\n{'='*60}\nNARRACAO {idx}: {nf.get('label', '')}\n{'='*60}\n\n"
                        narracao_combined += (nf.get("content", "") or "") + "\n\n"
                    _drive_doc(f"Narracoes Completas - {niche_name} ({len(narracao_files)} roteiros)", narracao_combined)

                log_activity(project_id, "drive_exported", f"{drive_exported}/14 arquivos exportados para Google Drive")
                logger.info(f"[ANALYZE] Drive export: {drive_exported}/14 arquivos")

            except Exception as e:
                logger.warning(f"[ANALYZE] Drive export failed: {e}")

        _step(12, "Pipeline concluido!", f"{niche_name} - Todos os arquivos gerados")

        result = {
            "ok": True,
            "project_id": project_id,
            "sop_source": sop_source,
            "niche_name": niche_name,
            "niches_generated": niches_generated,
            "titles_generated": titles_generated,
            "seo_generated": seo_generated,
            "mindmap_generated": mindmap_generated,
            "drive_folder_id": drive_folder_id,
        }
        clear_progress(f"pipeline_{niche_name}")
        return result

    # Run pipeline in thread so health checks keep responding
    try:
        result = await asyncio.to_thread(_run_pipeline)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"analyze-channel error: {e}")
        from progress_store import clear_progress as _cp
        _cp(f"pipeline_{niche_name}")
        return JSONResponse({"error": "Falha na analise. Tente novamente ou contate o administrador."}, status_code=500)


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


# ─── Channel Mockup (Modelar Canal) ─────────────────────────────────

@app.post("/api/admin/generate-channel-mockup")
@limiter.limit("5/minute")
async def api_generate_channel_mockup(request: Request, user=Depends(require_admin)):
    """
    Generate a complete channel identity mockup for a project's niche.
    Persists as a file with category='mockup' so the student can see it.
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    override_language = (body.get("language") or "").strip()
    # Admin overrides when regenerating — any of these may be empty
    override_niche = (body.get("niche") or "").strip()
    custom_channel_name = (body.get("custom_channel_name") or "").strip()
    custom_tagline = (body.get("custom_tagline") or "").strip()
    custom_description_hint = (body.get("custom_description_hint") or "").strip()
    custom_niche_angle = (body.get("custom_niche_angle") or "").strip()
    extra_instructions = (body.get("extra_instructions") or "").strip()
    reset_images = bool(body.get("reset_images"))
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_project, save_file, get_files, get_ideas
    from services import get_project_sop
    from protocols.channel_mockup import generate_channel_mockup
    import asyncio
    import json as _json

    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    niche_name = override_niche or proj.get("niche_chosen") or proj.get("name", "")
    language = override_language or (proj.get("language") or "pt-BR").strip()
    # Map our internal lang code to country (best-effort)
    country_map = {
        "pt-BR": "BR", "es": "ES", "en": "US", "fr": "FR", "de": "DE",
        "it": "IT", "ja": "JP", "ko": "KR", "zh": "CN", "ru": "RU",
        "ar": "SA", "hi": "IN", "tr": "TR", "nl": "NL",
    }
    country = country_map.get(language, "US")
    sop_excerpt = (get_project_sop(project_id) or "")[:3000]

    # Pull the top 4 SOP-generated titles from the project to seed the mockup
    seed_titles: list[str] = []
    try:
        ideas = get_ideas(project_id) or []
        # Prefer scored ideas first, then fall back to creation order
        ideas_sorted = sorted(ideas, key=lambda i: -(i.get("score") or 0))
        for it in ideas_sorted[:4]:
            t = (it.get("title") or "").strip()
            if t:
                seed_titles.append(t)
    except Exception as e:
        logger.warning(f"generate-channel-mockup: failed to fetch seed titles: {e}")

    try:
        mockup = await asyncio.to_thread(
            generate_channel_mockup,
            niche_name,
            sop_excerpt,
            language,
            country,
            "faceless",
            seed_titles,
            custom_channel_name,
            custom_tagline,
            custom_description_hint,
            custom_niche_angle,
            extra_instructions,
        )
    except Exception as e:
        logger.exception(f"generate-channel-mockup error: {e}")
        return JSONResponse({"error": f"Falha ao gerar mockup: {str(e)[:200]}"}, status_code=500)

    # Persist as a file (overwrite previous mockup if any). By default we keep
    # previously generated images so they survive a "regenerate identity", but
    # when the admin explicitly asks to reset them (reset_images=true) we drop
    # them so the new identity gets a fresh set of logo/banner/thumbs.
    try:
        existing = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
        if existing:
            from database import get_db
            if not reset_images:
                try:
                    prev = _json.loads(existing[0].get("content", "") or "{}")
                    prev_images = prev.get("images") or {}
                    if prev_images:
                        mockup["images"] = prev_images
                except Exception:
                    pass
            with get_db() as conn:
                for f in existing:
                    conn.execute("DELETE FROM files WHERE id=?", (f["id"],))
        save_file(
            project_id,
            "mockup",
            f"Mockup do Canal - {niche_name}",
            f"channel_mockup_{project_id}.json",
            _json.dumps(mockup, ensure_ascii=False, indent=2),
            visible_to_students=True,
        )
    except Exception as e:
        logger.warning(f"generate-channel-mockup: failed to persist file: {e}")

    return JSONResponse({"ok": True, "mockup": mockup})


@app.get("/api/admin/get-channel-mockup")
async def api_get_channel_mockup(request: Request, user=Depends(require_admin), project_id: str = ""):
    """Return the saved mockup for a project, or null if none exists yet."""
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)
    from database import get_files
    import json as _json
    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"ok": True, "mockup": None})
    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
        return JSONResponse({"ok": True, "mockup": mockup})
    except Exception as e:
        return JSONResponse({"error": f"Mockup salvo invalido: {e}"}, status_code=500)


@app.get("/api/admin/mockup-report")
async def api_mockup_report(request: Request, user=Depends(require_admin), project_id: str = ""):
    """
    Render the saved channel mockup as a print-friendly HTML report.
    When opened in a new tab the page auto-triggers window.print() so the
    mentor can save it as PDF and forward to the student.
    """
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    import json as _json
    import html as _html
    from database import get_files, get_project

    proj = get_project(project_id)
    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return HTMLResponse("<h1>Mockup nao encontrado para este projeto.</h1>", status_code=404)
    try:
        m = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return HTMLResponse(f"<h1>Mockup invalido: {_html.escape(str(e))}</h1>", status_code=500)

    def esc(s) -> str:
        return _html.escape(str(s or ""))

    images = m.get("images") or {}
    colors = m.get("colors") or {}
    primary = esc(colors.get("primary") or "#7c3aed")
    accent = esc(colors.get("accent") or "#fbbf24")

    channel_name = esc(m.get("channel_name") or (proj or {}).get("name") or "Canal")
    tagline = esc(m.get("tagline") or "")
    description = esc(m.get("description") or "")
    disclaimer = esc(m.get("disclaimer") or "")
    sub_est = esc(m.get("subscriber_estimate") or "")
    sub_12 = esc(m.get("subscriber_estimate_12m") or "")
    language = esc(m.get("language") or m.get("description_language") or "pt-BR")
    whats_better = esc(m.get("whats_better") or "")
    strategy_edge = esc(m.get("strategy_edge") or "")
    weaknesses = m.get("weaknesses_fixed") or []
    tags = m.get("tags") or []
    hashtags = m.get("hashtags") or []
    keywords = m.get("keywords") or []
    videos = m.get("videos") or []

    banner_pos = esc(m.get("banner_position") or "center")
    banner_html = (
        f'<img src="{esc(images.get("banner"))}" alt="Banner" style="object-position:{banner_pos}" />'
        if images.get("banner")
        else f'<div class="placeholder banner-ph">Banner não gerado</div>'
    )
    logo_html = (
        f'<img src="{esc(images.get("logo"))}" alt="Logo" />'
        if images.get("logo")
        else f'<div class="placeholder logo-ph">Logo</div>'
    )

    videos_html = ""
    for i, v in enumerate(videos[:4]):
        thumb_url = images.get(f"thumb{i}")
        thumb = (
            f'<img src="{esc(thumb_url)}" alt="Thumb {i + 1}" />'
            if thumb_url
            else '<div class="placeholder thumb-ph">Thumb não gerada</div>'
        )
        views = esc(v.get("views_estimate") or "")
        duration = esc(v.get("duration") or "")
        videos_html += f"""
        <div class="video-card">
            <div class="video-thumb">{thumb}<span class="duration-badge">{duration}</span></div>
            <div class="video-meta">
                <div class="video-num">VÍDEO {i + 1:02d}</div>
                <div class="video-title">{esc(v.get("title") or "")}</div>
                <div class="video-views">▶ {views} views previstos</div>
            </div>
        </div>"""

    weaknesses_html = "".join(f'<li><span class="check">✓</span> {esc(w)}</li>' for w in weaknesses[:6])
    tags_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tags[:20])
    hashtags_html = "".join(f'<span class="hashtag">{esc(h)}</span>' for h in hashtags[:15])
    keywords_html = "".join(f'<span class="keyword">{esc(k)}</span>' for k in keywords[:15])

    # Pre-build conditional blocks (Python 3.11 forbids backslashes inside f-string expressions)
    disclaimer_block = f'<div class="disclaimer-card"><div class="disclaimer-icon">⚠</div><div class="disclaimer-text">{disclaimer}</div></div>' if disclaimer else ""
    description_block = f'<section class="block"><div class="block-eyebrow">01 · POSICIONAMENTO</div><h2 class="block-title">A promessa do canal</h2><p class="block-body">{description}</p></section>' if description else ""

    superior_inner = ""
    if whats_better:
        superior_inner += f'<p class="block-body">{whats_better}</p>'
    if weaknesses_html:
        superior_inner += f'<div class="weaknesses-title">Fraquezas do mercado que você corrige</div><ul class="weaknesses">{weaknesses_html}</ul>'
    if strategy_edge:
        superior_inner += f'<div class="strategy-callout"><div class="strategy-label">📈 ESTRATÉGIA DE CRESCIMENTO</div><div class="strategy-body">{strategy_edge}</div></div>'
    superior_block = (
        f'<section class="block"><div class="block-eyebrow">03 · DIFERENCIAL COMPETITIVO</div><h2 class="block-title">Por que este canal vai dominar</h2>{superior_inner}</section>'
        if (whats_better or weaknesses_html)
        else ""
    )

    tags_row = f'<div class="seo-row"><div class="seo-label">🏷️ Tags YouTube · {len(tags)}</div><div class="seo-chips">{tags_html}</div></div>' if tags_html else ""
    hashtags_row = f'<div class="seo-row"><div class="seo-label">#️⃣ Hashtags · {len(hashtags)}</div><div class="seo-chips">{hashtags_html}</div></div>' if hashtags_html else ""
    keywords_row = f'<div class="seo-row"><div class="seo-label">🔑 Keywords · {len(keywords)}</div><div class="seo-chips">{keywords_html}</div></div>' if keywords_html else ""
    seo_block = f'<section class="block"><div class="block-eyebrow">04 · SEO PACK</div><h2 class="block-title">Otimização para o algoritmo</h2><p class="block-body small">Conjunto pronto pra colar no YouTube Studio. Tudo no idioma do canal e calibrado pro nicho.</p>{tags_row}{hashtags_row}{keywords_row}</section>' if (tags_html or hashtags_html or keywords_html) else ""

    # Convert "#hex" → "r,g,b" for rgba() interpolation in CSS
    def _hex_to_rgb_str(hex_color: str, fallback: str = "251,191,36") -> str:
        h = (hex_color or "").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            return fallback
        try:
            return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
        except ValueError:
            return fallback

    accent_rgb = _hex_to_rgb_str(colors.get("accent") or "#fbbf24", "251,191,36")
    primary_rgb = _hex_to_rgb_str(colors.get("primary") or "#7c3aed", "124,58,237")

    handle = channel_name.lower().replace(" ", "")
    sub_6_display = sub_est or "—"
    sub_12_display = sub_12 or "—"
    rpm_avg_raw = m.get("rpm_estimate") or ""
    rpm_max_raw = m.get("rpm_max") or ""
    rpm_currency = esc(m.get("rpm_currency") or "USD")
    monthly_views_display = esc(m.get("monthly_views_estimate") or "—")
    adsense_display = esc(m.get("adsense_monthly_estimate") or "—")

    # ── Path to first $1,000 ─────────────────────────────────
    # Parse RPM strings like "$2.50", "USD 3.00", "3" → float
    import re as _re_pdf
    def _parse_rpm(s: str) -> float:
        if not s:
            return 0.0
        match = _re_pdf.search(r"(\d+(?:[.,]\d+)?)", str(s))
        if not match:
            return 0.0
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return 0.0

    rpm_avg_num = _parse_rpm(rpm_avg_raw)
    # Fallback: if AI didn't return rpm_max, default to 2x the avg
    rpm_max_num = _parse_rpm(rpm_max_raw)
    if rpm_max_num == 0 and rpm_avg_num > 0:
        rpm_max_num = round(rpm_avg_num * 2, 2)

    rpm_avg_display = esc(rpm_avg_raw or (f"${rpm_avg_num:.2f}" if rpm_avg_num else "—"))
    rpm_max_display = esc(rpm_max_raw or (f"${rpm_max_num:.2f}" if rpm_max_num else "—"))

    creator_share = 0.55  # YouTube keeps 45%

    def _format_views(n: float) -> str:
        if n <= 0:
            return "—"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
        if n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return f"{int(n)}"

    if rpm_avg_num > 0:
        views_for_1k_avg = 1000 / (rpm_avg_num * creator_share) * 1000
        views_for_1k_avg_display = _format_views(views_for_1k_avg)
    else:
        views_for_1k_avg_display = "—"

    if rpm_max_num > 0:
        views_for_1k_max = 1000 / (rpm_max_num * creator_share) * 1000
        views_for_1k_max_display = _format_views(views_for_1k_max)
    else:
        views_for_1k_max_display = "—"

    from datetime import datetime as _dt
    today_br = _dt.now().strftime("%d/%m/%Y")

    project_label = esc((proj or {}).get("name") or m.get("channel_name") or "")
    lang_upper = language.upper()

    # Cover hero — uses banner image as background if available
    if images.get("banner"):
        hero_bg = f'background-image: linear-gradient(180deg, rgba(10,10,15,0.55) 0%, rgba(10,10,15,0.95) 100%), url("{esc(images.get("banner"))}"); background-size: cover; background-position: {banner_pos};'
    else:
        hero_bg = f'background: linear-gradient(135deg, {primary}, #0a0a0f);'

    seo_page = (
        f'<div class="page page-break"><div class="page-header"><div class="ph-brand"><div class="ph-brand-dot"></div>SEO Pack</div><div class="ph-channel">{channel_name} · LACASADARK</div></div>{seo_block}<div class="page-footer"><div>{channel_name} · LACASADARK · canaisdarks.com.br</div><div>05</div></div></div>'
        if seo_block
        else ""
    )

    html_doc = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>LACASADARK · Identidade Estratégica — {channel_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif; color: #1a1a1a; background: #f5f5f7; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .doc {{ max-width: 880px; margin: 0 auto; background: #fff; box-shadow: 0 20px 80px rgba(0,0,0,0.08); }}
  .page {{ padding: 60px 64px 90px; min-height: 1100px; position: relative; }}
  .page-break {{ page-break-before: always; }}

  /* COVER */
  .cover {{ {hero_bg} background-color: #0a0a0f; color: #fff; padding: 80px 64px 50px; min-height: 1100px; display: flex; flex-direction: column; justify-content: space-between; position: relative; overflow: hidden; }}
  .cover-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .cover-brand {{ display: flex; align-items: center; gap: 10px; font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; opacity: 0.85; font-weight: 600; }}
  .cover-brand-dot {{ width: 8px; height: 8px; border-radius: 50%; background: {accent}; box-shadow: 0 0 14px {accent}; }}
  .cover-date {{ font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase; opacity: 0.7; }}
  .cover-center {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
  .cover-eyebrow {{ font-size: 12px; letter-spacing: 0.4em; text-transform: uppercase; color: {accent}; font-weight: 700; margin-bottom: 18px; }}
  .cover-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 76px; line-height: 0.95; letter-spacing: -0.02em; font-weight: 600; margin: 0 0 18px; text-shadow: 0 4px 30px rgba(0,0,0,0.6); }}
  .cover-tagline {{ font-size: 18px; line-height: 1.5; font-weight: 300; max-width: 580px; opacity: 0.92; font-style: italic; }}
  .cover-divider {{ width: 60px; height: 3px; background: {accent}; margin: 28px 0; border-radius: 2px; }}
  .cover-meta {{ display: flex; gap: 36px; margin-top: 32px; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; opacity: 0.85; }}
  .cover-meta span strong {{ display: block; color: {accent}; font-size: 14px; margin-bottom: 4px; font-weight: 700; letter-spacing: 0.05em; }}
  .cover-bottom {{ padding-top: 28px; border-top: 1px solid rgba(255,255,255,0.18); display: flex; justify-content: space-between; align-items: center; font-size: 10px; letter-spacing: 0.15em; text-transform: uppercase; opacity: 0.6; }}

  /* INNER PAGE */
  .page-header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 22px; margin-bottom: 38px; border-bottom: 1px solid #ececef; }}
  .ph-brand {{ display: flex; align-items: center; gap: 8px; font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: #888; font-weight: 600; }}
  .ph-brand-dot {{ width: 6px; height: 6px; border-radius: 50%; background: {primary}; }}
  .ph-channel {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 16px; color: #1a1a1a; font-weight: 600; }}
  .page-footer {{ position: absolute; bottom: 30px; left: 64px; right: 64px; display: flex; justify-content: space-between; font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase; color: #aaa; padding-top: 14px; border-top: 1px solid #ececef; }}

  /* BLOCKS */
  .block {{ margin-bottom: 50px; }}
  .block-eyebrow {{ font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; color: {primary}; font-weight: 700; margin-bottom: 12px; }}
  .block-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 38px; line-height: 1.05; letter-spacing: -0.01em; font-weight: 600; color: #0f0f12; margin: 0 0 22px; }}
  .block-body {{ font-size: 14px; line-height: 1.75; color: #2a2a30; margin: 0 0 14px; font-weight: 400; }}
  .block-body.small {{ font-size: 12px; color: #666; margin-bottom: 22px; }}

  /* DISCLAIMER */
  .disclaimer-card {{ display: flex; gap: 14px; align-items: flex-start; background: linear-gradient(135deg, #fffbeb, #fef3c7); border: 1px solid #fcd34d; border-left: 4px solid {accent}; border-radius: 10px; padding: 16px 20px; margin-bottom: 32px; }}
  .disclaimer-icon {{ font-size: 22px; line-height: 1; color: #b45309; }}
  .disclaimer-text {{ font-size: 12px; line-height: 1.6; color: #78350f; font-weight: 500; }}

  /* IDENTITY CARD */
  .identity-card {{ border-radius: 14px; overflow: hidden; box-shadow: 0 8px 30px rgba(0,0,0,0.06); border: 1px solid #ececef; margin-bottom: 38px; }}
  .identity-banner {{ width: 100%; aspect-ratio: 5.4/1; max-height: 280px; min-height: 150px; overflow: hidden; background: #0f0f12; }}
  .identity-banner img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .identity-row {{ display: flex; align-items: center; gap: 22px; padding: 24px 28px; background: #fff; }}
  .identity-logo {{ width: 92px; height: 92px; border-radius: 50%; overflow: hidden; flex-shrink: 0; background: linear-gradient(135deg, {primary}, {accent}); display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 800; font-size: 36px; box-shadow: 0 6px 20px rgba(0,0,0,0.12); border: 3px solid #fff; }}
  .identity-logo img {{ width: 135%; height: 135%; object-fit: cover; }}
  .identity-name {{ flex: 1; min-width: 0; }}
  .identity-name h3 {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 30px; line-height: 1; font-weight: 700; margin: 0 0 4px; color: #0f0f12; letter-spacing: -0.01em; }}
  .identity-handle {{ font-size: 12px; color: #888; font-weight: 500; }}
  .identity-tag {{ font-size: 13px; color: #444; margin-top: 6px; font-style: italic; line-height: 1.5; }}
  .identity-cta {{ padding: 10px 22px; border-radius: 22px; background: #0f0f12; color: #fff; font-size: 12px; font-weight: 700; flex-shrink: 0; }}
  .identity-tabs {{ display: flex; gap: 0; padding: 0 28px; border-top: 1px solid #ececef; background: #fff; }}
  .identity-tab {{ padding: 14px 18px; font-size: 12px; font-weight: 500; color: #888; border-bottom: 2px solid transparent; }}
  .identity-tab.active {{ color: #0f0f12; font-weight: 700; border-bottom-color: #0f0f12; }}
  .identity-videos {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding: 18px 22px 24px; background: #fff; }}
  .identity-videos .video-card {{ border: none; box-shadow: none; background: transparent; border-radius: 8px; }}
  .identity-videos .video-thumb {{ border-radius: 8px; }}
  .identity-videos .video-meta {{ padding: 8px 2px 0; }}
  .identity-videos .video-num {{ font-size: 7px; margin-bottom: 3px; }}
  .identity-videos .video-title {{ font-size: 11px; line-height: 1.35; -webkit-line-clamp: 2; display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }}
  .identity-videos .video-views {{ font-size: 9px; }}
  .identity-videos .duration-badge {{ font-size: 8px; padding: 2px 5px; }}

  /* KPI STATS */
  .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 38px; }}
  .stats-grid-5 {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 24px; }}
  .stats-grid-5 .stat-card {{ padding: 18px 14px; }}
  .stats-grid-5 .stat-value {{ font-size: 26px; }}
  .stats-grid-5 .stat-label {{ font-size: 8px; }}
  .stats-grid-5 .stat-sub {{ font-size: 9px; }}
  .stat-card {{ border: 1px solid #ececef; border-radius: 12px; padding: 22px 20px; background: linear-gradient(180deg, #fff, #fafafb); position: relative; }}
  .stat-card::before {{ content: ''; position: absolute; top: 0; left: 0; width: 38px; height: 3px; background: {primary}; border-radius: 0 0 3px 0; }}
  .stat-label {{ font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #888; font-weight: 700; margin-bottom: 10px; }}
  .stat-value {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 32px; line-height: 1; font-weight: 700; color: #0f0f12; }}
  .stat-sub {{ font-size: 10px; color: #aaa; margin-top: 4px; }}
  .stat-card.accent {{ background: linear-gradient(180deg, {primary}, #1a1a2e); border: none; }}
  .stat-card.accent::before {{ background: {accent}; }}
  .stat-card.accent .stat-label {{ color: rgba(255,255,255,0.65); }}
  .stat-card.accent .stat-value {{ color: #fff; }}
  .stat-card.accent .stat-sub {{ color: rgba(255,255,255,0.55); }}

  /* VIDEOS */
  .videos-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .video-card {{ border-radius: 12px; overflow: hidden; background: #fff; border: 1px solid #ececef; box-shadow: 0 4px 16px rgba(0,0,0,0.04); page-break-inside: avoid; }}
  .video-thumb {{ width: 100%; aspect-ratio: 16/9; background: #0f0f12; position: relative; overflow: hidden; }}
  .video-thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .duration-badge {{ position: absolute; bottom: 8px; right: 8px; background: rgba(0,0,0,0.85); color: #fff; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }}
  .video-meta {{ padding: 14px 16px 16px; }}
  .video-num {{ font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: {primary}; font-weight: 800; margin-bottom: 6px; }}
  .video-title {{ font-weight: 600; font-size: 13px; color: #0f0f12; line-height: 1.4; margin-bottom: 8px; }}
  .video-views {{ font-size: 11px; color: #999; font-weight: 500; }}
  .placeholder {{ width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: #aaa; font-size: 11px; background: repeating-linear-gradient(45deg, #f5f5f7, #f5f5f7 8px, #ececef 8px, #ececef 16px); }}

  /* WEAKNESSES + STRATEGY */
  .weaknesses-title {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #c2410c; font-weight: 700; margin: 22px 0 12px; }}
  .weaknesses {{ list-style: none; padding: 0; margin: 0 0 22px; }}
  .weaknesses li {{ font-size: 13px; line-height: 1.6; color: #2a2a30; padding: 10px 0; border-bottom: 1px solid #f0f0f3; display: flex; gap: 10px; align-items: flex-start; }}
  .weaknesses li:last-child {{ border-bottom: none; }}
  .check {{ color: #16a34a; font-weight: 800; flex-shrink: 0; font-size: 14px; }}
  .strategy-callout {{ background: linear-gradient(135deg, #f0fdf4, #dcfce7); border: 1px solid #86efac; border-left: 4px solid #16a34a; border-radius: 10px; padding: 18px 22px; margin-top: 22px; }}
  .strategy-label {{ font-size: 9px; letter-spacing: 0.25em; text-transform: uppercase; color: #166534; font-weight: 800; margin-bottom: 8px; }}
  .strategy-body {{ font-size: 13px; line-height: 1.65; color: #14532d; font-weight: 500; font-style: italic; }}

  /* SEO PACK */
  .seo-row {{ margin-bottom: 26px; }}
  .seo-label {{ font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: #555; font-weight: 700; margin-bottom: 10px; }}
  .seo-chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .tag, .hashtag, .keyword {{ display: inline-block; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 500; }}
  .tag {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }}
  .hashtag {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }}
  .keyword {{ background: #faf5ff; color: #7c3aed; border: 1px solid #ddd6fe; }}

  /* PATH TO FIRST $1K */
  .path-1k {{ background: linear-gradient(135deg, #0f0f12, #1a1a2e); border-radius: 14px; padding: 26px 28px 24px; margin: 28px 0 24px; color: #fff; position: relative; overflow: hidden; }}
  .path-1k::before {{ content: ''; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: {accent}; }}
  .path-1k-header {{ margin-bottom: 20px; }}
  .path-1k-eyebrow {{ font-size: 9px; letter-spacing: 0.3em; text-transform: uppercase; color: {accent}; font-weight: 800; margin-bottom: 8px; }}
  .path-1k-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 24px; line-height: 1.2; font-weight: 600; margin: 0; color: #fff; letter-spacing: -0.01em; }}
  .path-1k-grid {{ display: grid; grid-template-columns: 1.1fr 1fr 1fr; gap: 16px; align-items: stretch; }}
  .path-1k-card {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 18px 18px; display: flex; flex-direction: column; justify-content: center; }}
  .path-1k-card.best {{ background: linear-gradient(135deg, rgba({accent_rgb},0.22), rgba(255,255,255,0.04)); border-color: {accent}; }}
  .path-1k-card-label {{ font-size: 9px; letter-spacing: 0.16em; text-transform: uppercase; color: rgba(255,255,255,0.65); font-weight: 700; margin-bottom: 10px; }}
  .path-1k-card.best .path-1k-card-label {{ color: {accent}; }}
  .path-1k-card-value {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 38px; line-height: 1; font-weight: 700; color: #fff; margin-bottom: 6px; }}
  .path-1k-card-sub {{ font-size: 10px; color: rgba(255,255,255,0.55); }}

  /* MEDAL — first $1000 achievement */
  .path-1k-medal {{ background: linear-gradient(135deg, rgba({accent_rgb},0.18), rgba(0,0,0,0.4)); border: 2px solid {accent}; border-radius: 14px; padding: 18px 14px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; position: relative; box-shadow: inset 0 0 30px rgba({accent_rgb},0.15); }}
  .medal-ring {{ width: 130px; height: 130px; border-radius: 50%; background: radial-gradient(circle at 30% 30%, rgba({accent_rgb},0.95), rgba({accent_rgb},0.55) 60%, rgba({accent_rgb},0.3)); display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: 0 0 40px rgba({accent_rgb},0.4), inset 0 -8px 20px rgba(0,0,0,0.3), inset 0 4px 12px rgba(255,255,255,0.3); border: 3px solid rgba(255,255,255,0.4); }}
  .medal-amount {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 36px; font-weight: 700; color: #1a0f00; line-height: 1; text-shadow: 0 1px 2px rgba(255,255,255,0.4); }}
  .medal-label {{ font-size: 8px; letter-spacing: 0.18em; text-transform: uppercase; color: rgba(26,15,0,0.75); font-weight: 800; margin-top: 4px; }}
  .medal-badge {{ font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: {accent}; font-weight: 800; padding: 5px 12px; border: 1px solid {accent}; border-radius: 999px; background: rgba(0,0,0,0.4); }}

  /* REALITY NOTE */
  .reality-note {{ background: #fff8eb; border: 1px solid #fde68a; border-left: 3px solid #d97706; border-radius: 8px; padding: 12px 16px; font-size: 11px; line-height: 1.55; color: #78350f; margin-top: 8px; margin-bottom: 38px; }}
  .reality-note strong {{ color: #92400e; font-weight: 700; }}
  .reality-note em {{ font-style: italic; color: #92400e; }}

  /* BACK COVER */
  .back-cover {{ background: #0f0f12; color: #fff; min-height: 800px; padding: 180px 64px 80px; text-align: center; }}
  .back-eyebrow {{ font-size: 11px; letter-spacing: 0.4em; text-transform: uppercase; color: {accent}; font-weight: 700; margin-bottom: 24px; }}
  .back-title {{ font-family: 'Cormorant Garamond', Georgia, serif; font-size: 48px; font-weight: 600; margin: 0 0 22px; line-height: 1.05; letter-spacing: -0.01em; }}
  .back-text {{ font-size: 15px; line-height: 1.75; max-width: 520px; margin: 0 auto 40px; color: rgba(255,255,255,0.78); font-weight: 300; }}
  .back-line {{ width: 60px; height: 3px; background: {accent}; margin: 0 auto 40px; border-radius: 2px; }}
  .back-meta {{ font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; color: rgba(255,255,255,0.5); }}

  /* PRINT BAR */
  .print-bar {{ position: fixed; top: 16px; right: 16px; background: #0f0f12; color: #fff; padding: 12px 18px; border-radius: 12px; font-size: 12px; z-index: 9999; box-shadow: 0 12px 40px rgba(0,0,0,0.4); display: flex; align-items: center; gap: 14px; }}
  .print-bar button {{ padding: 8px 16px; background: {accent}; color: #0f0f12; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 12px; }}

  @media print {{
    body {{ background: #fff; }}
    .print-bar {{ display: none; }}
    .doc {{ box-shadow: none; max-width: none; }}
    .page {{ padding: 50px 50px 80px; }}
    .cover {{ padding: 70px 50px 50px; }}
    .back-cover {{ padding: 160px 50px 70px; }}
    .page-footer {{ left: 50px; right: 50px; }}
    section {{ page-break-inside: avoid; }}
    .video-card {{ page-break-inside: avoid; }}
  }}
  @page {{ size: A4; margin: 0; }}
</style>
</head>
<body>
<div class="print-bar">
  💡 Use "Salvar como PDF" no diálogo de impressão
  <button onclick="window.print()">📄 Salvar PDF</button>
</div>

<div class="doc">

  <!-- COVER -->
  <div class="cover">
    <div class="cover-top">
      <div class="cover-brand"><div class="cover-brand-dot"></div>LACASADARK · Mentoria</div>
      <div class="cover-date">{today_br}</div>
    </div>
    <div class="cover-center">
      <div class="cover-eyebrow">Documento Confidencial · Identidade Estratégica</div>
      <h1 class="cover-title">{channel_name}</h1>
      <div class="cover-divider"></div>
      <div class="cover-tagline">{tagline}</div>
      <div class="cover-meta">
        <span><strong>{lang_upper}</strong>Idioma</span>
        <span><strong>{sub_6_display}</strong>Inscritos · 6m</span>
        <span><strong>{sub_12_display}</strong>Inscritos · 12m</span>
        <span><strong>{rpm_avg_display}</strong>RPM médio</span>
      </div>
    </div>
    <div class="cover-bottom">
      <div>Projeto · {project_label}</div>
      <div>LACASADARK · canaisdarks.com.br</div>
    </div>
  </div>

  <!-- PAGE 2 — IDENTIDADE -->
  <div class="page page-break">
    <div class="page-header">
      <div class="ph-brand"><div class="ph-brand-dot"></div>Identidade Visual</div>
      <div class="ph-channel">{channel_name} · LACASADARK</div>
    </div>

    {disclaimer_block}

    <div class="block">
      <div class="block-eyebrow">02 · IDENTIDADE VISUAL</div>
      <h2 class="block-title">Como o canal aparece no YouTube</h2>
      <p class="block-body small">Mockup completo do canal — banner, logo, header e os 4 vídeos iniciais. Pronto pra você reproduzir no canal real.</p>

      <div class="identity-card">
        <div class="identity-banner">{banner_html}</div>
        <div class="identity-row">
          <div class="identity-logo">{logo_html}</div>
          <div class="identity-name">
            <h3>{channel_name} ✓</h3>
            <div class="identity-handle">@{handle} · {len(videos)} vídeos · {sub_6_display} inscritos previstos</div>
            <div class="identity-tag">{tagline}</div>
          </div>
          <div class="identity-cta">Inscrever-se</div>
        </div>
        <div class="identity-tabs">
          <div class="identity-tab active">Início</div>
          <div class="identity-tab">Vídeos</div>
          <div class="identity-tab">Playlists</div>
          <div class="identity-tab">Posts</div>
        </div>
        <div class="identity-videos">{videos_html}</div>
      </div>
    </div>

    <div class="page-footer">
      <div>{channel_name} · LACASADARK · canaisdarks.com.br</div>
      <div>02</div>
    </div>
  </div>

  <!-- PAGE 3 — PROJEÇÃO FINANCEIRA + DESCRIÇÃO -->
  <div class="page page-break">
    <div class="page-header">
      <div class="ph-brand"><div class="ph-brand-dot"></div>Projeção & Posicionamento</div>
      <div class="ph-channel">{channel_name} · LACASADARK</div>
    </div>

    <div class="block">
      <div class="block-eyebrow">03 · PROJEÇÃO ESTIMADA</div>
      <h2 class="block-title">Potencial financeiro do canal</h2>
      <p class="block-body small">Suposições baseadas em médias de mercado de canais bem executados no nicho. Não são promessas — são referências do que é possível com disciplina, consistência e qualidade de execução.</p>

      <div class="stats-grid-5">
        <div class="stat-card">
          <div class="stat-label">Inscritos · 6m</div>
          <div class="stat-value">{sub_6_display}</div>
          <div class="stat-sub">Estimativa</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Inscritos · 12m</div>
          <div class="stat-value">{sub_12_display}</div>
          <div class="stat-sub">Estimativa</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">RPM Médio</div>
          <div class="stat-value">{rpm_avg_display}</div>
          <div class="stat-sub">{rpm_currency} · típico</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">RPM Máximo</div>
          <div class="stat-value">{rpm_max_display}</div>
          <div class="stat-sub">{rpm_currency} · pico nicho</div>
        </div>
        <div class="stat-card accent">
          <div class="stat-label">AdSense/mês</div>
          <div class="stat-value">{adsense_display}</div>
          <div class="stat-sub">{monthly_views_display} views/mês</div>
        </div>
      </div>

      <!-- Path to first $1000 -->
      <div class="path-1k">
        <div class="path-1k-header">
          <div class="path-1k-eyebrow">PRIMEIRA GRANDE META</div>
          <h3 class="path-1k-title">Quanto o canal precisa entregar para o primeiro $1K?</h3>
        </div>
        <div class="path-1k-grid">
          <div class="path-1k-medal">
            <div class="medal-ring">
              <div class="medal-amount">$1.000</div>
              <div class="medal-label">PRIMEIRA META</div>
            </div>
            <div class="medal-badge">🏆 ALCANÇADO</div>
          </div>
          <div class="path-1k-card">
            <div class="path-1k-card-label">Cenário Médio · RPM {rpm_avg_display}</div>
            <div class="path-1k-card-value">{views_for_1k_avg_display}</div>
            <div class="path-1k-card-sub">views totais necessárias</div>
          </div>
          <div class="path-1k-card best">
            <div class="path-1k-card-label">Cenário Pico · RPM {rpm_max_display}</div>
            <div class="path-1k-card-value">{views_for_1k_max_display}</div>
            <div class="path-1k-card-sub">views totais necessárias</div>
          </div>
        </div>
      </div>

      <div class="reality-note">⚠ <strong>Tudo isto é uma suposição</strong> baseada em médias de canais bem executados no mesmo nicho. Os números reais dependem de <em>consistência de postagem, qualidade de hooks, retenção, CTR e otimização contínua</em>. Use como referência de potencial, não como garantia.</div>
    </div>

    {description_block}

    <div class="page-footer">
      <div>{channel_name} · LACASADARK · canaisdarks.com.br</div>
      <div>03</div>
    </div>
  </div>

  <!-- PAGE 4 — DIFERENCIAL -->
  <div class="page page-break">
    <div class="page-header">
      <div class="ph-brand"><div class="ph-brand-dot"></div>Diferencial Competitivo</div>
      <div class="ph-channel">{channel_name} · LACASADARK</div>
    </div>

    {superior_block}

    <div class="page-footer">
      <div>{channel_name} · LACASADARK · canaisdarks.com.br</div>
      <div>04</div>
    </div>
  </div>

  <!-- PAGE 4 — SEO -->
  {seo_page}

  <!-- BACK COVER -->
  <div class="back-cover page-break">
    <div class="back-eyebrow">Próximo passo</div>
    <h2 class="back-title">Agora é executar.</h2>
    <p class="back-text">Use este documento como blueprint. Cada elemento foi desenhado pra que seu canal nasça posicionado pra dominar o nicho desde o primeiro upload. Consistência + hooks fortes + qualidade = crescimento real.</p>
    <div class="back-line"></div>
    <div style="font-family: 'Cormorant Garamond', Georgia, serif; font-size: 32px; font-weight: 600; color: #fff; margin-bottom: 6px; letter-spacing: 0.04em;">LACASADARK</div>
    <div style="font-size: 10px; letter-spacing: 0.3em; text-transform: uppercase; color: rgba(255,255,255,0.55); margin-bottom: 14px;">Mentoria de Canais Faceless</div>
    <div style="font-size: 13px; color: {accent}; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 32px;">canaisdarks.com.br</div>
    <div class="back-meta">Documento gerado em {today_br}</div>
  </div>

</div>

<script>
  window.addEventListener('load', function() {{
    setTimeout(function() {{ window.print(); }}, 800);
  }});
</script>
</body>
</html>"""
    return HTMLResponse(html_doc)


@app.post("/api/admin/save-mockup-banner-position")
@limiter.limit("60/minute")
async def api_save_mockup_banner_position(request: Request, user=Depends(require_admin)):
    """
    Persist the user-chosen banner position (drag-to-reposition). The position
    is stored as a CSS background-position string ("50% 30%") in
    mockup['banner_position'].
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    position = (body.get("position") or "").strip()
    if not project_id or not position:
        return JSONResponse({"error": "project_id e position obrigatorios"}, status_code=400)
    # Sanity check — only digits, %, decimal dot and spaces
    import re as _re
    if not _re.match(r"^[\d\.\s%]+$", position) or len(position) > 30:
        return JSONResponse({"error": "position invalida"}, status_code=400)

    import json as _json
    from database import get_files, get_db

    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"error": "Mockup nao encontrado"}, status_code=404)
    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"Mockup invalido: {e}"}, status_code=500)

    mockup["banner_position"] = position
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET content=? WHERE id=?",
                (_json.dumps(mockup, ensure_ascii=False, indent=2), files[0]["id"]),
            )
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

    return JSONResponse({"ok": True})


@app.post("/api/admin/save-mockup-image")
@limiter.limit("60/minute")
async def api_save_mockup_image(request: Request, user=Depends(require_admin)):
    """
    Persist a generated image URL on the saved mockup file under
    mockup['images'][slot]. The slot is one of: logo, banner, thumb0..3.
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    slot = (body.get("slot") or "").strip()
    url = (body.get("url") or "").strip()
    if not project_id or not slot or not url:
        return JSONResponse({"error": "project_id, slot e url obrigatorios"}, status_code=400)

    import json as _json
    from database import get_files, get_db

    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"error": "Mockup nao encontrado"}, status_code=404)
    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"Mockup invalido: {e}"}, status_code=500)

    images = mockup.get("images") or {}
    images[slot] = url
    mockup["images"] = images

    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET content=? WHERE id=?",
                (_json.dumps(mockup, ensure_ascii=False, indent=2), files[0]["id"]),
            )
    except Exception as e:
        logger.warning(f"save-mockup-image failed: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)

    return JSONResponse({"ok": True})


@app.post("/api/admin/translate-mockup-description")
@limiter.limit("10/minute")
async def api_translate_mockup_description(request: Request, user=Depends(require_admin)):
    """
    Translate the saved mockup description into a target language and persist
    the change so the next render shows it. Returns the updated description.
    """
    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    target_language = (body.get("language") or "").strip()
    if not project_id or not target_language:
        return JSONResponse({"error": "project_id e language obrigatorios"}, status_code=400)

    import json as _json
    from database import get_files, get_db

    files = [f for f in (get_files(project_id) or []) if f.get("category") == "mockup"]
    if not files:
        return JSONResponse({"error": "Mockup nao encontrado"}, status_code=404)

    try:
        mockup = _json.loads(files[0].get("content", "") or "{}")
    except Exception as e:
        return JSONResponse({"error": f"Mockup salvo invalido: {e}"}, status_code=500)

    original_desc = (mockup.get("description") or "").strip()
    if not original_desc:
        return JSONResponse({"error": "Sem descricao para traduzir"}, status_code=400)

    from protocols.ai_client import chat
    import asyncio

    system = (
        "Voce e um tradutor profissional especializado em conteudo para YouTube. "
        "Traduza o texto preservando tom, estrutura e impacto emocional. "
        "Retorne APENAS a traducao, sem explicacoes, sem aspas, sem preambulo."
    )
    user_prompt = (
        f"Traduza a descricao de canal abaixo para o idioma: {target_language}.\n"
        f"Mantenha o mesmo comprimento aproximado e o mesmo estilo persuasivo.\n\n"
        f"TEXTO ORIGINAL:\n{original_desc}"
    )

    try:
        translated = await asyncio.to_thread(
            chat,
            prompt=user_prompt,
            system=system,
            max_tokens=1500,
            temperature=0.4,
            timeout=120,
        )
    except Exception as e:
        logger.exception(f"translate-mockup-description error: {e}")
        return JSONResponse({"error": f"Falha na traducao: {str(e)[:200]}"}, status_code=502)

    translated = (translated or "").strip()
    if not translated:
        return JSONResponse({"error": "Tradutor retornou vazio"}, status_code=502)

    new_mockup = {**mockup, "description": translated, "description_language": target_language}
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET content=? WHERE id=?",
                (_json.dumps(new_mockup, ensure_ascii=False, indent=2), files[0]["id"]),
            )
    except Exception as e:
        logger.warning(f"translate-mockup-description: failed to persist: {e}")

    return JSONResponse({"ok": True, "description": translated, "language": target_language})


@app.post("/api/admin/generate-mockup-image")
@limiter.limit("20/minute")
async def api_generate_mockup_image(request: Request, user=Depends(require_admin)):
    """
    Generate a single image via ImageFX for a mockup field (logo/banner/thumb).
    Returns a data:image/png;base64 URL the frontend can render directly.
    """
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    aspect = (body.get("aspect") or "LANDSCAPE").upper()
    if not prompt:
        return JSONResponse({"error": "prompt obrigatorio"}, status_code=400)

    import asyncio
    from protocols.imagefx_client import get_client, ImageFXError

    try:
        client = get_client()
    except ImageFXError as e:
        return JSONResponse({"error": str(e), "code": "NO_COOKIE"}, status_code=400)

    try:
        images = await asyncio.to_thread(client.generate, prompt, aspect, 1, 90)
    except ImageFXError as e:
        status = 401 if e.status in (401, 403) else (429 if e.status == 429 else 502)
        return JSONResponse({"error": str(e), "code": f"IMAGEFX_{e.status}"}, status_code=status)
    except Exception as e:
        logger.exception(f"generate-mockup-image error: {e}")
        return JSONResponse({"error": f"Erro inesperado: {str(e)[:200]}"}, status_code=500)

    if not images:
        return JSONResponse({"error": "Nenhuma imagem gerada"}, status_code=502)

    return JSONResponse({"ok": True, "url": images[0]["url"], "seed": images[0].get("seed")})


@app.post("/api/admin/imagefx-cookie")
@limiter.limit("5/minute")
async def api_imagefx_cookie_save(request: Request, user=Depends(require_admin)):
    """Save (Fernet-encrypted) ImageFX cookie. Pass empty string to clear."""
    body = await request.json()
    cookie = (body.get("cookie") or "").strip()
    from protocols.imagefx_client import set_imagefx_cookie
    try:
        set_imagefx_cookie(cookie)
        return JSONResponse({"ok": True, "cleared": not cookie})
    except Exception as e:
        logger.exception(f"imagefx-cookie save error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@app.get("/api/admin/imagefx-cookie/status")
async def api_imagefx_cookie_status(request: Request, user=Depends(require_admin)):
    """
    Diagnostic: returns whether a cookie is saved and tries to fetch a session
    to confirm it's still valid. Bypasses any cache.
    """
    from protocols.imagefx_client import get_imagefx_cookie, ImageFXClient, ImageFXError
    cookie = get_imagefx_cookie()
    if not cookie:
        return JSONResponse({
            "configured": False,
            "valid": False,
            "hint": "Cookie nao configurado. Cole o cookie do labs.google na pagina de Admin.",
        })
    masked = (cookie[:30] + "…") if len(cookie) > 30 else cookie
    try:
        client = ImageFXClient(cookie)
        # Trigger a session fetch but don't generate an image (cheap call)
        client._refresh_session_if_needed()
        return JSONResponse({
            "configured": True,
            "valid": True,
            "cookie_length": len(cookie),
            "cookie_masked": masked,
            "hint": "✅ Cookie valido — sessao ativa.",
        })
    except ImageFXError as e:
        return JSONResponse({
            "configured": True,
            "valid": False,
            "cookie_length": len(cookie),
            "cookie_masked": masked,
            "error": str(e),
            "hint": "❌ Cookie invalido ou expirado. Atualize cole um novo do labs.google.",
        })


@app.get("/api/admin/gdrive/admin-root-status")
async def api_gdrive_admin_root_status(request: Request, user=Depends(require_admin)):
    """
    Diagnostic endpoint for the Drive admin root folder.
    Returns current state and allows identifying why project folders
    might be failing to nest under the admin root.
    """
    from database import get_setting
    result: dict = {"ok": True}
    try:
        saved_id = get_setting("drive_admin_root_id") or ""
        result["saved_id"] = saved_id
        result["saved_id_present"] = bool(saved_id)

        from protocols.google_export import get_drive_service
        try:
            drive = get_drive_service()
            result["drive_service"] = "connected"
        except Exception as e:
            result["drive_service"] = "error"
            result["drive_error"] = str(e)[:200]
            return JSONResponse(result)

        # Verify saved folder still exists
        if saved_id:
            try:
                info = drive.files().get(fileId=saved_id, fields="id,name,trashed,webViewLink").execute()
                result["saved_folder_exists"] = not info.get("trashed", False)
                result["saved_folder_name"] = info.get("name", "")
                result["saved_folder_url"] = info.get("webViewLink", "")
            except Exception as e:
                result["saved_folder_exists"] = False
                result["saved_folder_error"] = str(e)[:200]

        # Search for any "YT Cloner" folders owned by user (detect duplicates)
        try:
            q = "name='YT Cloner' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            found = drive.files().list(q=q, fields="files(id,name,webViewLink,createdTime)").execute()
            result["all_yt_cloner_folders"] = found.get("files", [])
            result["duplicates_count"] = max(0, len(found.get("files", [])) - 1)
        except Exception as e:
            result["list_error"] = str(e)[:200]
    except Exception as e:
        logger.exception(f"admin-root-status error: {e}")
        result["ok"] = False
        result["error"] = str(e)[:200]

    return JSONResponse(result)


@app.post("/api/admin/gdrive/reset-admin-root")
async def api_gdrive_reset_admin_root(request: Request, user=Depends(require_admin)):
    """
    Force re-creation of the admin root folder. Use if it got deleted or
    if projects are being created as flat folders instead of nested.
    """
    from database import set_setting
    try:
        # Clear cached value
        from protocols import google_export
        google_export._admin_root_id = None
        set_setting("drive_admin_root_id", "")

        # Trigger recreation
        new_id = google_export.get_admin_root_folder()
        return JSONResponse({
            "ok": True,
            "new_admin_root_id": new_id,
            "message": "Admin root recriado — novos projetos vao usar essa pasta",
        })
    except Exception as e:
        logger.exception(f"reset-admin-root error: {e}")
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
    admin_ai_model = get_setting("admin_ai_model") or "claude-3-7-sonnet-latest"

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


@app.post("/api/admin/rename-project")
@limiter.limit("30/minute")
async def api_rename_project(request: Request, user=Depends(require_admin)):
    body = await request.json()
    project_id = body.get("project_id", "")
    new_name = (body.get("name") or "").strip()
    if not project_id or not new_name:
        return JSONResponse({"error": "project_id e name obrigatorios"}, status_code=400)
    if len(new_name) > 100:
        return JSONResponse({"error": "Nome muito longo (max 100)"}, status_code=400)
    from database import update_project
    update_project(project_id, name=new_name)
    return JSONResponse({"ok": True, "name": new_name})


@app.post("/api/admin/update-project-channel")
@limiter.limit("30/minute")
async def api_update_project_channel(request: Request, user=Depends(require_admin)):
    """Update or clear the channel_original field of a project.
    Accepts a YouTube URL, a free-text label (e.g. 'Loaded Dice'), or empty string.
    """
    body = await request.json()
    project_id = body.get("project_id", "")
    raw = (body.get("channel_original") or "").strip()
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)
    if len(raw) > 300:
        return JSONResponse({"error": "Valor muito longo (max 300)"}, status_code=400)

    # Light validation: if it looks like a URL, ensure it's youtube; otherwise accept as label
    value = raw
    if raw and ("://" in raw or raw.startswith("www.")):
        try:
            value = validate_url(raw)
        except Exception:
            return JSONResponse({"error": "URL invalida"}, status_code=400)
        if "youtube.com" not in value and "youtu.be" not in value:
            return JSONResponse({"error": "URL deve ser do YouTube"}, status_code=400)

    from database import get_project, update_project
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)
    update_project(project_id, channel_original=value)
    return JSONResponse({"ok": True, "channel_original": value})


@app.post("/api/admin/delete-project")
@limiter.limit("10/minute")
async def api_delete_project(request: Request, user=Depends(require_admin)):
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)
    try:
        from database import delete_project
        delete_project(str(project_id))
        # Also delete mindmap file
        try:
            mm = OUTPUT_DIR / f"mindmap_{project_id}.html"
            if mm.exists():
                mm.unlink()
        except Exception:
            pass
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"Delete project error: {e}")
        return JSONResponse({"error": "Erro ao excluir projeto."}, status_code=500)


@app.post("/api/admin/delete-file")
@limiter.limit("20/minute")
async def api_admin_delete_file(request: Request, user=Depends(require_admin)):
    """Delete a file from a project."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)
    try:
        from database import delete_file
        deleted = delete_file(int(file_id))
        if deleted and deleted.get("filename"):
            fpath = OUTPUT_DIR / deleted["filename"]
            if fpath.exists():
                fpath.unlink()
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-file error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao excluir arquivo."}, status_code=500)


@app.post("/api/admin/connect-drive")
@limiter.limit("5/minute")
async def api_connect_drive(request: Request, user=Depends(require_admin)):
    """Create Google Drive folder for an existing project that doesn't have one."""
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_project, update_project, get_files, save_file, log_activity

    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    if proj.get("drive_folder_id"):
        return JSONResponse({
            "ok": True,
            "already_connected": True,
            "drive_folder_url": proj.get("drive_folder_url", ""),
        })

    try:
        from protocols.google_export import create_folder, create_doc, create_sheet
        import json as _json

        niche_name = proj.get("niche_chosen") or proj.get("name", "Projeto")

        # Get or create project folder (no duplicates)
        from protocols.google_export import get_or_create_project_folder
        folder_id = get_or_create_project_folder(niche_name)
        drive_url = f"https://drive.google.com/drive/folders/{folder_id}"
        update_project(project_id, drive_folder_id=folder_id, drive_folder_url=drive_url)

        # Upload existing files to Drive
        files = get_files(project_id)
        uploaded = 0
        for f in files:
            content = f.get("content", "") or ""
            if not content or len(content) < 50:
                continue
            cat = f.get("category", "")
            label = f.get("label", f.get("filename", ""))
            try:
                if cat in ("analise", "seo", "roteiro", "narracao", "outros", "visual"):
                    create_doc(label, content, folder_id)
                    uploaded += 1
            except Exception as e:
                logger.warning(f"Drive upload failed for {label}: {e}")

        # Upload ideas as Sheet
        try:
            from database import get_ideas
            ideas = get_ideas(project_id)
            if ideas:
                data = [["#", "Titulo", "Hook", "Pilar", "Prioridade", "Score"]]
                for i, idea in enumerate(ideas, 1):
                    data.append([str(i), idea.get("title", ""), idea.get("hook", "")[:100],
                                idea.get("pillar", ""), idea.get("priority", ""), str(idea.get("score", 0))])
                create_sheet(f"Titulos - {niche_name}", data, folder_id)
                uploaded += 1
        except Exception:
            pass

        # Upload niches as Sheet
        try:
            from database import get_niches
            niches = get_niches(project_id)
            if niches:
                data = [["Nome", "Descricao", "RPM", "Competicao", "Escolhido"]]
                for n in niches:
                    pillars = n.get("pillars", "")
                    if isinstance(pillars, str):
                        try:
                            import json as _j2
                            pillars = ", ".join(_j2.loads(pillars))
                        except Exception:
                            pass
                    data.append([n.get("name", ""), n.get("description", "")[:100],
                                n.get("rpm_range", ""), n.get("competition", ""),
                                "Sim" if n.get("chosen") else ""])
                create_sheet(f"5 Nichos Derivados - {niche_name}", data, folder_id)
                uploaded += 1
        except Exception:
            pass

        # Upload SEO details as Sheet
        try:
            from database import get_ideas as _gi2
            ideas2 = _gi2(project_id)
            seo_data = [["#", "Titulo", "Score", "Rating", "Pilar", "Prioridade"]]
            for i, idea in enumerate(ideas2[:15], 1):
                seo_data.append([str(i), idea.get("title", ""), str(idea.get("score", 0)),
                                idea.get("rating", ""), idea.get("pillar", ""), idea.get("priority", "")])
            if len(seo_data) > 1:
                create_sheet(f"SEO Sheet - Titulos e Tags ({len(seo_data)-1} videos)", seo_data, folder_id)
                uploaded += 1
        except Exception:
            pass

        # Mind Map as standalone doc
        try:
            mindmap_file = OUTPUT_DIR / f"mindmap_{project_id}.html"
            if mindmap_file.exists():
                mm_content = mindmap_file.read_text(encoding="utf-8")
                if len(mm_content) > 100:
                    create_doc(f"MIND MAP - Visao Geral do Projeto", mm_content[:50000], folder_id)
                    uploaded += 1
        except Exception:
            pass

        log_activity(project_id, "drive_connected", f"Google Drive conectado: {uploaded} arquivos enviados")

        return JSONResponse({
            "ok": True,
            "drive_folder_url": drive_url,
            "uploaded": uploaded,
        })
    except Exception as e:
        logger.error(f"connect-drive error: {e}", exc_info=True)
        msg = str(e)
        if "nao conectado" in msg.lower() or "not connected" in msg.lower():
            return JSONResponse({"error": "Google Drive nao conectado. Va em Admin Panel > Google Drive para autenticar."}, status_code=400)
        if "expired" in msg.lower() or "invalid_grant" in msg.lower():
            return JSONResponse({"error": "Token do Google Drive expirado. Reconecte em Admin Panel > Google Drive."}, status_code=400)
        return JSONResponse({"error": f"Falha ao conectar Google Drive: {msg[:200]}"}, status_code=500)


@app.post("/api/admin/sync-drive")
@limiter.limit("5/minute")
async def api_sync_drive(request: Request, user=Depends(require_admin)):
    """Re-sync all project files to Google Drive (14 standard files)."""
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    import asyncio

    def _sync():
        from database import get_project, get_files, get_ideas, get_niches, log_activity, update_project
        from protocols.google_export import (
            create_doc, create_sheet, get_drive_service,
            get_or_create_project_folder,
        )

        proj = get_project(project_id)
        if not proj:
            return {"error": "Projeto nao encontrado"}

        niche_name = proj.get("niche_chosen") or proj.get("name", "Projeto")
        folder_id = proj.get("drive_folder_id", "") or ""
        folder_created = False
        folder_recreated = False

        # Verify folder still exists in Drive (it may have been deleted manually).
        # If it doesn't exist OR project never had one, create it now via the
        # admin-root-aware helper (no flat folders, no duplicates).
        try:
            drive = get_drive_service()
        except Exception as e:
            logger.error(f"Drive sync: drive_service unavailable: {e}")
            return {"error": "Google Drive nao conectado. Conecte em Admin > Drive."}

        folder_valid = False
        if folder_id:
            try:
                info = drive.files().get(
                    fileId=folder_id, fields="id,trashed"
                ).execute()
                folder_valid = not info.get("trashed", False)
            except Exception as e:
                logger.warning(f"Drive sync: saved folder {folder_id} not found ({e}) — will recreate")
                folder_valid = False

        if not folder_valid:
            try:
                folder_id = get_or_create_project_folder(niche_name)
                if not folder_id:
                    return {"error": "Falha ao criar pasta no Drive."}
                update_project(
                    project_id,
                    drive_folder_id=folder_id,
                    drive_folder_url=f"https://drive.google.com/drive/folders/{folder_id}",
                )
                folder_created = not bool(proj.get("drive_folder_id"))
                folder_recreated = bool(proj.get("drive_folder_id")) and not folder_created
                logger.info(f"Drive sync: {'created' if folder_created else 'recreated'} folder {folder_id} for {niche_name}")
            except Exception as e:
                logger.error(f"Drive sync: failed to create folder: {e}")
                return {"error": f"Falha ao criar pasta no Drive: {str(e)[:120]}"}

        uploaded = 0
        skipped = 0

        # List existing files in Drive folder to avoid duplicates
        existing_names = set()
        try:
            results = drive.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(name)",
                pageSize=100,
            ).execute()
            existing_names = {f["name"] for f in results.get("files", [])}
            logger.info(f"Drive sync: {len(existing_names)} existing files in folder")
        except Exception as e:
            logger.warning(f"Drive sync: could not list existing files: {e}")

        def _doc(title, content):
            nonlocal uploaded, skipped
            if content and len(content) > 50:
                if title in existing_names:
                    skipped += 1
                    return
                try:
                    create_doc(title, content, folder_id)
                    uploaded += 1
                    existing_names.add(title)
                except Exception as e:
                    logger.warning(f"Sync doc '{title}': {e}")

        def _sheet(title, data):
            nonlocal uploaded, skipped
            if data and len(data) > 1:
                if title in existing_names:
                    skipped += 1
                    return
                try:
                    create_sheet(title, data, folder_id)
                    uploaded += 1
                    existing_names.add(title)
                except Exception as e:
                    logger.warning(f"Sync sheet '{title}': {e}")

        files = get_files(project_id)
        ideas = get_ideas(project_id)
        niches = get_niches(project_id)

        # 1. SOP
        sop = next((f for f in files if f.get("category") == "analise"), None)
        if sop:
            _doc(f"SOP - {niche_name}", sop.get("content", ""))

        # 2. SEO Pack
        seo = next((f for f in files if f.get("category") == "seo"), None)
        if seo:
            _doc(f"SEO Pack - {niche_name}", seo.get("content", ""))

        # 3-5. Roteiros
        roteiros = [f for f in files if f.get("category") == "roteiro"]
        for i, rf in enumerate(roteiros[:3], 1):
            _doc(f"Roteiro {i} - {rf.get('label', '').replace('Roteiro - ', '')}", rf.get("content", ""))

        # 6. Thumbnails
        thumb = next((f for f in files if "thumbnail" in (f.get("filename", "") or "").lower()), None)
        if thumb:
            _doc("Thumbnail Prompts - Midjourney DALL-E", thumb.get("content", ""))

        # 7. Music
        music = next((f for f in files if "music" in (f.get("filename", "") or "").lower()), None)
        if music:
            _doc("Music Prompts - Suno Udio MusicGPT", music.get("content", ""))

        # 8. Teaser
        teaser = next((f for f in files if "teaser" in (f.get("filename", "") or "").lower()), None)
        if teaser:
            _doc("Teaser Prompts - Shorts Reels TikTok", teaser.get("content", ""))

        # 9. Mind Map
        mindmap = next((f for f in files if f.get("category") == "visual"), None)
        if mindmap:
            _doc("MIND MAP - Visao Geral do Projeto", mindmap.get("content", ""))
        else:
            mm_file = OUTPUT_DIR / f"mindmap_{project_id}.html"
            if mm_file.exists():
                _doc("MIND MAP - Visao Geral do Projeto", mm_file.read_text(encoding="utf-8")[:50000])

        # 10. 30 Ideias (Doc)
        if ideas:
            ideas_text = f"# 30 Ideias de Videos - {niche_name}\n\n"
            for idx, idea in enumerate(ideas, 1):
                ideas_text += f"## {idx}. {idea.get('title', '')}\n"
                ideas_text += f"**Hook:** {idea.get('hook', '')}\n"
                ideas_text += f"**Pilar:** {idea.get('pillar', '')} | **Prioridade:** {idea.get('priority', '')}\n\n"
            _doc(f"30 Ideias de Videos - {niche_name}", ideas_text)

        # 11. Titulos (Sheet)
        if ideas:
            td = [["#", "Titulo", "Hook", "Pilar", "Prioridade", "Score"]]
            for idx, idea in enumerate(ideas, 1):
                td.append([str(idx), idea.get("title",""), idea.get("hook","")[:100],
                          idea.get("pillar",""), idea.get("priority",""), str(idea.get("score",0))])
            _sheet(f"Titulos - {niche_name}", td)

        # 12. Nichos (Sheet)
        if niches:
            nd = [["Nome", "Descricao", "RPM", "Competicao"]]
            for n in niches:
                nd.append([n.get("name",""), n.get("description","")[:100],
                          n.get("rpm_range",""), n.get("competition","")])
            _sheet("5 Nichos Derivados - Niche Bending", nd)

        # 13. SEO Sheet
        if ideas:
            sd = [["#", "Titulo", "Score", "Rating", "Pilar", "Prioridade"]]
            for idx, idea in enumerate(ideas[:15], 1):
                sd.append([str(idx), idea.get("title",""), str(idea.get("score",0)),
                          idea.get("rating",""), idea.get("pillar",""), idea.get("priority","")])
            _sheet(f"SEO Sheet - Titulos e Tags ({len(sd)-1} videos)", sd)

        # 14. Narracoes
        narracoes = [f for f in files if f.get("category") == "narracao"]
        if narracoes:
            combined = ""
            for idx, nf in enumerate(narracoes[:3], 1):
                combined += f"\n{'='*60}\nNARRACAO {idx}: {nf.get('label', '')}\n{'='*60}\n\n"
                combined += (nf.get("content", "") or "") + "\n\n"
            _doc(f"Narracoes Completas - {niche_name}", combined)

        action_label = "drive_folder_created" if folder_created else ("drive_folder_recreated" if folder_recreated else "drive_synced")
        log_activity(project_id, action_label, f"{uploaded} novos + {skipped} ja existentes no Drive")
        return {
            "ok": True,
            "uploaded": uploaded,
            "skipped": skipped,
            "folder_id": folder_id,
            "folder_created": folder_created,
            "folder_recreated": folder_recreated,
        }

    try:
        result = await asyncio.to_thread(_sync)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"sync-drive error: {e}")
        return JSONResponse({"error": "Falha ao sincronizar com Google Drive."}, status_code=500)


@app.post("/api/admin/remove-title")
@limiter.limit("20/minute")
async def api_remove_title(request: Request, user=Depends(require_admin)):
    body = await request.json()
    idea_id = body.get("idea_id")
    progress_id = body.get("progress_id")

    if not idea_id and not progress_id:
        return JSONResponse({"error": "idea_id ou progress_id obrigatorio"}, status_code=400)

    from database import delete_idea, get_db

    if progress_id:
        # Remove assignment from student (delete progress entry), keep the idea
        with get_db() as conn:
            conn.execute("DELETE FROM progress WHERE id=?", (int(progress_id),))
        return JSONResponse({"ok": True})

    if idea_id:
        # Delete the idea entirely
        delete_idea(int(idea_id))
        return JSONResponse({"ok": True})


@app.post("/api/admin/release-titles")
@limiter.limit("20/minute")
async def api_release_titles(request: Request, user=Depends(require_admin)):
    body = await request.json()
    assignment_id = body.get("assignment_id")
    count = body.get("count", 5)
    if not assignment_id:
        return JSONResponse({"error": "assignment_id obrigatorio"}, status_code=400)
    from database import release_more_titles, get_db, create_notification
    added = release_more_titles(int(assignment_id), int(count))

    # Notify student
    try:
        with get_db() as conn:
            row = conn.execute("SELECT student_id, niche FROM assignments WHERE id=?", (int(assignment_id),)).fetchone()
            if row:
                create_notification(row["student_id"], "titles_released",
                    f"{added} novos titulos liberados!",
                    f"Voce recebeu {added} novos titulos no nicho {row['niche']}. Acesse seu painel para comecar.",
                    "/student")
    except Exception:
        pass

    return JSONResponse({"ok": True, "added": added})


@app.post("/api/admin/assign-niche")
@limiter.limit("20/minute")
async def api_assign_niche(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    project_id = body.get("project_id", "")
    niche = (body.get("niche") or "").strip()
    titles = body.get("titles", 5)
    if not student_id or not niche:
        return JSONResponse({"error": "student_id e niche obrigatorios"}, status_code=400)
    from database import create_assignment
    aid = create_assignment(int(student_id), project_id, niche, int(titles))
    return JSONResponse({"ok": True, "assignment_id": aid})


@app.post("/api/admin/toggle-student")
@limiter.limit("20/minute")
async def api_toggle_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)
    from database import get_user, update_user
    student = get_user(int(student_id))
    if student:
        update_user(int(student_id), active=0 if student["active"] else 1)
    return JSONResponse({"ok": True})


@app.post("/api/admin/regenerate-titles")
@limiter.limit("3/minute")
async def api_regenerate_titles(request: Request, user=Depends(require_admin)):
    """Delete all existing titles and regenerate 30 based on chosen niches + SOP."""
    body = await request.json()
    project_id = body.get("project_id", "").strip()
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_db, get_niches, get_project, get_ideas, save_idea, log_activity
    from services import get_project_sop
    from protocols.ai_client import chat
    from config import MAX_TOKENS_LARGE, LANG_LABELS
    import asyncio

    project = get_project(project_id)
    if not project:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    sop = get_project_sop(project_id)
    if not sop:
        return JSONResponse({"error": "SOP nao encontrado para este projeto"}, status_code=400)

    # Get chosen niches
    all_niches = get_niches(project_id)
    chosen = [n for n in all_niches if n.get("chosen")]
    if not chosen:
        chosen = all_niches[:2] if all_niches else [{"name": project.get("niche_chosen", ""), "description": ""}]

    niches_text = "\n".join([f"- {n['name']}: {n.get('description', '')}" for n in chosen])
    lang = project.get("language", "pt-BR")
    lang_label = LANG_LABELS.get(lang, lang)
    lang_instruction = f"\n\nIMPORTANTE: Todo o conteudo deve ser gerado em {lang_label}."

    try:
        # PRE-RESEARCH: collect trending data (YouTube + Google Trends)
        demand_summary = ""
        demand_data = {}
        try:
            from protocols.trend_research import research_niche_demand
            yt_key = ""
            with get_db() as conn:
                yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
                if yt_row:
                    yt_key = yt_row["value"]
            niche_for_research = project.get("niche_chosen", project.get("name", ""))
            demand_data = research_niche_demand(niche_for_research, lang, yt_key)
            demand_summary = demand_data.get("summary", "")
        except Exception as e:
            logger.warning(f"Pre-research failed (non-blocking): {e}")

        # KEYWORD RESEARCH: SOP + niches + titles + trending keywords + Google Trends
        keywords_block = ""
        niche_keywords = []
        existing_titles = [i["title"] for i in get_ideas(project_id)]
        lang_to_country = {"pt": "br", "en": "us", "es": "es", "fr": "fr", "de": "de"}
        country = lang_to_country.get(lang[:2], "us")
        niche_names = [n["name"] for n in chosen]
        cached = None
        try:
            from protocols.keywords_everywhere import research_niche_keywords

            # Collect trending keywords from YouTube + Google Trends
            trending_seeds = []
            trending_seeds.extend(demand_data.get("trending_keywords", []))
            for rs in demand_data.get("rising_searches", []):
                trending_seeds.append(rs.get("query", ""))

            # Check cache first (valid 7 days, saves DataForSEO credits)
            from database import get_keyword_cache, save_keyword_cache
            cached = get_keyword_cache(project_id)
            if cached:
                niche_keywords = cached
                logger.info(f"Using cached keywords ({len(cached)} keywords)")
            else:
                niche_keywords = research_niche_keywords(
                    niche_names, language=lang, country=country,
                    sop_text=sop, existing_titles=existing_titles,
                    trending_keywords=trending_seeds,
                )
                if niche_keywords:
                    save_keyword_cache(project_id, niche_keywords)
        except Exception as e:
            logger.warning(f"Niche keyword research failed (non-blocking): {e}")

        # YouTube Autocomplete — what people ACTUALLY search for
        autocomplete_suggestions = []
        try:
            from protocols.viral_engine import research_autocomplete_keywords
            seed_kws = [n["name"] for n in chosen]
            if niche_keywords:
                seed_kws.extend([kw["keyword"] for kw in niche_keywords[:5]])
            autocomplete_suggestions = research_autocomplete_keywords(seed_kws, lang[:2])
            # Also add autocomplete suggestions to niche_keywords volume lookup
            if autocomplete_suggestions and not cached:
                from protocols.keywords_everywhere import get_keyword_data
                auto_vol = get_keyword_data(
                    autocomplete_suggestions[:50],
                    country=country,
                    language=lang[:2],
                )
                for av in auto_vol:
                    if av.get("vol", 0) > 0:
                        niche_keywords.append(av)
                # Re-sort by volume
                niche_keywords.sort(key=lambda x: x.get("vol", 0), reverse=True)
                # Update cache with expanded keywords
                if niche_keywords:
                    save_keyword_cache(project_id, niche_keywords)
        except Exception as e:
            logger.warning(f"YouTube autocomplete failed (non-blocking): {e}")

        # Analyze channel's OWN best videos (what already works)
        channel_best_videos = []
        try:
            from protocols.viral_engine import analyze_channel_best_videos
            channel_url = project.get("channel_original", "")
            if channel_url:
                channel_best_videos = analyze_channel_best_videos(channel_url)
                logger.info(f"Channel analysis: {len(channel_best_videos)} top videos found")
        except Exception as e:
            logger.warning(f"Channel best videos analysis failed (non-blocking): {e}")

        # Delete existing ideas (not assigned to students)
        with get_db() as conn:
            conn.execute("""
                DELETE FROM ideas WHERE project_id=? AND id NOT IN (
                    SELECT DISTINCT idea_id FROM progress WHERE idea_id IS NOT NULL
                )
            """, (project_id,))
            deleted = conn.total_changes

        # Build viral prompt using the Viral Engine
        from protocols.viral_engine import build_viral_prompt
        system_prompt, user_prompt = build_viral_prompt(
            channel_name=project.get('name', ''),
            niches=chosen,
            sop_text=sop,
            keywords_with_volume=niche_keywords,
            autocomplete_suggestions=autocomplete_suggestions,
            demand_summary=demand_summary,
            lang=lang,
            count=35,  # Generate 35 so quality gate can filter to best 30
            existing_titles=existing_titles,
            channel_best_videos=channel_best_videos,
        )

        response = await asyncio.to_thread(
            chat, user_prompt,
            system_prompt,
            None,  # model (use default)
            MAX_TOKENS_LARGE,  # max_tokens
            0.85,  # temperature — slightly higher for creativity
        )

        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if not json_match:
            return JSONResponse({"error": "IA nao retornou JSON valido"}, status_code=500)

        new_ideas = json.loads(json_match.group())

        # QUALITY GATE — score each title for viral potential and map volume
        from protocols.viral_engine import filter_best_titles, score_viral_title
        from protocols.keywords_everywhere import _strip_accents, _GENERIC_SINGLE_WORDS, match_keyword_in_title

        # Map volume using keyword matching
        def _map_volumes(ideas_list):
            if not niche_keywords:
                return
            kw_vol_map = {
                _strip_accents(kw["keyword"].lower()): kw["vol"]
                for kw in niche_keywords
                if " " in kw["keyword"] or kw["keyword"].lower() not in _GENERIC_SINGLE_WORDS
            }
            for idea in ideas_list:
                title_lower = _strip_accents(idea.get("title", "").lower())
                best_vol = 0
                for kw_text, kw_vol in kw_vol_map.items():
                    if match_keyword_in_title(kw_text, title_lower) and kw_vol > best_vol:
                        best_vol = kw_vol
                idea["vol"] = best_vol if best_vol > 0 else -1

        _map_volumes(new_ideas)

        # Score and filter — only keep titles with viral potential
        accepted, rejected = filter_best_titles(new_ideas, niche_keywords, lang[:2])
        logger.info(f"Quality gate R1: {len(accepted)} accepted, {len(rejected)} rejected")

        # REGENERATION LOOP — if too many rejected, ask AI to replace them
        if len(accepted) < 28 and len(rejected) >= 3:
            missing = 30 - len(accepted)
            rejected_titles = [r.get("title", "") for r in rejected[:5]]
            rejected_issues = []
            for r in rejected[:5]:
                issues = r.get("_viral_issues", [])
                if issues:
                    rejected_issues.append(f'  "{r.get("title", "")[:50]}" — problemas: {", ".join(issues)}')

            regen_prompt = f"""Estes {len(rejected)} titulos foram REJEITADOS pelo quality gate:
{chr(10).join(rejected_issues)}

Gere {missing} titulos SUBSTITUTOS que corrijam esses problemas.
CADA titulo DEVE:
- Conter keyword de volume: {', '.join(f'"{kw["keyword"]}"' for kw in niche_keywords[:10])}
- Ter POWER WORD em CAPS
- Criar CURIOSITY GAP
- Maximo 80 caracteres
- Seguir o estilo do SOP

Retorne APENAS JSON: [{{"title":"...","title_b":"","hook":"...","summary":"...","pillar":"...","priority":"ALTA"}}]"""

            try:
                regen_response = await asyncio.to_thread(
                    chat, regen_prompt, system_prompt, None, MAX_TOKENS_MEDIUM, 0.9,
                )
                regen_match = re.search(r'\[.*\]', regen_response, re.DOTALL)
                if regen_match:
                    regen_ideas = json.loads(regen_match.group())
                    _map_volumes(regen_ideas)
                    regen_accepted, _ = filter_best_titles(regen_ideas, niche_keywords, lang[:2], min_score=30)
                    accepted.extend(regen_accepted)
                    logger.info(f"Quality gate R2: +{len(regen_accepted)} from regeneration")
            except Exception as e:
                logger.warning(f"Regeneration loop failed (non-blocking): {e}")

        # Use accepted titles (sorted by viral score, cap at 30)
        new_ideas = accepted[:30]

        # Mark titles containing TRENDING keywords (YouTube trending + Google Trends)
        trending_terms = set()
        for kw in demand_data.get("trending_keywords", []):
            trending_terms.add(_strip_accents(kw.lower()))
        for rs in demand_data.get("rising_searches", []):
            trending_terms.add(_strip_accents(rs.get("query", "").lower()))
        # Also trending titles from YouTube (last 14 days)
        for tt in demand_data.get("trending_titles", []):
            # Extract significant words from viral titles
            words = [w for w in _strip_accents(tt.lower()).split() if len(w) >= 5]
            trending_terms.update(words)

        for idea in new_ideas:
            title_lower = _strip_accents(idea.get("title", "").lower())
            is_trending = 0
            for term in trending_terms:
                if len(term) >= 4 and term in title_lower:
                    is_trending = 1
                    break
            idea["_trending"] = is_trending

        kw_hit_count = sum(1 for idea in new_ideas if idea.get("vol", 0) and idea.get("vol", 0) > 0)

        generated = 0
        for i, idea in enumerate(new_ideas[:30]):
            title = idea.get("title", f"Titulo {i+1}")
            if len(title) > 100:
                title = title[:97] + "..."
            vol = idea.get("vol", 0) or 0
            comp = idea.get("competition", -1)
            title_b = idea.get("title_b", "")
            if title_b and len(title_b) > 100:
                title_b = title_b[:97] + "..."
            save_idea(project_id, i + 1, title,
                     idea.get("hook", ""), idea.get("summary", ""),
                     idea.get("pillar", ""), idea.get("priority", "MEDIA"),
                     search_volume=vol, search_competition=comp, title_b=title_b,
                     trending=idea.get("_trending", 0))
            generated += 1

        total = len(new_ideas[:30])
        kw_coverage = (kw_hit_count / total * 100) if total > 0 else 0
        log_activity(project_id, "titles_regenerated",
                     f"{generated} titulos re-gerados baseados em {len(chosen)} nicho(s) | "
                     f"Keywords: {kw_hit_count}/{total} ({kw_coverage:.0f}%) com volume")

        return JSONResponse({
            "ok": True,
            "generated": generated,
            "deleted": deleted,
            "niches_used": len(chosen),
            "keyword_coverage": f"{kw_coverage:.0f}%",
            "keywords_matched": kw_hit_count,
            "keywords_total": total,
            "cached_keywords": bool(cached) if 'cached' in dir() else False,
        })
    except Exception as e:
        logger.error(f"regenerate-titles error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao re-gerar titulos."}, status_code=500)


# ═══════════════════════════════════════════════════════════
# ADMIN RESOURCES — Files shared with students for download
# ═══════════════════════════════════════════════════════════

@app.post("/api/admin/upload-resource")
@limiter.limit("10/minute")
async def api_upload_resource(request: Request, user=Depends(require_admin)):
    """Upload a resource file for students to download.

    target_student_id semantics:
      - NULL (or 0 on input) = available to ALL students
      - <positive int> = restricted to that specific student (must exist in users table)

    target_project_id semantics:
      - '' = not tied to a specific project
      - '<project_id>' = restricted to students assigned to that project
    """
    from database import get_db
    from datetime import datetime

    form = await request.form()
    file = form.get("file")
    label = form.get("label", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "general").strip()
    badge_color = form.get("badge_color", "#7c3aed").strip()
    badge_icon = form.get("badge_icon", "📦").strip()
    # target_student=0 means "all students" — must be stored as NULL to satisfy
    # FOREIGN KEY constraint (id=0 does not exist in users table)
    try:
        _raw_target = int(form.get("target_student_id", 0) or 0)
    except (ValueError, TypeError):
        _raw_target = 0
    target_student: int | None = _raw_target if _raw_target > 0 else None
    target_project = form.get("target_project_id", "").strip()

    if not file or not label:
        return JSONResponse({"error": "Arquivo e label obrigatorios"}, status_code=400)

    # Validate target_student exists (if specific)
    if target_student is not None:
        from database import get_user
        if not get_user(target_student):
            return JSONResponse({"error": f"Aluno {target_student} nao encontrado"}, status_code=404)

    # Save file to output/resources/
    resources_dir = OUTPUT_DIR / "resources"
    resources_dir.mkdir(exist_ok=True)

    import secrets as _sec
    safe_name = f"{_sec.token_hex(4)}_{file.filename}"
    file_path = resources_dir / safe_name
    content = await file.read()
    file_path.write_bytes(content)

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO admin_resources (label, description, filename, file_path, file_size, category, badge_color, badge_icon, target_student_id, target_project_id, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                (label, description, file.filename, str(safe_name), len(content), category, badge_color, badge_icon, target_student, target_project, datetime.now().isoformat()),
            )
    except Exception as exc:
        # Clean up orphan file if DB insert failed
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
        logger.exception("upload-resource INSERT failed: %s", exc)
        raise

    scope = "TODOS os alunos" if target_student is None else f"aluno {target_student}"
    logger.info(f"Resource uploaded: {label} ({len(content)} bytes) → {scope}")
    return JSONResponse({"ok": True, "filename": file.filename, "size": len(content), "target": scope})


@app.post("/api/admin/delete-resource")
@limiter.limit("20/minute")
async def api_delete_resource(request: Request, user=Depends(require_admin)):
    """Delete a resource."""
    body = await request.json()
    resource_id = body.get("resource_id")
    if not resource_id:
        return JSONResponse({"error": "resource_id obrigatorio"}, status_code=400)

    from database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT file_path FROM admin_resources WHERE id=?", (int(resource_id),)).fetchone()
        if row:
            fpath = OUTPUT_DIR / "resources" / row["file_path"]
            if fpath.exists():
                fpath.unlink()
            conn.execute("DELETE FROM admin_resources WHERE id=?", (int(resource_id),))
    return JSONResponse({"ok": True})


@app.get("/api/resource/download/{resource_id}")
async def api_download_resource(request: Request, resource_id: int, user=Depends(require_auth)):
    """Download a resource file."""
    from database import get_db
    from fastapi.responses import FileResponse

    with get_db() as conn:
        row = conn.execute("SELECT * FROM admin_resources WHERE id=? AND active=1", (resource_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Recurso nao encontrado"}, status_code=404)
        row = dict(row)

        # Check if resource is targeted to specific student
        if row["target_student_id"] and row["target_student_id"] != user["id"] and user.get("role") != "admin":
            return JSONResponse({"error": "Sem permissao"}, status_code=403)

        # Increment download counter
        conn.execute("UPDATE admin_resources SET downloads = downloads + 1 WHERE id=?", (resource_id,))

    fpath = OUTPUT_DIR / "resources" / row["file_path"]
    if not fpath.exists():
        return JSONResponse({"error": "Arquivo nao encontrado no servidor"}, status_code=404)

    return FileResponse(str(fpath), filename=row["filename"], media_type="application/octet-stream")


@app.post("/api/admin/generate-agent")
@limiter.limit("3/minute")
async def api_generate_agent(request: Request, user=Depends(require_admin)):
    """Generate a pipeline agent for a student's channel based on the SOP."""
    body = await request.json()
    student_id = body.get("student_id")
    channel_id = body.get("channel_id", 0)
    project_id = body.get("project_id", "")

    if not student_id or not project_id:
        return JSONResponse({"error": "student_id e project_id obrigatorios"}, status_code=400)

    from database import get_user, get_project, get_db
    from services import get_project_sop
    from protocols.ai_client import chat
    import asyncio

    student = get_user(int(student_id))
    project = get_project(project_id)
    if not student or not project:
        return JSONResponse({"error": "Aluno ou projeto nao encontrado"}, status_code=404)

    sop = get_project_sop(project_id)
    if not sop:
        return JSONResponse({"error": "SOP nao encontrado"}, status_code=400)

    niche = project.get("niche_chosen", project["name"])
    lang = project.get("language", "pt-BR")

    # Get channel info if available
    channel_name = niche
    channel_url = project.get("channel_original", "")
    if channel_id:
        with get_db() as conn:
            ch = conn.execute("SELECT * FROM student_channels WHERE id=?", (int(channel_id),)).fetchone()
            if ch:
                channel_name = ch["channel_name"]
                channel_url = ch["channel_url"] or channel_url

    try:
        # Use the REAL build_agent.py from ATOMACAO pipeline
        # This generates the FULL 30KB agent with all VEO3 rules, EDITOR_META, sync, etc.
        import sys
        from pathlib import Path as _Path
        from datetime import datetime

        # Try bundled location first (production Docker), then external (local dev)
        BUNDLED = _Path(__file__).parent / "atomacao_agent"
        EXTERNAL = _Path(__file__).parent.parent / "ATOMACAO CANAL FULL" / "agent"

        if (BUNDLED / "base" / "AGENT_BASE.md").exists():
            AGENT_TOOLS = BUNDLED / "tools"
            AGENT_BASE = BUNDLED / "base" / "AGENT_BASE.md"
            NICHE_CONFIG = BUNDLED / "niches" / "niche_configs.json"
            STYLES_CONFIG = BUNDLED / "styles" / "visual_styles.json"
        else:
            AGENT_TOOLS = EXTERNAL / "tools"
            AGENT_BASE = EXTERNAL / "base" / "AGENT_BASE.md"
            NICHE_CONFIG = EXTERNAL / "niches" / "niche_configs.json"
            STYLES_CONFIG = EXTERNAL / "styles" / "visual_styles.json"

        if not AGENT_BASE.exists():
            return JSONResponse({"error": "Template de agente nao encontrado. Verifique atomacao_agent/ ou ATOMACAO CANAL FULL/."}, status_code=500)

        # Find best matching niche from configs
        import json as _json
        niche_configs = _json.loads(NICHE_CONFIG.read_text(encoding="utf-8"))
        styles_config = {}
        if STYLES_CONFIG.exists():
            styles_config = _json.loads(STYLES_CONFIG.read_text(encoding="utf-8"))
            styles_config.pop("_meta", None)

        # Match niche key by name similarity
        niche_lower = niche.lower()
        best_key = None
        best_score = 0
        for key, cfg in niche_configs.items():
            score = 0
            check_names = [key, cfg.get("title", ""), cfg.get("agent_name", "")]
            for name in check_names:
                if niche_lower in name.lower() or name.lower() in niche_lower:
                    score = max(score, len(name))
            # Check keywords
            for word in niche_lower.split():
                if len(word) > 3 and word in key.lower():
                    score += 5
            if score > best_score:
                best_score = score
                best_key = key

        if not best_key:
            # Default to civilizacao_historica or first available
            best_key = list(niche_configs.keys())[0]
            logger.warning(f"No niche match for '{niche}', using default: {best_key}")

        cfg = niche_configs[best_key]
        agent_name = cfg.get("agent_name", "AGENT")

        # Get style from request
        style_key = body.get("style", "")
        style_cfg = styles_config.get(style_key) if style_key else None

        # Import and run build_agent
        sys.path.insert(0, str(AGENT_TOOLS))
        try:
            from build_agent import build_agent, load_base
            base_template = AGENT_BASE.read_text(encoding="utf-8")
            agent_text = build_agent(best_key, cfg, base_template, style_cfg)
        finally:
            sys.path.pop(0)

        if not agent_text or len(agent_text) < 1000:
            return JSONResponse({"error": "Agente gerado muito curto"}, status_code=500)

        # Save as resource for the student
        resources_dir = OUTPUT_DIR / "resources"
        resources_dir.mkdir(exist_ok=True)

        style_suffix = f"_{style_key}" if style_key else ""
        filename = f"AGENT_{agent_name}_v2.0{style_suffix}.md"
        file_path = resources_dir / filename
        file_path.write_text(agent_text, encoding="utf-8")
        file_size = len(agent_text.encode("utf-8"))

        with get_db() as conn:
            # Remove previous agent for same student+niche if exists
            conn.execute(
                "DELETE FROM admin_resources WHERE target_student_id=? AND category='agente' AND label LIKE ?",
                (int(student_id), f"Agente {agent_name}%"),
            )
            conn.execute(
                "INSERT INTO admin_resources (label, description, filename, file_path, file_size, category, badge_color, badge_icon, target_student_id, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                (f"Agente {agent_name} v2.0{style_suffix}",
                 f"Agente COMPLETO ({file_size // 1024}KB) para {channel_name} — cole no Claude/Gemini para produzir videos",
                 filename, filename, file_size, "agente", "#7c3aed", "🤖",
                 int(student_id), datetime.now().isoformat()),
            )

        from database import log_activity, create_notification
        log_activity(project_id, "agent_generated",
                     f"Agente {agent_name} v2.0{style_suffix} ({file_size // 1024}KB) gerado para {student['name']}")
        create_notification(int(student_id), "agent", f"Agente {agent_name} Disponivel",
                           f"Seu agente de producao ({file_size // 1024}KB) esta pronto para download. Cole no Claude/Gemini.",
                           link="/student")

        return JSONResponse({
            "ok": True,
            "filename": filename,
            "size": file_size,
            "niche": niche,
            "agent_name": agent_name,
            "niche_key": best_key,
        })
    except Exception as e:
        logger.error(f"generate-agent error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao gerar agente."}, status_code=500)


@app.post("/api/admin/set-ai-model")
@limiter.limit("10/minute")
async def api_set_ai_model(request: Request, user=Depends(require_admin)):
    """Set the AI model used when admin shares API with students."""
    body = await request.json()
    model = body.get("model", "").strip()
    if not model:
        return JSONResponse({"error": "model obrigatorio"}, status_code=400)
    from database import set_setting
    set_setting("admin_ai_model", model)
    return JSONResponse({"ok": True})


@app.post("/api/admin/toggle-admin-api")
@limiter.limit("20/minute")
async def api_toggle_admin_api(request: Request, user=Depends(require_admin)):
    """Toggle whether a student can use the admin's LaoZhang API key."""
    body = await request.json()
    student_id = body.get("student_id")
    enable = body.get("enable", False)

    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import update_user, log_activity
    update_user(int(student_id), use_admin_api=1 if enable else 0)
    log_activity("", "admin_api_toggle",
                 f"API admin {'liberada' if enable else 'revogada'} para aluno {student_id}")
    return JSONResponse({"ok": True})


@app.post("/api/admin/create-student-drive")
@limiter.limit("5/minute")
async def api_create_student_drive(request: Request, user=Depends(require_admin)):
    """Create Google Drive folder for a student and share with their email."""
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import get_user, set_student_drive_folder, log_activity
    student = get_user(int(student_id))
    if not student:
        return JSONResponse({"error": "Aluno nao encontrado"}, status_code=404)

    if student.get("drive_folder_id"):
        return JSONResponse({"error": "Aluno ja tem pasta Drive"}, status_code=400)

    try:
        from protocols.google_export import get_or_create_student_folder, share_folder, find_or_create_subfolder, create_doc
        from database import get_student_channels, get_db, save_student_drive_file

        # 1. Create root folder + share
        folder_id = get_or_create_student_folder(student["name"])
        share_folder(folder_id, student["email"], "writer")
        set_student_drive_folder(int(student_id), folder_id)

        # 2. Create channel subfolders
        channels = get_student_channels(int(student_id))
        synced = 0
        for ch in channels:
            ch_name = ch.get("channel_name", "Canal")
            find_or_create_subfolder(ch_name, folder_id)
            logger.info(f"[DRIVE] Channel folder created: {ch_name}")

        # 3. Auto-sync existing files
        with get_db() as conn:
            assignments = conn.execute(
                "SELECT DISTINCT project_id FROM assignments WHERE student_id=?",
                (int(student_id),),
            ).fetchall()
            project_ids = [a["project_id"] for a in assignments]

            if project_ids:
                placeholders = ",".join("?" * len(project_ids))
                files = conn.execute(f"""
                    SELECT f.id, f.category, f.label, f.filename, f.content, f.project_id
                    FROM files f
                    WHERE f.project_id IN ({placeholders})
                    AND f.category NOT IN ('analise', 'visual')
                    AND f.content IS NOT NULL AND f.content != ''
                    AND LENGTH(f.content) > 50
                    ORDER BY f.created_at
                """, project_ids).fetchall()

                # Check already synced
                existing_synced = set()
                for row in conn.execute(
                    "SELECT file_id FROM student_drive_files WHERE student_id=?",
                    (int(student_id),),
                ).fetchall():
                    existing_synced.add(row["file_id"])

                # Map channels to projects
                channel_by_project = {}
                for ch in channels:
                    if ch.get("project_id"):
                        channel_by_project[ch["project_id"]] = ch.get("channel_name", "Canal")

                for f in files:
                    f = dict(f)
                    if f["id"] in existing_synced:
                        continue
                    try:
                        ch_name = channel_by_project.get(f["project_id"], "Projeto")
                        ch_folder = find_or_create_subfolder(ch_name, folder_id)
                        doc_id = create_doc(f["label"], f["content"], ch_folder)
                        if doc_id:
                            save_student_drive_file(int(student_id), f["id"], doc_id, ch_folder,
                                                   f["filename"], f["label"], f["category"])
                            synced += 1
                    except Exception as e:
                        logger.warning(f"[DRIVE] Sync file failed: {f['filename']}: {e}")

        log_activity("", "drive_student_created",
                     f"Pasta Drive criada para {student['name']} + {synced} arquivos sincronizados")
        return JSONResponse({
            "ok": True,
            "folder_id": folder_id,
            "folder_url": f"https://drive.google.com/drive/folders/{folder_id}",
            "channels_created": len(channels),
            "files_synced": synced,
        })
    except Exception as e:
        logger.error(f"create-student-drive error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao criar pasta Drive. Verifique a conexao Google Drive."}, status_code=500)


@app.post("/api/admin/sync-student-drive")
@limiter.limit("3/minute")
async def api_sync_student_drive(request: Request, user=Depends(require_admin)):
    """Sync all existing student files to their Google Drive folder."""
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import get_user, get_db, get_student_drive_folder

    student = get_user(int(student_id))
    if not student:
        return JSONResponse({"error": "Aluno nao encontrado"}, status_code=404)

    folder_id = get_student_drive_folder(int(student_id))
    if not folder_id:
        return JSONResponse({"error": "Aluno nao tem pasta Drive. Crie primeiro."}, status_code=400)

    try:
        from protocols.google_export import create_doc, find_or_create_subfolder
        from database import get_student_channels, save_student_drive_file

        synced = 0

        # Get all visible files for projects this student is assigned to
        with get_db() as conn:
            assignments = conn.execute(
                "SELECT DISTINCT project_id FROM assignments WHERE student_id=?",
                (int(student_id),),
            ).fetchall()
            project_ids = [a["project_id"] for a in assignments]

            if not project_ids:
                return JSONResponse({"ok": True, "synced": 0, "message": "Nenhum projeto atribuido"})

            placeholders = ",".join("?" * len(project_ids))
            # Sync student-accessible files to Drive:
            # INCLUDE: roteiros, narracoes, SEO, thumbnails, music, teasers, trends, disclaimers
            # EXCLUDE: SOP/analise (admin-only), mind maps (visual), nichos brutos
            files = conn.execute(f"""
                SELECT f.id, f.category, f.label, f.filename, f.content, f.project_id
                FROM files f
                WHERE f.project_id IN ({placeholders})
                AND f.content IS NOT NULL AND f.content != ''
                AND LENGTH(f.content) > 50
                AND f.category NOT IN ('analise', 'visual')
                ORDER BY f.created_at
            """, project_ids).fetchall()

        # Get channels for subfolder naming
        channels = get_student_channels(int(student_id))
        channel_by_project = {}
        for ch in channels:
            if ch.get("project_id"):
                channel_by_project[ch["project_id"]] = ch.get("channel_name", "Canal")

        # Check which files are already synced
        with get_db() as conn:
            existing = set()
            for row in conn.execute(
                "SELECT file_id FROM student_drive_files WHERE student_id=?",
                (int(student_id),),
            ).fetchall():
                existing.add(row["file_id"])

        # Sync each file
        for f in files:
            f = dict(f)
            if f["id"] in existing:
                continue  # Already synced

            try:
                # Create channel subfolder
                channel_name = channel_by_project.get(f["project_id"], "Projeto")
                channel_folder = find_or_create_subfolder(channel_name, folder_id)

                # Create doc in Drive
                doc_id = create_doc(f["label"], f["content"], channel_folder)
                if doc_id:
                    save_student_drive_file(
                        int(student_id), f["id"], doc_id, channel_folder,
                        f["filename"], f["label"], f["category"],
                    )
                    synced += 1
            except Exception as e:
                logger.warning(f"Sync file {f['filename']} failed: {e}")
                continue

        return JSONResponse({"ok": True, "synced": synced})
    except Exception as e:
        logger.error(f"sync-student-drive error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao sincronizar arquivos."}, status_code=500)


@app.post("/api/admin/delete-student-drive")
@limiter.limit("5/minute")
async def api_delete_student_drive(request: Request, user=Depends(require_admin)):
    """Delete a student's Google Drive folder."""
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import get_user, set_student_drive_folder, log_activity
    student = get_user(int(student_id))
    if not student:
        return JSONResponse({"error": "Aluno nao encontrado"}, status_code=404)

    folder_id = student.get("drive_folder_id", "")
    if not folder_id:
        return JSONResponse({"error": "Aluno nao tem pasta Drive"}, status_code=400)

    try:
        from protocols.google_export import delete_drive_file
        delete_drive_file(folder_id)  # Deleting a folder deletes all contents
        set_student_drive_folder(int(student_id), "")
        log_activity("", "drive_student_deleted",
                     f"Pasta Drive removida de {student['name']}")
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-student-drive error: {e}", exc_info=True)
        # Even if Drive delete fails, clear the reference
        set_student_drive_folder(int(student_id), "")
        return JSONResponse({"ok": True, "warning": "Pasta pode nao ter sido removida do Drive"})


@app.post("/api/admin/delete-student")
@limiter.limit("10/minute")
async def api_delete_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)
    try:
        from database import delete_user
        delete_user(int(student_id))
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-student error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao excluir aluno."}, status_code=500)


@app.post("/api/admin/add-student-channel")
@limiter.limit("20/minute")
async def api_admin_add_student_channel(request: Request, user=Depends(require_admin)):
    """Admin adds a YouTube channel to a student."""
    body = await request.json()
    student_id = body.get("student_id")
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    niche = (body.get("niche") or "").strip()
    language = (body.get("language") or "pt-BR").strip()

    if not student_id or not name:
        return JSONResponse({"error": "student_id e nome do canal obrigatorios"}, status_code=400)

    from database import create_student_channel
    project_id = (body.get("project_id") or "").strip()
    try:
        cid = create_student_channel(int(student_id), name, url, niche, language, project_id=project_id)
        return JSONResponse({"ok": True, "channel_id": cid})
    except ValueError as e:
        return JSONResponse({"error": "Falha ao cadastrar canal."}, status_code=400)


@app.post("/api/admin/remove-student-channel")
@limiter.limit("20/minute")
async def api_admin_remove_student_channel(request: Request, user=Depends(require_admin)):
    """Admin removes a channel from a student."""
    body = await request.json()
    channel_id = body.get("channel_id")
    student_id = body.get("student_id")
    if not channel_id:
        return JSONResponse({"error": "channel_id obrigatorio"}, status_code=400)
    from database import delete_student_channel
    delete_student_channel(int(channel_id), int(student_id) if student_id else 0)
    return JSONResponse({"ok": True})


@app.post("/api/regenerate-mindmap")
@limiter.limit("5/minute")
async def api_regenerate_mindmap(request: Request, user=Depends(require_admin)):
    """Regenerate mind map HTML for a project."""
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id or not validate_project_id(project_id):
        return JSONResponse({"error": "project_id invalido"}, status_code=400)

    from database import get_project, get_niches, get_ideas, get_scripts, get_files as db_get_files, save_file, log_activity

    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    niches = get_niches(project_id)
    ideas = get_ideas(project_id)
    scripts = get_scripts(project_id)

    sop = ""
    for f in db_get_files(project_id, "analise"):
        if "sop" in f.get("label", "").lower() and f.get("content"):
            sop = f["content"]
            break

    niche_name = proj.get("niche_chosen") or proj.get("name", "Canal")
    niche_list = [{"name": n["name"], "description": n.get("description", ""),
                   "rpm_range": n.get("rpm_range", ""), "competition": n.get("competition", ""),
                   "pillars": json.loads(n["pillars"]) if isinstance(n.get("pillars"), str) else n.get("pillars", [])}
                  for n in niches]

    idea_list = [{"title": i["title"], "hook": i.get("hook", ""), "summary": i.get("summary", ""),
                  "priority": i.get("priority", "MEDIA")} for i in ideas]

    try:
        mindmap_html = generate_mindmap_html(
            niche_name, proj.get("channel_original", ""), sop,
            niche_list, idea_list[:15], len(scripts),
        )
        mindmap_filename = f"mindmap_{project_id}.html"
        (OUTPUT_DIR / mindmap_filename).write_text(mindmap_html, encoding="utf-8")
        log_activity(project_id, "mindmap_regenerated", "Mind Map atualizado")
        return JSONResponse({"ok": True, "path": f"/output-file?name={mindmap_filename}"})
    except Exception as e:
        logger.error(f"regenerate-mindmap error: {e}")
        return JSONResponse({"error": "Falha ao gerar mind map"}, status_code=500)


@app.post("/api/admin/toggle-file-visibility")
@limiter.limit("20/minute")
async def api_toggle_file_visibility(request: Request, user=Depends(require_admin)):
    """Toggle whether a file is visible to students."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT id, visible_to_students FROM files WHERE id=?", (int(file_id),)).fetchone()
        if not row:
            return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)
        new_val = 0 if row["visible_to_students"] else 1
        conn.execute("UPDATE files SET visible_to_students=? WHERE id=?", (new_val, int(file_id)))

        # Notify students if file made visible
        if new_val == 1:
            try:
                file_row = conn.execute("SELECT label, project_id FROM files WHERE id=?", (int(file_id),)).fetchone()
                if file_row:
                    students = conn.execute("SELECT DISTINCT student_id FROM assignments WHERE project_id=?",
                                           (file_row["project_id"],)).fetchall()
                    from database import create_notification
                    for s in students:
                        create_notification(s["student_id"], "file_available",
                            "Novo arquivo disponivel!",
                            f"O arquivo '{file_row['label']}' foi liberado para voce.",
                            "/student")
            except Exception:
                pass

    return JSONResponse({"ok": True, "visible": bool(new_val)})


@app.post("/api/admin/bulk-file-visibility")
@limiter.limit("20/minute")
async def api_bulk_file_visibility(request: Request, user=Depends(require_admin)):
    """Set visibility for all files in a project."""
    body = await request.json()
    project_id = body.get("project_id", "")
    visible = body.get("visible", False)
    category = body.get("category", "")

    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_db
    with get_db() as conn:
        if category:
            conn.execute(
                "UPDATE files SET visible_to_students=? WHERE project_id=? AND category=?",
                (1 if visible else 0, project_id, category),
            )
        else:
            conn.execute(
                "UPDATE files SET visible_to_students=? WHERE project_id=?",
                (1 if visible else 0, project_id),
            )

    return JSONResponse({"ok": True})


@app.post("/api/admin/youtube-settings")
@limiter.limit("5/minute")
async def api_admin_youtube_settings(request: Request, user=Depends(require_admin)):
    """Save YouTube API settings."""
    body = await request.json()
    api_key = (body.get("api_key") or "").strip()
    channel_id = (body.get("channel_id") or "").strip()

    from database import set_setting, _encrypt_api_key
    if api_key:
        set_setting("youtube_api_key", _encrypt_api_key(api_key))
    if channel_id:
        # Clean up: extract handle or ID from full URL
        cleaned = _extract_channel_identifier(channel_id)
        set_setting("youtube_channel_id", cleaned)
    return JSONResponse({"ok": True})


@app.post("/api/admin/save-dataforseo")
@limiter.limit("10/minute")
async def api_save_dataforseo(request: Request, user=Depends(require_admin)):
    """Save DataForSEO credentials to admin_settings."""
    body = await request.json()
    login = (body.get("login") or "").strip()
    password = (body.get("password") or "").strip()

    if not login or not password:
        return JSONResponse({"error": "Login e password obrigatorios"}, status_code=400)

    from database import set_setting
    set_setting("dataforseo_login", login)
    set_setting("dataforseo_password", password)

    # Clear cached credentials so next call picks up new ones
    from protocols.keywords_everywhere import _DATAFORSEO_LOGIN
    import protocols.keywords_everywhere as kw_mod
    kw_mod._DATAFORSEO_LOGIN = ""
    kw_mod._DATAFORSEO_PASSWORD = ""

    # Quick validation — check balance
    from protocols.keywords_everywhere import check_credits
    result = check_credits()
    if "error" in result:
        return JSONResponse({"ok": True, "warning": f"Salvo, mas verificacao falhou: {result['error']}"})

    return JSONResponse({"ok": True, "balance": result.get("balance", 0)})


def _extract_channel_identifier(raw: str) -> str:
    """Extract @handle or UCxxx from various YouTube URL formats."""
    import re as _re
    raw = raw.strip().rstrip("/")
    # https://youtube.com/@Handle or https://www.youtube.com/@Handle
    m = _re.search(r'youtube\.com/(@[\w.-]+)', raw)
    if m:
        return m.group(1)
    # https://youtube.com/channel/UCxxxxxx
    m = _re.search(r'youtube\.com/channel/(UC[\w-]+)', raw)
    if m:
        return m.group(1)
    # https://youtube.com/c/ChannelName
    m = _re.search(r'youtube\.com/c/([\w.-]+)', raw)
    if m:
        return m.group(1)
    # Already a bare @handle or UCxxx
    return raw


@app.get("/api/admin/youtube-stats")
@limiter.limit("5/minute")
async def api_admin_youtube_stats(request: Request, user=Depends(require_admin)):
    """Fetch YouTube channel stats using YouTube Data API.
    Resolves @handle to channel ID automatically.
    """
    from database import get_setting, _decrypt_api_key, set_setting

    yt_key = _decrypt_api_key(get_setting("youtube_api_key"))
    channel_id = get_setting("youtube_channel_id")

    if not yt_key or not channel_id:
        return JSONResponse({"error": "Configure YouTube API key e Channel ID primeiro"}, status_code=400)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:

            # If it's a @handle, resolve to channel ID first
            if channel_id.startswith("@"):
                search_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "q": channel_id, "type": "channel", "maxResults": 1, "key": yt_key},
                )
                search_data = search_resp.json()
                items = search_data.get("items", [])
                if not items:
                    # Try channels list with forHandle
                    handle_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/channels",
                        params={"part": "id", "forHandle": channel_id.lstrip("@"), "key": yt_key},
                    )
                    handle_data = handle_resp.json()
                    h_items = handle_data.get("items", [])
                    if h_items:
                        channel_id = h_items[0]["id"]
                        set_setting("youtube_channel_id", channel_id)
                    else:
                        return JSONResponse({"error": f"Handle {channel_id} nao encontrado"}, status_code=404)
                else:
                    channel_id = items[0]["snippet"]["channelId"]
                    set_setting("youtube_channel_id", channel_id)

            # Fetch channel stats
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "statistics,snippet", "id": channel_id, "key": yt_key},
            )
            data = resp.json()

        if "items" not in data or not data["items"]:
            return JSONResponse({"error": "Canal nao encontrado. Verifique o Channel ID."}, status_code=404)

        ch = data["items"][0]
        stats = ch.get("statistics", {})
        snippet = ch.get("snippet", {})

        return JSONResponse({
            "ok": True,
            "channel": snippet.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
            "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
        })
    except Exception as e:
        logger.error(f"youtube-stats error: {e}")
        return JSONResponse({"error": "Falha ao buscar estatisticas"}, status_code=500)


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
