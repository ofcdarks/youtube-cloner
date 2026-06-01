"""
Seed / one-off admin maintenance routes — reseed SOPs, seed the ROBOS
ENCANTADOS and RELATOS FAMILIARES projects, fix overlong titles, apply the
chibi concept override. Extracted from api_routes.py. Admin-only.
"""

import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_admin
from rate_limit import limiter
from routes._seed_data import (
    _ROBOS_SEED_NICHES, _ROBOS_SEED_TITLES,
    _RELATOS_SEED_NICHES, _RELATOS_SEED_TITLES,
)

logger = logging.getLogger("ytcloner.routes.seed")

router = APIRouter(tags=["seed"])


SOP_FILE_MAP = {
    "ROBOS ENCANTADOS": "sop_robos_encantados_floresta.md",
    "RESCUE": "sop_rescue_complete.md",
    "BIBLICO": "sop_biblico_complete.md",
    "POV": "sop_pov_complete.md",
    "ANACRON": "sop_anacron_complete.md",
    "HISTORICOS 3D": "sop_anacron_complete.md",
    "GHIBLI": "sop_ghibli_cozy_life.md",
    "GLIBLI": "sop_ghibli_cozy_life.md",
    "RELATOS FAMILIARES": "SOP_RELATOS_FAMILIARES.md",
}


