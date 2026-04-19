"""
Pipeline Routes — Full channel analysis pipeline + title/niche regeneration.
Extracted from dashboard.py for modularity.
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_admin
from config import OUTPUT_DIR, MAX_TOKENS_LARGE, MAX_TOKENS_MEDIUM
from rate_limit import limiter
from services import (
    validate_url, sanitize_niche_name, analyze_via_transcripts,
    generate_mindmap_html,
)

logger = logging.getLogger("ytcloner.routes.pipeline")

router = APIRouter(tags=["pipeline"])


@router.post("/api/admin/analyze-channel")
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
        from database import get_niches, get_files, get_ideas
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

Seja EXTREMAMENTE detalhado. Cada secao deve ter ao menos 200 palavras. SOP total minimo: 4000 palavras. Especifico para o nicho \"{niche_name}\".{lang_instruction}"""
            sop_content = chat(sop_prompt, system="Voce e um estrategista de canais faceless do YouTube com 10 anos de experiencia. Sua especialidade e criar SOPs (Standard Operating Procedures) ultra detalhados de 17 secoes que servem como DNA para replicar e elevar canais bem-sucedidos.", max_tokens=MAX_TOKENS_LARGE)

        save_file(project_id, "analise", f"SOP - {niche_name}", f"sop_{project_id}.md", sop_content)
        log_activity(project_id, "sop_generated", f"SOP via {sop_source}")

        _step(3, 'Gerando 5 nichos derivados')

        # Step 3: Generate 5 niches
        _channel_ref = f'"{niche_name}" ({url})' if url else f'"{niche_name}" (template de nicho, sem canal de referencia)'
        niche_prompt = f"""Baseado neste canal {_channel_ref}, gere 5 sub-nichos derivados.
SOP: {sop_content[:3000]}

REGRAS OBRIGATORIAS:
1. O campo "name" deve ser no IDIOMA ORIGINAL do canal ({lang_label}).
2. O campo "description" deve ser SEMPRE em Portugues Brasileiro (PT-BR), independente do idioma do canal. Descricao curta de 1-2 frases explicando o sub-nicho.
3. Inclua o campo "recommended" (true/false) — marque como true o nicho com MELHOR potencial baseado em: RPM alto + competicao baixa/media + tendencia de crescimento. Maximo 1-2 nichos recomendados.
4. O campo "recommended_reason" (string PT-BR) — explique em 5-8 palavras porque e recomendado (ex: "RPM alto, pouca concorrencia, tendencia subindo").

Retorne JSON: [{{"name":"...","description":"descricao em PT-BR","rpm_range":"$X-Y","competition":"Low/Medium/High","color":"#hex","pillars":["..."],"recommended":false,"recommended_reason":""}}]
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
                    # Store recommended flag inside pillars JSON for template rendering
                    pillars_data = n.get("pillars", [])
                    if not isinstance(pillars_data, list):
                        pillars_data = []
                    # Inject recommended metadata as special entry
                    if n.get("recommended"):
                        pillars_data.append({"__recommended": True, "__reason": n.get("recommended_reason", "")})
                    save_niche(project_id, n.get("name", f"Nicho {i+1}"), n.get("description", ""),
                              n.get("rpm_range", ""), n.get("competition", ""),
                              n.get("color", niche_colors[i % 5]), chosen=(i == 0), pillars=pillars_data)
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
            from database import get_db
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
- CADA titulo DEVE ter MINIMO 70 caracteres e MAXIMO 100 caracteres (incluindo espacos)
- Titulos curtos NAO performam — use frases completas com numeros, emocao, curiosidade e open loops
- NUNCA gerar titulos com menos de 70 caracteres

TESTE A/B (CRITICO pra regra de 4 horas):
Pra CADA ideia gera DOIS titulos (title_a e title_b) sobre o MESMO assunto mas usando
ANGULOS DIFERENTES — pra que se o primeiro nao trouxer impressoes nas 4h iniciais,
o aluno troque pelo segundo. Angulos opostos funcionam melhor:
- title_a = angulo CURIOSITY GAP (promessa/mistério, ex "O metodo que NINGUEM te contou sobre X")
- title_b = angulo NUMERO ESPECIFICO (dado concreto, ex "Fiz isso por 47 dias e o resultado foi X")
OU title_a = PERGUNTA vs title_b = AFIRMACAO, title_a = IDENTIDADE vs title_b = CONTRASTE.
Ambos devem ter 70-100 chars e ser sobre o MESMO VIDEO — so muda o angulo de ataque.

Retorne JSON: [{{"title_a":"...","title_b":"...","hook":"...","summary":"...","pillar":"nome do sub-nicho","priority":"ALTA"}}]
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
                    # Compat: aceita tanto formato novo (title_a/title_b) quanto antigo (title)
                    title_a = idea.get("title_a") or idea.get("title", f"Titulo {i+1}")
                    title_b = idea.get("title_b", "")
                    # save_idea() enforces 100-char limit via enforce_title_limit()
                    save_idea(project_id, i + 1, title_a,
                             hook=idea.get("hook", ""),
                             summary=idea.get("summary", ""),
                             pillar=idea.get("pillar", ""),
                             priority=idea.get("priority", "MEDIA"),
                             title_b=title_b)
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
                seo_content = future_seo.result(timeout=120)
                if seo_content and len(seo_content) > 100:
                    save_file(project_id, "seo", "SEO Pack", f"seo_pack_{project_id}.md", seo_content)
                    seo_generated = 10
                    log_activity(project_id, "seo_generated", f"SEO Pack para {seo_generated} videos")
                _step(5, 'SEO Pack concluido', f'{seo_generated} videos')
            except Exception as e:
                logger.error(f"SEO generation failed: {e}")

            # Collect Thumbnail result
            try:
                thumb_content = future_thumb.result(timeout=120)
                if thumb_content and len(thumb_content) > 100:
                    save_file(project_id, "outros", "Thumbnail Prompts - Midjourney DALL-E", f"thumbnail_prompts_{project_id}.md", thumb_content)
                    log_activity(project_id, "thumbnail_prompts", "Thumbnail Prompts gerados")
                _step(6, 'Thumbnail Prompts concluidos', 'Midjourney + DALL-E')
            except Exception as e:
                logger.error(f"Thumbnail prompts failed: {e}")

            # Collect Music result
            try:
                music_content = future_music.result(timeout=120)
                if music_content and len(music_content) > 100:
                    save_file(project_id, "outros", "Music Prompts - Suno Udio MusicGPT", f"music_prompts_{project_id}.md", music_content)
                    log_activity(project_id, "music_prompts", "Music Prompts gerados")
                _step(7, 'Music Prompts concluidos', 'Suno + Udio + MusicGPT')
            except Exception as e:
                logger.error(f"Music prompts failed: {e}")

            # Collect Teaser result
            try:
                teaser_content = future_teaser.result(timeout=120)
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
                        roteiro = future.result(timeout=120)
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


@router.post("/api/admin/regenerate-titles")
@limiter.limit("3/minute")
async def api_regenerate_titles(request: Request, user=Depends(require_admin)):
    """Regenerate titles using chosen niches + keyword volume data."""
    body = await request.json()
    project_id = body.get("project_id", "").strip()
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_project, get_niches, get_db, get_ideas
    from services import get_project_sop
    from protocols.ai_client import chat
    from database import save_idea, log_activity
    import asyncio

    project = get_project(project_id)
    if not project:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    sop = get_project_sop(project_id)
    if not sop:
        return JSONResponse({"error": "SOP nao encontrado"}, status_code=400)

    niches = get_niches(project_id)
    chosen = [n for n in niches if n.get("chosen")]
    if not chosen:
        return JSONResponse({"error": "Nenhum nicho selecionado"}, status_code=400)

    lang = project.get("language", "en")
    from config import LANG_LABELS
    lang_label = LANG_LABELS.get(lang, lang)

    try:
        # Collect existing titles to avoid duplicates
        existing_ideas = get_ideas(project_id) or []
        existing_titles = [i.get("title", "").strip().lower() for i in existing_ideas if i.get("title")]

        # Get keyword data from cache or generate
        from protocols.keywords_everywhere import get_keyword_data
        from database import save_keyword_cache, get_keyword_cache
        niche_keywords = []
        cached = False

        cached_kws = get_keyword_cache(project_id)
        if cached_kws:
            niche_keywords = cached_kws
            cached = True
            logger.info(f"Using cached keywords: {len(niche_keywords)} keywords")
        else:
            # Generate keywords for chosen niches
            all_keywords = []
            for n in chosen:
                kws = get_keyword_data(n["name"], lang[:2])
                all_keywords.extend(kws)

            # Sort by volume and deduplicate
            seen = set()
            for kw in sorted(all_keywords, key=lambda x: x.get("vol", 0), reverse=True):
                key = kw.get("keyword", "").lower()
                if key and key not in seen:
                    niche_keywords.append(kw)
                    seen.add(key)

            if niche_keywords:
                save_keyword_cache(project_id, niche_keywords)

        # Demand research (trending data)
        demand_data = {}
        demand_summary = ""
        try:
            from protocols.trend_research import research_niche_demand
            niche_name_for_research = chosen[0]["name"] if chosen else project.get("name", "")
            yt_key = ""
            with get_db() as conn:
                yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
                if yt_row:
                    yt_key = yt_row["value"]
            demand_data = research_niche_demand(niche_name_for_research, lang, yt_key)
            demand_summary = demand_data.get("summary", "")
        except Exception as e:
            logger.warning(f"Demand research failed (non-blocking): {e}")

        # YouTube autocomplete suggestions
        autocomplete_suggestions = []
        try:
            from protocols.keywords_everywhere import get_youtube_autocomplete
            for n in chosen[:2]:
                auto = get_youtube_autocomplete(n["name"], lang[:2])
                autocomplete_suggestions.extend(auto[:10])
        except Exception as e:
            logger.warning(f"YouTube autocomplete failed (non-blocking): {e}")

        # Expand keywords with autocomplete volume
        try:
            if autocomplete_suggestions and not cached:
                from protocols.keywords_everywhere import get_keyword_volumes
                auto_terms = [s for s in autocomplete_suggestions if s not in [kw.get("keyword", "") for kw in niche_keywords]]
                if auto_terms:
                    auto_vol = get_keyword_volumes(auto_terms[:20], lang[:2])
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

        # Use admin_ai_model from DB settings (set in admin panel), fallback to env AI_MODEL
        from database import get_setting, set_setting
        from config import AI_MODEL as _default_model
        admin_model = get_setting("admin_ai_model") or _default_model
        logger.info(f"[AI] Using model: {admin_model}")
        response = await asyncio.to_thread(
            chat, user_prompt,
            system_prompt,
            admin_model,  # model from admin panel DB setting
            16000,  # max_tokens — needs room for 35 titles in JSON
            0.85,  # temperature — slightly higher for creativity
            180,  # timeout — large prompt needs more time
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

        # REGENERATION LOOP — if not enough titles (rejected OR AI returned too few)
        if len(accepted) < 28:
            missing = 30 - len(accepted)
            existing_accepted = [a.get("title", "") for a in accepted[:10]]
            existing_list = "\n".join([f'- {t}' for t in existing_accepted])

            regen_prompt = f"""Preciso de mais {missing} titulos para completar 30. Ja tenho {len(accepted)}.

