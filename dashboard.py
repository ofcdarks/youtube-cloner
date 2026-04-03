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
from middleware import CSRFMiddleware, SafeErrorMiddleware, RequestLogMiddleware, generate_csrf_token
from auth import (
    require_auth, require_admin, optional_auth, check_auth,
    get_session_token, SESSIONS,
)
from services import (
    get_filesystem_projects, get_project_files, get_output_files,
    build_categories, load_ideas, validate_file_path, validate_project_id,
    analyze_via_notebooklm, analyze_via_transcripts,
    sanitize_niche_name, validate_url, generate_mindmap_html,
)

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ytcloner")

# ── App Creation ─────────────────────────────────────────
app = FastAPI(title="YT Channel Cloner Dashboard", docs_url=None, redoc_url=None)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"error": "Muitas requisicoes. Tente novamente em alguns minutos."}, status_code=429)


# ── Middleware (order matters: last added = first executed) ──
app.add_middleware(SafeErrorMiddleware)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
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

    # NotebookLM credentials from env
    try:
        import base64
        nlm_creds = os.environ.get("NOTEBOOKLM_CREDENTIALS", "")
        if nlm_creds:
            nlm_dir = Path.home() / ".notebooklm"
            nlm_dir.mkdir(parents=True, exist_ok=True)
            (nlm_dir / "storage_state.json").write_text(
                base64.b64decode(nlm_creds.encode()).decode(), encoding="utf-8"
            )
            ctx = os.environ.get("NOTEBOOKLM_CONTEXT", "")
            if ctx:
                (nlm_dir / "context.json").write_text(
                    base64.b64decode(ctx.encode()).decode(), encoding="utf-8"
                )
            logger.info("NotebookLM credentials loaded from env")
    except Exception as e:
        logger.debug(f"NotebookLM setup: {e}")


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

    # Build categories from DB files (primary source)
    categories = {}
    if files:
        cat_config = {
            "analise": {"label": "Analise / SOP", "icon": "&#128200;", "color": "#7c3aed"},
            "seo": {"label": "SEO Pack", "icon": "&#128269;", "color": "#06b6d4"},
            "roteiros": {"label": "Roteiros", "icon": "&#128221;", "color": "#eab308"},
            "visual": {"label": "Mind Map / Visual", "icon": "&#127912;", "color": "#e040fb"},
            "musica": {"label": "Musica", "icon": "&#127925;", "color": "#22c55e"},
            "outro": {"label": "Outros", "icon": "&#128196;", "color": "#64748b"},
        }
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
            })

    # Also add legacy filesystem files
    output_files = get_output_files()
    cat_config = {
        "analise": {"label": "Analise / SOP", "icon": "&#128200;", "color": "#7c3aed"},
        "seo": {"label": "SEO Pack", "icon": "&#128269;", "color": "#06b6d4"},
        "roteiro": {"label": "Roteiros", "icon": "&#128221;", "color": "#eab308"},
        "narracao": {"label": "Narracoes", "icon": "&#127908;", "color": "#ff6e40"},
        "visual": {"label": "Mind Map / Visual", "icon": "&#127912;", "color": "#e040fb"},
        "outro": {"label": "Outros", "icon": "&#128196;", "color": "#64748b"},
    }
    for f in output_files:
        cat_key = f.get("category", "outro")
        if cat_key not in categories:
            cfg = cat_config.get(cat_key, cat_config["outro"])
            categories[cat_key] = {"label": cfg["label"], "icon": cfg["icon"], "color": cfg["color"], "files": []}
        existing_names = {ff.get("name", "") for ff in categories[cat_key]["files"]}
        if f.get("name", "") not in existing_names:
            categories[cat_key]["files"].append(f)

    # Mind map path
    mindmap_path = ""
    if current_project:
        mm = OUTPUT_DIR / f"mindmap_{current_project['id']}.html"
        if mm.exists():
            mindmap_path = f"/output-file?name=mindmap_{current_project['id']}.html"

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
    """Serve files from output directory safely — blocks DB and sensitive files."""
    if not name:
        return JSONResponse({"error": "nome obrigatorio"}, status_code=400)

    # Block sensitive files
    blocked = [".db", ".db-wal", ".db-shm", ".json", ".key", ".pem"]
    if any(name.lower().endswith(ext) for ext in blocked):
        return JSONResponse({"error": "Acesso negado"}, status_code=403)

    resolved = validate_file_path(name)
    if not resolved:
        return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)

    # Determine content type
    suffix = resolved.suffix.lower()
    content_types = {
        ".html": "text/html",
        ".md": "text/plain",
        ".txt": "text/plain",
        ".json": "application/json",
    }
    ct = content_types.get(suffix, "text/plain")

    try:
        content = resolved.read_text(encoding="utf-8")
        return PlainTextResponse(content, media_type=ct)
    except Exception:
        return JSONResponse({"error": "Erro ao ler arquivo"}, status_code=500)