def _load_sop_file(filename: str) -> str | None:
    """Try multiple paths to load a SOP file (Docker build-time + dev)."""
    import os
    for base in ["/app/seed_output", "/app/output", "output"]:
        path = os.path.join(base, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            continue
    return None


@router.get("/api/admin/fix-long-titles")
async def fix_long_titles(request: Request, dry_run: bool = False, user=Depends(require_admin)):
    """Find and fix all titles exceeding 100 chars across all projects.

    Query params:
    - dry_run=true: only return what would be changed, don't update DB

    Strategy: truncate at word boundary <= 100 chars (no ellipsis).
    For a smarter rewrite, could call AI here but that's expensive for bulk.
    """
    from database import find_long_titles, enforce_title_limit, update_idea_title
    long_ones = find_long_titles()
    results = []
    for row in long_ones:
        old_title = row.get("title", "") or ""
        old_title_b = row.get("title_b", "") or ""
        new_title = enforce_title_limit(old_title) if len(old_title) > 100 else old_title
        new_title_b = enforce_title_limit(old_title_b) if len(old_title_b) > 100 else old_title_b
        entry = {
            "id": row["id"],
            "project_id": row["project_id"],
            "num": row["num"],
            "old_title": old_title,
            "old_length": len(old_title),
            "new_title": new_title,
            "new_length": len(new_title),
        }
        if old_title_b and len(old_title_b) > 100:
            entry["old_title_b"] = old_title_b
            entry["new_title_b"] = new_title_b
        results.append(entry)
        if not dry_run:
            try:
                update_idea_title(row["id"], new_title, new_title_b if old_title_b else None)
            except Exception as e:
                entry["error"] = str(e)
                logger.error(f"Failed to fix title {row['id']}: {e}")
    return JSONResponse({
        "ok": True,
        "total_long": len(long_ones),
        "dry_run": dry_run,
        "fixes": results,
    })


@router.get("/api/reseed-all-sops")
async def reseed_all_sops(request: Request, user=Depends(require_admin)):
    """Update SOPs for all projects from output/ files — idempotent, safe to rerun."""
    from database import get_projects, save_file, get_db
    results = {}
    for project in get_projects():
        name = project.get("name", "").strip()
        if name not in SOP_FILE_MAP:
            results[name or "(unnamed)"] = "skipped (not in map)"
            continue
        filename = SOP_FILE_MAP[name]
        sop = _load_sop_file(filename)
        if not sop:
            results[name] = f"file not found: {filename}"
            continue
        pid = project["id"]
        # Delete any existing SOP files for this project to avoid duplicates
        try:
            with get_db() as conn:
                conn.execute(
                    "DELETE FROM files WHERE project_id=? AND category='analise' AND (label LIKE '%SOP%' OR filename LIKE 'sop_%')",
                    (pid,),
                )
        except Exception as e:
            logger.warning(f"Failed to clean old SOPs for {name}: {e}")
        # Insert fresh SOP
        try:
            save_file(pid, "analise", f"SOP - {name} (Complete 17 Sections)", f"sop_{pid}.md", sop)
            results[name] = f"updated ({len(sop)} chars)"
        except Exception as e:
            results[name] = f"error: {e}"
            logger.error(f"Failed to save SOP for {name}: {e}")
    return JSONResponse({"ok": True, "results": results})


@router.get("/api/seed-robos-encantados")
async def seed_robos_encantados(request: Request, force: int = 0, user=Depends(require_admin)):
    """Seed/reseed the miniature enchanted village project.

    Keeps the legacy endpoint name and project key "ROBOS ENCANTADOS" for
    back-compat but the content is now chibi characters (no robots).
    Pass ?force=1 to wipe and reseed (useful after SOP updates).
    """
    from database import (
        get_projects,
        create_project,
        save_niche,
        save_idea,
        save_file,
        log_activity,
        get_db,
        delete_project,
    )
    existing = [p for p in get_projects() if "ROBOS ENCANTADOS" == p.get("name", "")]
    with get_db() as conn:
        for sql in [
            "ALTER TABLE ideas ADD COLUMN search_competition REAL DEFAULT -1",
            "ALTER TABLE ideas ADD COLUMN title_b TEXT DEFAULT ''",
            "ALTER TABLE ideas ADD COLUMN trending INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass
    if existing:
        pid = existing[0]["id"]
        with get_db() as conn:
            nc = conn.execute("SELECT COUNT(*) FROM niches WHERE project_id=?", (pid,)).fetchone()[0]
            ic = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id=?", (pid,)).fetchone()[0]
        if nc > 0 and ic > 0 and not force:
            return JSONResponse({
                "ok": True,
                "msg": "already seeded — pass ?force=1 to wipe and reseed with new chibi niches/titles",
                "id": pid,
                "niches": nc,
                "ideas": ic,
            })
        delete_project(pid)
    pid = create_project(
        name="ROBOS ENCANTADOS",  # chave legada — mantida pro SOP_FILE_MAP e paineis existentes
        channel_original="https://www.youtube.com/@ForestSpirits25",
        niche_chosen="Enchanted Miniature Chibi Village",
        language="en",
    )
    # Override de conceito: projeto foi repositionado — IA NUNCA deve gerar robos.
    # /api/admin/regenerate-titles le esses campos pra sobrescrever channel_name,
    # pular channel_best_videos e injetar FORBIDDEN_THEMES no prompt.
    try:
        from database import update_project
        import json as _json
        meta = {
            "concept_override_name": "Enchanted Miniature Chibi Village",
            "concept_override_summary": (
                "Canal repositionado: personagens chibi artesanais (clay figurine stop-motion 3D) "
                "vivendo em vila medieval em miniatura + floresta encantada. Cottagecore cozy ASMR. "
                "NAO ha robos, engrenagens, cobre, bronze ou qualquer elemento mecanico."
            ),
            "forbidden_themes": [
                "robots", "robot", "robô", "robôs", "mechanical", "mecânico", "mecanica",
                "gears", "engrenagem", "copper body", "bronze body", "LED eyes",
                "steampunk", "steam puffs", "exhaust vents", "antenna",
                "android", "cyborg", "automaton", "clockwork",
            ],
            # Prefixos proibidos de INICIO de titulo — IA tende a repetir frases
            # marca que monotonizam os titulos
            "forbidden_prefixes": [
                "tiny chibi folk", "tiny chibi", "chibi folk", "tiny folk",
                "little robots", "tiny robots",
            ],
            "skip_channel_fetch": True,  # nao puxa videos antigos (robos) do YouTube
        }
        update_project(pid, meta=_json.dumps(meta))
    except Exception as e:
        logger.warning(f"concept_override meta set skipped: {e}")
    sop = ""
    for sop_path in [
        "/app/seed_output/sop_robos_encantados_floresta.md",
        "/app/output/sop_robos_encantados_floresta.md",
        "output/sop_robos_encantados_floresta.md",
    ]:
        try:
            with open(sop_path, "r", encoding="utf-8") as f:
                sop = f.read()
            logger.info(f"Loaded chibi-village SOP from {sop_path} ({len(sop)} chars)")
            break
        except FileNotFoundError:
            continue
    if not sop:
        sop = "# VILA ENCANTADA EM MINIATURA SOP\nFallback - SOP file not found in seed_output."
    try:
        save_file(pid, "analise", "SOP - VILA ENCANTADA EM MINIATURA (chibi cottagecore)", f"sop_{pid}.md", sop)
    except Exception as e:
        logger.warning(f"SOP save skipped: {e}")
    for name, desc, rpm, comp, color, chosen in _ROBOS_SEED_NICHES:
        try:
            save_niche(pid, name, desc, rpm, comp, color, chosen)
        except Exception as e:
            logger.warning(f"Niche save skipped ({name}): {e}")
    saved_titles = 0
    for i, (title, pillar, pri, vol) in enumerate(_ROBOS_SEED_TITLES):
        try:
            save_idea(pid, i + 1, title, "", "", pillar, pri, search_volume=vol, trending=1)
            saved_titles += 1
        except Exception as e:
            logger.warning(f"Idea save skipped ({i + 1}): {e}")
    log_activity(
        pid,
        "project_seeded",
        f"VILA ENCANTADA (chibi) seeded: {len(_ROBOS_SEED_NICHES)} niches, {saved_titles} titles",
    )
    return JSONResponse({
        "ok": True,
        "project_id": pid,
        "niches": len(_ROBOS_SEED_NICHES),
        "titles": saved_titles,
        "forced": bool(force),
    })


@router.get("/api/seed-relatos-familiares")
async def seed_relatos_familiares(request: Request, force: int = 0, user=Depends(require_admin)):
    """Seed the Relatos Familiares project with SOP, niches and titles."""
    from database import (
        get_projects, create_project, save_niche, save_idea,
        save_file, log_activity, get_db, delete_project,
    )
    existing = [p for p in get_projects() if "RELATOS FAMILIARES" == p.get("name", "")]
    if existing:
        pid = existing[0]["id"]
        with get_db() as conn:
            nc = conn.execute("SELECT COUNT(*) FROM niches WHERE project_id=?", (pid,)).fetchone()[0]
            ic = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id=?", (pid,)).fetchone()[0]
        if nc > 0 and ic > 0 and not force:
            return JSONResponse({
                "ok": True,
                "msg": "already seeded — pass ?force=1 to reseed",
                "id": pid, "niches": nc, "ideas": ic,
            })
        delete_project(pid)

    pid = create_project(
        name="RELATOS FAMILIARES",
        channel_original="",
        niche_chosen="Relatos Familiares Dramáticos",
        language="pt-BR",
    )

    # Load SOP from file
    sop = _load_sop_file("SOP_RELATOS_FAMILIARES.md") or "# SOP RELATOS FAMILIARES\nFallback."
    try:
        save_file(pid, "analise", "SOP - RELATOS FAMILIARES (17 Seções)", f"sop_{pid}.md", sop)
    except Exception as e:
        logger.warning(f"SOP save skipped: {e}")

    for name, desc, rpm, comp, color, chosen in _RELATOS_SEED_NICHES:
        try:
            save_niche(pid, name, desc, rpm, comp, color, chosen)
        except Exception as e:
            logger.warning(f"Niche save skipped ({name}): {e}")

    saved = 0
    for i, (title, pillar, pri, vol) in enumerate(_RELATOS_SEED_TITLES):
        try:
            save_idea(pid, i + 1, title, "", "", pillar, pri, search_volume=vol, trending=1)
            saved += 1
        except Exception as e:
            logger.warning(f"Idea save skipped ({i+1}): {e}")

    log_activity(pid, "project_seeded",
                 f"RELATOS FAMILIARES seeded: {len(_RELATOS_SEED_NICHES)} niches, {saved} titles")

    return JSONResponse({
        "ok": True, "project_id": pid,
        "niches": len(_RELATOS_SEED_NICHES),
        "titles": saved, "forced": bool(force),
    })


@router.get("/api/apply-chibi-override")
async def apply_chibi_override(request: Request, user=Depends(require_admin)):
    """Atualiza meta do projeto ROBOS ENCANTADOS com concept_override + forbidden_prefixes
    SEM apagar nichos/ideias/roteiros. Use quando ja houver conteudo que voce quer
    manter e so precisa injetar as guards pra proximas geracoes."""
    from database import get_projects, get_project, update_project
    import json as _json
    candidates = [p for p in get_projects() if "ROBOS ENCANTADOS" == (p.get("name") or "")]
    if not candidates:
        return JSONResponse({"error": "Projeto ROBOS ENCANTADOS nao encontrado"}, status_code=404)
    pid = candidates[0]["id"]
    project = get_project(pid) or {}
    try:
        existing_meta = _json.loads(project.get("meta") or "{}")
    except Exception:
        existing_meta = {}
    existing_meta.update({
        "concept_override_name": "Enchanted Miniature Chibi Village",
        "concept_override_summary": (
            "Canal repositionado: personagens chibi artesanais (clay figurine stop-motion 3D) "
            "vivendo em vila medieval em miniatura + floresta encantada. Cottagecore cozy ASMR. "
            "NAO ha robos, engrenagens, cobre, bronze ou qualquer elemento mecanico."
        ),
        "forbidden_themes": [
            "robots", "robot", "robô", "robôs", "mechanical", "mecânico", "mecanica",
            "gears", "engrenagem", "copper body", "bronze body", "LED eyes",
            "steampunk", "steam puffs", "exhaust vents", "antenna",
            "android", "cyborg", "automaton", "clockwork",
        ],
        "forbidden_prefixes": [
            "tiny chibi folk", "tiny chibi", "chibi folk", "tiny folk",
            "little robots", "tiny robots",
        ],
        "skip_channel_fetch": True,
    })
    update_project(pid, meta=_json.dumps(existing_meta))
    return JSONResponse({
        "ok": True,
        "project_id": pid,
        "msg": "Concept override aplicado. Agora pode clicar 'Refazer pelos Nichos' que os prefixos proibidos sao filtrados.",
        "meta": existing_meta,
    })


@router.get("/api/admin/refresh-titles")
@limiter.limit("5/minute")
async def refresh_titles(request: Request, channel: str = "", mode: str = "replace",
                         user=Depends(require_admin)):
    """Insert curated replacement titles into each channel's project.

    Query params:
    - channel: exact project name (empty = all channels in the curated set)
    - mode: "replace" (default) deletes unused titles (used=0 AND not started by
      any student) then appends the new ones; "add" only appends.

    Titles a student already started (linked to progress) or marked used are
    NEVER deleted. Source: routes/_new_titles_data.NEW_TITLES.
    """
    from routes._new_titles_data import NEW_TITLES
    from database import get_projects, get_db, save_idea, log_activity

    if mode not in ("replace", "add"):
        return JSONResponse({"error": "mode deve ser 'replace' ou 'add'"}, status_code=400)

    targets = [channel] if channel else list(NEW_TITLES.keys())
    results: dict = {}

    for name in targets:
        titles = NEW_TITLES.get(name)
        if not titles:
            results[name] = "sem titulos curados para este canal"
            continue
        projs = [p for p in get_projects() if (p.get("name") or "") == name]
        if not projs:
            results[name] = "projeto nao encontrado"
            continue
        pid = projs[0]["id"]

        deleted = 0
        with get_db() as conn:
            if mode == "replace":
                cur = conn.execute(
                    "DELETE FROM ideas WHERE project_id=? AND COALESCE(used,0)=0 "
                    "AND id NOT IN (SELECT idea_id FROM progress WHERE idea_id IS NOT NULL)",
                    (pid,),
                )
                deleted = cur.rowcount or 0
            row = conn.execute(
                "SELECT COALESCE(MAX(num), 0) FROM ideas WHERE project_id=?", (pid,)
            ).fetchone()
            next_num = (row[0] or 0) + 1

        added = 0
        for entry in titles:
            title, pillar, priority = entry[0], entry[1], entry[2]
            volume = entry[3] if len(entry) > 3 else 0
            save_idea(pid, next_num, title, pillar=pillar, priority=priority,
                      search_volume=volume)
            next_num += 1
            added += 1

        log_activity(pid, "titles_refreshed",
                     f"{added} novos titulos curados (mode={mode}, removidos={deleted})")
        results[name] = {"added": added, "deleted_unused": deleted}

    return JSONResponse({"ok": True, "mode": mode, "results": results})