TITULOS JA ACEITOS (NAO REPETIR):
{existing_list}

Gere EXATAMENTE {missing} titulos NOVOS e DIFERENTES.
CADA titulo DEVE:
- Conter keyword de volume: {', '.join(f'"{kw["keyword"]}"' for kw in niche_keywords[:10])}
- Ter POWER WORD em CAPS
- Criar CURIOSITY GAP
- MINIMO 70 caracteres, MAXIMO 100 caracteres
- Seguir o estilo do SOP
- Distribuir entre os sub-nichos: {', '.join([n['name'] for n in chosen])}

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
        from protocols.keywords_everywhere import _strip_accents as _sa
        trending_terms = set()
        for kw in demand_data.get("trending_keywords", []):
            trending_terms.add(_sa(kw.lower()))
        for rs in demand_data.get("rising_searches", []):
            trending_terms.add(_sa(rs.get("query", "").lower()))
        # Also trending titles from YouTube (last 14 days)
        for tt in demand_data.get("trending_titles", []):
            # Extract significant words from viral titles
            words = [w for w in _sa(tt.lower()).split() if len(w) >= 5]
            trending_terms.update(words)

        for idea in new_ideas:
            title_lower = _sa(idea.get("title", "").lower())
            is_trending = 0
            for term in trending_terms:
                if len(term) >= 4 and term in title_lower:
                    is_trending = 1
                    break
            idea["_trending"] = is_trending

        kw_hit_count = sum(1 for idea in new_ideas if idea.get("vol", 0) and idea.get("vol", 0) > 0)

        # Auto-expand short titles (<70 chars) via AI retry
        short_titles = [idea for idea in new_ideas if len(idea.get("title", "")) < 70]
        if short_titles:
            logger.info(f"Expanding {len(short_titles)} short titles (<70 chars)")
            short_list = "\n".join([f'- "{t["title"]}" ({len(t["title"])} chars)' for t in short_titles])
            expand_prompt = f"""Estos {len(short_titles)} titulos de YouTube son DEMASIADO CORTOS (menos de 70 caracteres).
Reescribe CADA UNO para que tenga ENTRE 70 y 100 caracteres, manteniendo el mismo tema y emocion.

TITULOS CORTOS:
{short_list}

REGLAS:
- MINIMO 70 caracteres, MAXIMO 100 caracteres por titulo
- Agrega numeros especificos, open loops, emociones fuertes
- Mantener el mismo tema original

JSON: [{{"original": "titulo original", "expanded": "titulo expandido 70-100 chars"}}]
Solo JSON."""
            try:
                expand_resp = await asyncio.to_thread(
                    chat, expand_prompt,
                    "Expande titulos cortos de YouTube a 70-100 caracteres.",
                    admin_model, 4000, 0.7
                )
                expand_match = re.search(r'\[.*\]', expand_resp, re.DOTALL)
                if expand_match:
                    expansions = json.loads(expand_match.group())
                    expand_map = {e["original"]: e["expanded"] for e in expansions if 70 <= len(e.get("expanded", "")) <= 100}
                    replaced = 0
                    for idea in new_ideas:
                        if idea["title"] in expand_map:
                            idea["title"] = expand_map[idea["title"]]
                            replaced += 1
                    logger.info(f"Expanded {replaced}/{len(short_titles)} short titles")
            except Exception as e:
                logger.warning(f"Title expansion failed (keeping originals): {e}")

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
    except ValueError as e:
        logger.error(f"regenerate-titles config error: {e}")
        return JSONResponse({"error": f"Configuracao: {str(e)}"}, status_code=400)
    except Exception as e:
        error_msg = str(e)[:300] if str(e) else "Erro desconhecido"
        logger.error(f"regenerate-titles error: {e}", exc_info=True)
        # Show real error to admin for debugging (admin-only route)
        return JSONResponse({"error": f"Falha ao re-gerar titulos: {error_msg}"}, status_code=500)


