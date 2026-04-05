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
        except Exception:
            pass
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
    """Read project files concatenated."""
    if not validate_project_id(id):
        return JSONResponse({"error": "ID invalido"}, status_code=400)

    project_dir = PROJECTS_DIR / id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    content = ""
    for f in sorted(project_dir.glob("*.md")):
        content += f"{'=' * 60}\n{f.stem.upper()}\n{'=' * 60}\n\n"
        content += f.read_text(encoding="utf-8") + "\n\n"
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

    from database import get_student_channels
    channels = get_student_channels(student_id)

    return render(request, "admin_student_detail.html", {
        "user": user,
        "student": student,
        "assignments": assignments,
        "has_api": has_api,
        "status_labels": status_labels,
        "status_colors": status_colors,
        "channels": channels,
    })


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
    if not password or len(password) < 12:
        return JSONResponse({"error": "Senha deve ter pelo menos 12 caracteres"}, status_code=400)

    from database import create_user, create_assignment
    uid = create_user(name, email, password, role="student", created_by=user.get("id"))
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

    return JSONResponse({"ok": True, "user_id": uid, "assignment_id": assignment_id})


@app.post("/api/admin/analyze-channel")
@limiter.limit("3/minute")
async def api_admin_analyze_channel(request: Request, user=Depends(require_admin)):
    """Full channel analysis pipeline: SOP → Niches → Titles → SEO → Mind Map."""
    body = await request.json()
    url = validate_url(body.get("url", ""))
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

    if not url:
        return JSONResponse({"error": "URL invalida"}, status_code=400)
    if not niche_name or len(niche_name) < 2:
        return JSONResponse({"error": "Nome do nicho invalido (min 2 caracteres)"}, status_code=400)

    logger.info(f"[ANALYZE] {user.get('email')}: url={url[:80]}, niche={niche_name}, lang={language}, nlm_sop={len(nlm_sop)} chars")

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
            from protocols.google_export import create_folder
            drive_folder_id = create_folder(f"YT Cloner - {niche_name}")
            update_project(project_id, drive_folder_id=drive_folder_id,
                          drive_folder_url=f"https://drive.google.com/drive/folders/{drive_folder_id}")
            logger.info(f"[ANALYZE] Drive folder created: {drive_folder_id}")
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

        # Priority 2: Transcripts + AI
        if not sop_content:
            logger.info(f"[ANALYZE] Trying transcript analysis for {url}")
            sop_content = analyze_via_transcripts(url, niche_name)
            if sop_content and len(sop_content) > 200:
                sop_source = "Transcricoes"
                logger.info(f"[ANALYZE] Transcript SOP: {len(sop_content)} chars")

        if not sop_content:
            sop_prompt = f"""Analise o conceito deste canal do YouTube e crie um SOP completo e detalhado.

URL: {url}
Nicho: {niche_name}

Crie um SOP (Standard Operating Procedure) incluindo TODAS estas secoes:

1. VISAO GERAL DO CANAL: Nicho exato, publico-alvo, estilo visual, formato dos videos, duracao media
2. FORMULA DE TITULOS: Padroes de titulos virais para esse nicho com exemplos
3. ESTRUTURA DE ROTEIRO: Hook (primeiros 30s), desenvolvimento por atos, climax, resolucao, CTA
4. PLAYBOOK DE HOOKS: 10 tipos de ganchos que funcionam nesse nicho com exemplos
5. TECNICAS DE STORYTELLING: Open loops, pattern interrupts, cliffhangers, specific spikes
6. REGRAS DE OURO: 10 regras que devem ser seguidas em todo roteiro
7. PILARES DE CONTEUDO: 5 categorias principais de videos
8. ESTILO DE THUMBNAIL: Padroes visuais (cores, tipografia, composicao) para thumbnails virais
9. VERSAO IA: Instrucoes para uma IA replicar este estilo (tom, vocabulario, ritmo, formalidade)

Seja EXTREMAMENTE detalhado e especifico para o nicho "{niche_name}".{lang_instruction}"""
            sop_content = chat(sop_prompt, system="Voce e um estrategista de canais faceless do YouTube com 10 anos de experiencia.", max_tokens=MAX_TOKENS_LARGE)

        save_file(project_id, "analise", f"SOP - {niche_name}", f"sop_{project_id}.md", sop_content)
        log_activity(project_id, "sop_generated", f"SOP via {sop_source}")

        _step(3, 'Gerando 5 nichos derivados')

        # Step 3: Generate 5 niches
        niche_prompt = f"""Baseado neste canal "{niche_name}" ({url}), gere 5 sub-nichos derivados.
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

        _step(4, 'Gerando 30 titulos virais')

        # Step 4: Generate 30 titles
        titles_prompt = f"""Gere 30 ideias de videos para o canal "{niche_name}".
SOP: {sop_content[:3000]}

REGRAS OBRIGATORIAS DO YOUTUBE:
- CADA titulo DEVE ter no MAXIMO 100 caracteres (incluindo espacos). Titulos maiores serao cortados pelo YouTube.
- Titulos devem ser impactantes mesmo sendo curtos.

Retorne JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"...","priority":"ALTA"}}]
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
                    # YouTube limit: max 100 characters
                    if len(title) > 100:
                        title = title[:97] + "..."
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

    # AI Usage stats
    ai_usage = {"total_tokens": 0, "total_cost": 0, "total_calls": 0, "by_project": [], "by_operation": []}
    try:
        from database import get_ai_usage_summary
        ai_usage = get_ai_usage_summary()
    except Exception:
        pass

    return render(request, "admin_panel.html", {
        "user": user,
        "stats": stats,
        "users": users,
        "projects": projects[:10],
        "activity": activity,
        "api_keys": api_keys,
        "ai_usage": ai_usage,
    })


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

        # Create main folder
        folder_id = create_folder(f"YT Cloner - {niche_name}")
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
        logger.error(f"connect-drive error: {e}")
        return JSONResponse({"error": "Falha ao conectar Google Drive."}, status_code=500)


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
        from database import get_project, get_files, get_ideas, get_niches, log_activity
        from protocols.google_export import create_doc, create_sheet, get_drive_service

        proj = get_project(project_id)
        if not proj:
            return {"error": "Projeto nao encontrado"}

        folder_id = proj.get("drive_folder_id", "")
        if not folder_id:
            return {"error": "Projeto sem pasta no Drive. Use 'Conectar' primeiro."}

        niche_name = proj.get("niche_chosen") or proj.get("name", "Projeto")
        uploaded = 0
        skipped = 0

        # List existing files in Drive folder to avoid duplicates
        existing_names = set()
        try:
            drive = get_drive_service()
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

        log_activity(project_id, "drive_synced", f"{uploaded} novos + {skipped} ja existentes no Drive")
        return {"ok": True, "uploaded": uploaded, "skipped": skipped}

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
