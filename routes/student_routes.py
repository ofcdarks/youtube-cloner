"""
Student routes — dashboard, progress tracking, script generation, file management.
"""

import logging

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth import require_auth
from config import OUTPUT_DIR
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.student")

router = APIRouter(tags=["student"])


def _render(request, template, ctx=None):
    from dashboard import render
    return render(request, template, ctx)


@router.get("/student", response_class=HTMLResponse)
async def student_dashboard(request: Request, view_as: int = 0, channel: int = 0, user=Depends(require_auth)):
    """Student dashboard with kanban board.
    Admin can view as any student via ?view_as=<student_id>
    Student switches channels via ?channel=<channel_id>
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

    from database import get_assignments, get_student_ideas, get_project, get_db, get_student_channels, count_unread_notifications

    # ── Get all channels and determine active one ──
    channels = get_student_channels(student_id)
    active_channel = None
    if channels:
        if channel:
            active_channel = next((ch for ch in channels if ch["id"] == channel), channels[0])
        else:
            active_channel = channels[0]

    # ── Build kanban — filter by active channel's project ──
    assignments = get_assignments(student_id)
    all_ideas = []
    project_ids = set()
    active_assignment = None

    for a in assignments:
        if a.get("project_id"):
            project_ids.add(a["project_id"])

    # Match active channel to assignment
    if active_channel:
        ch_project_id = active_channel.get("project_id", "")

        # 1. Direct match by project_id (best)
        if ch_project_id:
            for a in assignments:
                if a.get("project_id") == ch_project_id:
                    active_assignment = a
                    break

        # 2. Fallback: match by niche name
        if not active_assignment:
            ch_niche = (active_channel.get("niche") or "").strip().lower()
            for a in assignments:
                a_niche = (a.get("niche") or "").strip().lower()
                if ch_niche and a_niche and (ch_niche == a_niche or ch_niche in a_niche or a_niche in ch_niche):
                    active_assignment = a
                    # Auto-link channel to project for next time
                    if a.get("project_id") and not ch_project_id:
                        try:
                            with get_db() as conn:
                                conn.execute("UPDATE student_channels SET project_id=? WHERE id=?",
                                           (a["project_id"], active_channel["id"]))
                        except Exception:
                            pass
                    break

    # 3. NO fallback to other projects — if no match, this channel has no project
    if not active_assignment:
        # Channel has no project assigned — show empty state
        pass

    # Filter to active assignment only
    active_project_id = active_assignment.get("project_id", "") if active_assignment else ""
    active_project_ids = {active_project_id} if active_project_id else set()

    # Build kanban for active project only
    kanban = {"pending": [], "writing": [], "recording": [], "editing": [], "published": []}
    if active_assignment:
        ideas = get_student_ideas(active_assignment["id"])
        for idea in ideas:
            idea["niche"] = active_assignment.get("niche", "")
            idea["assignment_id"] = active_assignment["id"]
            idea["project_id"] = active_assignment.get("project_id", "")
            status = idea.get("status", "pending")
            if status in kanban:
                kanban[status].append(idea)
            all_ideas.append(idea)

    # Also collect all project_ids for global queries
    for a in assignments:
        if a.get("project_id"):
            project_ids.add(a["project_id"])

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

    # ── Student's files (proper DB-based access control) ──
    student_categories = {}

    # Get all files from projects this student is assigned to
    if active_project_ids:
        try:
            with get_db() as conn:
                placeholders = ",".join("?" * len(active_project_ids))
                pid_list = list(active_project_ids)

                # 1. Shared project files (only those marked visible by admin)
                shared_files = conn.execute(f"""
                    SELECT f.id, f.category, f.label, f.filename, f.project_id, LENGTH(f.content) as content_len
                    FROM files f
                    WHERE f.project_id IN ({placeholders})
                    AND f.category IN ('analise', 'seo', 'outros', 'visual')
                    AND f.visible_to_students = 1
                    ORDER BY f.category, f.created_at
                """, pid_list).fetchall()

                # 2. Roteiros/narracoes — any visible ones from assigned projects
                student_files = conn.execute(f"""
                    SELECT f.id, f.category, f.label, f.filename, f.project_id, LENGTH(f.content) as content_len
                    FROM files f
                    WHERE f.project_id IN ({placeholders})
                    AND f.category IN ('roteiro', 'narracao')
                    AND f.visible_to_students = 1
                    ORDER BY f.created_at
                """, pid_list).fetchall()

                # 3. Filesystem roteiros generated by student
                fs_roteiros = []
                for fpath in sorted(OUTPUT_DIR.glob(f"roteiro_student_{student_id}_*.md")):
                    fs_roteiros.append({
                        "id": 0,
                        "name": fpath.name,
                        "path": fpath.name,
                        "size": fpath.stat().st_size,
                        "label": fpath.stem.replace(f"roteiro_student_{student_id}_", "Roteiro - ").replace("_", " ").title(),
                    })

                # Build categories
                cat_config = {
                    "analise": {"label": "Analise / SOP", "icon": "&#128200;", "color": "#7c3aed"},
                    "seo": {"label": "SEO Pack", "icon": "&#128269;", "color": "#06b6d4"},
                    "outros": {"label": "Prompts (Thumb/Music/Teaser)", "icon": "&#127912;", "color": "#f59e0b"},
                    "visual": {"label": "Mind Map", "icon": "&#128506;", "color": "#22c55e"},
                    "roteiro": {"label": "Meus Roteiros", "icon": "&#128221;", "color": "#eab308"},
                    "narracao": {"label": "Minhas Narracoes", "icon": "&#127908;", "color": "#ec4899"},
                }

                seen_filenames = set()
                for row in list(shared_files) + list(student_files):
                    row = dict(row)
                    cat = row["category"]
                    fname = row["filename"] or ""
                    if fname in seen_filenames:
                        continue
                    seen_filenames.add(fname)

                    if cat not in student_categories:
                        cfg = cat_config.get(cat, {"label": cat.title(), "icon": "&#128196;", "color": "#71717a"})
                        student_categories[cat] = {**cfg, "files": []}

                    fpath = OUTPUT_DIR / fname
                    content_len = row.get("content_len", 0) or 0
                    # For roteiros: estimate voice-over words (content has markers ~15% overhead)
                    if cat == "roteiro":
                        word_count = round(content_len / 7) if content_len > 0 else 0  # roteiro has markers
                    elif cat == "narracao":
                        word_count = round(content_len / 5.5) if content_len > 0 else 0  # clean text
                    else:
                        word_count = round(content_len / 6) if content_len > 0 else 0
                    duration_min = round(word_count / 150) if word_count > 0 else 0  # 150 wpm natural narration

                    student_categories[cat]["files"].append({
                        "id": row["id"],
                        "name": fname,
                        "path": fname,
                        "size": fpath.stat().st_size if fpath.exists() else content_len,
                        "label": row["label"],
                        "words": word_count,
                        "duration": f"{duration_min}-{duration_min+2} min" if duration_min > 0 else "",
                    })

                # Add filesystem roteiros
                if fs_roteiros:
                    if "roteiro" not in student_categories:
                        cfg = cat_config["roteiro"]
                        student_categories["roteiro"] = {**cfg, "files": []}
                    for fr in fs_roteiros:
                        if fr["name"] not in seen_filenames:
                            student_categories["roteiro"]["files"].append(fr)

        except Exception as e:
            logger.error(f"Student files error: {e}")

    # ── Project info (active channel's project) ──
    current_project = None
    if active_project_id:
        proj = get_project(active_project_id)
        if proj:
            current_project = {
                "id": proj["id"],
                "name": proj["name"],
                "niche": proj.get("niche_chosen", ""),
                "channel_original": proj.get("channel_original", ""),
                "language": proj.get("language", "pt-BR"),
            }

    # ── Schedule from SOP ──
    schedule_info = {
        "frequency": "Diaria (1a semana)",
        "best_days": "Aguardando dados do Analytics",
        "best_times": "nao definido",
        "video_duration": "12-19 minutos",
        "language": "pt-BR",
    }
    if active_project_ids:
        try:
            pid = list(active_project_ids)[0]
            with get_db() as conn:
                proj_row = conn.execute("SELECT language, niche_chosen, name FROM projects WHERE id=?", (pid,)).fetchone()
                if proj_row:
                    schedule_info["language"] = proj_row["language"] or "pt-BR"
                    proj_niche = proj_row["niche_chosen"] or proj_row["name"] or ""

                # Check cache first
                cache_key = f"schedule_{pid}"
                cached = conn.execute("SELECT value FROM admin_settings WHERE key=?", (cache_key,)).fetchone()
                if cached and cached["value"]:
                    try:
                        import json as _json
                        cached_data = _json.loads(cached["value"])
                        for k in ["best_times", "video_duration"]:
                            if k in cached_data and cached_data[k] and cached_data[k] != "nao definido":
                                schedule_info[k] = cached_data[k]
                    except Exception:
                        pass
                # PERFORMANCE: Don't call AI on GET — use defaults.
                # Schedule info is populated lazily via /api/student/update-calendar endpoint.
        except Exception:
            pass

    # ── Assignment schedule (admin-defined) ──
    for a in assignments:
        try:
            import json as _j
            sched = _j.loads(a.get("schedule", "{}") or "{}")
            if sched:
                a["schedule_parsed"] = sched
        except Exception:
            a["schedule_parsed"] = {}

    # ── Trend Radar files for student view ──
    trend_files = []
    if active_project_ids:
        try:
            with get_db() as conn:
                pid = list(active_project_ids)[0]
                trend_rows = conn.execute(
                    "SELECT id, filename, content, created_at FROM files WHERE project_id=? AND (filename LIKE '%trend%' OR filename LIKE '%radar%') AND visible_to_students=1 ORDER BY created_at DESC LIMIT 3",
                    (pid,)
                ).fetchall()
                for tr in trend_rows:
                    trend_files.append(dict(tr))
        except Exception:
            pass

    # Check if YouTube API key is configured
    has_yt_key = False
    try:
        with get_db() as conn:
            yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
            has_yt_key = bool(yt_row and yt_row["value"])
    except Exception:
        pass

    return _render(request, "student_dashboard.html", {
        "user": target_user,
        "real_user": user,
        "assignments": assignments,
        "kanban": kanban,
        "active_channel": active_channel,
        "stats": stats,
        "api_provider": api_provider,
        "has_api_key": has_api_key,
        "categories": student_categories,
        "current_project": current_project,
        "impersonating": impersonating,
        "readonly": impersonating,
        "channels": channels,
        "schedule": schedule_info,
        "unread_notifs": count_unread_notifications(target_user["id"]) if not impersonating else 0,
        "trend_files": trend_files,
        "has_yt_key": has_yt_key,
    })


@router.post("/api/student/update-progress")
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

    # SECURITY: Verify ownership — prevent IDOR (any student updating any other student's progress)
    from database import get_db, update_progress
    if user.get("role") != "admin":
        with get_db() as conn:
            owned = conn.execute(
                "SELECT id FROM progress WHERE id = ? AND student_id = ?",
                (int(progress_id), user["id"]),
            ).fetchone()
            if not owned:
                return JSONResponse({"error": "Sem permissao"}, status_code=403)

    update_progress(int(progress_id), status, video_url, notes)
    return JSONResponse({"ok": True})


@router.post("/api/student/update-api-key")
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

    api_key = _decrypt_api_key(user.get("api_key_encrypted", ""))
    provider = user.get("api_provider", "")
    if not api_key or not provider:
        return JSONResponse({"error": "Configure sua API key primeiro"}, status_code=400)

    try:
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

        # The SOP contains a complete replication manual (17 sections) including:
        # - Section 15: System prompt for AI to generate identical scripts
        # - Section 16: Template with exact timestamps
        # - Section 17: Quality checklist
        # We feed the FULL SOP as context so the AI follows every pattern but ELEVATES

        prompt = f"""TITULO DO VIDEO: {title}
