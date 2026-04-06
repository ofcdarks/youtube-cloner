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


@router.get("/api/seed-pov")
async def seed_pov(request: Request):
    """One-time seed: creates POV project with SOP + niches + 30 titles."""
    from database import get_projects, create_project, save_niche, save_idea, save_file, log_activity, get_db
    existing = [p for p in get_projects() if "POV" == p.get("name", "")]
    if existing:
        return JSONResponse({"ok": True, "msg": "POV already exists", "id": existing[0]["id"]})
    with get_db() as conn:
        for sql in ["ALTER TABLE ideas ADD COLUMN search_competition REAL DEFAULT -1",
                     "ALTER TABLE ideas ADD COLUMN title_b TEXT DEFAULT ''",
                     "ALTER TABLE ideas ADD COLUMN trending INTEGER DEFAULT 0"]:
            try: conn.execute(sql)
            except: pass
    pid = create_project(name="POV", channel_original="", niche_chosen="POV Storytelling", language="es")
    sop = """# POV STORYTELLING SOP
## DNA: POV immersive storytelling (Biz Life POV, POVrank, Professor POV, Odd Dude Explained style)
FORMAT: 15-30 min, 2nd person present tense, viewer IS the protagonist. Visual: 3D cinematic, faceless mannequins, motion graphics.
TITLE FORMULA: "POV: Eres el [ROL] del [ORGANIZACION]" / "POV: Tu vida como cada rango de [SISTEMA]" / "Tu vida en cada nivel de [JERARQUIA]"
HOOK: Immediate sensory immersion. "Tu telefono suena a las 3am. No reconoces el numero pero sabes que tienes que contestar..."
STRUCTURE: Level/Rank progression (nivel 1 a nivel X), each level = higher stakes, more power, more danger
TONE: Cinematic, tense, immersive. YOU are there. Present tense always. Sensory details mandatory.
GOLDEN RULES: 1.Always 2nd person 2.Present tense 3.Sensory details every 30s 4.Stakes escalate per level 5.Point of no return at 60% 6.Dark moment before climax 7.Jargon for authenticity 8.Supporting characters with personality 9.Physical consequences described 10.Never break POV 11.Cliffhanger between levels 12.Twist at highest rank 13.Consequences are REAL 14.End with philosophical weight 15.Binge-bait outro
VISUAL: 3D cinematic scenes, faceless mannequin characters, dark atmospheric lighting, motion graphics for data/maps, text overlays for ranks/levels
RPM: $8-15. Audience: 18-35 male, interested in power structures, military, crime, espionage."""
    save_file(pid, "analise", "SOP - POV (NotebookLM)", f"sop_{pid}.md", sop)
    niches = [
        ("Carteles y Narcotrafico", "POV como sicario, hijo del capo, abogado del narco, policia corrupto, agente de la DEA", "$8-15", "Alta", "#8B0000", True),
        ("Espionaje y Operaciones Secretas", "POV como agente CIA, espia doble, hacker gubernamental, operativo black ops", "$10-18", "Media", "#1A1A2E", True),
        ("Militar y Fuerzas Especiales", "POV como francotirador, piloto de combate, SWAT, soldado de trinchera, Navy SEAL", "$8-14", "Media", "#2D3A4A", False),
        ("Crimen y Mundo Criminal", "POV como jefe de la mafia, ladron de bancos, falsificador, testigo protegido", "$8-15", "Alta", "#FF0000", False),
        ("Poder y Jerarquias", "POV cada nivel de poder en Corea del Norte, cada rango del FBI, cada nivel de riqueza", "$10-16", "Baja", "#DAA520", False),
    ]
    for name, desc, rpm, comp, color, chosen in niches:
        save_niche(pid, name, desc, rpm, comp, color, chosen)
    titles = [
        ("POV: Eres el SICARIO mas LETAL del Cartel", "Carteles y Narcotrafico", "ALTA", 40500),
        ("POV: Eres el HIJO del Jefe del Cartel mas PELIGROSO", "Carteles y Narcotrafico", "ALTA", 33100),
        ("POV: Eres el ABOGADO del Narco mas BUSCADO del Mundo", "Carteles y Narcotrafico", "ALTA", 22200),
        ("POV: Eres un Policia CORRUPTO en la Nomina del Cartel", "Carteles y Narcotrafico", "ALTA", 18100),
        ("POV: Eres un Agente de la DEA ADICTO a las Drogas", "Carteles y Narcotrafico", "ALTA", 14800),
        ("POV: Eres el que DESAPARECE los Cuerpos del Cartel", "Carteles y Narcotrafico", "MEDIA", 9900),
        ("POV: Eres un Cirujano CORRUPTO que Vende Organos", "Carteles y Narcotrafico", "MEDIA", 8100),
        ("POV: Eres un Agente de la CIA en Operaciones PROHIBIDAS", "Espionaje y Operaciones Secretas", "ALTA", 27100),
        ("POV: Tu Vida en Cada Rango de las Operaciones BLACK OPS", "Espionaje y Operaciones Secretas", "ALTA", 22200),
        ("POV: Eres un HACKER que Trabaja para el Gobierno", "Espionaje y Operaciones Secretas", "ALTA", 18100),
        ("POV: Eres un Agente del FBI CORRUPTO", "Espionaje y Operaciones Secretas", "ALTA", 14800),
        ("POV: Eres un Agente de la Agencia que NO Existe", "Espionaje y Operaciones Secretas", "MEDIA", 9900),
        ("POV: Eres un US Marshal CORRUPTO", "Espionaje y Operaciones Secretas", "MEDIA", 6600),
        ("POV: Tu Vida en Cada Rango de Francotirador MILITAR", "Militar y Fuerzas Especiales", "ALTA", 33100),
        ("POV: Tu Vida en Cada Unidad de Operaciones Especiales de EEUU", "Militar y Fuerzas Especiales", "ALTA", 22200),
        ("POV: Tu Vida como Piloto de un F-22 RAPTOR", "Militar y Fuerzas Especiales", "ALTA", 18100),
        ("POV: Tu Vida como Piloto de un Bombardero STEALTH", "Militar y Fuerzas Especiales", "MEDIA", 12100),
        ("POV: Tu Vida como Cada Rango de Soldado en las TRINCHERAS", "Militar y Fuerzas Especiales", "MEDIA", 9900),
        ("POV: Tu Vida en Cada Rango del Ejercito ALEMAN en la WWII", "Militar y Fuerzas Especiales", "MEDIA", 8100),
        ("POV: Eres el JEFE de la Mafia", "Crimen y Mundo Criminal", "ALTA", 27100),
        ("POV: Eres un Boxeador COMPRADO por un Jefe del Cartel", "Crimen y Mundo Criminal", "ALTA", 14800),
        ("POV: Eres un Abogado FALSO que Nunca Paso el Examen", "Crimen y Mundo Criminal", "MEDIA", 9900),
        ("POV: Tu Vida Despues de Ganar 500 MILLONES en la Loteria", "Crimen y Mundo Criminal", "MEDIA", 49500),
        ("POV: Tu Vida en Cada Nivel de PROTECCION de Testigos", "Crimen y Mundo Criminal", "MEDIA", 6600),
        ("POV: Tu Vida en Cada Nivel de PODER en Corea del Norte", "Poder y Jerarquias", "ALTA", 40500),
        ("POV: Tu Vida en Cada Rango de la Lista de los MAS BUSCADOS del FBI", "Poder y Jerarquias", "ALTA", 22200),
        ("POV: Tu Vida en Cada Rango SWAT", "Poder y Jerarquias", "MEDIA", 12100),
        ("POV: Tu Vida en Cada Nivel de BUSQUEDA del FBI", "Poder y Jerarquias", "MEDIA", 9900),
        ("POV: Tu Vida en Cada Rango de un FAMILY OFFICE", "Poder y Jerarquias", "MEDIA", 5400),
        ("POV: Tu Vida como Cada Rango de RAPPER", "Poder y Jerarquias", "BAIXA", 33100),
    ]
    for i, (title, pillar, pri, vol) in enumerate(titles):
        save_idea(pid, i+1, title, "", "", pillar, pri, search_volume=vol, trending=1)
    log_activity(pid, "project_seeded", f"POV seeded: 5 niches, {len(titles)} titles, SOP from NotebookLM")
    return JSONResponse({"ok": True, "project_id": pid, "niches": 5, "titles": len(titles), "sop_chars": len(sop)})



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
            demand_data = research_niche_demand(niche, proj_data.get("language", "pt-BR") if proj_data else "pt-BR", yt_key)
            demand_summary = demand_data.get("summary", "")
        except Exception:
            pass

        # Get chosen niches for focused title generation
        from database import get_niches
        chosen_niches = [n for n in get_niches(pid) if n.get("chosen")]
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

        prompt = f"""Gere {count} novas ideias de videos para o canal "{niche}".
{niches_instruction}
{demand_summary}
{keywords_block}

REGRAS:
- Cada ideia deve ser UNICA e diferente das existentes
- Siga a mesma estrutura do SOP (hook forte, numeros impactantes, historia real)
- Inclua para cada ideia: titulo viral, hook dos primeiros 30s, resumo de 2 linhas, pilar de conteudo, prioridade (ALTA/MEDIA/BAIXA)
{f'- Distribua igualmente entre os sub-nichos escolhidos' if chosen_niches else ''}

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
    except Exception as e:
        logger.error(f"generate-ideas error: {e}")
        return JSONResponse({"error": "Falha ao gerar ideias"}, status_code=500)


@router.post("/api/generate-script")
@limiter.limit("10/minute")
async def api_generate_script(request: Request, user=Depends(require_auth)):
    body = await request.json()
    idea_id = body.get("idea_id")
    project_id = body.get("project_id", "")

    if not idea_id:
        return JSONResponse({"error": "idea_id obrigatorio"}, status_code=400)

    try:
        from database import get_idea, get_files as db_get_files, get_projects as db_projects, save_script, get_project
        from protocols.ai_client import generate_script

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

        script = generate_script(idea["title"], idea.get("hook", ""), sop, language=lang)

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
    """Clone a project's SOP and adapt it for a different language/market."""
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
        return JSONResponse({"error": f"Idioma invalido. Use: {', '.join(LANG_LABELS.keys())}"}, status_code=400)

    import asyncio

    def _clone():
        from database import get_project, get_db, create_project, save_file, save_niche, save_idea, log_activity
        from protocols.ai_client import chat

        source = get_project(source_project_id)
        if not source:
            return {"error": "Projeto fonte nao encontrado"}

        # Get source SOP
        with get_db() as conn:
            sop_row = conn.execute("SELECT content FROM files WHERE project_id=? AND category='analise' LIMIT 1",
                                  (source_project_id,)).fetchone()
            ideas = [dict(r) for r in conn.execute("SELECT title, hook, pillar, priority FROM ideas WHERE project_id=? LIMIT 30",
                                                    (source_project_id,)).fetchall()]
            niches = [dict(r) for r in conn.execute("SELECT name, description, rpm_range, competition, color, pillars FROM niches WHERE project_id=?",
                                                     (source_project_id,)).fetchall()]

        if not sop_row:
            return {"error": "SOP do projeto fonte nao encontrado"}

        source_sop = sop_row["content"]
        source_lang = source.get("language", "pt-BR")
        target_label = LANG_LABELS[target_language]
        source_label = LANG_LABELS.get(source_lang, source_lang)
        niche_name = new_name or f"{source.get('name', 'Projeto')} ({target_language.upper()})"

        # Create new project
        new_project_id = create_project(
            name=niche_name,
            channel_original=source.get("channel_original", ""),
            niche_chosen=niche_name,
            language=target_language,
        )

        # Adapt SOP for target language/market
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

        adapted_sop = chat(adapt_prompt,
                          system=f"Especialista em localizacao de conteudo YouTube para {target_label}. Adaptacao cultural profunda, nao traducao.",
                          max_tokens=8000, temperature=0.7)

        save_file(new_project_id, "analise", f"SOP - {niche_name}", f"sop_{new_project_id}.md", adapted_sop)

        # Adapt titles
        if ideas:
            titles_text = "\n".join([f'- {i["title"]}' for i in ideas[:30]])
            titles_prompt = f"""Adapte estes 30 titulos de {source_label} para {target_label}.

TITULOS ORIGINAIS:
{titles_text}

SOP ADAPTADO (referencia de estilo):
{adapted_sop[:2000]}

Para CADA titulo:
- Adapte (nao traduza literalmente) pro mercado {target_label}
- Mantenha o mesmo hook/impacto emocional
- Use keywords que funcionam no YouTube {target_label}

Retorne APENAS JSON: [{{"title":"...","hook":"...","summary":"...","pillar":"...","priority":"ALTA/MEDIA/BAIXA"}}]"""

            titles_response = chat(titles_prompt, max_tokens=6000, temperature=0.8)
            import re
            json_match = re.search(r'\[.*\]', titles_response, re.DOTALL)
            if json_match:
                try:
                    import json as _json
                    adapted_ideas = _json.loads(json_match.group())
                    for i, idea in enumerate(adapted_ideas[:30]):
                        save_idea(new_project_id, i+1, idea.get("title", ""),
                                 idea.get("hook", ""), idea.get("summary", ""),
                                 idea.get("pillar", ""), idea.get("priority", "MEDIA"))
                except Exception:
                    pass

        # Copy niches (adapt names)
        niche_colors = ["#e040fb", "#448aff", "#ff5252", "#ffd740", "#00e5ff"]
        for i, n in enumerate(niches[:5]):
            save_niche(new_project_id, n.get("name", ""), n.get("description", ""),
                      n.get("rpm_range", ""), n.get("competition", ""),
                      n.get("color", niche_colors[i % 5]), chosen=(i == 0),
                      pillars=n.get("pillars", []))

        log_activity(new_project_id, "cloned", f"Clonado de {source.get('name', '')} ({source_lang}) para {target_language}")

        return {
            "ok": True,
            "new_project_id": new_project_id,
            "name": niche_name,
            "source_lang": source_lang,
            "target_lang": target_language,
        }

    try:
        result = await asyncio.to_thread(_clone)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"clone-language error: {e}")
        return JSONResponse({"error": "Falha ao clonar projeto."}, status_code=500)