@router.post("/api/admin/regenerate-niches")
@limiter.limit("3/minute")
async def api_regenerate_niches(request: Request, user=Depends(require_admin)):
    """Delete all niches and regenerate 5 based on SOP analysis."""
    body = await request.json()
    project_id = body.get("project_id", "").strip()
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_db, get_project, get_setting, set_setting
    from services import get_project_sop
    from protocols.ai_client import chat
    from config import LANG_LABELS
    import asyncio

    project = get_project(project_id)
    if not project:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    sop = get_project_sop(project_id)
    if not sop:
        return JSONResponse({"error": "SOP nao encontrado para este projeto"}, status_code=400)

    lang = project.get("language", "en")
    lang_label = LANG_LABELS.get(lang, lang)
    niche_name = project.get("niche_chosen", project.get("name", ""))

    try:
        from config import AI_MODEL as _def_model
        admin_model = get_setting("admin_ai_model") or _def_model

        niche_prompt = f"""Voce e um estrategista de canais YouTube com 10 anos de experiencia.
Analise este SOP de um canal e gere 5 sub-nichos derivados OTIMIZADOS para crescimento.

CANAL: "{niche_name}"
IDIOMA DO CANAL: {lang_label}

SOP (DNA do canal):
{sop[:4000]}

REGRAS OBRIGATORIAS:
1. O campo "name" deve ser no IDIOMA ORIGINAL do canal ({lang_label}).
2. O campo "description" deve ser SEMPRE em Portugues Brasileiro (PT-BR), independente do idioma do canal. Descricao de 2-3 frases explicando o sub-nicho, publico-alvo, e potencial de views baseado nos dados do SOP.
3. O campo "recommended" (true/false) — marque como true os 1-2 nichos com MELHOR potencial baseado em: RPM alto + competicao baixa/media + tendencia de crescimento + performance comprovada nos dados do SOP.
4. O campo "recommended_reason" (string PT-BR curta) — explique em 8-12 palavras porque e recomendado (ex: "RPM alto, 1M+ views comprovado, competicao baixa, tendencia subindo").
5. Baseie a analise nos DADOS REAIS do SOP: views dos videos, pilares de conteudo, publico-alvo, formula de titulos.
6. rpm_range no formato "$X-$Y", competition como "Low", "Medium" ou "High".
7. Inclua cores hex variadas para cada nicho.

Retorne APENAS JSON valido: [{{"name":"...","description":"descricao em PT-BR 2-3 frases","rpm_range":"$X-$Y","competition":"Low/Medium/High","color":"#hex","pillars":["pilar1","pilar2","pilar3"],"recommended":false,"recommended_reason":""}}]"""

        response = await asyncio.to_thread(
            chat, niche_prompt,
            "Voce e um analista de canais YouTube especializado em nichos faceless.",
            admin_model,
            3000,
            0.7,
        )

        niche_json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if not niche_json_match:
            return JSONResponse({"error": "IA nao retornou JSON valido"}, status_code=500)

        niche_list = json.loads(niche_json_match.group())
        niche_colors = ["#e040fb", "#448aff", "#ff5252", "#ffd740", "#00e5ff"]

        # Delete old niches
        with get_db() as conn:
            conn.execute("DELETE FROM niches WHERE project_id=?", (project_id,))

        # Save new niches
        from database import save_niche
        generated = 0
        for i, n in enumerate(niche_list[:5]):
            pillars_data = n.get("pillars", [])
            if not isinstance(pillars_data, list):
                pillars_data = []
            if n.get("recommended"):
                pillars_data.append({"__recommended": True, "__reason": n.get("recommended_reason", "")})
            save_niche(
                project_id, n.get("name", f"Nicho {i+1}"), n.get("description", ""),
                n.get("rpm_range", ""), n.get("competition", ""),
                n.get("color", niche_colors[i % 5]), chosen=bool(n.get("recommended")),
                pillars=pillars_data
            )
            generated += 1

        from database import log_activity
        log_activity(project_id, "niches_regenerated", f"{generated} nichos regenerados via AI")

        return JSONResponse({"ok": True, "generated": generated})

    except ValueError as e:
        return JSONResponse({"error": f"Configuracao: {str(e)}"}, status_code=400)
    except Exception as e:
        error_msg = str(e)[:300]
        logger.error(f"regenerate-niches error: {e}", exc_info=True)
        return JSONResponse({"error": f"Falha ao regenerar nichos: {error_msg}"}, status_code=500)
