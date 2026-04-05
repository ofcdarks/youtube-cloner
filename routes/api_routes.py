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


@router.get("/api/score-all")
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

    def _score_all():
        """Run scoring in thread so health checks keep responding."""
        from protocols.title_scorer import score_title
        results = []
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
                logger.warning(f"Score failed for '{idea['title'][:30]}': {e}")
                results.append({"id": idea["id"], "title": idea["title"], "score": 0, "rating": "N/A", "error": "Falha ao pontuar"})
        return results

    try:
        results = await asyncio.to_thread(_score_all)
        return JSONResponse({"ok": True, "scored": len(results), "results": results})
    except Exception as e:
        logger.error(f"score-all error: {e}")
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

Retorne APENAS o JSON.{lang_instruction}"""

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

        # AI generates trend-aware title suggestions
        trend_prompt = f"""Voce e um analista de tendencias do YouTube para o nicho "{niche}".

SOP DO CANAL (referencia de estilo):
{sop_excerpt}

{trending_report}

{trends_data}

TAREFA: Baseado nas tendencias REAIS acima, gere:

1. ANALISE DE TENDENCIAS (3-5 paragrafos):
   - O que esta em alta no nicho agora?
   - Quais padroes de titulo estao funcionando?
   - Que assuntos estao ganhando tracao?

2. 10 TITULOS URGENTES (para postar AGORA):
   Para cada titulo:
   - Titulo viral seguindo o SOP
   - Hook de 5 segundos
   - Por que este assunto esta quente AGORA
   - Janela de oportunidade (dias restantes)

3. ALERTAS:
   - Assuntos que concorrentes estao cobrindo e voce NAO
   - Gaps de conteudo (o que o publico busca mas ninguem fez)
   - Tendencia que vai explodir nas proximas semanas

Idioma: {"Portugues BR" if lang == "pt-BR" else lang}
Seja especifico e acionavel. Cada titulo deve ser algo que pode ser produzido HOJE."""

        result = chat(trend_prompt,
                     system="Analista de tendencias do YouTube. Usa dados reais, nao achismos. Cada recomendacao e acionavel e urgente.",
                     max_tokens=4000, temperature=0.8)

        # Save as file
        from database import save_file
        save_file(project_id, "outros", f"Radar de Tendencias - {niche}",
                 f"trends_{project_id}.md", result)
        log_activity(project_id, "trend_radar", f"Radar: {len(trending_videos)} videos + trends analisados")

        return {
            "ok": True,
            "report": result,
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