HOOK SUGERIDO: {hook}

===== SOP DO CANAL MODELO (REFERENCIA DE SUCESSO) =====
{sop}
===== FIM DO SOP =====

INSTRUCAO: Usando o SOP acima como REFERENCIA DE EXCELENCIA, escreva um roteiro COMPLETO para o video "{title}" que SUPERE o canal original.

FILOSOFIA: Voce NAO esta copiando — voce esta ELEVANDO. O SOP mostra o que funciona. Seu trabalho e pegar cada tecnica e executar MELHOR:
- Hooks mais impactantes que os exemplos do SOP
- Open loops mais intrigantes
- Storytelling mais envolvente
- Specific spikes mais intensos
- Transicoes mais fluidas
- Fechamento mais memoravel

REGRAS:
1. USE a estrutura e tecnicas da secao 3 e 5 do SOP como BASE, mas MELHORE a execucao
2. APLIQUE as Regras de Ouro da secao 6 — essas sao inegociaveis
3. USE o vocabulario e tom do nicho (secao 15) mas com VOZ PROPRIA — nao seja um clone, seja a EVOLUCAO
4. SIGA o Template da secao 16 como esqueleto, adaptando os tempos ao conteudo
5. Cada hook, open loop e spike deve ser ORIGINAL e mais poderoso que os exemplos do SOP
6. Inclua marcacoes: [MUSICA: tipo], [SFX: descricao], [B-ROLL: descricao]
7. O roteiro deve passar no Checklist da secao 17 com NOTA MAXIMA
8. DIFERENCIAL: adicione insights, dados ou angulos que o canal original NAO explorou
9. OBRIGATORIO: Inclua no FINAL do roteiro (apos o fechamento) um disclaimer lido pelo narrador:
   "Este conteudo foi produzido com auxilio de inteligencia artificial. As narrativas apresentadas sao reconstituicoes ficcionais baseadas em fatos reais e pesquisas, com fins de entretenimento e educacao."

