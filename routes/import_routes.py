"""
Import routes — upload project data via API (for deploying local pipeline results to server).
"""

import json
import logging
import re

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_admin
from config import OUTPUT_DIR

logger = logging.getLogger("ytcloner.routes.import")

router = APIRouter(prefix="/api/admin/import", tags=["import"])


@router.post("/full-project")
async def import_full_project(request: Request, user=Depends(require_admin)):
    """Import a complete project with files, niches, and ideas.

    Body: {
        name, channel_original, niche_chosen, language,
        files: [{category, label, filename, content}],
        niches: [{name, description, rpm_range, competition, color, chosen, pillars}],
        ideas: [{num, title, hook, summary, pillar, priority}]
    }
    """
    body = await request.json()

    name = body.get("name", "Imported Project")
    channel = body.get("channel_original", "")
    niche = body.get("niche_chosen", "")
    language = body.get("language", "pt-BR")

    from database import create_project, save_file, save_niche, save_idea, log_activity

    pid = create_project(name, channel, niche, language=language)

    files_count = 0
    for f in body.get("files", []):
        category = f.get("category", "analise")
        label = f.get("label", "")
        filename = f.get("filename", "")
        content = f.get("content", "")

        # Rename mindmap files to use the new server project ID
        if category == "visual" and filename and re.match(r"mindmap_.*\.html$", filename):
            filename = f"mindmap_{pid}.html"
            # Write mindmap to disk so it can be served directly
            try:
                mindmap_path = OUTPUT_DIR / filename
                mindmap_path.write_text(content, encoding="utf-8")
                logger.info(f"Mindmap written to disk: {mindmap_path}")
            except Exception as e:
                logger.warning(f"Failed to write mindmap to disk: {e}")

        save_file(pid, category, label, filename, content)
        files_count += 1

    niches_count = 0
    for n in body.get("niches", []):
        save_niche(pid, n.get("name", ""), n.get("description", ""), n.get("rpm_range", ""),
                   n.get("competition", ""), n.get("color", "#888"), n.get("chosen", False),
                   n.get("pillars", []))
        niches_count += 1

    ideas_count = 0
    for i in body.get("ideas", []):
        save_idea(pid, i.get("num", 0), i.get("title", ""), i.get("hook", ""),
                  i.get("summary", ""), i.get("pillar", ""), i.get("priority", "MEDIA"))
        ideas_count += 1

    log_activity(pid, "imported", f"Projeto importado: {files_count} arquivos, {niches_count} nichos, {ideas_count} titulos")

    return JSONResponse({
        "ok": True,
        "project_id": pid,
        "files": files_count,
        "niches": niches_count,
        "ideas": ideas_count,
    })