@app.get("/file")
async def read_file(request: Request, path: str = "", user=Depends(require_auth)):
    """Read a file content — with path validation and role-based access."""
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
# API ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/api/ideas")
async def api_ideas(request: Request, project: str = "", user=Depends(require_auth)):
    from database import get_ideas, get_projects as db_projects
    if project:
        ideas = get_ideas(project)
    else:
        projs = db_projects()
        ideas = get_ideas(projs[0]["id"]) if projs else []
    return JSONResponse(ideas)


@app.get("/api/idea-details")
async def api_idea_details(request: Request, id: str = "", user=Depends(require_auth)):
    if not id:
        return JSONResponse({"error": "id obrigatorio"}, status_code=400)
    from database import get_idea, get_seo
    idea = get_idea(int(id))
    if not idea:
        return JSONResponse({"error": "Ideia nao encontrada"}, status_code=404)
    seo = get_seo(int(id))
    return JSONResponse({"idea": idea, "seo": seo})


@app.post("/api/toggle-used")
async def api_toggle_used(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("id")
    if not idea_id:
        return JSONResponse({"error": "id obrigatorio"}, status_code=400)
    from database import toggle_idea_used
    new_val = toggle_idea_used(int(idea_id))
    return JSONResponse({"ok": True, "used": new_val})


@app.get("/api/score-all")
@limiter.limit("3/minute")
async def api_score_all(
    request: Request,
    countries: str = "global,BR,US",
    force: str = "false",
    project: str = "",
    user=Depends(require_auth),
):
    country_list = countries.split(",")
    force_rescore = force.lower() in ("true", "1", "yes")

    from database import get_ideas, get_projects as db_projects, update_idea_score

    if project:
        pid = project
    else:
        projs = db_projects()
        pid = projs[0]["id"] if projs else ""

    if not pid:
        return JSONResponse({"error": "Nenhum projeto"}, status_code=400)

    ideas = get_ideas(pid)
    results = []

    from protocols.title_scorer import score_title

    for idea in ideas:
        if idea.get("score", 0) > 0 and not force_rescore:
            results.append({"id": idea["id"], "title": idea["title"], "score": idea["score"], "rating": idea["rating"], "skipped": True})
            continue
        try:
            score_result = score_title(idea["title"], country_list)
            update_idea_score(idea["id"], score_result["final_score"], score_result["rating"], score_result)
            results.append({
                "id": idea["id"],
                "title": idea["title"],
                "score": score_result["final_score"],
                "rating": score_result["rating"],
            })
        except Exception as e:
            results.append({"id": idea["id"], "title": idea["title"], "error": "Falha no scoring"})

    return JSONResponse({"ok": True, "scored": len(results), "results": results})


@app.post("/api/score-title")
@limiter.limit("10/minute")
async def api_score_title(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("id")
    if not idea_id:
        return JSONResponse({"error": "id obrigatorio"}, status_code=400)

    from database import get_idea, update_idea_score
    from protocols.title_scorer import score_title

    idea = get_idea(int(idea_id))
    if not idea:
        return JSONResponse({"error": "Ideia nao encontrada"}, status_code=404)

    result = score_title(idea["title"])
    update_idea_score(int(idea_id), result["final_score"], result["rating"], result)
    return JSONResponse({"ok": True, "score": result["final_score"], "rating": result["rating"], "details": result})


@app.post("/api/generate-ideas")
@limiter.limit("5/minute")
async def api_generate_ideas(request: Request, user=Depends(require_auth)):
    body = await request.json()
    niche = sanitize_niche_name(body.get("niche", "System Breakers"))
    count = body.get("count", 10)

    if not isinstance(count, int) or count < 1 or count > MAX_IDEAS_PER_REQUEST:
        return JSONResponse({"error": f"Quantidade deve ser entre 1 e {MAX_IDEAS_PER_REQUEST}"}, status_code=400)

    project_id = body.get("project_id", "")

    try:
        from protocols.ai_client import chat
        from database import get_ideas, get_projects as db_projects, save_idea, get_project, get_files as db_get_files

        if project_id:
            proj = get_project(project_id)
            if not proj:
                return JSONResponse({"error": "Projeto nao encontrado"}, status_code=400)
            pid = project_id
        else:
            projs = db_projects()
            if not projs:
                return JSONResponse({"error": "Nenhum projeto"}, status_code=400)
            pid = projs[0]["id"]

        existing = get_ideas(pid)
        existing_titles = [i["title"] for i in existing]
        next_num = max([i.get("num", 0) for i in existing], default=0) + 1

        # Load SOP
        sop = ""
        for f in db_get_files(pid, "analise"):
            if "sop" in f.get("label", "").lower() and f.get("content"):
                sop = f["content"]
                break
        if not sop:
            sop_path = OUTPUT_DIR / "loaded_dice_sop.md"
            sop = sop_path.read_text(encoding="utf-8") if sop_path.exists() else ""

        prompt = f"""Gere {count} novas ideias de videos para o canal "{niche}".

REGRAS:
- Cada ideia deve ser UNICA e diferente das existentes
- Siga a mesma estrutura do SOP (hook forte, numeros impactantes, historia real)
- Inclua para cada ideia: titulo viral, hook dos primeiros 30s, resumo de 2 linhas, pilar de conteudo, prioridade (ALTA/MEDIA/BAIXA)

TITULOS JA EXISTENTES (NAO REPETIR):
{chr(10).join(f'- {t}' for t in existing_titles[:30])}

SOP:
{sop[:4000]}

Retorne em formato JSON valido:
[{{"title": "...", "hook": "...", "summary": "...", "pillar": "...", "priority": "ALTA"}}]

Retorne APENAS o JSON."""

        response = chat(prompt, max_tokens=MAX_TOKENS_MEDIUM, temperature=0.8)
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if not json_match:
            return JSONResponse({"error": "IA nao retornou JSON valido"}, status_code=500)

        new_ideas = json.loads(json_match.group())
        saved = []
        for idea in new_ideas:
            iid = save_idea(
                pid, next_num,
                idea.get("title", ""),
                idea.get("hook", ""),
                idea.get("summary", ""),
                idea.get("pillar", ""),
                idea.get("priority", "MEDIA"),
            )
            saved.append({"id": iid, "num": next_num, "title": idea.get("title", "")})
            next_num += 1

        return JSONResponse({"ok": True, "generated": len(saved), "ideas": saved})
    except Exception as e:
        logger.error(f"generate-ideas error: {e}")
        return JSONResponse({"error": "Falha ao gerar ideias"}, status_code=500)


@app.post("/api/generate-script")
@limiter.limit("5/minute")
async def api_generate_script(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("idea_id")
    project_id = body.get("project_id", "")

    if not idea_id:
        return JSONResponse({"error": "idea_id obrigatorio"}, status_code=400)

    try:
        from database import get_idea, get_files as db_get_files, get_projects as db_projects, save_script
        from protocols.ai_client import generate_script

        idea = get_idea(int(idea_id))
        if not idea:
            return JSONResponse({"error": "Ideia nao encontrada"}, status_code=404)

        pid = project_id or idea["project_id"]

        # Load SOP
        sop = ""
        for f in db_get_files(pid, "analise"):
            if "sop" in f.get("label", "").lower() and f.get("content"):
                sop = f["content"]
                break
        if not sop:
            sop_path = OUTPUT_DIR / "loaded_dice_sop.md"
            sop = sop_path.read_text(encoding="utf-8") if sop_path.exists() else ""

        script = generate_script(idea["title"], idea.get("hook", ""), sop)

        save_script(pid, idea["title"], script, int(idea_id), "10-12 min")

        words = len(script.split())
        return JSONResponse({
            "ok": True,
            "title": idea["title"],
            "script": script[:500] + "...",
            "words": words,
            "duration_estimate": f"~{round(words / 140, 1)} min",
        })
    except Exception as e:
        logger.error(f"generate-script error: {e}")
        return JSONResponse({"error": "Falha ao gerar roteiro"}, status_code=500)


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

    return render(request, "admin_student_detail.html", {
        "user": user,
        "student": student,
        "assignments": assignments,
        "has_api": has_api,
        "status_labels": status_labels,
        "status_colors": status_colors,
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
    if not password or len(password) < 6:
        return JSONResponse({"error": "Senha deve ter pelo menos 6 caracteres"}, status_code=400)

    from database import create_user, create_assignment
    uid = create_user(name, email, password, role="student", created_by=user.get("id"))
    if not uid:
        return JSONResponse({"error": "Email ja cadastrado"}, status_code=400)

    assignment_id = None
    if niche and project_id:
        assignment_id = create_assignment(uid, project_id, niche)

    return JSONResponse({"ok": True, "user_id": uid, "assignment_id": assignment_id})


@app.post("/api/admin/analyze-channel")
@limiter.limit("3/minute")
async def api_admin_analyze_channel(request: Request, user=Depends(require_admin)):
    """Full channel analysis pipeline: SOP → Niches → Titles → SEO → Mind Map."""
    body = await request.json()
    url = validate_url(body.get("url", ""))
    niche_name = sanitize_niche_name(body.get("niche_name", ""))
    notebook_id = body.get("notebook_id", "").strip()

    if not url:
        return JSONResponse({"error": "URL invalida"}, status_code=400)
    if not niche_name or len(niche_name) < 2:
        return JSONResponse({"error": "Nome do nicho invalido (min 2 caracteres)"}, status_code=400)

    logger.info(f"[ANALYZE] {user.get('email')}: url={url[:80]}, niche={niche_name}")

    try:
        from database import create_project, save_niche, save_idea, save_file, log_activity, update_project
        from protocols.ai_client import chat

        # Step 1: Create project
        project_id = create_project(name=niche_name, channel_original=url, niche_chosen=niche_name,
                                     meta={"channel_url": url, "niche": niche_name, "created_by": user["id"]})

        # Step 1b: Google Drive folder
        drive_folder_id = ""
        try:
            from protocols.google_export import create_folder
            drive_folder_id = create_folder(f"YT Cloner - {niche_name}")
            update_project(project_id, drive_folder_id=drive_folder_id,
                          drive_folder_url=f"https://drive.google.com/drive/folders/{drive_folder_id}")
        except Exception as e:
            logger.debug(f"Drive folder: {e}")

        # Step 2: Generate SOP (NotebookLM → Transcripts → AI fallback)
        sop_content = ""
        sop_source = "AI"

        if notebook_id:
            sop_content = analyze_via_notebooklm(notebook_id, niche_name)
            if sop_content and len(sop_content) > 200:
                sop_source = "NotebookLM"

        if not sop_content:
            sop_content = analyze_via_transcripts(url, niche_name)
            if sop_content and len(sop_content) > 200:
                sop_source = "Transcricoes"

        if not sop_content:
            sop_prompt = f"""Analise o conceito deste canal do YouTube e crie um SOP completo.
URL: {url}
Nicho: {niche_name}

Crie um SOP detalhado com: CONCEITO, ESTRUTURA DE VIDEO, HOOKS, STORYTELLING, VISUAL, CTA, SEO, PILARES DE CONTEUDO."""
            sop_content = chat(sop_prompt, system="Voce e um estrategista de canais faceless do YouTube.", max_tokens=MAX_TOKENS_MEDIUM)

        save_file(project_id, "analise", f"SOP - {niche_name}", f"sop_{project_id}.md", sop_content)
        log_activity(project_id, "sop_generated", f"SOP via {sop_source}")

        # Step 3: Generate 5 niches
        niche_prompt = f"""Baseado neste canal "{niche_name}" ({url}), gere 5 sub-nichos derivados.
SOP: {sop_content[:3000]}
Retorne JSON: [{{"name":"...","description":"...","rpm_range":"$X-Y","competition":"Baixa/Media/Alta","color":"#hex","pillars":["..."]}}]
Retorne APENAS o JSON."""

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

        # Step 4: Generate 30 titles
        titles_prompt = f"""Gere 30 ideias de videos para o canal "{niche_name}".
SOP: {sop_content[:3000]}
Retorne JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"...","priority":"ALTA"}}]
Misture: ~10 ALTA, ~12 MEDIA, ~8 BAIXA. Titulos VIRAIS. Retorne APENAS o JSON."""

        titles_response = chat(titles_prompt, max_tokens=6000, temperature=0.8)
        titles_json_match = re.search(r'\[.*\]', titles_response, re.DOTALL)
        titles_generated = 0

        if not titles_json_match:
            retry_prompt = f'Gere 10 ideias de videos para "{niche_name}". Retorne APENAS JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"...","priority":"ALTA"}}]'
            titles_response = chat(retry_prompt, max_tokens=MAX_TOKENS_MEDIUM, temperature=0.7)
            titles_json_match = re.search(r'\[.*\]', titles_response, re.DOTALL)

        if titles_json_match:
            try:
                ideas_list = json.loads(titles_json_match.group())
                for i, idea in enumerate(ideas_list[:30]):
                    save_idea(project_id, i + 1, idea.get("title", f"Titulo {i+1}"),
                             idea.get("hook", ""), idea.get("summary", ""),
                             idea.get("pillar", ""), idea.get("priority", "MEDIA"))
                    titles_generated += 1
            except (json.JSONDecodeError, Exception):
                pass

        log_activity(project_id, "titles_generated", f"{titles_generated} titulos")

        # Step 5: Export to Drive
        if drive_folder_id:
            try:
                from protocols.google_export import create_doc, create_sheet
                create_doc(f"SOP - {niche_name}", sop_content, drive_folder_id)
                if titles_json_match:
                    data = [["#", "Titulo", "Hook", "Pilar", "Prioridade"]]
                    for i, idea in enumerate(json.loads(titles_json_match.group())[:30], 1):
                        data.append([str(i), idea.get("title", ""), idea.get("hook", "")[:100],
                                    idea.get("pillar", ""), idea.get("priority", "")])
                    create_sheet(f"Titulos - {niche_name}", data, drive_folder_id)
            except Exception as e:
                logger.debug(f"Drive export: {e}")

        # Step 6: SEO Pack
        seo_generated = 0
        if titles_json_match:
            try:
                top_titles = json.loads(titles_json_match.group())[:10]
                titles_block = "\n".join([f'{i+1}. {t.get("title", "")}' for i, t in enumerate(top_titles)])
                seo_prompt = f"""Gere SEO pack para estes 10 videos do canal "{niche_name}":
{titles_block}
Para CADA video: 3 variacoes de titulo, descricao YouTube (150-200 palavras), 15 tags, 5 hashtags."""
                seo_content = chat(seo_prompt, system="Especialista em YouTube SEO.", max_tokens=MAX_TOKENS_LARGE, temperature=0.7)
                if seo_content and len(seo_content) > 100:
                    save_file(project_id, "seo", "SEO Pack", f"seo_pack_{project_id}.md", seo_content)
                    seo_generated = 10
                    log_activity(project_id, "seo_generated", f"SEO Pack para {seo_generated} videos")
            except Exception as e:
                logger.debug(f"SEO: {e}")

        # ── Step 7: Generate Mind Map HTML ──
        mindmap_generated = False
        try:
            mindmap_html = generate_mindmap_html(
                niche_name, url, sop_content,
                niche_list if niche_json_match else [{"name": niche_name}],
                json.loads(titles_json_match.group())[:15] if titles_json_match else [],
                scripts_count=0,
            )
            mindmap_filename = f"mindmap_{project_id}.html"
            mindmap_path = OUTPUT_DIR / mindmap_filename
            mindmap_path.write_text(mindmap_html, encoding="utf-8")
            save_file(project_id, "visual", f"Mind Map - {niche_name}", mindmap_filename, "")
            log_activity(project_id, "mindmap_generated", "Mind Map gerado")
            mindmap_generated = True
        except Exception as e:
            logger.debug(f"Mindmap: {e}")

        return JSONResponse({
            "ok": True,
            "project_id": project_id,
            "sop_source": sop_source,
            "niches_generated": niches_generated,
            "titles_generated": titles_generated,
            "seo_generated": seo_generated,
            "mindmap_generated": mindmap_generated,
            "drive_folder_id": drive_folder_id,
        })

    except Exception as e:
        logger.error(f"analyze-channel error: {e}")
        return JSONResponse({"error": "Falha na analise do canal"}, status_code=500)


@app.get("/admin/projects", response_class=HTMLResponse)
async def admin_projects(request: Request, user=Depends(require_admin)):
    from database import get_projects as db_projects, get_db

    projects = db_projects()

    # Enrich with counts
    with get_db() as conn:
        for p in projects:
            pid = p["id"]
            p["idea_count"] = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id=?", (pid,)).fetchone()[0]
            p["niche_count"] = conn.execute("SELECT COUNT(*) FROM niches WHERE project_id=?", (pid,)).fetchone()[0]
            p["script_count"] = conn.execute("SELECT COUNT(*) FROM scripts WHERE project_id=?", (pid,)).fetchone()[0]

    return render(request, "admin_projects.html", {"user": user, "projects": projects})


@app.post("/api/admin/delete-project")
async def api_delete_project(request: Request, user=Depends(require_admin)):
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id or not validate_project_id(project_id):
        return JSONResponse({"error": "project_id invalido"}, status_code=400)
    from database import delete_project
    delete_project(project_id)
    return JSONResponse({"ok": True})


@app.post("/api/admin/remove-title")
async def api_remove_title(request: Request, user=Depends(require_admin)):
    body = await request.json()
    idea_id = body.get("idea_id")
    if not idea_id:
        return JSONResponse({"error": "idea_id obrigatorio"}, status_code=400)
    from database import delete_idea
    delete_idea(int(idea_id))
    return JSONResponse({"ok": True})


@app.post("/api/admin/release-titles")
async def api_release_titles(request: Request, user=Depends(require_admin)):
    body = await request.json()
    assignment_id = body.get("assignment_id")
    count = body.get("count", 5)
    if not assignment_id:
        return JSONResponse({"error": "assignment_id obrigatorio"}, status_code=400)
    from database import release_more_titles
    added = release_more_titles(int(assignment_id), int(count))
    return JSONResponse({"ok": True, "added": added})


@app.post("/api/admin/assign-niche")
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
async def api_delete_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)
    from database import delete_user
    delete_user(int(student_id))
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
        set_setting("youtube_channel_id", channel_id)
    return JSONResponse({"ok": True})


@app.get("/api/admin/youtube-stats")
@limiter.limit("5/minute")
async def api_admin_youtube_stats(request: Request, user=Depends(require_admin)):
    """Fetch YouTube channel stats using YouTube Data API."""
    from database import get_setting, _decrypt_api_key

    yt_key = _decrypt_api_key(get_setting("youtube_api_key"))
    channel_id = get_setting("youtube_channel_id")

    if not yt_key or not channel_id:
        return JSONResponse({"error": "Configure YouTube API key e Channel ID primeiro"}, status_code=400)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "statistics,snippet", "id": channel_id, "key": yt_key},
            )
            data = resp.json()

        if "items" not in data or not data["items"]:
            return JSONResponse({"error": "Canal nao encontrado"}, status_code=404)

        ch = data["items"][0]
        stats = ch.get("statistics", {})
        snippet = ch.get("snippet", {})

        return JSONResponse({
            "ok": True,
            "channel": snippet.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
        })
    except Exception as e:
        logger.error(f"youtube-stats error: {e}")
        return JSONResponse({"error": "Falha ao buscar estatisticas"}, status_code=500)


# ══════════════════════════════════════════════════════════
# NOTEBOOKLM AUTH ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/admin/notebooklm", response_class=HTMLResponse)
async def admin_nlm_auth_page(request: Request, user=Depends(require_admin)):
    """NotebookLM credential management page."""
    has_credentials = False
    try:
        has_credentials = (Path.home() / ".notebooklm" / "storage_state.json").exists()
    except Exception:
        pass
    return render(request, "admin_nlm_auth.html", {"user": user, "has_credentials": has_credentials})


@app.post("/api/admin/nlm-save-credentials")
@limiter.limit("10/minute")
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

        # Save to file
        nlm_dir = Path.home() / ".notebooklm"
        nlm_dir.mkdir(parents=True, exist_ok=True)
        (nlm_dir / "storage_state.json").write_text(storage_state, encoding="utf-8")

        # Also save to DB
        from database import set_setting
        b64 = base64.b64encode(storage_state.encode()).decode()
        set_setting("notebooklm_storage_state", b64)

        logger.info(f"NotebookLM credentials saved: {len(storage_state)} chars, {len(parsed.get('cookies', []))} cookies")

        return JSONResponse({"ok": True, "cookies": len(parsed.get("cookies", [])), "origins": len(parsed.get("origins", []))})
    except Exception as e:
        logger.error(f"NLM save error: {e}")
        return JSONResponse({"error": "Falha ao salvar credenciais"}, status_code=500)


# ══════════════════════════════════════════════════════════
# STUDENT ROUTES
# ══════════════════════════════════════════════════════════

@app.get("/student", response_class=HTMLResponse)
async def student_dashboard(request: Request, view_as: int = 0, user=Depends(require_auth)):
    """Student dashboard with kanban board.
    Admin can view as any student via ?view_as=<student_id>
    """
    # ── Impersonation: admin viewing as student ──
    impersonating = False
    target_user = user

    if view_as and user.get("role") == "admin":
        from database import get_user
        student = get_user(view_as)
        if not student:
            raise HTTPException(status_code=404, detail="Aluno nao encontrado")
        target_user = student
        impersonating = True
    elif user.get("role") == "admin" and not view_as:
        return RedirectResponse("/", status_code=302)

    student_id = target_user["id"]

    from database import get_assignments, get_student_ideas, get_project, get_db

    # ── Build kanban data ──
    assignments = get_assignments(student_id)
    all_ideas = []
    project_ids = set()

    for a in assignments:
        ideas = get_student_ideas(a["id"])
        for idea in ideas:
            idea["niche"] = a["niche"]
            idea["assignment_id"] = a["id"]
        all_ideas.extend(ideas)
        if a.get("project_id"):
            project_ids.add(a["project_id"])

    kanban = {"pending": [], "writing": [], "recording": [], "editing": [], "published": []}
    for idea in all_ideas:
        status = idea.get("status", "pending")
        if status in kanban:
            kanban[status].append(idea)

    # ── Stats ──
    stats = {
        "total": len(all_ideas),
        "completed": len(kanban["published"]),
        "in_progress": len(kanban["writing"]) + len(kanban["recording"]) + len(kanban["editing"]),
        "pending": len(kanban["pending"]),
    }

    # ── API key info ──
    api_provider = target_user.get("api_provider", "")
    has_api_key = bool(target_user.get("api_key_encrypted"))

    # ── Student's roteiro files ──
    student_categories = {}
    student_roteiros = []

    for fpath in sorted(OUTPUT_DIR.glob(f"roteiro_student_{student_id}_*.md")):
        student_roteiros.append({
            "id": 0,
            "name": fpath.name,
            "path": fpath.name,
            "size": fpath.stat().st_size,
            "label": fpath.stem.replace(f"roteiro_student_{student_id}_", "Roteiro - ").replace("_", " ").title(),
        })

    # Also check DB for linked scripts
    try:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT s.id, s.title, f.filename, f.id as file_id
                FROM scripts s
                LEFT JOIN files f ON f.project_id = s.project_id AND f.category = 'roteiros'
                    AND LOWER(f.label) LIKE '%' || LOWER(SUBSTR(s.title, 1, 30)) || '%'
                JOIN progress p ON p.idea_id = s.idea_id AND p.student_id = ?
                WHERE s.idea_id IS NOT NULL
            """, (student_id,)).fetchall()
            seen_names = {r["name"] for r in student_roteiros}
            for row in rows:
                fname = row["filename"] or ""
                if fname and fname not in seen_names:
                    fpath = OUTPUT_DIR / fname
                    student_roteiros.append({
                        "id": row["file_id"] or 0,
                        "name": fname,
                        "path": fname,
                        "size": fpath.stat().st_size if fpath.exists() else 0,
                        "label": f"Roteiro - {row['title']}" if row["title"] else fname,
                    })
                    seen_names.add(fname)
    except Exception:
        pass

    if student_roteiros:
        student_categories["roteiros"] = {
            "label": "Meus Roteiros", "icon": "&#128221;", "color": "#eab308",
            "files": student_roteiros,
        }

    # ── Project info ──
    current_project = None
    if project_ids:
        proj = get_project(list(project_ids)[0])
        if proj:
            current_project = {
                "id": proj["id"],
                "name": proj["name"],
                "drive_folder_url": proj.get("drive_folder_url", ""),
                "channel_original": proj.get("channel_original", ""),
            }

    return render(request, "student_dashboard.html", {
        "user": target_user,
        "real_user": user,
        "assignments": assignments,
        "kanban": kanban,
        "stats": stats,
        "api_provider": api_provider,
        "has_api_key": has_api_key,
        "categories": student_categories,
        "current_project": current_project,
        "impersonating": impersonating,
        "readonly": impersonating,
    })


@app.post("/api/student/update-progress")
@limiter.limit("30/minute")
async def api_student_update_progress(request: Request, user=Depends(require_auth)):
    body = await request.json()
    progress_id = body.get("progress_id")
    status = body.get("status", "")
    video_url = body.get("video_url", "")
    notes = body.get("notes", "")

    if not progress_id or not status:
        return JSONResponse({"error": "progress_id e status obrigatorios"}, status_code=400)

    allowed_statuses = {"pending", "writing", "recording", "editing", "published"}
    if status not in allowed_statuses:
        return JSONResponse({"error": f"Status invalido. Use: {', '.join(allowed_statuses)}"}, status_code=400)

    from database import update_progress
    update_progress(int(progress_id), status, video_url, notes)
    return JSONResponse({"ok": True})


@app.post("/api/student/update-api-key")
@limiter.limit("10/minute")
async def api_student_update_api_key(request: Request, user=Depends(require_auth)):
    body = await request.json()
    provider = (body.get("provider") or "").strip()
    api_key = (body.get("api_key") or "").strip()

    allowed_providers = {"laozhang", "openai", "anthropic", "google"}
    if provider and provider not in allowed_providers:
        return JSONResponse({"error": f"Provider invalido"}, status_code=400)

    from database import _encrypt_api_key, update_user
    encrypted = _encrypt_api_key(api_key) if api_key else ""
    update_user(user["id"], api_provider=provider, api_key_encrypted=encrypted)
    return JSONResponse({"ok": True})


@app.post("/api/student/generate-script")
@limiter.limit("5/minute")
async def api_student_generate_script(request: Request, user=Depends(require_auth)):
    body = await request.json()
    progress_id = body.get("progress_id")

    if not progress_id:
        return JSONResponse({"error": "progress_id obrigatorio"}, status_code=400)

    from database import get_db, _decrypt_api_key, mark_progress_script_generated, save_script

    with get_db() as conn:
        progress = conn.execute(
            """SELECT p.*, i.title, i.hook, i.project_id, i.id as idea_real_id
               FROM progress p JOIN ideas i ON p.idea_id = i.id
               WHERE p.id=? AND p.student_id=?""",
            (progress_id, user["id"]),
        ).fetchone()

    if not progress:
        return JSONResponse({"error": "Progresso nao encontrado"}, status_code=404)
    progress = dict(progress)

    api_key = _decrypt_api_key(user.get("api_key_encrypted", ""))
    provider = user.get("api_provider", "")
    if not api_key or not provider:
        return JSONResponse({"error": "Configure sua API key primeiro"}, status_code=400)

    try:
        title = progress["title"]
        hook = progress.get("hook", "")
        project_id = progress["project_id"]

        sop_path = OUTPUT_DIR / "loaded_dice_sop.md"
        sop = sop_path.read_text(encoding="utf-8") if sop_path.exists() else ""

        prompt = f"""Escreva um roteiro completo de video para YouTube:
TITULO: {title}
HOOK: {hook}
SOP: {sop[:3000]}

Inclua: Hook forte (30s), estrutura clara, CTA, duracao 10-12 min, linguagem envolvente. Em portugues."""

        import httpx

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(api_url, json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 4000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                script = data["choices"][0]["message"]["content"]

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4000,
                    "messages": [{"role": "user", "content": prompt}],
                }, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                data = resp.json()
                script = data["content"][0]["text"]

        elif provider == "google":
            api_url = "https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{api_url}?key={api_key}", json={
                    "contents": [{"parts": [{"text": prompt}]}],
                })
                data = resp.json()
                script = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return JSONResponse({"error": f"Provider '{provider}' nao suportado"}, status_code=400)

        # Save script
        save_script(project_id, title, script, progress["idea_real_id"], "10-12 min")
        mark_progress_script_generated(int(progress_id))

        words = len(script.split())
        return JSONResponse({
            "ok": True,
            "progress_id": progress_id,
            "title": title,
            "words": words,
            "duration_estimate": f"~{round(words / 140, 1)} min",
        })
    except Exception as e:
        logger.error(f"student generate-script error: {e}")
        return JSONResponse({"error": "Falha ao gerar roteiro"}, status_code=500)


@app.post("/api/student/delete-file")
async def api_student_delete_file(request: Request, user=Depends(require_auth)):
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db, delete_file as db_delete_file

    # Verify access
    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if not f:
            return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)

        if f["category"] == "analise":
            return JSONResponse({"error": "Arquivos de analise nao podem ser excluidos"}, status_code=400)

        if user.get("role") != "admin":
            assignment = conn.execute(
                "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
                (user["id"], f["project_id"]),
            ).fetchone()
            if not assignment:
                return JSONResponse({"error": "Sem permissao"}, status_code=403)

    deleted = db_delete_file(int(file_id))
    if deleted and deleted.get("filename"):
        fpath = OUTPUT_DIR / deleted["filename"]
        if fpath.exists():
            fpath.unlink()

    return JSONResponse({"ok": True})


# ── Entry point ──────────────────────────────────────────

def run_dashboard(port: int = PORT):
    import uvicorn
    logger.info(f"Dashboard: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=LOG_LEVEL)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_dashboard(port)