LIMITES DO YOUTUBE:
- Titulo: MAXIMO 100 caracteres
- Tags: MAXIMO 500 caracteres no total

O objetivo: alguem que conhece o canal original assiste e pensa "esse video e ainda MELHOR que os outros".

Escreva em {lang_label}. Seja EXTREMAMENTE detalhado."""

        system_msg = "Voce e um roteirista de elite para YouTube. Voce recebeu um SOP extraido de um canal real de sucesso como REFERENCIA. Seu trabalho NAO e copiar — e ELEVAR. Voce domina as mesmas tecnicas do canal original mas executa com maestria SUPERIOR. Cada hook mais afiado, cada open loop mais intrigante, cada spike mais intenso. Voce pega o que funciona e entrega uma versao MELHORADA. O resultado e um roteiro que honra o estilo do nicho mas surpreende ate quem conhece o canal original."

        import httpx

        script = ""

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post(api_url, json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
                    "max_tokens": 8000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    error_msg = data["error"].get("message", "") if isinstance(data["error"], dict) else str(data["error"])
                    logger.error(f"AI API error ({provider}): {error_msg[:200]}")
                    return JSONResponse({"error": f"Erro na API ({provider}): verifique sua chave API."}, status_code=400)
                script = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 8000,
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
            api_url = "https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent"
            async with httpx.AsyncClient(timeout=240) as client:
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

        # Delete previous script/narration if re-generating
        from database import save_file
        import re as _re
        safe_title = title.replace("/", "-").replace("\\", "-")[:80]
        roteiro_filename = f"roteiro_student_{progress_id}.md"
        narracao_filename = f"narracao_student_{progress_id}.md"

        with get_db() as conn:
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
    except Exception as e:
        logger.error(f"student generate-script error: {e}")
        return JSONResponse({"error": "Falha ao gerar roteiro"}, status_code=500)


@router.post("/api/student/delete-file")
@limiter.limit("20/minute")
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

        # Shared project files cannot be deleted by students
        if f["category"] in ("analise", "seo", "outros", "visual"):
            if user.get("role") != "admin":
                return JSONResponse({"error": "Apenas admin pode excluir arquivos compartilhados"}, status_code=403)

        if user.get("role") != "admin":
            # Student must have an assignment for this project
            assignment = conn.execute(
                "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
                (user["id"], f["project_id"]),
            ).fetchone()
            if not assignment:
                return JSONResponse({"error": "Sem permissao"}, status_code=403)

            # Student can only delete roteiro/narracao files
            if f["category"] not in ("roteiro", "narracao"):
                return JSONResponse({"error": "Sem permissao para excluir este tipo de arquivo"}, status_code=403)

    deleted = db_delete_file(int(file_id))
    if deleted and deleted.get("filename"):
        fpath = OUTPUT_DIR / deleted["filename"]
        if fpath.exists():
            fpath.unlink()

    return JSONResponse({"ok": True})


# ── Student Channels ─────────────────────────────────────

@router.get("/api/student/channels")
async def api_student_channels(request: Request, user=Depends(require_auth)):
    from database import get_student_channels
    channels = get_student_channels(user["id"])
    return JSONResponse({"ok": True, "channels": channels})


@router.post("/api/student/add-channel")
@limiter.limit("10/minute")
async def api_student_add_channel(request: Request, user=Depends(require_auth)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    niche = (body.get("niche") or "").strip()
    language = (body.get("language") or "pt-BR").strip()

    if not name or len(name) < 2:
        return JSONResponse({"error": "Nome do canal obrigatorio (min 2 chars)"}, status_code=400)

    from database import create_student_channel
    try:
        cid = create_student_channel(user["id"], name, url, niche, language)
        return JSONResponse({"ok": True, "channel_id": cid})
    except ValueError:
        return JSONResponse({"error": "Maximo de 5 canais atingido."}, status_code=400)


@router.post("/api/student/remove-channel")
@limiter.limit("10/minute")
async def api_student_remove_channel(request: Request, user=Depends(require_auth)):
    body = await request.json()
    channel_id = body.get("channel_id")
    if not channel_id:
        return JSONResponse({"error": "channel_id obrigatorio"}, status_code=400)
    from database import delete_student_channel
    delete_student_channel(int(channel_id), user["id"])
    return JSONResponse({"ok": True})


# ── Student Drive Sync ───────────────────────────────────

@router.post("/api/student/sync-to-drive")
@limiter.limit("5/minute")
async def api_student_sync_to_drive(request: Request, user=Depends(require_auth)):
    """Sync a student-generated file to their personal Drive folder."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db, get_student_drive_folder, set_student_drive_folder, save_student_drive_file

    # Get the file
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

    try:
        from protocols.google_export import create_folder, create_doc

        # Get or create student's Drive folder
        folder_id = get_student_drive_folder(user["id"])
        if not folder_id:
            folder_id = create_folder(f"YT Cloner - {user['name']}")
            set_student_drive_folder(user["id"], folder_id)

        # Upload file
        content = f.get("content", "") or ""
        if not content or len(content) < 50:
            return JSONResponse({"error": "Arquivo sem conteudo"}, status_code=400)

        label = f.get("label", f.get("filename", ""))
        drive_file_id = create_doc(label, content, folder_id)

        # Track in DB
        save_student_drive_file(user["id"], int(file_id), drive_file_id, folder_id,
                               f.get("filename", ""), label, f.get("category", ""))

        return JSONResponse({"ok": True, "drive_file_id": drive_file_id})
    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"student sync-to-drive error: {e}")
        return JSONResponse({"error": "Falha ao sincronizar com Google Drive."}, status_code=500)


