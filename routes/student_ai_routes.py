"""
Student AI generation routes — script generation, scoring, improvement,
companion assets (SEO/thumbnail/music/teaser) and A/B title-B generation.

Extracted from student_routes.py. Shares _auto_mark_checklist (imported below).
"""

import logging
import re

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth import require_auth
from config import OUTPUT_DIR
from rate_limit import limiter
from routes.student_routes import _auto_mark_checklist

logger = logging.getLogger("ytcloner.routes.student_ai")

router = APIRouter(tags=["student"])


def _get_student_ai_config(user: dict) -> tuple[str, str, str]:
    """Get API key, provider, and model for a student.

    Returns: (api_key, provider, model)
    If use_admin_api is enabled, returns admin's LaoZhang key with claude-sonnet-4-6.
    Otherwise returns the student's own configured key with provider-default model.
    """
    from database import _decrypt_api_key

    # Check if student is allowed to use admin API
    if user.get("use_admin_api"):
        from config import LAOZHANG_API_KEY
        if LAOZHANG_API_KEY:
            # Get admin-configured model from settings
            from database import get_setting
            admin_model = get_setting("admin_ai_model") or "claude-sonnet-4-6"
            return LAOZHANG_API_KEY, "laozhang", admin_model

    # Fall back to student's own key with default models per provider
    api_key = _decrypt_api_key(user.get("api_key_encrypted", ""))
    provider = user.get("api_provider", "")
    default_models = {
        "laozhang": "gpt-4o-mini",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "google": "gemini-2.0-flash",
    }
    model = default_models.get(provider, "gpt-4o-mini")
    return api_key, provider, model


