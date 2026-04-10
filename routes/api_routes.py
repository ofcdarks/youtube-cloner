"""
API routes — ideas, scoring, script generation.
"""

import json
import re
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_auth
from config import OUTPUT_DIR, MAX_TOKENS_LARGE, MAX_TOKENS_MEDIUM, MAX_IDEAS_PER_REQUEST
from services import sanitize_niche_name
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.api")

router = APIRouter(tags=["api"])


@router.get("/api/deploy-check-9ab")
async def deploy_check(request: Request):
    return JSONResponse({"deployed": "9ab9872", "ts": "2026-04-06"})


@router.get("/api/admin/fix-long-titles")
async def fix_long_titles(request: Request, dry_run: bool = False):
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


# ── Idea Bender (dobra de nicho/ideia) ──────────────────────────────
@router.post("/api/admin/bend-idea")
@limiter.limit("10/minute")
async def api_bend_idea(request: Request, user=Depends(require_auth)):
    """
    Bend a validated idea into N variations.

    Modes:
    - internal: {idea_id: 123}  — bends an idea from the DB using its project SOP
    - external: {youtube_url: "..."}  — fetches metadata from a YouTube URL
    - manual:   {title: "...", sop: "...", niche: "...", language: "en"}
    """
    from protocols.idea_bender import bend_idea, fetch_youtube_metadata
    from database import (
        get_ideas,
        get_projects,
        get_files,
        save_bent_idea,
    )

    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin only"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    mode = body.get("mode", "internal")
    num_variations = max(3, min(int(body.get("num_variations", 5)), 10))

    title = ""
    sop = ""
    niche = ""
    language = "en"
    source_project_id = ""
    source_idea_id = 0
    source_url = ""
    source_views = 0
    extra_context = ""

    if mode == "internal":
        idea_id = int(body.get("idea_id", 0))
        if not idea_id:
            return JSONResponse({"error": "idea_id required for internal mode"}, status_code=400)
        # Find the idea across all projects
        found = None
        for p in get_projects():
            for i in get_ideas(p["id"]):
                if i["id"] == idea_id:
                    found = (p, i)
                    break
            if found:
                break
        if not found:
            return JSONResponse({"error": f"Idea {idea_id} not found"}, status_code=404)
        project, idea = found
        title = idea.get("title", "")
        niche = idea.get("pillar") or project.get("niche_chosen", "")
        language = project.get("language", "en")
        source_project_id = project["id"]
        source_idea_id = idea_id
        # Load SOP from project files
        sop_files = [f for f in get_files(project["id"], "analise") if "SOP" in (f.get("label") or "")]
        if sop_files:
            sop = sop_files[0].get("content", "")
        extra_context = f"views: {idea.get('search_volume', 0)}/month, score: {idea.get('score', 0)}"

    elif mode == "external":
        url = (body.get("youtube_url") or "").strip()
        if not url:
            return JSONResponse({"error": "youtube_url required for external mode"}, status_code=400)
        meta = fetch_youtube_metadata(url)
        if "error" in meta:
            return JSONResponse({"error": meta["error"]}, status_code=400)

        # v2: compute virality signals + handle channel/playlist candidates
        from protocols.idea_bender import extract_success_signals
        signals = extract_success_signals(meta)

        title = meta["title"]
        language = body.get("language", "en")
        niche = body.get("niche", meta.get("channel", ""))
        source_url = meta.get("webpage_url", url)
        source_views = meta.get("views", 0)
        # Use user-provided SOP if any, otherwise use the video description
        sop = body.get("sop", "") or meta.get("description", "")

        url_type = meta.get("url_type", "video")
        candidates_info = ""
        if url_type == "channel" and meta.get("candidates"):
            candidates_info = (
                f"\n  source_type: CHANNEL ({meta.get('candidates_count', 0)} videos scanned, "
                f"top video picked by views)"
            )
        elif url_type == "playlist" and meta.get("candidates"):
            candidates_info = f"\n  source_type: PLAYLIST ({len(meta['candidates'])} videos)"

        extra_context = (
            f"channel: {meta.get('channel', '')}, views: {signals['views']:,}, "
            f"likes: {signals['likes']:,}, comments: {signals['comments']:,}, "
            f"duration: {signals['duration_label']}, "
            f"engagement: {signals['engagement_rate_pct']}%, "
            f"views/day: {signals['views_per_day']:,}, "
            f"days_since_upload: {signals['days_since_upload']}, "
            f"virality_tier: {signals['virality_tier']}"
            f"{candidates_info}"
        )
        if meta.get("tags"):
            extra_context += f", tags: {', '.join(meta['tags'][:10])}"

    elif mode == "manual":
        title = (body.get("title") or "").strip()
        sop = body.get("sop", "")
        niche = body.get("niche", "")
        language = body.get("language", "en")
        if not title:
            return JSONResponse({"error": "title required for manual mode"}, status_code=400)

    else:
        return JSONResponse({"error": f"Unknown mode: {mode}"}, status_code=400)

    # Fetch YouTube API key for market research pre-phase
    youtube_api_key = ""
    try:
        from database import get_db
        with get_db() as conn:
            yt_row = conn.execute(
                "SELECT value FROM admin_settings WHERE key='youtube_api_key'"
            ).fetchone()
            if yt_row:
                youtube_api_key = yt_row["value"]
    except Exception as e:
        logger.warning(f"[BEND] Could not fetch YouTube API key: {e}")

    # Run the bender v2 (includes market research phase)
    result = bend_idea(
        title=title,
        sop=sop,
        niche=niche,
        language=language,
        num_variations=num_variations,
        extra_context=extra_context,
        youtube_api_key=youtube_api_key,
    )

    if "error" in result:
        return JSONResponse({"error": result["error"], "raw": result.get("raw", "")}, status_code=500)

    # Persist to history
    try:
        bent_id = save_bent_idea(
            source_mode=mode,
            source_title=title,
            language=language,
            dna=result.get("dna", {}),
            variations=result.get("variations", []),
            source_project_id=source_project_id,
            source_idea_id=source_idea_id,
            source_url=source_url,
            source_views=source_views,
            created_by=user.get("id", 0),
        )
        result["bent_id"] = bent_id
    except Exception as e:
        logger.warning(f"Failed to persist bent idea: {e}")

    result["ok"] = True
    result["source"] = {
        "mode": mode,
        "title": title,
        "niche": niche,
        "language": language,
        "views": source_views,
        "url": source_url,
    }
    return JSONResponse(result)