# ── Notifications ────────────────────────────────────────

@router.get("/api/student/notifications")
async def api_student_notifications(request: Request, user=Depends(require_auth)):
    from database import get_notifications, count_unread_notifications
    notifs = get_notifications(user["id"], limit=20)
    unread = count_unread_notifications(user["id"])
    return JSONResponse({"ok": True, "notifications": notifs, "unread": unread})


@router.post("/api/student/mark-notification-read")
@limiter.limit("30/minute")
async def api_mark_notification_read(request: Request, user=Depends(require_auth)):
    body = await request.json()
    nid = body.get("notification_id")
    if nid == "all":
        from database import mark_all_notifications_read
        mark_all_notifications_read(user["id"])
    elif nid:
        from database import mark_notification_read
        mark_notification_read(int(nid), user["id"])
    return JSONResponse({"ok": True})


# ── AI Script Judge ──────────────────────────────────────

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

    # Get student API key
    api_key = _decrypt_api_key(user.get("api_key_encrypted", ""))
    provider = user.get("api_provider", "")
    if not api_key or not provider:
        return JSONResponse({"error": "Configure sua API key primeiro"}, status_code=400)

    try:
        judge_prompt = f"""Voce e um JUIZ DE QUALIDADE de roteiros para YouTube. Avalie o roteiro abaixo contra o SOP do canal.

===== SOP DO CANAL (REFERENCIA DE EXCELENCIA) =====
{sop_content[:8000]}
===== FIM DO SOP =====

===== ROTEIRO A AVALIAR =====
{script_content[:10000]}
===== FIM DO ROTEIRO =====

AVALIE o roteiro em CADA criterio abaixo com nota 0-10 e feedback ESPECIFICO:

1. HOOK (0-10): O hook prende nos primeiros 5 segundos? Segue o playbook do SOP?
2. OPEN LOOPS (0-10): Tem 3+ open loops bem construidos? Sao resolvidos no momento certo?
3. STORYTELLING (0-10): Usa pattern interrupts, cliffhangers, specific spikes como o SOP define?
4. TOM DE VOZ (0-10): Vocabulario, ritmo e formalidade batem com a secao 15 do SOP?
5. ESTRUTURA (0-10): Segue o template da secao 16? Atos bem definidos? Transicoes fluidas?
6. REGRAS DE OURO (0-10): Respeita todas as regras da secao 6? Alguma foi quebrada?
7. DURACAO (0-10): Tamanho adequado ao padrao do canal? Nem curto nem longo demais?
8. ENGAGEMENT (0-10): Mantem atencao do inicio ao fim? Tem spikes a cada 2-3 min?
9. ORIGINALIDADE (0-10): Traz insights/angulos novos ou so copia o padrao?
10. FECHAMENTO (0-10): Encerra no estilo do SOP? CTA natural? Gancho pro proximo video?

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

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(api_url, json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": judge_prompt}],
                    "max_tokens": 3000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                result_text = data["choices"][0]["message"]["content"]

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 3000,
                    "system": system_msg,
                    "messages": [{"role": "user", "content": judge_prompt}],
                }, headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
                data = resp.json()
                result_text = data["content"][0]["text"]

        elif provider == "google":
            api_url = "https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{api_url}?key={api_key}", json={
                    "contents": [{"parts": [{"text": system_msg + "\n\n" + judge_prompt}]}],
                })
                data = resp.json()
                result_text = data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return JSONResponse({"error": f"Provider '{provider}' nao suportado"}, status_code=400)

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


# ── Improve Script based on Score ──────────────────────

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
    weak_points = [c for c in criterios if c.get("nota", 10) < 7]

    feedback_text = ""
    if weak_points:
        feedback_text += "PONTOS FRACOS (nota < 7):\n"
        for c in weak_points:
            feedback_text += f"- {c['nome']}: {c.get('nota', '?')}/10 — {c.get('feedback', '')}\n"
    if sugestoes:
        feedback_text += "\nSUGESTOES DE MELHORIA:\n"
        for s in sugestoes:
            feedback_text += f"- {s}\n"

    # Load SOP
    from services import get_project_sop
    sop = get_project_sop(f["project_id"])

    api_key = _decrypt_api_key(user.get("api_key_encrypted", ""))
    provider = user.get("api_provider", "")
    if not api_key:
        return JSONResponse({"error": "Configure sua API key"}, status_code=400)

    prompt = f"""ROTEIRO ORIGINAL:
{roteiro}

===== AVALIACAO DO JUDGE (Score: {score_data.get('score', '?')}/100) =====
{feedback_text}
===== FIM DA AVALIACAO =====

SOP DO CANAL (referencia):
{sop[:4000]}