@router.post("/api/student/generate-script")
@limiter.limit("10/minute")
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

    try:
        api_key, provider, ai_model = _get_student_ai_config(user)
        logger.info(f"[SCRIPT-GEN] progress_id={progress_id}, provider={provider}, model={ai_model}, key_len={len(api_key) if api_key else 0}")
        if not api_key or not provider:
            return JSONResponse({"error": "Configure sua API key ou peca ao admin para liberar a API."}, status_code=400)

        title = progress["title"]
        hook = progress.get("hook", "")
        project_id = progress["project_id"]

        # Get project language
        lang = "pt-BR"
        try:
            from database import get_project
            proj = get_project(project_id)
            if proj:
                lang = proj.get("language", "pt-BR")
        except Exception:
            pass

        from config import LANG_LABELS
        lang_label = LANG_LABELS.get(lang, lang)

        # Load SOP — centralized function handles DB + legacy fallback
        from services import get_project_sop
        sop = get_project_sop(project_id)

        # Lookup per-project override for duration/wordcount
        from protocols.ai_client import _SCRIPT_OVERRIDES
        proj_name = (proj.get("name", "") if proj else "").upper().strip()
        override = _SCRIPT_OVERRIDES.get(proj_name, {})
        ov_duration = override.get("duration_minutes", 12)
        ov_min_words = override.get("min_words", 1500)
        ov_max_words = override.get("max_words", 1800)
        ov_max_tokens = override.get("max_tokens", 8000)
        ov_timeout = override.get("timeout", 120)
        ov_forbidden = override.get("forbidden_words", [])

        # Build duration-aware structure
        if ov_duration >= 30:
            structure_rules = f"""6. TAMANHO: {ov_min_words}-{ov_max_words} palavras de narracao ({ov_duration} minutos)
7. ESTRUTURA LONGA OBRIGATORIA:
   - HOOK (0:00-0:30) + HOOK EXPANDIDO (0:30-2:00)
   - CONTEXTO (2:00-5:00) com humanizacao completa
   - ATO 1 (5:00-12:00) MINIMO 5 micro-humilhacoes detalhadas com dialogo
   - ATO 2 (12:00-22:00) planejamento silencioso, advogados, provas
   - ATO 3 (22:00-32:00) armadilha armada, tensao crescente
   - CLIMAX (32:00-42:00) humilhacao PUBLICA (jantar, assembleia, cartorio)
   - RESOLUCAO (42:00-47:00) destruicao financeira
   - REFLEXAO + CTA (47:00-{ov_duration}:00) licao moral fria"""
        else:
            structure_rules = f"6. TAMANHO: {ov_min_words}-{ov_max_words} palavras de narracao"

        # Build forbidden words block
        forbidden_block = ""
        if ov_forbidden:
            forbidden_block = "\n\nPALAVRAS PROIBIDAS (NUNCA use — roteiro sera REJEITADO):\n" + ", ".join(f'"{w}"' for w in ov_forbidden)

        prompt = f"""TITULO DO VIDEO: {title}
HOOK SUGERIDO: {hook}

===== SOP DO CANAL MODELO (REFERENCIA DE SUCESSO) =====
{sop}
===== FIM DO SOP =====

INSTRUCAO CRITICA: Leia o SOP acima com ATENCAO TOTAL. O SOP define:
- O NICHO do canal (Secao 1 — identidade profunda)
- O TOM e VOCABULARIO (Secao 15 — system prompt)
- A ESTRUTURA e REGRAS do roteiro
- As REGRAS inegociaveis (Secao 6 — regras de ouro)

Seu roteiro DEVE estar 100% alinhado com o nicho e estilo do SOP. Se o SOP e sobre poker, o roteiro e sobre poker. Se e sobre crime, e sobre crime. Se e sobre ciencia, e sobre ciencia. NAO invente outro nicho.

FILOSOFIA: Voce NAO esta copiando — voce esta ELEVANDO. Pega o que funciona no SOP e executa MELHOR.

FORMATO DO ROTEIRO (OBRIGATORIO) — ROTEIRO CORRIDO:
Escreva como TEXTO CONTINUO de narracao (voice-over). NAO divida em cenas (Escena 1, Escena 2).
NAO inclua:
- Analise tecnica, scores, ou meta-comentarios
- Listas de tags, keywords, SEO
- Secoes de "Analise de Elevacao", "Frameworks", "Retencao Esperada"
- Headers como "## HOOK DEVASTADOR" (use transicoes naturais)
- Descricoes de estilo visual ou formato

INCLUA:
- Marcacoes inline entre colchetes: [MUSICA: tipo], [SFX: descricao], [B-ROLL: descricao], [PAUSA DRAMATICA]
- Disclaimer de IA no final (lido pelo narrador)
- Transicoes naturais entre atos (sem headers markdown)

REGRAS DO SOP:
1. Escreva como TEXTO CORRIDO (NAO divida em cenas numeradas)
2. APLIQUE as Regras de Ouro da Secao 6 — todas sem excecao
3. USE o vocabulario da Secao 15 — tom, ritmo, formalidade
4. APLIQUE hooks da Secao 4 — escolha um dos frameworks
5. USE open loops da Secao 5 — setup explicito + resolucao tardia
{structure_rules}

LIMITES DO YOUTUBE:
- Titulo: MAXIMO 100 caracteres
- Tags: MAXIMO 500 caracteres no total{forbidden_block}

O objetivo: alguem que conhece o canal original assiste e pensa "esse video e ainda MELHOR que os outros".

Escreva em {lang_label}. Seja EXTREMAMENTE detalhado. LEMBRE-SE: MINIMO {ov_min_words} palavras."""

        system_msg = """Voce e um roteirista de elite para YouTube. Voce recebeu um SOP extraido de um canal real de sucesso como REFERENCIA. Seu trabalho NAO e copiar — e ELEVAR. Voce domina as mesmas tecnicas do canal original mas executa com maestria SUPERIOR. Cada hook mais afiado, cada open loop mais intrigante, cada spike mais intenso. Voce pega o que funciona e entrega uma versao MELHORADA. O resultado e um roteiro que honra o estilo do nicho mas surpreende ate quem conhece o canal original.

REGRAS ABSOLUTAS:
- NUNCA comece com meta-comentarios como 'Claro!', 'Vamos construir', 'Segue o roteiro', 'Aqui esta' etc.
- Comece DIRETAMENTE com a primeira frase do roteiro (narracao do protagonista).
- NUNCA coloque o texto entre aspas — escreva como texto corrido de narracao.
- NAO faca introducoes ou explicacoes sobre o que vai escrever.
- O roteiro DEVE ter o numero de palavras solicitado. Se pediram 7000+ palavras, ESCREVA 7000+ palavras.
- Se o roteiro ficou curto, EXPANDA cada ato com mais dialogos, detalhes de ambiente, e monologos internos."""

        import httpx

        logger.info(f"[SCRIPT-GEN] Calling AI: provider={provider}, model={ai_model}, sop_len={len(sop)}, prompt_len={len(prompt)}")
        script = ""

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=ov_timeout) as client:
                resp = await client.post(api_url, json={
                    "model": ai_model,
                    "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
                    "max_tokens": ov_max_tokens,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    error_msg = data["error"].get("message", "") if isinstance(data["error"], dict) else str(data["error"])
                    logger.error(f"AI API error ({provider}): {error_msg[:500]}")
                    # If max_tokens too high, auto-retry with lower value
                    if "max_tokens" in error_msg.lower() or "too large" in error_msg.lower() or "maximum" in error_msg.lower():
                        logger.warning(f"Retrying with reduced max_tokens: {ov_max_tokens} -> {min(ov_max_tokens, 8000)}")
                        reduced_tokens = min(ov_max_tokens, 8000)
                        resp2 = await client.post(api_url, json={
                            "model": ai_model,
                            "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
                            "max_tokens": reduced_tokens,
                        }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                        data2 = resp2.json()
                        if "error" not in data2:
                            script = data2.get("choices", [{}])[0].get("message", {}).get("content", "")
                        else:
                            return JSONResponse({"error": f"Erro na API ({provider}): {error_msg[:200]}"}, status_code=400)
                    else:
                        return JSONResponse({"error": f"Erro na API ({provider}): {error_msg[:200]}"}, status_code=400)
                script = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=ov_timeout) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": ai_model,
                    "max_tokens": ov_max_tokens,
                    "system": system_msg,
                    "messages": [{"role": "user", "content": prompt}],
                }, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    logger.error(f"Anthropic API error: {data['error']}")
                    return JSONResponse({"error": "Erro na API Anthropic: verifique sua chave API."}, status_code=400)
                content_blocks = data.get("content", [])
                script = content_blocks[0].get("text", "") if content_blocks else ""

        elif provider == "google":
            api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
            async with httpx.AsyncClient(timeout=ov_timeout) as client:
                resp = await client.post(f"{api_url}?key={api_key}", json={
                    "contents": [{"parts": [{"text": prompt}]}],
                })
                data = resp.json()
                if "error" in data:
                    logger.error(f"Google API error: {data['error']}")
                    return JSONResponse({"error": "Erro na API Google: verifique sua chave API."}, status_code=400)
                candidates = data.get("candidates", [])
                script = candidates[0]["content"]["parts"][0]["text"] if candidates else ""
        else:
            return JSONResponse({"error": f"Provider '{provider}' nao suportado"}, status_code=400)

        # Validate AI response is not empty
        if not script or len(script.strip()) < 200:
            logger.error(f"AI returned empty/short script ({len(script) if script else 0} chars) for progress_id={progress_id}")
            return JSONResponse({"error": "IA retornou roteiro vazio ou muito curto. Tente novamente."}, status_code=500)

        # Post-generation: strip meta-commentary prefix
        import re as _fre
        # Remove common AI meta-commentary prefixes
        _meta_patterns = [
            r'^\s*(?:Claro|Certo|Ok|Aqui est[aá]|Vamos|Segue|Com certeza|Perfeito)[!.,]*\s*(?:Vamos\s+)?(?:construir|criar|escrever|elaborar|desenvolver)?[^\n]*\n+',
            r'^\s*"',  # Remove opening quote if AI wrapped in quotes
            r'^\s*(?:Segue o (?:texto|roteiro|script)[^\n]*\n+)',
        ]
        for _mp in _meta_patterns:
            script = _fre.sub(_mp, '', script, count=1, flags=_fre.IGNORECASE)

        # Fix encoding corruption: 'a...s' -> 'apenas', 'a...s ' patterns
        # This happens when the forbidden word cleaner corrupts 'apenas' (contains no forbidden word)
        # or tokenization issues create broken words
        _corruption_fixes = [
            (r'\ba\.\.\.s\b', 'apenas'),
            (r'\ba\.\.\.\s', 'a... '),
        ]
        for _pat, _repl in _corruption_fixes:
            script = _fre.sub(_pat, _repl, script)

        # Post-generation: auto-clean forbidden words (with word boundaries to avoid corrupting 'apenas' etc)
        if ov_forbidden:
            script_lower = script.lower()
            for fw in ov_forbidden:
                if _fre.search(r'\b' + _fre.escape(fw.lower()) + r'\b', script_lower):
                    logger.warning(f"[SCRIPT] Forbidden word '{fw}' detected in student script. Auto-cleaning.")
                    script = _fre.sub(r'\b' + _fre.escape(fw) + r'\b', '...', script, flags=_fre.IGNORECASE)

        # Delete previous script/narration if re-generating
        from database import save_file
        import re as _re
        safe_title = title.replace("/", "-").replace("\\", "-")[:80]
        roteiro_filename = f"roteiro_student_{progress_id}.md"
        narracao_filename = f"narracao_student_{progress_id}.md"

        with get_db() as conn:
            # Delete Drive references FIRST (foreign key constraint)
            for fn in (roteiro_filename, narracao_filename):
                old_file = conn.execute("SELECT id FROM files WHERE filename=? AND project_id=?", (fn, project_id)).fetchone()
                if old_file:
                    conn.execute("DELETE FROM student_drive_files WHERE file_id=?", (old_file["id"],))
            # Now safe to delete the files
            conn.execute("DELETE FROM files WHERE filename=? AND project_id=?", (roteiro_filename, project_id))
            conn.execute("DELETE FROM files WHERE filename=? AND project_id=?", (narracao_filename, project_id))

        # Save new script as file
        save_file(project_id, "roteiro", f"Roteiro - {safe_title}", roteiro_filename, script, visible_to_students=True)

        # Generate clean narration (strip markers like pipeline Step 10)
        narracao = _re.sub(r'\[.*?\]', '', script)  # Remove [MUSICA:], [SFX:], [B-ROLL:] markers
        narracao = _re.sub(r'\n{3,}', '\n\n', narracao).strip()
        if narracao and len(narracao) > 200:
            save_file(project_id, "narracao", f"Narracao - {safe_title}", narracao_filename, narracao, visible_to_students=True)

        # Save to scripts table
        save_script(project_id, title, script, progress["idea_real_id"], "15-20 min")
        mark_progress_script_generated(int(progress_id))

        # Auto-marca roteiro + narracao no checklist de producao
        auto_keys = ["roteiro"]
        if narracao and len(narracao) > 200:
            auto_keys.append("narracao")
        _auto_mark_checklist(int(progress_id), int(user["id"]), *auto_keys)

        # Auto-sync to Google Drive
        try:
            from database import get_student_drive_folder, save_student_drive_file
            drive_folder_id = get_student_drive_folder(user["id"])
            if drive_folder_id:
                from protocols.google_export import find_or_create_subfolder, get_daily_folder, sync_file_to_drive

                # Get DB file IDs we just saved
                with get_db() as conn:
                    script_file_row = conn.execute(
                        "SELECT id FROM files WHERE filename=? AND project_id=? ORDER BY created_at DESC LIMIT 1",
                        (roteiro_filename, project_id)
                    ).fetchone()
                    narr_file_row = conn.execute(
                        "SELECT id FROM files WHERE filename=? AND project_id=? ORDER BY created_at DESC LIMIT 1",
                        (narracao_filename, project_id)
                    ).fetchone()
                script_file_id = script_file_row["id"] if script_file_row else 0
                narr_file_id = narr_file_row["id"] if narr_file_row else 0

                # Find/create channel subfolder
                channel_name = "Canal"
                try:
                    with get_db() as conn:
                        ch_row = conn.execute(
                            "SELECT channel_name FROM student_channels WHERE student_id=? AND active=1 LIMIT 1",
                            (user["id"],)
                        ).fetchone()
                        if ch_row:
                            channel_name = ch_row["channel_name"]
                except Exception:
                    pass
                channel_folder_id = find_or_create_subfolder(channel_name, drive_folder_id)
                daily_folder_id = get_daily_folder(channel_folder_id)

                # Sync script
                script_drive_id = sync_file_to_drive(script, roteiro_filename, f"Roteiro - {safe_title}", daily_folder_id)
                if script_drive_id and script_file_id:
                    save_student_drive_file(user["id"], script_file_id, script_drive_id, daily_folder_id, roteiro_filename, f"Roteiro - {safe_title}", "roteiro")

                # Sync narration
                if narracao and len(narracao) > 200:
                    narr_drive_id = sync_file_to_drive(narracao, narracao_filename, f"Narracao - {safe_title}", daily_folder_id)
                    if narr_drive_id and narr_file_id:
                        save_student_drive_file(user["id"], narr_file_id, narr_drive_id, daily_folder_id, narracao_filename, f"Narracao - {safe_title}", "narracao")

                logger.info(f"[DRIVE-SYNC] Script+narration synced for student {user['id']}")
        except Exception as e:
            logger.warning(f"[DRIVE-SYNC] Failed to sync to Drive (non-blocking): {e}")

        # Count voice-over words only (narration without markers/instructions)
        vo_words = len(narracao.split()) if narracao else len(script.split())
        vo_minutes = round(vo_words / 150, 1)  # 150 wpm for natural narration pace
        return JSONResponse({
            "ok": True,
            "progress_id": progress_id,
            "title": title,
            "words": vo_words,
            "duration_estimate": f"~{vo_minutes} min",
        })
    except ValueError as e:
        logger.error(f"student generate-script config error: {e}")
        return JSONResponse({"error": "Erro de configuracao. Reconfigure sua API key."}, status_code=400)
    except httpx.TimeoutException:
        logger.error(f"student generate-script timeout for progress_id={progress_id}")
        return JSONResponse({"error": "Timeout — a IA demorou muito para responder. Tente novamente."}, status_code=504)
    except httpx.ConnectError:
        logger.error(f"student generate-script connection error")
        return JSONResponse({"error": "Erro de conexao com a API. Verifique sua chave e tente novamente."}, status_code=502)
    except Exception as e:
        err_str = str(e).lower()
        logger.error(f"student generate-script error: {e}", exc_info=True)
        if "api_key" in err_str or "unauthorized" in err_str or "401" in err_str:
            return JSONResponse({"error": "Chave API invalida ou expirada. Reconfigure em Configuracao da API."}, status_code=400)
        if "rate" in err_str or "429" in err_str or "quota" in err_str:
            return JSONResponse({"error": "Limite de requisicoes atingido. Aguarde alguns minutos."}, status_code=429)
        if "model" in err_str or "not found" in err_str:
            return JSONResponse({"error": "Modelo de IA nao encontrado. Peca ao admin para verificar a configuracao."}, status_code=400)
        return JSONResponse({"error": "Falha ao gerar roteiro. Tente novamente."}, status_code=500)


@router.post("/api/student/score-script")
@limiter.limit("10/minute")
async def api_score_script(request: Request, user=Depends(require_auth)):
    """AI evaluates a script against the SOP checklist. Returns score 0-100 + feedback."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db, _decrypt_api_key

    # Get the script file
    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (int(file_id),)).fetchone()
        if not f:
            return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)
        f = dict(f)

        # Verify student has access
        assignment = conn.execute(
            "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
            (user["id"], f["project_id"]),
        ).fetchone()
        if not assignment:
            return JSONResponse({"error": "Sem permissao"}, status_code=403)

        # Get SOP for this project
        sop_row = conn.execute(
            "SELECT content FROM files WHERE project_id=? AND category='analise' ORDER BY created_at LIMIT 1",
            (f["project_id"],),
        ).fetchone()

    script_content = f.get("content", "")
    sop_content = sop_row["content"] if sop_row else ""

    if not script_content or len(script_content) < 200:
        return JSONResponse({"error": "Roteiro muito curto para avaliar"}, status_code=400)
    if not sop_content:
        return JSONResponse({"error": "SOP do projeto nao encontrado"}, status_code=400)

    # Get API key (student's own or admin's if authorized)
    api_key, provider, ai_model = _get_student_ai_config(user)
    if not api_key or not provider:
        return JSONResponse({"error": "Configure sua API key ou peca ao admin para liberar a API."}, status_code=400)

    try:
        judge_prompt = f"""Voce e um JUIZ IMPLACAVEL de roteiros YouTube. Seu trabalho: avaliar o roteiro CONTRA o SOP do canal.
O SOP e o DNA do canal — cada secao define uma regra. Seu Score DEVE refletir o quanto o roteiro segue o SOP.

===== SOP COMPLETO DO CANAL =====
{sop_content}
===== FIM DO SOP =====

===== ROTEIRO A AVALIAR =====
{script_content}
===== FIM DO ROTEIRO =====

AVALIE o roteiro em CADA criterio. Para CADA um, CITE a secao especifica do SOP que embasa sua nota:

1. HOOK (0-10): Segue o Playbook de Hooks da Secao 4 do SOP? Qual dos 8 frameworks usa? O hook prende em 5s?
2. OPEN LOOPS (0-10): Segue as tecnicas da Secao 5? Tem 3+ open loops? Resolucao tardia como o SOP define?
3. STORYTELLING (0-10): Aplica pattern interrupts e specific spikes da Secao 5? Cliffhangers nos pontos certos?
4. TOM DE VOZ (0-10): Bate com o system prompt da Secao 15? Vocabulario, ritmo, formalidade corretos?
5. ESTRUTURA (0-10): Segue o template da Secao 16 com timestamps? Atos claros? Transicoes do SOP?
6. REGRAS DE OURO (0-10): Respeita CADA uma das 15 regras da Secao 6? Liste quais foram quebradas.
7. DURACAO (0-10): Bate com a duracao ideal definida na Secao 2? Conte as palavras de voice-over.
8. ENGAGEMENT (0-10): Tem spikes de retencao como a Secao 12 define? A cada quantos minutos?
9. ORIGINALIDADE (0-10): Traz algo que o canal original NAO explorou? Ou e um clone sem valor adicional?
10. FECHAMENTO (0-10): Segue o modelo de fechamento da Secao 3? CTA natural? Gancho pro proximo?

Responda EXATAMENTE neste formato JSON (sem texto antes ou depois):
{{
  "score": 85,
  "grade": "A",
  "criterios": [
    {{"nome": "Hook", "nota": 9, "feedback": "Hook forte, usa choque como o SOP define. Poderia ser mais especifico com numeros."}},
    {{"nome": "Open Loops", "nota": 8, "feedback": "3 open loops, mas o segundo resolve muito cedo."}},
    {{"nome": "Storytelling", "nota": 9, "feedback": "Pattern interrupts a cada 2 min. Excellent specific spikes."}},
    {{"nome": "Tom de Voz", "nota": 8, "feedback": "Vocabulario correto, mas ritmo desacelera no ato 2."}},
    {{"nome": "Estrutura", "nota": 9, "feedback": "Template seguido. Transicoes fluidas."}},
    {{"nome": "Regras de Ouro", "nota": 8, "feedback": "14/15 regras respeitadas. Regra 7 quebrada levemente."}},
    {{"nome": "Duracao", "nota": 9, "feedback": "~2800 palavras, dentro do padrao."}},
    {{"nome": "Engagement", "nota": 8, "feedback": "Bom ritmo, mas ato 3 tem gap de 4 min sem spike."}},
    {{"nome": "Originalidade", "nota": 9, "feedback": "Angulo unico no climax. Dados novos."}},
    {{"nome": "Fechamento", "nota": 8, "feedback": "Fechamento ciclico. CTA poderia ser mais natural."}}
  ],
  "resumo": "Roteiro solido com hooks fortes e storytelling consistente. Principais pontos de melhoria: resolver open loop 2 mais tarde, adicionar spike no ato 3, e naturalizar o CTA.",
  "aprovado": true,
  "sugestoes": [
    "Mover resolucao do open loop 2 do minuto 6 pro minuto 9",
    "Adicionar specific spike (dado chocante) no ato 3 por volta do minuto 8",
    "Substituir CTA direto por gancho narrativo pro proximo video"
  ]
}}

REGRAS:
- score = media das 10 notas (0-100)
- grade: A (90+), B (80-89), C (70-79), D (60-69), F (<60)
- aprovado = true se score >= 80
- Seja HONESTO e ESPECIFICO. Cite trechos do roteiro. Nao dê nota alta sem justificar.
- sugestoes = 3-5 acoes concretas pra melhorar"""

        system_msg = "Voce e um critico implacavel de roteiros para YouTube. Avalia com precisao cirurgica. Cada ponto de feedback deve ser acionavel e especifico. Nao infle notas — um roteiro mediocre recebe nota mediocre."

        import httpx, json

        result_text = ""

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(api_url, json={
                    "model": ai_model,
                    "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": judge_prompt}],
                    "max_tokens": 4000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    logger.error(f"Score API error: {data['error']}")
                    return JSONResponse({"error": "Erro na API ao avaliar. Verifique sua chave."}, status_code=400)
                result_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": ai_model,
                    "max_tokens": 4000,
                    "system": system_msg,
                    "messages": [{"role": "user", "content": judge_prompt}],
                }, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    logger.error(f"Score Anthropic error: {data['error']}")
                    return JSONResponse({"error": "Erro na API Anthropic ao avaliar."}, status_code=400)
                content_blocks = data.get("content", [])
                result_text = content_blocks[0].get("text", "") if content_blocks else ""

        elif provider == "google":
            api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{api_url}?key={api_key}", json={
                    "contents": [{"parts": [{"text": system_msg + "\n\n" + judge_prompt}]}],
                })
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API Google ao avaliar."}, status_code=400)
                candidates = data.get("candidates", [])
                result_text = candidates[0]["content"]["parts"][0]["text"] if candidates else ""
        else:
            return JSONResponse({"error": f"Provider '{provider}' nao suportado"}, status_code=400)

        if not result_text:
            return JSONResponse({"error": "IA retornou resposta vazia ao avaliar."}, status_code=500)

        # Parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            score_data = json.loads(json_match.group())
        else:
            return JSONResponse({"error": "AI nao retornou formato valido"}, status_code=500)

        # Save score to DB
        with get_db() as conn:
            conn.execute(
                "UPDATE files SET score_json=? WHERE id=?",
                (json.dumps(score_data, ensure_ascii=False), int(file_id)),
            )

        return JSONResponse({"ok": True, "score": score_data})

    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"score-script error: {e}")
        return JSONResponse({"error": "Falha ao avaliar roteiro."}, status_code=500)


@router.post("/api/student/improve-script")
@limiter.limit("5/minute")
async def api_improve_script(request: Request, user=Depends(require_auth)):
    """Rewrite script based on Score feedback — fixes weak points identified by AI Judge."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db, _decrypt_api_key, save_file

    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (int(file_id),)).fetchone()
        if not f:
            return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)
        f = dict(f)

        # Verify student owns this file's project
        if user.get("role") != "admin":
            assignment = conn.execute(
                "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
                (user["id"], f["project_id"]),
            ).fetchone()
            if not assignment:
                return JSONResponse({"error": "Sem permissao"}, status_code=403)

    roteiro = f.get("content", "")
    score_json = f.get("score_json", "")
    if not roteiro or len(roteiro) < 200:
        return JSONResponse({"error": "Roteiro muito curto"}, status_code=400)

    # Parse score feedback
    import json as _json
    score_data = {}
    if score_json:
        try:
            score_data = _json.loads(score_json)
        except Exception:
            pass

    if not score_data:
        return JSONResponse({"error": "Faca o Score primeiro antes de melhorar"}, status_code=400)

    # Build improvement prompt from score feedback
    sugestoes = score_data.get("sugestoes", [])
    criterios = score_data.get("criterios", [])
    all_criteria = sorted(criterios, key=lambda c: c.get("nota", 10))
    weak_points = [c for c in criterios if c.get("nota", 10) < 8]
    strong_points = [c for c in criterios if c.get("nota", 10) >= 8]

    # Build detailed diagnosis
    diagnosis = f"SCORE ATUAL: {score_data.get('score', '?')}/100 — META: 85+\n\n"
    diagnosis += "CRITERIOS QUE PRECISAM MELHORAR (FOCO PRINCIPAL):\n"
    for c in weak_points:
        diagnosis += f"  [{c.get('nota', '?')}/10] {c['nome']}: {c.get('feedback', '')}\n"
    diagnosis += "\nCRITERIOS QUE ESTAO BONS (NAO PIORAR):\n"
    for c in strong_points:
        diagnosis += f"  [{c.get('nota', '?')}/10] {c['nome']}\n"
    if sugestoes:
        diagnosis += "\nACOES ESPECIFICAS DO JUDGE:\n"
        for i, s in enumerate(sugestoes, 1):
            diagnosis += f"  {i}. {s}\n"

    # Load SOP
    from services import get_project_sop
    sop = get_project_sop(f["project_id"])

    api_key, provider, ai_model = _get_student_ai_config(user)
    if not api_key:
        return JSONResponse({"error": "Configure sua API key ou peca ao admin para liberar a API."}, status_code=400)

    prompt = f"""VOCE E UM EDITOR QUE TRANSFORMA ROTEIROS DE SCORE 30-70 EM SCORE 85+.

REGRA #0 (MAIS IMPORTANTE): Leia o SOP PRIMEIRO. O SOP define o NICHO do canal.
Se o SOP e sobre poker, o roteiro TEM QUE SER sobre poker.
Se o SOP e sobre crime, o roteiro TEM QUE SER sobre crime.
Se o roteiro atual esta no NICHO ERRADO (ex: SOP de poker mas roteiro de crypto),
voce DEVE reescrever o roteiro INTEIRO no nicho correto do SOP, mantendo o titulo.

===== SOP COMPLETO DO CANAL (LEIA PRIMEIRO) =====
{sop}
===== FIM DO SOP =====

===== DIAGNOSTICO DO JUDGE (Score: {score_data.get('score', '?')}/100) =====
{diagnosis}
===== FIM DO DIAGNOSTICO =====

===== ROTEIRO ATUAL (PARA REESCREVER) =====
{roteiro}
===== FIM DO ROTEIRO =====

O Judge avalia o roteiro CONTRA o SOP. Cada criterio reflete uma secao do SOP:
- Hook → SOP Secao 4 (Playbook de Hooks — 8 tipos com exemplos)
- Open Loops → SOP Secao 5 (Tecnicas de Storytelling)
- Storytelling → SOP Secao 5 (Pattern interrupts, cliffhangers, spikes)
- Tom de Voz → SOP Secao 15 (System prompt com vocabulario e tom especificos)
- Estrutura → SOP Secao 16 (Template de roteiro com timestamps)
- Regras de Ouro → SOP Secao 6 (15 regras inegociaveis com exemplos)
- Duracao → SOP Secao 2 (Formato e producao — duracao ideal)
- Engagement → SOP Secao 12 (Retencao — spikes a cada 2 min)
- Originalidade → SOP Secao 14 (Evolucao — diferenciais)
- Fechamento → SOP Secao 3 (Anatomia do roteiro — climax e CTA)

INSTRUCOES CIRURGICAS:

1. PARA CADA CRITERIO COM NOTA < 8, RELEIA a secao correspondente do SOP acima e aplique EXATAMENTE o que ela diz:
   - Se Open Loops esta baixo: releia SOP Secao 5, use os MESMOS tipos de open loops listados, com setup explicito e resolucao tardia
   - Se Hook esta baixo: releia SOP Secao 4, escolha UM dos 8 frameworks de hook e aplique com exemplo real
   - Se Tom de Voz esta baixo: releia SOP Secao 15, copie o vocabulario e ritmo descritos, substitua palavras formais
   - Se Regras de Ouro esta baixo: releia SOP Secao 6, verifique CADA uma das 15 regras e corrija violacoes
   - Se Engagement esta baixo: releia SOP Secao 12, adicione spikes nos intervalos que o SOP define
   - Se Fechamento esta baixo: releia SOP Secao 3, aplique o modelo de fechamento descrito
   - Se Duracao esta baixo: releia SOP Secao 2, ajuste para a duracao que o SOP recomenda
   - Se Estrutura esta baixo: releia SOP Secao 16, siga o template EXATO com timestamps
   - Se Originalidade esta baixo: adicione dados, perspectivas ou angulos que o canal original NAO explorou
   - Se Storytelling esta baixo: releia SOP Secao 5, use os pattern interrupts e cliffhangers ESPECIFICOS listados

2. APLIQUE CADA ACAO ESPECIFICA do Judge (listadas no diagnostico) — sem excecao.

3. NAO PIORAR os criterios com nota >= 8 — mantenha essas secoes intactas.

4. Inclua marcacoes [MUSICA:], [SFX:], [B-ROLL:] nos momentos certos.

5. Inclua disclaimer de IA no final.

6. ESCREVA O ROTEIRO COMPLETO — nao resuma, nao pule secoes.

7. A narracao (voice-over puro) deve ter entre 1500-2100 palavras.

FORMATO DE SAIDA (OBRIGATORIO):
Escreva APENAS a narracao que sera lida em voz alta.
NAO inclua analise tecnica, scores, meta-comentarios, listas de tags/keywords,
secoes de "Analise de Elevacao", "Frameworks", "Retencao Esperada" etc.
Inclua marcacoes inline [MUSICA:], [SFX:], [B-ROLL:] nos momentos certos.
Use transicoes naturais entre atos — sem headers markdown (## TITULO)."""

    system_msg = "Voce e um EDITOR SENIOR de roteiros YouTube. Quando o roteiro esta no nicho ERRADO comparado ao SOP, voce REESCREVE no nicho correto. Quando esta no nicho certo mas com problemas, voce faz cirurgia precisa. Voce NUNCA inclui analise, scores, tags ou meta-comentarios no roteiro — apenas narracao pura com marcacoes [MUSICA/SFX/B-ROLL]."

    try:
        import httpx
        script = ""

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(api_url, json={
                    "model": ai_model,
                    "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
                    "max_tokens": 8000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API: verifique sua chave."}, status_code=400)
                script = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": ai_model,
                    "max_tokens": 8000,
                    "system": system_msg,
                    "messages": [{"role": "user", "content": prompt}],
                }, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API Anthropic: verifique sua chave."}, status_code=400)
                content_blocks = data.get("content", [])
                script = content_blocks[0].get("text", "") if content_blocks else ""

        elif provider == "google":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                    json={"contents": [{"parts": [{"text": system_msg + "\n\n" + prompt}]}]},
                )
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API Google: verifique sua chave."}, status_code=400)
                candidates = data.get("candidates", [])
                script = candidates[0]["content"]["parts"][0]["text"] if candidates else ""

        if not script or len(script.strip()) < 200:
            return JSONResponse({"error": "IA retornou roteiro vazio. Tente novamente."}, status_code=500)

        # Delete old file and save improved version
        import re as _re
        with get_db() as conn:
            conn.execute("UPDATE files SET content=?, score_json=NULL WHERE id=?", (script, int(file_id)))

        # Also update narration
        narracao = _re.sub(r'\[.*?\]', '', script)
        narracao = _re.sub(r'\n{3,}', '\n\n', narracao).strip()

        # Find and update narration file
        narracao_filename = f.get("filename", "").replace("roteiro_", "narracao_")
        if narracao and len(narracao) > 200:
            with get_db() as conn:
                existing_narr = conn.execute(
                    "SELECT id FROM files WHERE filename=? AND project_id=?",
                    (narracao_filename, f["project_id"]),
                ).fetchone()
                if existing_narr:
                    conn.execute("UPDATE files SET content=? WHERE id=?", (narracao, existing_narr["id"]))
                else:
                    safe_title = f.get("label", "").replace("Roteiro - ", "")
                    save_file(f["project_id"], "narracao", f"Narracao - {safe_title}",
                             narracao_filename, narracao, visible_to_students=True)

        # Calculate voice-over word count (narration only, no markers)
        vo_words = len(narracao.split()) if narracao else len(script.split())
        vo_minutes = round(vo_words / 150, 1)  # 150 wpm for natural narration

        return JSONResponse({
            "ok": True,
            "words": vo_words,
            "duration_estimate": f"~{vo_minutes} min",
        })

    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"improve-script error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao melhorar roteiro."}, status_code=500)