@router.get("/api/admin/bent-ideas-history")
async def api_bent_ideas_history(request: Request, user=Depends(require_auth), limit: int = 30, project: str = ""):
    """List recent bent ideas (history)."""
    from database import get_bent_ideas
    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin only"}, status_code=403)
    items = get_bent_ideas(limit=limit, project_id=project)
    return JSONResponse({"ok": True, "items": items, "count": len(items)})


# Mapping: project name (exact match in DB) -> SOP file basename in output/
SOP_FILE_MAP = {
    "ROBOS ENCANTADOS": "sop_robos_encantados_floresta.md",
    "RESCUE": "sop_rescue_complete.md",
    "BIBLICO": "sop_biblico_complete.md",
    "POV": "sop_pov_complete.md",
    "ANACRON": "sop_anacron_complete.md",
    "HISTORICOS 3D": "sop_anacron_complete.md",
    "GHIBLI": "sop_ghibli_cozy_life.md",
    "GLIBLI": "sop_ghibli_cozy_life.md",
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


@router.get("/api/reseed-all-sops")
async def reseed_all_sops(request: Request):
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
async def seed_robos_encantados(request: Request):
    """One-time seed: ROBOS ENCANTADOS DA FLORESTA project."""
    from database import get_projects, create_project, save_niche, save_idea, save_file, log_activity, get_db
    from database import delete_project
    existing = [p for p in get_projects() if "ROBOS ENCANTADOS" == p.get("name", "")]
    with get_db() as conn:
        for sql in ["ALTER TABLE ideas ADD COLUMN search_competition REAL DEFAULT -1",
                     "ALTER TABLE ideas ADD COLUMN title_b TEXT DEFAULT ''",
                     "ALTER TABLE ideas ADD COLUMN trending INTEGER DEFAULT 0"]:
            try: conn.execute(sql)
            except: pass
    if existing:
        pid = existing[0]["id"]
        with get_db() as conn:
            nc = conn.execute("SELECT COUNT(*) FROM niches WHERE project_id=?", (pid,)).fetchone()[0]
            ic = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id=?", (pid,)).fetchone()[0]
        if nc > 0 and ic > 0:
            return JSONResponse({"ok": True, "msg": "already seeded", "id": pid, "niches": nc, "ideas": ic})
        delete_project(pid)
    pid = create_project(name="ROBOS ENCANTADOS", channel_original="https://www.youtube.com/@ForestSpirits25", niche_chosen="Enchanted Miniature Robot Village", language="en")
    sop = ""
    for sop_path in [
        "/app/seed_output/sop_robos_encantados_floresta.md",
        "/app/output/sop_robos_encantados_floresta.md",
        "output/sop_robos_encantados_floresta.md",
    ]:
        try:
            with open(sop_path, "r", encoding="utf-8") as f:
                sop = f.read()
            logger.info(f"Loaded ROBOS SOP from {sop_path} ({len(sop)} chars)")
            break
        except FileNotFoundError:
            continue
    if not sop:
        sop = "# ROBOS ENCANTADOS SOP\nFallback - SOP file not found in seed_output."
    try:
        save_file(pid, "analise", "SOP - ROBOS ENCANTADOS (NotebookLM + Forest Spirits)", f"sop_{pid}.md", sop)
    except Exception as e:
        logger.warning(f"SOP save skipped: {e}")
    niches = [
        ("Miniature Robot Cooking", "Tiny robots making jam, baking bread in acorn ovens, brewing herbal tea, making honey with mechanical bees", "$3-6", "Baja", "#B87333", True),
        ("Robot Village Crafts", "Weaving on miniature looms, painting with petal pigments, pottery from river clay, sewing leaf clothes", "$3-5", "Baja", "#4A7C59", True),
        ("Forest Harvest & Foraging", "Collecting morning dew, picking wild berries, gathering mushrooms, fishing in tiny streams", "$3-5", "Baja", "#DAA520", False),
        ("Tiny Robot Engineering", "Building bridges, constructing new mushroom houses, installing waterwheels, crafting lanterns", "$3-6", "Baja", "#CD7F32", False),
        ("Enchanted Forest Exploration", "Discovering secret lakes, crystal caves, meeting gentle giant animals (cats, butterflies, ladybugs)", "$4-7", "Baja", "#CC3333", False),
    ]
    for name, desc, rpm, comp, color, chosen in niches:
        try:
            save_niche(pid, name, desc, rpm, comp, color, chosen)
        except Exception as e:
            logger.warning(f"Niche save skipped ({name}): {e}")
    titles = [
        ("Tiny Robots Making Wild Berry Jam in Acorn Pots | Relaxing Forest Ambience & Celtic Music", "Miniature Robot Cooking", "ALTA", 40500),
        ("A Cozy Day in the Tiny Robot Workshop | Calming Celtic Harp & Nature Sounds", "Tiny Robot Engineering", "ALTA", 33100),
        ("Tiny Robots Baking Acorn Bread by the Fireplace | Peaceful Celtic Music & ASMR", "Miniature Robot Cooking", "ALTA", 49500),
        ("Little Robots Harvesting Morning Dew Drops | Enchanted Forest Ambience & Gentle Music", "Forest Harvest & Foraging", "ALTA", 27100),
        ("Tiny Robot Village Market Day | Relaxing Celtic Music & Cozy Fantasy Ambience", "Robot Village Crafts", "ALTA", 40500),
        ("Tiny Robots Find a Secret Crystal Cave | Calming Celtic Music & Forest Ambience", "Enchanted Forest Exploration", "ALTA", 33100),
        ("Tiny Robots Meet a Gentle Giant Butterfly | Relaxing Harp Music & Nature Sounds", "Enchanted Forest Exploration", "ALTA", 74000),
        ("Tiny Robots Build a Bridge Over the Stream | Cozy Celtic Music & Rain Ambience", "Tiny Robot Engineering", "ALTA", 22200),
        ("Tiny Robots Open a Flower Paint Studio | Enchanted Village Music & Forest Sounds", "Robot Village Crafts", "MEDIA", 18100),
        ("Tiny Robots Discover a Hidden Waterfall | Peaceful Celtic Music & Water Sounds", "Enchanted Forest Exploration", "ALTA", 27100),
        ("Tiny Robots Brewing Herbal Tea in Nutshell Cups | ASMR Forest Ambience & Celtic Harp", "Miniature Robot Cooking", "ALTA", 33100),
        ("Tiny Robots Weaving on a Miniature Loom | Calming Celtic Music & Rain Sounds", "Robot Village Crafts", "MEDIA", 14800),
        ("A Rainy Day in the Enchanted Robot Village | Relaxing Rain & Celtic Music", "Robot Village Crafts", "ALTA", 49500),
        ("Tiny Robots Picking Wild Strawberries | Peaceful Forest Ambience & Gentle Music", "Forest Harvest & Foraging", "ALTA", 40500),
        ("Tiny Robots Making Honey with Mechanical Bees | Relaxing Celtic Harp & ASMR", "Miniature Robot Cooking", "MEDIA", 22200),
        ("Tiny Robots Building a New Mushroom House | Cozy Celtic Music & Forest Ambience", "Tiny Robot Engineering", "ALTA", 33100),
        ("Tiny Robots Painting Magic Flowers | Enchanted Village Ambience & Celtic Music", "Robot Village Crafts", "MEDIA", 18100),
        ("Tiny Robots Fishing in a Crystal Stream | Relaxing Water Sounds & Celtic Harp", "Forest Harvest & Foraging", "MEDIA", 14800),
        ("Tiny Robots Meet a Gentle Giant Cat | Calming Celtic Music & Cottagecore Ambience", "Enchanted Forest Exploration", "ALTA", 74000),
        ("Tiny Robots Installing Firefly Lanterns | Peaceful Evening Ambience & Celtic Music", "Tiny Robot Engineering", "ALTA", 27100),
        ("Tiny Robots Making Pottery from River Clay | ASMR Forest Sounds & Gentle Music", "Robot Village Crafts", "MEDIA", 18100),
        ("First Snow in the Tiny Robot Village | Relaxing Celtic Music & Winter Ambience", "Robot Village Crafts", "ALTA", 49500),
        ("Tiny Robots Cooking Mushroom Soup by the Fire | Cozy ASMR & Celtic Harp Music", "Miniature Robot Cooking", "ALTA", 33100),
        ("Tiny Robots Explore Ancient Moss-Covered Ruins | Enchanted Forest Ambience & Music", "Enchanted Forest Exploration", "MEDIA", 22200),
        ("Tiny Robots Gathering Mushrooms at Dawn | Peaceful Celtic Music & Nature Sounds", "Forest Harvest & Foraging", "MEDIA", 14800),
        ("Tiny Robots Sewing Leaf Clothes for Winter | Calming Celtic Music & Rain Ambience", "Robot Village Crafts", "MEDIA", 12100),
        ("Tiny Robots Building a Waterwheel | Relaxing Water Sounds & Celtic Harp", "Tiny Robot Engineering", "MEDIA", 18100),
        ("Spring Festival in the Tiny Robot Village | Enchanted Music & Flower Ambience", "Robot Village Crafts", "ALTA", 40500),
        ("Tiny Robots Making Candles from Beeswax | ASMR Forest Sounds & Celtic Music", "Miniature Robot Cooking", "MEDIA", 14800),
        ("Tiny Robots Discover a Glowing Mushroom Garden | Magical Celtic Music & Ambience", "Enchanted Forest Exploration", "ALTA", 33100),
    ]
    saved_titles = 0
    for i, (title, pillar, pri, vol) in enumerate(titles):
        try:
            save_idea(pid, i+1, title, "", "", pillar, pri, search_volume=vol, trending=1)
            saved_titles += 1
        except Exception as e:
            logger.warning(f"Idea save skipped ({i+1}): {e}")
    log_activity(pid, "project_seeded", f"ROBOS ENCANTADOS seeded: 5 niches, {saved_titles} titles")
    return JSONResponse({"ok": True, "project_id": pid, "niches": 5, "titles": saved_titles})




@router.get("/api/ideas")
async def api_ideas(request: Request, project: str = "", user=Depends(require_auth)):
    from database import get_ideas, get_projects as db_projects
    if project:
        ideas = get_ideas(project)
    else:
        projs = db_projects()
        ideas = get_ideas(projs[0]["id"]) if projs else []
    return JSONResponse(ideas)


@router.get("/api/idea-details")
async def api_idea_details(request: Request, id: str = "", user=Depends(require_auth)):
    if not id:
        return JSONResponse({"error": "id obrigatorio"}, status_code=400)
    from database import get_idea, get_seo
    idea = get_idea(int(id))
    if not idea:
        return JSONResponse({"error": "Ideia nao encontrada"}, status_code=404)
    seo = get_seo(int(id))
    return JSONResponse({"idea": idea, "seo": seo})


@router.post("/api/toggle-used")
@limiter.limit("30/minute")
async def api_toggle_used(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("id")
    if not idea_id:
        return JSONResponse({"error": "id obrigatorio"}, status_code=400)
    from database import toggle_idea_used
    new_val = toggle_idea_used(int(idea_id))
    return JSONResponse({"ok": True, "used": new_val})


@router.post("/api/admin/toggle-niche-chosen")
@limiter.limit("30/minute")
async def api_toggle_niche_chosen(request: Request, user=Depends(require_auth)):
    """Toggle chosen status of a niche and persist to DB."""
    body = await request.json()
    niche_name = body.get("name", "")
    project_id = body.get("project_id", "")
    chosen = body.get("chosen", False)

    if not niche_name or not project_id:
        return JSONResponse({"error": "name e project_id obrigatorios"}, status_code=400)

    from database import get_niches, update_niche_chosen
    niches = get_niches(project_id)
    target = next((n for n in niches if n["name"] == niche_name), None)
    if not target:
        return JSONResponse({"error": "Nicho nao encontrado"}, status_code=404)

    # Check max 2 chosen
    if chosen:
        chosen_count = sum(1 for n in niches if n.get("chosen") and n["name"] != niche_name)
        if chosen_count >= 2:
            return JSONResponse({"error": "Maximo 2 nichos escolhidos"}, status_code=400)

    update_niche_chosen(target["id"], chosen)
    return JSONResponse({"ok": True, "name": niche_name, "chosen": chosen})


@router.get("/api/score-all")
@limiter.limit("2/minute")
async def api_score_all(
    request: Request,
    countries: str = "global,BR,US",
    force: str = "false",
    project: str = "",
    user=Depends(require_auth),
):
    import asyncio
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

    # Split: unscored first, then scored (for force rescore)
    unscored = [i for i in ideas if not i.get("score") or i.get("score", 0) == 0]
    scored = [i for i in ideas if i.get("score", 0) > 0]

    if force_rescore:
        # Force: score ALL but in batches — prioritize unscored first
        to_score = unscored + scored
    else:
        # Normal: only score unscored ones
        to_score = unscored

    skipped = [{"id": i["id"], "title": i["title"], "score": i["score"], "rating": i.get("rating", "N/A"), "skipped": True}
               for i in ideas if i not in to_score]

    # Cap at 15 to stay under timeout
    if len(to_score) > 15:
        logger.info(f"Score-all: batch {len(to_score)} → 15 (unscored={len(unscored)}, scored={len(scored)})")
        to_score = to_score[:15]

    def _score_batch():
        """Run scoring in thread so health checks keep responding."""
        from protocols.title_scorer import score_title
        results = []
        for idea in to_score:
            try:
                score_result = score_title(idea["title"], country_list, search_volume=idea.get("search_volume", 0))
                update_idea_score(idea["id"], score_result["final_score"], score_result["rating"], score_result)
                results.append({
                    "id": idea["id"],
                    "title": idea["title"],
                    "score": score_result["final_score"],
                    "rating": score_result["rating"],
                })
                logger.info(f"Scored: '{idea['title'][:30]}' → {score_result['final_score']}")
            except Exception as e:
                logger.warning(f"Score failed for '{idea['title'][:30]}': {e}")
                # Give a base score instead of 0 so it's not useless
                update_idea_score(idea["id"], 50, "N/A", {"error": str(e)[:100]})
                results.append({"id": idea["id"], "title": idea["title"], "score": 50, "rating": "N/A", "error": "Falha ao pontuar"})
        return results

    try:
        results = await asyncio.to_thread(_score_batch)
        all_results = skipped + results
        remaining = len(ideas) - len(skipped) - len(to_score)
        msg = ""
        if remaining > 0:
            msg = f" ({remaining} titulos restantes — clique novamente para pontuar mais)"
        return JSONResponse({"ok": True, "scored": len(results), "skipped": len(skipped), "remaining": remaining, "results": all_results, "message": msg})
    except Exception as e:
        logger.error(f"score-all error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao pontuar titulos."}, status_code=500)


@router.post("/api/score-title")
@limiter.limit("10/minute")
async def api_score_title(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("id")
    force = body.get("force", False)
    if not idea_id:
        return JSONResponse({"error": "id obrigatorio"}, status_code=400)

    from database import get_idea, update_idea_score
    from protocols.title_scorer import score_title
    import json as _json

    idea = get_idea(int(idea_id))
    if not idea:
        return JSONResponse({"error": "Ideia nao encontrada"}, status_code=404)

    # Return cached score if already scored and not forcing rescore
    if not force and idea.get("score", 0) > 0 and idea.get("score_details"):
        try:
            cached = _json.loads(idea["score_details"]) if isinstance(idea["score_details"], str) else idea["score_details"]
            if cached and cached.get("final_score"):
                return JSONResponse({"ok": True, "score": idea["score"], "rating": idea.get("rating", ""), "details": cached, "cached": True})
        except (ValueError, TypeError):
            pass

    import asyncio
    result = await asyncio.to_thread(score_title, idea["title"])
    await asyncio.to_thread(update_idea_score, int(idea_id), result["final_score"], result["rating"], result)
    return JSONResponse({"ok": True, "score": result["final_score"], "rating": result["rating"], "details": result})


@router.post("/api/generate-ideas")
@limiter.limit("10/minute")
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
            proj = projs[0]

        # Get project language
        if not proj:
            proj = get_project(pid)
        lang = (proj or {}).get("language", "pt-BR")
        from config import LANG_LABELS
        lang_instruction = f"\n\nIMPORTANTE: Todo o conteudo deve ser gerado em {LANG_LABELS.get(lang, lang)}."

        existing = get_ideas(pid)
        existing_titles = [i["title"] for i in existing]
        next_num = max([i.get("num", 0) for i in existing], default=0) + 1

        # Load SOP
        from services import get_project_sop
        sop = get_project_sop(pid)

        # Pre-research demand data (YouTube trending + Google Trends)
        demand_summary = ""
        demand_data = {}
        # Get chosen niches FIRST so we can use them in demand research
        from database import get_niches
        chosen_niches = [n for n in get_niches(pid) if n.get("chosen")]

        try:
            from protocols.trend_research import research_niche_demand
            from database import get_db as _gdb
            yt_key = ""
            with _gdb() as conn:
                yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
                if yt_row:
                    yt_key = yt_row["value"]
            from database import get_project
            proj_data = get_project(pid)
            # Use chosen niche names for demand research when available
            demand_niche = " + ".join([n["name"] for n in chosen_niches]) if chosen_niches else niche
            demand_data = research_niche_demand(demand_niche, proj_data.get("language", "pt-BR") if proj_data else "pt-BR", yt_key)
            demand_summary = demand_data.get("summary", "")
        except Exception:
            pass
        if chosen_niches:
            niches_text = "\n".join([f"- {n['name']}: {n.get('description', '')}" for n in chosen_niches])
            niches_instruction = f"\n\nSUB-NICHOS ESCOLHIDOS (gere titulos APENAS sobre estes):\n{niches_text}\nO campo 'pillar' DEVE ser o nome do sub-nicho.\n"
        else:
            niches_instruction = ""

        # KEYWORD RESEARCH: SOP + niches + titles + trending
        keywords_block = ""
        niche_keywords = []
        try:
            from protocols.keywords_everywhere import research_niche_keywords
            lang_to_country = {"pt": "br", "en": "us", "es": "es", "fr": "fr", "de": "de"}
            country = lang_to_country.get(lang[:2], "us")
            niche_names = [n["name"] for n in chosen_niches] if chosen_niches else [niche]

            # Collect trending keywords from YouTube + Google Trends
            trending_seeds = []
            trending_seeds.extend(demand_data.get("trending_keywords", []))
            for rs in demand_data.get("rising_searches", []):
                trending_seeds.append(rs.get("query", ""))

            # Check cache first (valid 7 days)
            from database import get_keyword_cache, save_keyword_cache
            cached = get_keyword_cache(pid)
            if cached:
                niche_keywords = cached
                logger.info(f"Using cached keywords ({len(cached)} keywords)")
            else:
                niche_keywords = research_niche_keywords(
                    niche_names, language=lang, country=country,
                    sop_text=sop or "", existing_titles=existing_titles,
                    trending_keywords=trending_seeds,
                )
                if niche_keywords:
                    save_keyword_cache(pid, niche_keywords)
            if niche_keywords:
                kw_lines = [f'  - "{kw["keyword"]}": {kw["vol"]:,} buscas/mes' for kw in niche_keywords[:20]]
                keywords_block = (
                    "\nKEYWORDS COM VOLUME REAL (use obrigatoriamente nos titulos):\n"
                    + "\n".join(kw_lines)
                    + "\nREGRA: Cada titulo DEVE conter pelo menos 1 keyword desta lista.\n"
                )
        except Exception as e:
            logger.warning(f"Niche keyword research failed (non-blocking): {e}")

        # When chosen niches exist, make them the PRIMARY focus of the prompt
        if chosen_niches:
            chosen_names = ", ".join([n["name"] for n in chosen_niches])
            prompt_header = f"""Gere {count} novas ideias de videos para o canal "{niche}".
FOCO OBRIGATORIO: Todos os titulos devem ser sobre os sub-nichos escolhidos: {chosen_names}.
{niches_instruction}"""
        else:
            prompt_header = f"""Gere {count} novas ideias de videos para o canal "{niche}"."""

        prompt = f"""{prompt_header}
{demand_summary}
{keywords_block}

REGRAS:
- Cada ideia deve ser UNICA e diferente das existentes
- Siga a mesma estrutura do SOP (hook forte, numeros impactantes, historia real)
- Inclua para cada ideia: titulo viral, hook dos primeiros 30s, resumo de 2 linhas, pilar de conteudo, prioridade (ALTA/MEDIA/BAIXA)
{f'- Distribua igualmente entre os sub-nichos escolhidos. O campo pillar DEVE ser um dos nichos escolhidos.' if chosen_niches else ''}

TITULOS JA EXISTENTES (NAO REPETIR):
{chr(10).join(f'- {t}' for t in existing_titles[:30])}

SOP (referencia de tom e estilo):
{sop[:4000]}

Retorne em formato JSON valido:
[{{"title": "...", "hook": "...", "summary": "...", "pillar": "...", "priority": "ALTA"}}]

Retorne APENAS o JSON.{lang_instruction}"""

        response = chat(prompt, max_tokens=MAX_TOKENS_MEDIUM, temperature=0.8)
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if not json_match:
            return JSONResponse({"error": "IA nao retornou JSON valido"}, status_code=500)

        new_ideas = json.loads(json_match.group())

        # Map volume from pre-researched keywords (no extra API call)
        # Exclude generic single words that match too broadly
        if niche_keywords:
            from protocols.keywords_everywhere import _strip_accents, _GENERIC_SINGLE_WORDS, match_keyword_in_title
            kw_vol_map = {
                _strip_accents(kw["keyword"].lower()): kw["vol"]
                for kw in niche_keywords
                if " " in kw["keyword"] or kw["keyword"].lower() not in _GENERIC_SINGLE_WORDS
            }
            for idea in new_ideas[:30]:
                title_lower = _strip_accents(idea.get("title", "").lower())
                best_vol = 0
                for kw_text, kw_vol in kw_vol_map.items():
                    if match_keyword_in_title(kw_text, title_lower) and kw_vol > best_vol:
                        best_vol = kw_vol
                idea["vol"] = best_vol if best_vol > 0 else -1
        else:
            # Fallback: enrich via separate DataForSEO call
            try:
                from protocols.keywords_everywhere import enrich_titles_with_volume
                lang_to_country = {"pt": "br", "en": "us", "es": "es", "fr": "fr", "de": "de"}
                country = lang_to_country.get(lang[:2], "us")
                new_ideas = enrich_titles_with_volume(new_ideas[:30], country=country)
            except Exception as e:
                logger.warning(f"Volume enrichment failed (non-blocking): {e}")

        saved = []
        for idea in new_ideas:
            vol = idea.get("vol", 0) or 0
            iid = save_idea(
                pid, next_num,
                idea.get("title", ""),
                idea.get("hook", ""),
                idea.get("summary", ""),
                idea.get("pillar", ""),
                idea.get("priority", "MEDIA"),
                search_volume=vol,
            )
            saved.append({"id": iid, "num": next_num, "title": idea.get("title", ""), "search_volume": vol})
            next_num += 1

        return JSONResponse({"ok": True, "generated": len(saved), "ideas": saved})
    except ValueError as e:
        logger.error(f"generate-ideas config error: {e}")
        return JSONResponse({"error": f"Configuracao: {str(e)}"}, status_code=400)
    except Exception as e:
        error_msg = str(e)[:300] if str(e) else "Erro desconhecido"
        logger.error(f"generate-ideas error: {e}", exc_info=True)
        return JSONResponse({"error": f"Falha ao gerar ideias: {error_msg}"}, status_code=500)


@router.post("/api/generate-script")
@limiter.limit("10/minute")
async def api_generate_script(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("idea_id")
    project_id = body.get("project_id", "")

    if not idea_id:
        return JSONResponse({"error": "idea_id obrigatorio"}, status_code=400)

    try:
        from database import (
            get_idea, save_script, get_project, save_file,
        )
        from protocols.ai_client import generate_script, generate_narration
        from services import sanitize_niche_name

        idea = get_idea(int(idea_id))
        if not idea:
            return JSONResponse({"error": "Ideia nao encontrada"}, status_code=404)

        pid = project_id or idea["project_id"]

        # Get project language
        proj = get_project(pid)
        lang = (proj or {}).get("language", "pt-BR")

        # Load SOP
        from services import get_project_sop
        sop = get_project_sop(pid)

        # 1. Generate full script (with markers, sections, etc.)
        script = generate_script(
            idea["title"], idea.get("hook", ""), sop, language=lang
        )

        # 2. Generate clean narration (text-only, ready for the agent / TTS)
        try:
            narration = generate_narration(script)
        except Exception as e:
            logger.warning(f"generate_narration failed (using script as fallback): {e}")
            narration = script

        # 3. Persist script in scripts table (legacy)
        save_script(pid, idea["title"], script, int(idea_id), "10-12 min")

        # 4. Also persist as files so they show up in the project's
        #    "Arquivos do Projeto" panel under Roteiros + Narracoes
        title_slug = sanitize_niche_name(idea["title"])[:60] or f"idea-{idea_id}"
        idea_num = idea.get("num", idea_id)
        roteiro_label = f"Roteiro - {idea['title'][:80]}"
        roteiro_filename = f"roteiro_{idea_num}_{title_slug}.md"
        narracao_label = f"Narracao - {idea['title'][:80]}"
        narracao_filename = f"narracao_{idea_num}_{title_slug}.md"

        try:
            save_file(pid, "roteiro", roteiro_label, roteiro_filename, script, visible_to_students=True)
        except Exception as e:
            logger.warning(f"save_file roteiro failed: {e}")
        try:
            save_file(pid, "narracao", narracao_label, narracao_filename, narration, visible_to_students=True)
        except Exception as e:
            logger.warning(f"save_file narracao failed: {e}")

        words = len(script.split())
        narration_words = len(narration.split())

        return JSONResponse({
            "ok": True,
            "title": idea["title"],
            "script": script,
            "narration": narration,
            "words": words,
            "narration_words": narration_words,
            "script_words": words,
            "duration_estimate": f"~{round(words / 140, 1)} min",
            "roteiro_label": roteiro_label,
            "narracao_label": narracao_label,
            "saved_to": "Arquivos do Projeto > Roteiros + Narracoes",
        })
    except Exception as e:
        logger.error(f"generate-script error: {e}")
        return JSONResponse({"error": "Falha ao gerar roteiro"}, status_code=500)


# ── Trend Radar — Niche Trend Detection ──────────────────

@router.post("/api/admin/trend-radar")
@limiter.limit("3/minute")
async def api_trend_radar(request: Request, user=Depends(require_auth)):
    """Scan YouTube for trending content in the niche and suggest timely video ideas."""
    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin only"}, status_code=403)

    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    import asyncio

    def _scan():
        from database import get_project, get_db, log_activity
        from protocols.ai_client import chat

        proj = get_project(project_id)
        if not proj:
            return {"error": "Projeto nao encontrado"}

        niche = proj.get("niche_chosen") or proj.get("name", "")
        lang = proj.get("language", "pt-BR")

        # Get SOP for context
        sop_excerpt = ""
        with get_db() as conn:
            sop_row = conn.execute("SELECT content FROM files WHERE project_id=? AND category='analise' LIMIT 1",
                                  (project_id,)).fetchone()
            if sop_row:
                sop_excerpt = sop_row["content"][:2000]

        # Get YouTube trending videos in the niche
        trending_videos = []
        try:
            yt_key = ""
            with get_db() as conn:
                yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
                if yt_row:
                    yt_key = yt_row["value"]

            if yt_key:
                import requests as _req
                # Search for recent popular videos in the niche
                resp = _req.get("https://www.googleapis.com/youtube/v3/search", params={
                    "part": "snippet",
                    "q": niche,
                    "type": "video",
                    "order": "viewCount",
                    "publishedAfter": _get_date_days_ago(14),
                    "maxResults": 15,
                    "key": yt_key,
                    "relevanceLanguage": lang[:2],
                }, timeout=15)
                if resp.status_code == 200:
                    for item in resp.json().get("items", []):
                        s = item.get("snippet", {})
                        trending_videos.append({
                            "title": s.get("title", ""),
                            "channel": s.get("channelTitle", ""),
                            "published": s.get("publishedAt", "")[:10],
                            "description": s.get("description", "")[:150],
                        })
        except Exception as e:
            import logging
            logging.getLogger("ytcloner").warning(f"Trend radar YouTube search failed: {e}")

        # Get Google Trends data
        trends_data = ""
        try:
            from pytrends.request import TrendReq
            pytrends = TrendReq(hl=lang[:2], tz=360)
            # Get related queries for the niche
            pytrends.build_payload([niche], timeframe='now 7-d')
            related = pytrends.related_queries()
            if niche in related and related[niche].get("rising") is not None:
                rising = related[niche]["rising"].head(10)
                trends_data = "GOOGLE TRENDS — Buscas em alta:\n"
                for _, row in rising.iterrows():
                    trends_data += f"- {row['query']} (crescimento: {row['value']}%)\n"
        except Exception:
            trends_data = "(Google Trends indisponivel)"

        # Build trending videos report
        trending_report = ""
        if trending_videos:
            trending_report = f"VIDEOS POPULARES NAS ULTIMAS 2 SEMANAS ({len(trending_videos)} encontrados):\n"
            for i, v in enumerate(trending_videos, 1):
                trending_report += f'{i}. "{v["title"]}" — {v["channel"]} ({v["published"]})\n'

        # AI generates trend-aware title suggestions in JSON
        from config import LANG_LABELS
        lang_label = LANG_LABELS.get(lang, lang)

        trend_prompt = f"""Voce e um analista de tendencias do YouTube para o nicho "{niche}".

SOP DO CANAL (referencia de tom e estilo — NAO modificar):
{sop_excerpt}

{trending_report}

{trends_data}

TAREFA: Retorne APENAS um JSON valido com esta estrutura:
{{
  "analise": "3-5 paragrafos analisando o que esta em alta agora no nicho",
  "titulos": [
    {{
      "titulo": "titulo viral max 100 chars",
      "hook": "frase de hook dos primeiros 5 segundos",
      "motivo": "por que este assunto esta quente AGORA",
      "urgencia": "ALTA/MEDIA/BAIXA",
      "janela_dias": 7,
      "duracao_ideal": "12-15 min",
      "pilar": "nome do sub-nicho/categoria"
    }}
  ],
  "alertas": [
    {{
      "tipo": "GAP/COMPETIDOR/EXPLOSAO",
      "descricao": "descricao do alerta"
    }}
  ],
  "fontes": "{len(trending_videos)} videos + Google Trends"
}}

REGRAS:
- Gere EXATAMENTE 10 titulos urgentes
- Cada titulo max 100 caracteres (regra YouTube)
- urgencia: ALTA = postar em 3-5 dias, MEDIA = 7-10 dias, BAIXA = 2-3 semanas
- duracao_ideal baseada no SOP
- Gere 3-5 alertas
- Idioma: {lang_label}
- Retorne APENAS o JSON, sem texto antes ou depois"""

        result_text = chat(trend_prompt,
                          "Analista de tendencias YouTube. Retorne APENAS JSON valido.",
                          None, 4000, 0.8)

        # Parse JSON from response
        import re as _re
        json_match = _re.search(r'\{.*\}', result_text, _re.DOTALL)
        result_data = None
        if json_match:
            try:
                result_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Save raw + structured as file
        from database import save_file
        save_content = result_text
        if result_data:
            save_content = json.dumps(result_data, ensure_ascii=False, indent=2)
        save_file(project_id, "outros", f"Radar de Tendencias - {niche}",
                 f"trends_{project_id}.md", save_content)
        log_activity(project_id, "trend_radar", f"Radar: {len(trending_videos)} videos + trends analisados")

        return {
            "ok": True,
            "report": result_data if result_data else result_text,
            "structured": bool(result_data),
            "trending_count": len(trending_videos),
            "has_google_trends": bool(trends_data and "indisponivel" not in trends_data),
        }

    try:
        result = await asyncio.to_thread(_scan)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"trend-radar error: {e}")
        return JSONResponse({"error": "Falha no radar de tendencias."}, status_code=500)


def _get_date_days_ago(days: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")


# ── Multi-Language Cloning ───────────────────────────────

@router.post("/api/admin/clone-language")
@limiter.limit("3/minute")
async def api_clone_language(request: Request, user=Depends(require_auth)):
    """Clone a project's SOP (and adapt it for a different language/market when applicable).

    Resilient version: each phase has specific error handling so the user gets
    actionable feedback. Same-language clones skip AI adaptation and just copy.
    Title/niche adaptation failures are non-fatal (SOP is the critical asset).
    """
    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin only"}, status_code=403)

    body = await request.json()
    source_project_id = body.get("project_id", "")
    target_language = body.get("target_language", "")
    new_name = (body.get("new_name") or "").strip()

    if not source_project_id or not target_language:
        return JSONResponse({"error": "project_id e target_language obrigatorios"}, status_code=400)

    from config import LANG_LABELS

    if target_language not in LANG_LABELS:
        return JSONResponse(
            {"error": f"Idioma invalido. Use: {', '.join(LANG_LABELS.keys())}"},
            status_code=400,
        )

    import asyncio
    import json as _json
    import logging
    import re as _re
    from pathlib import Path as _Path

    log = logging.getLogger("ytcloner.clone")

    def _clone():
        from datetime import datetime
        from database import (
            get_project, get_db, create_project, save_file, save_niche,
            save_idea, log_activity,
        )
        from protocols.ai_client import chat
        from config import PROJECTS_DIR

        # ── Phase 1: Load source project ──────────────────────────────
        source = get_project(source_project_id)
        if not source:
            return {"error": "Projeto fonte nao encontrado", "phase": "load_project"}

        log.info(f"[CLONE] phase=load_project source={source_project_id} name={source.get('name')}")

        # ── Phase 2: Load source SOP (DB → filesystem fallback) ───────
        source_sop = ""
        try:
            with get_db() as conn:
                sop_row = conn.execute(
                    "SELECT content FROM files WHERE project_id=? AND category='analise' AND content IS NOT NULL AND content != '' ORDER BY id ASC LIMIT 1",
                    (source_project_id,),
                ).fetchone()
            if sop_row and sop_row["content"]:
                source_sop = sop_row["content"]
        except Exception as e:
            log.exception(f"[CLONE] phase=load_sop_db error: {e}")

        # Filesystem fallback for legacy projects
        if not source_sop:
            try:
                proj_dir = PROJECTS_DIR / source_project_id
                if proj_dir.exists():
                    for f in sorted(proj_dir.glob("sop*.md")) + sorted(proj_dir.glob("*sop*.md")):
                        try:
                            source_sop = f.read_text(encoding="utf-8")
                            if source_sop.strip():
                                log.info(f"[CLONE] phase=load_sop_fs found at {f}")
                                break
                        except Exception:
                            continue
            except Exception as e:
                log.exception(f"[CLONE] phase=load_sop_fs error: {e}")

        if not source_sop or len(source_sop.strip()) < 50:
            return {
                "error": "Projeto fonte nao tem SOP carregado. Rode o pipeline ou gere o SOP antes de clonar.",
                "phase": "load_sop",
            }

        # ── Phase 3: Load ideas + niches (best effort) ────────────────
        ideas = []
        niches = []
        try:
            with get_db() as conn:
                ideas = [
                    dict(r) for r in conn.execute(
                        "SELECT title, hook, summary, pillar, priority FROM ideas WHERE project_id=? LIMIT 30",
                        (source_project_id,),
                    ).fetchall()
                ]
                niches = [
                    dict(r) for r in conn.execute(
                        "SELECT name, description, rpm_range, competition, color, pillars FROM niches WHERE project_id=?",
                        (source_project_id,),
                    ).fetchall()
                ]
        except Exception as e:
            log.exception(f"[CLONE] phase=load_ideas_niches error: {e}")
            # non-fatal — continue with empty lists

        log.info(f"[CLONE] loaded ideas={len(ideas)} niches={len(niches)}")

        source_lang = source.get("language", "pt-BR")
        target_label = LANG_LABELS[target_language]
        source_label = LANG_LABELS.get(source_lang, source_lang)
        niche_name = new_name or f"{source.get('name', 'Projeto')} ({target_language.upper()})"
        same_language = (source_lang == target_language)

        # ── Phase 4: Create destination project ───────────────────────
        try:
            new_project_id = create_project(
                name=niche_name,
                channel_original=source.get("channel_original", ""),
                niche_chosen=niche_name,
                language=target_language,
                meta={
                    "cloned_from": source_project_id,
                    "cloned_at": datetime.now().isoformat(),
                    "source_lang": source_lang,
                },
            )
        except Exception as e:
            log.exception(f"[CLONE] phase=create_project error: {e}")
            return {
                "error": f"Falha ao criar projeto destino: {str(e)[:200]}",
                "phase": "create_project",
            }

        log.info(f"[CLONE] created destination project_id={new_project_id} same_lang={same_language}")

        warnings: list[str] = []

        # ── Phase 5: SOP adaptation (or copy if same language) ────────
        adapted_sop = ""
        if same_language:
            # No translation needed — copy verbatim
            adapted_sop = source_sop
            log.info(f"[CLONE] phase=sop same language — copied verbatim ({len(adapted_sop)} chars)")
        else:
            adapt_prompt = f"""Voce e um especialista em adaptacao de conteudo para mercados internacionais.

Adapte o SOP abaixo de {source_label} para {target_label}.

===== SOP ORIGINAL ({source_label}) =====
{source_sop[:10000]}
===== FIM =====

INSTRUCOES DE ADAPTACAO:
1. NAO e traducao literal — e ADAPTACAO CULTURAL
2. Hooks: adapte referencias culturais, memes, expressoes pro publico {target_label}
3. Vocabulario: use girias e expressoes naturais de {target_label} (nao traduza, reinvente)
4. SEO: keywords e tags no idioma alvo
5. Exemplos: substitua exemplos locais por equivalentes no mercado alvo
6. Tom: ajuste formalidade pro padrao cultural do mercado alvo
7. Titulos: adapte formulas de titulo pro que funciona no YouTube {target_label}
8. Mantenha TODA a estrutura do SOP (17 secoes) — so mude o conteudo pra {target_label}
9. Na secao 15 (System Prompt para IA): reescreva INTEIRO em {target_label}

O resultado deve parecer que foi criado nativamente para o mercado {target_label}, nao traduzido.

Escreva o SOP completo adaptado em {target_label}."""

            try:
                adapted_sop = chat(
                    adapt_prompt,
                    system=f"Especialista em localizacao de conteudo YouTube para {target_label}. Adaptacao cultural profunda, nao traducao.",
                    max_tokens=12000,
                    temperature=0.7,
                    timeout=300,
                )
            except Exception as e:
                log.exception(f"[CLONE] phase=adapt_sop error: {e}")
                # Fallback: copy original SOP and warn
                adapted_sop = source_sop
                warnings.append(f"Adaptacao do SOP via IA falhou ({str(e)[:120]}) — SOP original copiado sem adaptacao")

            if not adapted_sop or len(adapted_sop.strip()) < 100:
                # AI returned empty/garbage — fall back to source
                adapted_sop = source_sop
                warnings.append("IA retornou SOP vazio — SOP original copiado sem adaptacao")

        try:
            save_file(
                new_project_id, "analise", f"SOP - {niche_name}",
                f"sop_{new_project_id}.md", adapted_sop,
            )
        except Exception as e:
            log.exception(f"[CLONE] phase=save_sop error: {e}")
            return {
                "error": f"Projeto criado mas falhou ao salvar SOP: {str(e)[:200]}",
                "phase": "save_sop",
                "new_project_id": new_project_id,
            }

        log.info(f"[CLONE] phase=save_sop OK ({len(adapted_sop)} chars)")

        # ── Phase 6: Title adaptation (non-fatal) ─────────────────────
        adapted_count = 0
        if ideas:
            if same_language:
                # Just copy titles verbatim
                for i, idea in enumerate(ideas[:30]):
                    try:
                        save_idea(
                            new_project_id, i + 1,
                            idea.get("title", ""), idea.get("hook", ""),
                            idea.get("summary", ""), idea.get("pillar", ""),
                            idea.get("priority", "MEDIA"),
                        )
                        adapted_count += 1
                    except Exception as e:
                        log.warning(f"[CLONE] save_idea failed for idea {i}: {e}")
            else:
                titles_text = "\n".join([f'- {i["title"]}' for i in ideas[:30]])
                titles_prompt = f"""Adapte estes {len(ideas[:30])} titulos de {source_label} para {target_label}.

TITULOS ORIGINAIS:
{titles_text}

SOP ADAPTADO (referencia de estilo):
{adapted_sop[:2000]}

Para CADA titulo:
- Adapte (nao traduza literalmente) pro mercado {target_label}
- Mantenha o mesmo hook/impacto emocional
- Use keywords que funcionam no YouTube {target_label}

Retorne APENAS JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"...","priority":"ALTA/MEDIA/BAIXA"}}]"""

                try:
                    titles_response = chat(
                        titles_prompt,
                        max_tokens=8000, temperature=0.8, timeout=240,
                    )
                    json_match = _re.search(r"\[.*\]", titles_response, _re.DOTALL)
                    if json_match:
                        adapted_ideas = _json.loads(json_match.group())
                        for i, idea in enumerate(adapted_ideas[:30]):
                            try:
                                save_idea(
                                    new_project_id, i + 1,
                                    idea.get("title", ""), idea.get("hook", ""),
                                    idea.get("summary", ""), idea.get("pillar", ""),
                                    idea.get("priority", "MEDIA"),
                                )
                                adapted_count += 1
                            except Exception as e:
                                log.warning(f"[CLONE] save_idea failed: {e}")
                    else:
                        warnings.append("Adaptacao de titulos: IA nao retornou JSON valido")
                except Exception as e:
                    log.exception(f"[CLONE] phase=adapt_titles error: {e}")
                    warnings.append(f"Adaptacao de titulos falhou: {str(e)[:120]}")

        log.info(f"[CLONE] phase=titles adapted={adapted_count}/{len(ideas)}")

        # ── Phase 7: Niche copy (non-fatal) ──────────────────────────
        # Fix: pillars from DB is a JSON string, need to decode before passing
        # to save_niche (which calls json.dumps on it again).
        niche_colors = ["#e040fb", "#448aff", "#ff5252", "#ffd740", "#00e5ff"]
        niches_saved = 0
        for i, n in enumerate(niches[:5]):
            try:
                # Decode pillars JSON string back to list
                pillars_raw = n.get("pillars", "")
                pillars_list: list = []
                if isinstance(pillars_raw, str) and pillars_raw.strip():
                    try:
                        decoded = _json.loads(pillars_raw)
                        if isinstance(decoded, list):
                            pillars_list = decoded
                    except (ValueError, TypeError):
                        pillars_list = []
                elif isinstance(pillars_raw, list):
                    pillars_list = pillars_raw

                save_niche(
                    new_project_id,
                    n.get("name", ""),
                    n.get("description", ""),
                    n.get("rpm_range", ""),
                    n.get("competition", ""),
                    n.get("color", niche_colors[i % 5]),
                    chosen=(i == 0),
                    pillars=pillars_list,
                )
                niches_saved += 1
            except Exception as e:
                log.warning(f"[CLONE] save_niche failed for niche {i}: {e}")
                warnings.append(f"Falha ao copiar nicho '{n.get('name', '?')}': {str(e)[:80]}")

        log.info(f"[CLONE] phase=niches saved={niches_saved}/{len(niches)}")

        # ── Phase 8: Activity log ─────────────────────────────────────
        try:
            log_activity(
                new_project_id, "cloned",
                f"Clonado de {source.get('name', '')} ({source_lang}) para {target_language}"
                + (f" — {len(warnings)} avisos" if warnings else ""),
            )
        except Exception as e:
            log.warning(f"[CLONE] log_activity failed: {e}")

        return {
            "ok": True,
            "new_project_id": new_project_id,
            "name": niche_name,
            "source_lang": source_lang,
            "target_lang": target_language,
            "same_language": same_language,
            "ideas_adapted": adapted_count,
            "niches_copied": niches_saved,
            "sop_chars": len(adapted_sop),
            "warnings": warnings,
        }

    try:
        result = await asyncio.to_thread(_clone)
        if result.get("error"):
            status = 404 if result.get("phase") == "load_project" else 400
            return JSONResponse(result, status_code=status)
        return JSONResponse(result)
    except Exception as e:
        import logging as _log_mod
        _log_mod.getLogger("ytcloner").exception(f"clone-language unexpected error: {e}")
        return JSONResponse(
            {"error": f"Falha inesperada ao clonar: {str(e)[:200]}"},
            status_code=500,
        )