INSTRUCAO: Reescreva o roteiro COMPLETO corrigindo TODOS os pontos fracos listados acima.
- Mantenha o que ja funciona bem (pontos com nota >= 8)
- MELHORE drasticamente os pontos com nota < 7
- Aplique TODAS as sugestoes de melhoria do Judge
- O resultado deve ter Score 85+ se avaliado novamente
- Mantenha a mesma estrutura (hook, atos, climax, fechamento)
- Inclua marcacoes [MUSICA:], [SFX:], [B-ROLL:] nos momentos certos
- A narracao (voice-over) deve ter entre 1500-2000 palavras (10-14 minutos)
- Inclua disclaimer de IA no final"""

    system_msg = "Voce e um roteirista de elite. Recebeu um roteiro com avaliacao detalhada. Sua missao: reescrever MELHORANDO os pontos fracos sem perder os pontos fortes."

    try:
        import httpx
        script = ""

        if provider in ("laozhang", "openai"):
            api_url = "https://api.laozhang.ai/v1/chat/completions" if provider == "laozhang" else "https://api.openai.com/v1/chat/completions"
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post(api_url, json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
                    "max_tokens": 8000,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
                data = resp.json()
                if "error" in data:
                    return JSONResponse({"error": "Erro na API: verifique sua chave."}, status_code=400)
                script = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", json={
                    "model": "claude-sonnet-4-20250514",
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
            async with httpx.AsyncClient(timeout=240) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={api_key}",
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


# ── YouTube Analytics Feedback Loop ──────────────────────

@router.post("/api/student/fetch-channel-stats")
@limiter.limit("5/minute")
async def api_fetch_channel_stats(request: Request, user=Depends(require_auth)):
    """Fetch YouTube channel stats and recent videos using student's API key."""
    body = await request.json()
    channel_url = (body.get("channel_url") or "").strip()
    channel_db_id = body.get("channel_id", 0)

    from database import _decrypt_api_key, get_db

    # Get student's YouTube API key
    with get_db() as conn:
        student = conn.execute("SELECT api_key_encrypted, api_provider FROM users WHERE id=?", (user["id"],)).fetchone()

    if not student:
        return JSONResponse({"error": "Usuario nao encontrado"}, status_code=404)

    # Try dedicated YouTube key first, then general key
    yt_api_key = ""
    try:
        with get_db() as conn:
            # Check if student has a youtube_data key stored
            yt_row = conn.execute("SELECT value FROM admin_settings WHERE key=?", ("youtube_api_key",)).fetchone()
            if yt_row:
                yt_api_key = yt_row["value"]
    except Exception:
        pass

    if not yt_api_key:
        return JSONResponse({"error": "YouTube API Key nao configurada. Peca ao admin para configurar."}, status_code=400)

    # Resolve channel URL to channel ID
    import httpx, re

    channel_id = ""
    if "youtube.com/@" in channel_url:
        handle = channel_url.split("/@")[-1].split("/")[0].split("?")[0]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "id,statistics,snippet", "forHandle": handle, "key": yt_api_key})
                data = resp.json()
                if data.get("items"):
                    channel_id = data["items"][0]["id"]
        except Exception:
            pass
    elif "youtube.com/channel/" in channel_url:
        channel_id = channel_url.split("/channel/")[-1].split("/")[0].split("?")[0]

    if not channel_id:
        # Try as direct channel ID
        channel_id = channel_url.strip()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get channel stats
            ch_resp = await client.get("https://www.googleapis.com/youtube/v3/channels",
                params={"part": "statistics,snippet,contentDetails", "id": channel_id, "key": yt_api_key})
            ch_data = ch_resp.json()

            if not ch_data.get("items"):
                return JSONResponse({"error": "Canal nao encontrado"}, status_code=404)

            channel = ch_data["items"][0]
            stats = channel.get("statistics", {})
            snippet = channel.get("snippet", {})

            # Get recent videos
            uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
            videos = []

            if uploads_playlist:
                pl_resp = await client.get("https://www.googleapis.com/youtube/v3/playlistItems",
                    params={"part": "snippet", "playlistId": uploads_playlist, "maxResults": 15, "key": yt_api_key})
                pl_data = pl_resp.json()

                video_ids = [item["snippet"]["resourceId"]["videoId"]
                            for item in pl_data.get("items", []) if item.get("snippet", {}).get("resourceId", {}).get("videoId")]

                if video_ids:
                    vid_resp = await client.get("https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "statistics,snippet,contentDetails", "id": ",".join(video_ids[:15]), "key": yt_api_key})
                    vid_data = vid_resp.json()

                    from database import upsert_video_performance

                    for v in vid_data.get("items", []):
                        v_stats = v.get("statistics", {})
                        v_snippet = v.get("snippet", {})
                        v_content = v.get("contentDetails", {})

                        vid_info = {
                            "video_id": v["id"],
                            "title": v_snippet.get("title", ""),
                            "published_at": v_snippet.get("publishedAt", "")[:10],
                            "views": int(v_stats.get("viewCount", 0)),
                            "likes": int(v_stats.get("likeCount", 0)),
                            "comments": int(v_stats.get("commentCount", 0)),
                            "duration": v_content.get("duration", ""),
                            "thumbnail": v_snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                        }
                        videos.append(vid_info)

                        # Save to DB
                        upsert_video_performance(
                            student_id=user["id"], video_id=v["id"], channel_id=int(channel_db_id),
                            title=vid_info["title"], published_at=vid_info["published_at"],
                            views=vid_info["views"], likes=vid_info["likes"], comments=vid_info["comments"],
                            duration=vid_info["duration"], thumbnail_url=vid_info["thumbnail"],
                        )

            # Calculate insights
            total_views = sum(v["views"] for v in videos)
            avg_views = round(total_views / len(videos)) if videos else 0
            best_video = max(videos, key=lambda x: x["views"]) if videos else None
            engagement_rates = []
            for v in videos:
                if v["views"] > 0:
                    eng = round((v["likes"] + v["comments"]) / v["views"] * 100, 2)
                    engagement_rates.append(eng)
            avg_engagement = round(sum(engagement_rates) / len(engagement_rates), 2) if engagement_rates else 0

            response_data = {
                "ok": True,
                "channel": {
                    "name": snippet.get("title", ""),
                    "subscribers": int(stats.get("subscriberCount", 0)),
                    "total_views": int(stats.get("viewCount", 0)),
                    "total_videos": int(stats.get("videoCount", 0)),
                    "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                },
                "videos": videos[:15],
                "insights": {
                    "avg_views": avg_views,
                    "avg_engagement": avg_engagement,
                    "best_video": best_video,
                    "total_recent_views": total_views,
                },
            }

            # Cache to DB for persistence
            try:
                import json as _json
                with get_db() as conn:
                    conn.execute("UPDATE student_channels SET cached_stats=? WHERE id=?",
                                (_json.dumps(response_data, ensure_ascii=False), int(channel_db_id)))
            except Exception:
                pass

            return JSONResponse(response_data)

    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"fetch-channel-stats error: {e}")
        return JSONResponse({"error": "Falha ao buscar dados do canal."}, status_code=500)


@router.get("/api/student/performance-summary")
async def api_performance_summary(request: Request, user=Depends(require_auth)):
    """Get aggregated performance data for the student."""
    from database import get_performance_summary, get_video_performance
    summary = get_performance_summary(user["id"])
    videos = get_video_performance(user["id"], limit=15)
    return JSONResponse({"ok": True, "summary": summary, "videos": videos})


# ── SOP Vivo — AI Insights from Real Performance ─────────

@router.post("/api/admin/evolve-sop")
@limiter.limit("3/minute")
async def api_evolve_sop(request: Request, user=Depends(require_auth)):
    """Evolve SOP based on real data. Two modes: 'canal' (original channel) or 'alunos' (student results per channel)."""
    if user.get("role") != "admin":
        return JSONResponse({"error": "Admin only"}, status_code=403)

    body = await request.json()
    project_id = body.get("project_id", "")
    mode = body.get("mode", "canal")  # "canal" or "alunos"
    channel_id = body.get("channel_id", 0)  # specific student channel for "alunos" mode

    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    import asyncio

    def _evolve():
        from database import get_db, get_project, save_file, log_activity
        from protocols.ai_client import chat

        proj = get_project(project_id)
        if not proj:
            return {"error": "Projeto nao encontrado"}

        niche_name = proj.get("niche_chosen") or proj.get("name", "")

        # Get current SOP
        sop = ""
        with get_db() as conn:
            sop_row = conn.execute("SELECT content FROM files WHERE project_id=? AND category='analise' ORDER BY created_at LIMIT 1",
                                  (project_id,)).fetchone()
            if sop_row:
                sop = sop_row["content"]

        if not sop:
            return {"error": "SOP do projeto nao encontrado"}

        perf_report = ""
        report_source = ""
        videos_count = 0

        # ── MODE: CANAL MODELO ──
        if mode == "canal":
            report_source = "Canal Modelo"
            channel_url = proj.get("channel_original", "")
            if not channel_url:
                return {"error": "URL do canal original nao encontrada no projeto"}

            # Fetch current videos from original channel via YouTube API
            try:
                yt_key = ""
                with get_db() as conn:
                    yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
                    if yt_row:
                        yt_key = yt_row["value"]

                if not yt_key:
                    return {"error": "YouTube API Key nao configurada. Va em Admin > YouTube Settings."}

                import requests as _req

                # Resolve channel
                ch_id = ""
                if "/@" in channel_url:
                    handle = channel_url.split("/@")[-1].split("/")[0].split("?")[0]
                    resp = _req.get("https://www.googleapis.com/youtube/v3/channels",
                        params={"part": "id,contentDetails", "forHandle": handle, "key": yt_key}, timeout=15)
                    items = resp.json().get("items", [])
                    if items:
                        ch_id = items[0]["id"]
                elif "/channel/" in channel_url:
                    ch_id = channel_url.split("/channel/")[-1].split("/")[0]

                if not ch_id:
                    return {"error": f"Nao conseguiu resolver o canal: {channel_url[:60]}"}

                # Get uploads playlist
                ch_resp = _req.get("https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "contentDetails,statistics", "id": ch_id, "key": yt_key}, timeout=15)
                ch_data = ch_resp.json()
                uploads_pl = ch_data.get("items", [{}])[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
                ch_stats = ch_data.get("items", [{}])[0].get("statistics", {})

                # Get latest 20 videos
                pl_resp = _req.get("https://www.googleapis.com/youtube/v3/playlistItems",
                    params={"part": "snippet", "playlistId": uploads_pl, "maxResults": 20, "key": yt_key}, timeout=15)
                video_ids = [item["snippet"]["resourceId"]["videoId"] for item in pl_resp.json().get("items", [])]

                videos = []
                if video_ids:
                    vid_resp = _req.get("https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "statistics,snippet,contentDetails", "id": ",".join(video_ids[:20]), "key": yt_key}, timeout=15)
                    for v in vid_resp.json().get("items", []):
                        vs = v.get("statistics", {})
                        videos.append({
                            "title": v["snippet"].get("title", ""),
                            "views": int(vs.get("viewCount", 0)),
                            "likes": int(vs.get("likeCount", 0)),
                            "comments": int(vs.get("commentCount", 0)),
                            "published": v["snippet"].get("publishedAt", "")[:10],
                            "duration": v.get("contentDetails", {}).get("duration", ""),
                        })

                videos.sort(key=lambda x: x["views"], reverse=True)
                videos_count = len(videos)

                perf_report = f"""DADOS REAIS DO CANAL MODELO ({videos_count} videos recentes):
Canal: {channel_url}
Inscritos: {int(ch_stats.get('subscriberCount', 0)):,}
Views total: {int(ch_stats.get('viewCount', 0)):,}

TOP 5 VIDEOS (mais views):
"""
                for i, v in enumerate(videos[:5], 1):
                    eng = round((v["likes"] + v["comments"]) / v["views"] * 100, 2) if v["views"] > 0 else 0
                    perf_report += f'{i}. "{v["title"]}" — {v["views"]:,} views, {eng}% eng ({v["published"]})\n'

                perf_report += "\nBOTTOM 5 VIDEOS (menos views):\n"
                for i, v in enumerate(sorted(videos, key=lambda x: x["views"])[:5], 1):
                    eng = round((v["likes"] + v["comments"]) / v["views"] * 100, 2) if v["views"] > 0 else 0
                    perf_report += f'{i}. "{v["title"]}" — {v["views"]:,} views, {eng}% eng ({v["published"]})\n'

                avg_views = round(sum(v["views"] for v in videos) / len(videos)) if videos else 0
                perf_report += f"\nMedia por video: {avg_views:,} views"

            except Exception as e:
                return {"error": "Falha ao buscar dados do canal modelo."}

        # ── MODE: ALUNOS (por canal especifico) ──
        elif mode == "alunos":
            report_source = "Canais dos Alunos"
            with get_db() as conn:
                if channel_id:
                    # Specific channel
                    ch_row = conn.execute("SELECT * FROM student_channels WHERE id=?", (int(channel_id),)).fetchone()
                    if ch_row:
                        report_source = f"Canal: {ch_row['channel_name']}"
                    perf_data = [dict(r) for r in conn.execute(
                        "SELECT * FROM video_performance WHERE channel_id=? ORDER BY views DESC",
                        (int(channel_id),)
                    ).fetchall()]
                else:
                    # All students of this project
                    students = conn.execute("SELECT DISTINCT student_id FROM assignments WHERE project_id=?", (project_id,)).fetchall()
                    student_ids = [s["student_id"] for s in students]
                    perf_data = []
                    if student_ids:
                        placeholders = ",".join("?" * len(student_ids))
                        perf_data = [dict(r) for r in conn.execute(
                            f"SELECT * FROM video_performance WHERE student_id IN ({placeholders}) ORDER BY views DESC",
                            student_ids
                        ).fetchall()]

            if not perf_data:
                return {"error": "Nenhum dado de performance dos alunos. Os alunos precisam clicar 'Atualizar Dados' no painel deles primeiro."}

            videos_count = len(perf_data)
            total_views = sum(v["views"] for v in perf_data)
            avg_views = round(total_views / videos_count) if videos_count else 0

            perf_report = f"""DADOS REAIS DOS ALUNOS ({videos_count} videos, fonte: {report_source}):
- Views total: {total_views:,}
- Media por video: {avg_views:,}

TOP 5 VIDEOS (melhor performance):
"""
            for i, v in enumerate(perf_data[:5], 1):
                eng = round((v["likes"] + v["comments"]) / v["views"] * 100, 2) if v["views"] > 0 else 0
                perf_report += f'{i}. "{v["title"]}" — {v["views"]:,} views, {v["likes"]:,} likes, {eng}% eng\n'

            perf_report += "\nBOTTOM 5 VIDEOS (pior performance):\n"
            for i, v in enumerate(sorted(perf_data, key=lambda x: x["views"])[:5], 1):
                eng = round((v["likes"] + v["comments"]) / v["views"] * 100, 2) if v["views"] > 0 else 0
                perf_report += f'{i}. "{v["title"]}" — {v["views"]:,} views, {v["likes"]:,} likes, {eng}% eng\n'

        evolve_prompt = f"""Voce e um consultor de YouTube que analisa dados REAIS de performance para melhorar o SOP.

FONTE DOS DADOS: {report_source}

===== SOP ATUAL =====
{sop[:8000]}
===== FIM DO SOP =====

===== PERFORMANCE REAL =====
{perf_report}
===== FIM DA PERFORMANCE =====

TAREFA: Analise os dados acima e gere um RELATORIO DE EVOLUCAO DO SOP:

1. PADROES VENCEDORES: O que os top 5 videos tem em comum?
2. PADROES PERDEDORES: O que os bottom 5 tem em comum? O que evitar?
3. ATUALIZACOES SUGERIDAS:
   - Secao 2 (Formula de Titulos)
   - Secao 4 (Playbook de Hooks)
   - Secao 6 (Regras de Ouro)
   - Secao 8 (Estilo de Thumbnail)
4. METRICAS-CHAVE: engagement ideal, duracao ideal, frequencia ideal
5. PROXIMOS PASSOS: 3 acoes concretas

Seja especifico e acionavel. Baseie-se APENAS nos dados fornecidos."""

        result = chat(evolve_prompt,
                     system="Consultor de YouTube. Analisa dados reais, nao teorias.",
                     max_tokens=4000, temperature=0.7)

        save_file(project_id, "analise", f"SOP Evolucao ({report_source}) - {niche_name}",
                 f"sop_evolution_{mode}_{project_id}.md", result)
        log_activity(project_id, "sop_evolved", f"SOP Vivo ({report_source}): {videos_count} videos")

        return {
            "ok": True,
            "report": result,
            "mode": mode,
            "source": report_source,
            "videos_analyzed": videos_count,
        }

    try:
        result = await asyncio.to_thread(_evolve)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"evolve-sop error: {e}")
        return JSONResponse({"error": "Falha ao evoluir SOP."}, status_code=500)

# ── Generate Companion Content (SEO, Thumbnail, Music, Teaser) ──

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

    api_key = _decrypt_api_key(user.get("api_key_encrypted", ""))
    provider = user.get("api_provider", "")
    if not api_key:
        return JSONResponse({"error": "Configure sua API key"}, status_code=400)

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
                    "model": "gpt-4o-mini",
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
                    "model": "claude-sonnet-4-20250514",
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
                resp = await client.post(f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={api_key}", json={
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
        save_file(f["project_id"], TYPE_CATS[comp_type],
                 f"{TYPE_LABELS[comp_type]} - {title[:40]}",
                 f"{comp_type}_{file_id}.md", result, visible_to_students=True)

        return JSONResponse({"ok": True, "type": comp_type})

    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"generate-companion error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao gerar conteudo complementar."}, status_code=500)


# ── Save YouTube API Key (to admin_settings) ─────────────

@router.post("/api/student/save-youtube-key")
@limiter.limit("5/minute")
async def api_save_youtube_key(request: Request, user=Depends(require_auth)):
    """Save YouTube Data API v3 key to admin_settings (shared)."""
    body = await request.json()
    api_key = (body.get("api_key") or "").strip()
    if not api_key:
        return JSONResponse({"error": "API key obrigatoria"}, status_code=400)

    from database import get_db
    try:
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES (?, ?)",
                        ("youtube_api_key", api_key))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": "Falha ao salvar chave da API."}, status_code=500)


# ── Update Calendar from Analytics Data ──────────────────

@router.post("/api/student/update-calendar")
@limiter.limit("3/minute")
async def api_update_calendar(request: Request, user=Depends(require_auth)):
    """AI analyzes channel analytics to determine optimal posting schedule."""
    body = await request.json()
    target_channel_id = body.get("channel_id", 0)

    from database import get_db, get_video_performance

    videos = get_video_performance(user["id"], limit=30)
    if not videos or len(videos) < 3:
        return JSONResponse({"error": "Precisa de pelo menos 3 videos com dados. Clique 'Atualizar Dados' primeiro."}, status_code=400)

    # Get the SPECIFIC channel
    active_ch = None
    with get_db() as conn:
        if target_channel_id:
            ch_row = conn.execute("SELECT * FROM student_channels WHERE id=? AND student_id=?",
                                 (int(target_channel_id), user["id"])).fetchone()
            if ch_row:
                active_ch = dict(ch_row)

        if not active_ch:
            ch_row = conn.execute("SELECT * FROM student_channels WHERE student_id=? LIMIT 1", (user["id"],)).fetchone()
            if ch_row:
                active_ch = dict(ch_row)

        # Get project linked to this channel
        project_id = ""
        if active_ch:
            project_id = active_ch.get("project_id", "")
        if not project_id:
            assignment = conn.execute("SELECT project_id FROM assignments WHERE student_id=? LIMIT 1", (user["id"],)).fetchone()
            project_id = assignment["project_id"] if assignment else ""
        proj = conn.execute("SELECT language, niche_chosen, name FROM projects WHERE id=?", (project_id,)).fetchone() if project_id else None

    lang = proj["language"] if proj else "pt-BR"
    niche = (proj["niche_chosen"] or proj["name"]) if proj else "YouTube"
    LANG_COUNTRIES = {"pt-BR": "Brasil", "en": "USA/UK", "es": "Espana/Latam", "fr": "Franca", "de": "Alemanha", "it": "Italia", "ja": "Japao", "ko": "Coreia"}
    country = LANG_COUNTRIES.get(lang, "Global")

    # Build analytics summary
    total_views = sum(v["views"] for v in videos)
    total_likes = sum(v["likes"] for v in videos)
    total_comments = sum(v["comments"] for v in videos)
    avg_views = round(total_views / len(videos))
    avg_eng = round((total_likes + total_comments) / total_views * 100, 2) if total_views > 0 else 0

    # Check monetization using REAL channel data from YouTube API
    subs = 0
    total_channel_views = 0
    total_channel_videos = 0
    try:
        yt_key = ""
        with get_db() as conn:
            yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
            if yt_row:
                yt_key = yt_row["value"]

        if yt_key and active_ch:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                ch_url = active_ch.get("channel_url", "")
                ch_id = ""
                if "/@" in ch_url:
                    handle = ch_url.split("/@")[-1].split("/")[0].split("?")[0]
                    resp = await client.get("https://www.googleapis.com/youtube/v3/channels",
                        params={"part": "statistics", "forHandle": handle, "key": yt_key})
                    items = resp.json().get("items", [])
                    if items:
                        stats = items[0].get("statistics", {})
                        subs = int(stats.get("subscriberCount", 0))
                        total_channel_views = int(stats.get("viewCount", 0))
                        total_channel_videos = int(stats.get("videoCount", 0))
                elif "/channel/" in ch_url:
                    ch_id = ch_url.split("/channel/")[-1].split("/")[0].split("?")[0]
                    resp = await client.get("https://www.googleapis.com/youtube/v3/channels",
                        params={"part": "statistics", "id": ch_id, "key": yt_key})
                    items = resp.json().get("items", [])
                    if items:
                        stats = items[0].get("statistics", {})
                        subs = int(stats.get("subscriberCount", 0))
                        total_channel_views = int(stats.get("viewCount", 0))
                        total_channel_videos = int(stats.get("videoCount", 0))
    except Exception as e:
        import logging
        logging.getLogger("ytcloner").warning(f"Monetization check failed: {e}")

    # Estimate watch hours from TOTAL CHANNEL VIEWS (not just tracked videos)
    avg_duration_min = 12
    # Use total channel views for estimation (more accurate)
    view_base = total_channel_views if total_channel_views > 0 else total_views
    estimated_watch_hours = round(view_base * avg_duration_min * 0.4 / 60)  # 40% avg retention

    monetized = subs >= 1000 and estimated_watch_hours >= 4000
    subs_pct = min(100, round(subs / 1000 * 100)) if subs < 1000 else 100
    hours_pct = min(100, round(estimated_watch_hours / 4000 * 100)) if estimated_watch_hours < 4000 else 100

    # Video list for AI analysis
    video_summary = ""
    for v in videos[:15]:
        video_summary += f'"{v["title"]}" — {v["views"]:,} views, {v["likes"]} likes, published {v.get("published_at","")}\n'

    try:
        from protocols.ai_client import chat
        import json as _json, re as _re

        result = chat(
            f"""Analise estes dados de um canal YouTube no nicho "{niche}" no mercado {country}:

METRICAS:
- {len(videos)} videos analisados
- Media: {avg_views:,} views/video
- Engagement: {avg_eng}%
- Inscritos: {subs:,}

VIDEOS RECENTES:
{video_summary}

Retorne SOMENTE JSON:
{{"frequency":"frequencia ideal de postagem baseada nos dados","best_days":"dias da semana que os videos performaram melhor","best_times":"horario ideal baseado no mercado {country} e engagement","video_duration":"duracao ideal em minutos baseada na retencao dos videos","daily_views_estimate":"estimativa de views diarias baseada nos dados"}}

Analise:
1. Qual frequencia maximiza views sem perder qualidade?
2. Em quais dias os videos tiveram mais views? (veja as datas de publicacao)
3. Qual horario de pico do YouTube no {country}?
4. Qual duracao os videos com mais views tem?
Valores curtos (max 35 chars).""",
            system="Analista YouTube. APENAS JSON valido.",
            max_tokens=200, temperature=0.2
        )

        json_match = _re.search(r'\{.*\}', result, _re.DOTALL)
        schedule = {}
        if json_match:
            schedule = _json.loads(json_match.group())

        # Cache it
        if project_id:
            with get_db() as conn:
                cache_data = {
                    "frequency": schedule.get("frequency", "3-4 videos/semana")[:40],
                    "best_days": schedule.get("best_days", "Aguardando mais dados")[:40],
                    "best_times": schedule.get("best_times", "17:00-19:00")[:40],
                    "video_duration": schedule.get("video_duration", "12-19 minutos")[:40],
                    "language": lang,
                }
                conn.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES (?, ?)",
                            (f"schedule_{project_id}", _json.dumps(cache_data, ensure_ascii=False)))

        return JSONResponse({
            "ok": True,
            "schedule": schedule,
            "monetization": {
                "monetized": monetized,
                "subscribers": subs,
                "subs_target": 1000,
                "subs_pct": subs_pct,
                "watch_hours": estimated_watch_hours,
                "hours_target": 4000,
                "hours_pct": hours_pct,
                "total_views": total_channel_views,
                "daily_views": schedule.get("daily_views_estimate", "N/A"),
            },
        })

    except Exception as e:
        import logging
        logging.getLogger("ytcloner").error(f"update-calendar error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao atualizar calendario."}, status_code=500)