@router.post("/api/student/generate-companion")
@limiter.limit("10/minute")
async def api_generate_companion(request: Request, user=Depends(require_auth)):
    """Generate companion content (SEO/Thumbnail/Music/Teaser) for a specific roteiro."""
    body = await request.json()
    file_id = body.get("file_id")
    comp_type = body.get("type", "")

    if not file_id or comp_type not in ("seo", "thumbnail", "music", "teaser"):
        return JSONResponse({"error": "file_id e type (seo/thumbnail/music/teaser) obrigatorios"}, status_code=400)

    from database import get_db, _decrypt_api_key, save_file

    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (int(file_id),)).fetchone()
        if not f:
            return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)
        f = dict(f)

        # Get SOP
        sop_row = conn.execute("SELECT content FROM files WHERE project_id=? AND category='analise' LIMIT 1",
                              (f["project_id"],)).fetchone()
        sop = sop_row["content"][:2000] if sop_row else ""

        # Get project info
        proj = conn.execute("SELECT language, niche_chosen, name FROM projects WHERE id=?", (f["project_id"],)).fetchone()
        niche = proj["niche_chosen"] or proj["name"] if proj else "Canal"
        lang = proj["language"] if proj else "pt-BR"

    roteiro = f.get("content", "")
    title = f.get("label", "").replace("Roteiro - ", "").replace("Roteiro — ", "")

    if not roteiro or len(roteiro) < 200:
        return JSONResponse({"error": "Roteiro muito curto"}, status_code=400)

    api_key, provider, ai_model = _get_student_ai_config(user)
    if not api_key:
        return JSONResponse({"error": "Configure sua API key ou peca ao admin para liberar a API."}, status_code=400)

    PROMPTS = {
        "seo": f"""Gere o SEO COMPLETO para publicar este video no YouTube:

TITULO: {title}
ROTEIRO (resumo): {roteiro[:2000]}

REGRAS DO YOUTUBE:
- Titulo: MAX 100 caracteres. Gere 3 variacoes.
- Tags: MAX 500 caracteres no TOTAL. Use 10-12 tags curtas e relevantes.
- Descricao: 150-200 palavras com keywords naturais.
- OBRIGATORIO no final da descricao: "⚠️ Este conteudo foi produzido com auxilio de inteligencia artificial. As narrativas apresentadas sao reconstituicoes ficcionais baseadas em fatos reais e pesquisas, com fins de entretenimento e educacao."
- 5 Hashtags relevantes
- Idioma: {lang}""",

        "thumbnail": f"""Crie prompts de thumbnail para o video "{title}" do canal "{niche}":

ROTEIRO (resumo): {roteiro[:1500]}
SOP (estilo visual): {sop[:500]}

Gere:
1. Prompt Midjourney (estilo cinematografico, dark, impactante)
2. Prompt DALL-E (mesmo conceito adaptado)
3. Paleta de cores (3 hex)
4. Texto overlay sugerido (1-3 palavras MAX)
5. Composicao e layout""",

        "music": f"""Crie prompts de musica/trilha sonora para o video "{title}" do canal "{niche}":

ROTEIRO (resumo): {roteiro[:1500]}

Gere prompts para:
1. Suno AI (com tags de genero, mood, BPM)
2. Udio (descritivo, com referencias)
3. MusicGPT (prompt detalhado)

Para cada momento do video:
- Intro (0-30s): mood de abertura
- Desenvolvimento: tensao crescente
- Climax: pico dramatico
- Fechamento: reflexao/resolucao""",

        "teaser": f"""Crie scripts de Teaser/Shorts para promover o video "{title}" no YouTube Shorts, Reels e TikTok:

ROTEIRO (resumo): {roteiro[:1500]}

Gere 3 versoes de teaser:
1. Hook de 3 segundos (frase que para o scroll)
2. Script completo 30-60 segundos (150-200 palavras)
3. CTA para o video completo
4. 10 Hashtags
5. Formato: vertical 9:16
Idioma: {lang}""",
    }

    prompt = PROMPTS[comp_type]
    system = "Especialista em YouTube. Gere conteudo profissional e acionavel."

    try:
        import httpx
        result = ""

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(api_url, json={
                    "model": ai_model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    "max_tokens": 3000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API: verifique sua chave."}, status_code=400)
                result = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": ai_model,
                    "max_tokens": 3000,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                }, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API Anthropic: verifique sua chave."}, status_code=400)
                content_blocks = data.get("content", [])
                result = content_blocks[0].get("text", "") if content_blocks else ""

        elif provider == "google":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}", json={
                    "contents": [{"parts": [{"text": system + "\n\n" + prompt}]}],
                })
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API Google: verifique sua chave."}, status_code=400)
                candidates = data.get("candidates", [])
                result = candidates[0]["content"]["parts"][0]["text"] if candidates else ""
        else:
            return JSONResponse({"error": f"Provider '{provider}' nao suportado"}, status_code=400)

        if not result or len(result.strip()) < 50:
            return JSONResponse({"error": "IA retornou conteudo vazio. Tente novamente."}, status_code=500)

        # Save as file
        TYPE_LABELS = {"seo": "SEO Pack", "thumbnail": "Thumbnail Prompts", "music": "Music Prompts", "teaser": "Teaser Prompts"}
        TYPE_CATS = {"seo": "seo", "thumbnail": "outros", "music": "outros", "teaser": "outros"}
        comp_filename = f"{comp_type}_{file_id}.md"
        comp_label = f"{TYPE_LABELS[comp_type]} - {title[:40]}"
        save_file(f["project_id"], TYPE_CATS[comp_type],
                 comp_label, comp_filename, result, visible_to_students=True)

        # Auto-marca item correspondente no checklist — extrai progress_id do filename (roteiro_student_{id}.md)
        try:
            import re as _re_ck
            fname = f.get("filename") or ""
            m = _re_ck.search(r"roteiro_student_(\d+)\.md", fname)
            if m:
                ck_key = {"seo": "seo", "thumbnail": "thumb", "music": "musica", "teaser": "teaser"}.get(comp_type)
                if ck_key:
                    _auto_mark_checklist(int(m.group(1)), int(user["id"]), ck_key)
        except Exception:
            pass

        # Auto-sync companion to Google Drive
        try:
            from database import get_student_drive_folder, save_student_drive_file
            drive_folder_id = get_student_drive_folder(user["id"])
            if drive_folder_id:
                from protocols.google_export import find_or_create_subfolder, get_daily_folder, sync_file_to_drive
                # Get the DB file ID of the companion we just saved
                with get_db() as conn:
                    comp_row = conn.execute(
                        "SELECT id FROM files WHERE filename=? AND project_id=? ORDER BY created_at DESC LIMIT 1",
                        (comp_filename, f["project_id"])
                    ).fetchone()
                comp_db_id = comp_row["id"] if comp_row else 0

                channel_name = niche or "Canal"
                channel_folder_id = find_or_create_subfolder(channel_name, drive_folder_id)
                daily_folder_id = get_daily_folder(channel_folder_id)
                comp_drive_id = sync_file_to_drive(result, comp_filename, comp_label, daily_folder_id)
                if comp_drive_id and comp_db_id:
                    save_student_drive_file(user["id"], comp_db_id, comp_drive_id, daily_folder_id, comp_filename, comp_label, comp_type)
                    logger.info(f"[DRIVE-SYNC] Companion {comp_type} synced for student {user['id']}")
        except Exception as e:
            logger.warning(f"[DRIVE-SYNC] Failed to sync companion to Drive (non-blocking): {e}")

        return JSONResponse({"ok": True, "type": comp_type})

    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"generate-companion error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao gerar conteudo complementar."}, status_code=500)


