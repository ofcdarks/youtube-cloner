"""
Resources Routes — File uploads/downloads for students + Agent generation.
Extracted from dashboard.py for modularity.
"""

import logging
import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_auth, require_admin
from config import OUTPUT_DIR
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.resources")

router = APIRouter(tags=["resources"])


@router.post("/api/admin/upload-resource")
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


@router.post("/api/admin/delete-resource")
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


@router.get("/api/resource/download/{resource_id}")
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


@router.post("/api/admin/generate-agent")
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
        BUNDLED = _Path(__file__).parent.parent / "atomacao_agent"
        EXTERNAL = _Path(__file__).parent.parent.parent / "ATOMACAO CANAL FULL" / "agent"

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