@router.post("/api/student/generate-title-b")
@limiter.limit("10/minute")
async def api_generate_title_b(request: Request, user=Depends(require_auth)):
    """DEPRECATED para alunos — titulos B vem da pesquisa/geracao do admin no pipeline.
    Aluno nao pode mais gerar B sob demanda (evita titulos de baixa qualidade fora do contexto SOP).
    Se a idea nao tem title_b, aluno deve pedir ao admin re-gerar o projeto."""
    return JSONResponse({
        "error": "Titulos B sao gerados pelo admin no pipeline (Passo 4). Se a idea nao tem variante B, peca ao admin re-gerar os titulos do projeto.",
        "code": "student_cannot_regen"
    }, status_code=403)

    # Mantido abaixo para referencia historica (nao executa):
    body = await request.json()
    idea_id = body.get("idea_id")
    if not idea_id:
        return JSONResponse({"error": "idea_id obrigatorio"}, status_code=400)

    from database import get_db, update_idea_title
    with get_db() as conn:
        # Confirma que a idea pertence a uma assignment deste aluno
        row = conn.execute(
            """SELECT i.id, i.title, i.title_b, i.hook, i.summary, i.pillar, p.language, p.niche_chosen, p.name AS proj_name
               FROM ideas i
               JOIN assignments a ON a.project_id = i.project_id
               JOIN projects p ON p.id = i.project_id
               WHERE i.id=? AND a.student_id=?
               LIMIT 1""",
            (int(idea_id), user["id"]),
        ).fetchone()
    if not row:
        return JSONResponse({"error": "Idea nao encontrada ou sem permissao"}, status_code=404)
    idea = dict(row)
    if idea.get("title_b"):
        return JSONResponse({"ok": True, "title_b": idea["title_b"], "already_existed": True})

    try:
        from protocols.ai_client import chat
        lang = idea.get("language") or "pt-BR"
        lang_hint = {"pt-BR": "PT-BR", "en": "English", "es": "Espanol"}.get(lang, lang)
        prompt = f"""Voce recebe o TITULO A de um video YouTube. Gere o TITULO B — mesmo video, mas com ANGULO COMPLETAMENTE DIFERENTE pra teste A/B (regra de 4h).

TITULO A: "{idea['title']}"
HOOK: {idea.get('hook', '')}
RESUMO: {idea.get('summary', '')}
NICHO: {idea.get('niche_chosen') or idea.get('proj_name', '')}

Regras:
- Mesmo conteudo/tema que A — NAO inventar outro video
- Angulo OPOSTO: se A for curiosity-gap, B deve ser numero-especifico; se A for pergunta, B afirmacao; se A for identidade, B contraste
- 70-100 chars (mesmo range do A)
- Idioma: {lang_hint}
- Mesmo formato de CAPS/emoji/pontuacao que A (pra teste justo)

Retorne APENAS o titulo B, sem aspas, sem prefixo, sem markdown."""
        result = chat(prompt, system="Especialista em CTR YouTube. Resposta curta.", max_tokens=120, temperature=0.7).strip()
        # Limpa artefatos comuns
        result = result.strip('"\'`').strip()
        if not result or len(result) < 20:
            return JSONResponse({"error": "IA retornou titulo B invalido"}, status_code=500)
        update_idea_title(int(idea_id), idea["title"], title_b=result)
        return JSONResponse({"ok": True, "title_b": result, "already_existed": False})
    except Exception as e:
        logging.getLogger("ytcloner").error(f"generate-title-b error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao gerar titulo B. Tente novamente."}, status_code=500)
