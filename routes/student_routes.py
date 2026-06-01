"""
Student routes — dashboard, progress tracking, script generation, file management.
"""

import logging
import re

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth import require_auth
from config import OUTPUT_DIR
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.student")



router = APIRouter(tags=["student"])


def _get_student_resources(student_id: int) -> list[dict]:
    """Get resources available to a student (global + targeted).

    target_student_id semantics:
      - NULL = available to all students (new default)
      - 0 = legacy value also treated as "all students" for backward compat
      - <positive int> = specific student only
    """
    try:
        from database import get_db
        with get_db() as conn:
            rows = conn.execute("""
                SELECT * FROM admin_resources
                WHERE active=1 AND (target_student_id IS NULL OR target_student_id=0 OR target_student_id=?)
                ORDER BY created_at DESC
            """, (student_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _render(request, template, ctx=None):
    from dashboard import render
    return render(request, template, ctx)


@router.get("/student", response_class=HTMLResponse)
async def student_dashboard(request: Request, view_as: int = 0, channel: int = 0, user=Depends(require_auth)):
    # Debug: catch any error and log full traceback before SafeErrorMiddleware hides it
    try:
        return await _student_dashboard_inner(request, view_as, channel, user)
    except Exception as e:
        logger.error(f"student_dashboard CRASH: {e}", exc_info=True)
        raise


async def _student_dashboard_inner(request: Request, view_as: int, channel: int, user: dict):
    """Student dashboard with kanban board.
    Admin can view as any student via ?view_as=<student_id>
    Student switches channels via ?channel=<channel_id>
    """
    # First-login: force password change before allowing access
    if user.get("must_change_password") and not view_as:
        return RedirectResponse("/change-password?first=1", status_code=302)

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
            active_channel = next((ch for ch in channels if ch["id"] == int(channel)), None)
            if not active_channel:
                active_channel = channels[0]
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
    has_api_key = bool(target_user.get("api_key_encrypted")) or bool(target_user.get("use_admin_api"))

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
                    content_len = dict(row).get("content_len", 0) or 0
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

    # ── Schedule defaults inteligentes por idioma (sobrescritos pelo cache do update-calendar) ──
    # Horários de pico reais por mercado (prime-time YouTube)
    PRIME_TIME_BY_LANG = {
        "pt-BR": "19:00-21:00",
        "en": "18:00-20:00 EST",
        "es": "20:00-22:00",
        "fr": "19:00-21:00 CET",
        "de": "19:00-21:00 CET",
        "it": "20:00-22:00 CET",
        "ja": "20:00-22:00 JST",
        "ko": "20:00-22:00 KST",
    }
    BEST_DAYS_GENERIC = "Ter, Qui, Sab"  # padrão YouTube: meio e fim de semana
    schedule_info = {
        "frequency": "3-4 videos/semana",
        "best_days": BEST_DAYS_GENERIC,
        "best_times": "19:00-21:00",
        "video_duration": "12-19 minutos",
        "language": "pt-BR",
    }
    if active_project_ids:
        try:
            pid = list(active_project_ids)[0]
            with get_db() as conn:
                proj_row = conn.execute("SELECT language, niche_chosen, name FROM projects WHERE id=?", (pid,)).fetchone()
                if proj_row:
                    lang = proj_row["language"] or "pt-BR"
                    schedule_info["language"] = lang
                    schedule_info["best_times"] = PRIME_TIME_BY_LANG.get(lang, "19:00-21:00")
                    proj_niche = proj_row["niche_chosen"] or proj_row["name"] or ""

                # Ajusta frequência baseada em quantos vídeos o aluno tem publicados
                try:
                    video_count = conn.execute(
                        "SELECT COUNT(*) as c FROM video_performance WHERE student_id=?",
                        (user["id"],)
                    ).fetchone()
                    vc = video_count["c"] if video_count else 0
                    if vc == 0:
                        schedule_info["frequency"] = "Diaria (1a semana de lancamento)"
                    elif vc < 10:
                        schedule_info["frequency"] = "3-4 videos/semana"
                    else:
                        schedule_info["frequency"] = "4-5 videos/semana"
                except Exception:
                    pass

                # Check cache (update-calendar gravou dados reais de analytics aqui)
                cache_key = f"schedule_{pid}"
                cached = conn.execute("SELECT value FROM admin_settings WHERE key=?", (cache_key,)).fetchone()
                if cached and cached["value"]:
                    try:
                        import json as _json
                        cached_data = _json.loads(cached["value"])
                        for k in ["frequency", "best_days", "best_times", "video_duration"]:
                            v = cached_data.get(k)
                            if v and v not in ("nao definido", "Aguardando mais dados", "Aguardando dados do Analytics"):
                                schedule_info[k] = v
                    except Exception:
                        pass
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

    # ── Janela A/B calculada automaticamente pelo tamanho do canal ──
    # Regra de negocio (NAO configuravel pelo aluno): canais menores precisam
    # de ciclo mais rapido pra aproveitar a janela algoritmica curta.
    ab_window_hours = 6  # default quando nao tem dados (nao assumir canal novo)
    active_subs = 0
    has_subs_data = False
    try:
        if active_channel and active_channel.get("cached_stats"):
            import json as _json
            cs = _json.loads(active_channel["cached_stats"])
            # cached_stats salva aninhado: { channel: { subscribers: N } }
            # mas aceita tambem formato flat (subscriberCount) pra compat.
            raw_subs = (
                cs.get("channel", {}).get("subscribers")
                or cs.get("channel", {}).get("subscriberCount")
                or cs.get("subscriberCount")
                or cs.get("subscribers")
                or 0
            )
            active_subs = int(raw_subs or 0)
            has_subs_data = active_subs > 0
        # So aplica faixas quando temos dados reais — senao mantem 6h default
        # (evita falsamente classificar canal grande como "novo" por falta de cache)
        if has_subs_data:
            if active_subs < 1000:
                ab_window_hours = 4
            elif active_subs < 10000:
                ab_window_hours = 6
            elif active_subs < 100000:
                ab_window_hours = 8
            else:
                ab_window_hours = 12
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
        "resources": _get_student_resources(target_user["id"]),
        "ab_window_hours": ab_window_hours,
        "ab_subs": active_subs,
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




@router.post("/api/student/delete-file")
@limiter.limit("20/minute")
async def api_student_delete_file(request: Request, user=Depends(require_auth)):
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db, delete_file as db_delete_file

    # Verify access
    try:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
            if not row:
                return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)
            f = dict(row)  # Convert Row to dict for safe .get() access

            if user.get("role") != "admin":
                fname = f.get("filename", "")
                is_student_file = (
                    "student_" in fname or
                    fname.startswith("seo_") or
                    fname.startswith("thumbnail_") or
                    fname.startswith("music_") or
                    fname.startswith("teaser_")
                )

                # Block deletion of admin-only files (SOP, mindmap)
                if f["category"] == "analise":
                    return JSONResponse({"error": "Este arquivo so pode ser excluido pelo admin"}, status_code=403)
                if f["category"] == "visual" and not is_student_file:
                    return JSONResponse({"error": "Este arquivo so pode ser excluido pelo admin"}, status_code=403)

                # Student must have an assignment for this project
                assignment = conn.execute(
                    "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
                    (user["id"], f["project_id"]),
                ).fetchone()
                if not assignment:
                    return JSONResponse({"error": "Sem permissao"}, status_code=403)

        # Delete from Google Drive if synced (search by file_id AND filename)
        try:
            from database import get_db as _get_db
            fname = f.get("filename", "")
            with _get_db() as dconn:
                drive_rows = dconn.execute(
                    "SELECT drive_file_id FROM student_drive_files WHERE (file_id=? OR filename=?) AND student_id=?",
                    (int(file_id), fname, user["id"])
                ).fetchall()
            if drive_rows:
                from protocols.google_export import delete_drive_file
                from database import delete_student_drive_file
                for dr in drive_rows:
                    try:
                        delete_drive_file(dr["drive_file_id"])
                    except Exception:
                        pass
                    delete_student_drive_file(dr["drive_file_id"], user["id"])
                logger.info(f"[DRIVE-SYNC] Deleted {len(drive_rows)} Drive file(s) for file_id={file_id}")
        except Exception as e:
            logger.warning(f"[DRIVE-SYNC] Failed to delete from Drive (non-blocking): {e}")

        deleted = db_delete_file(int(file_id))
        if deleted and deleted.get("filename"):
            fpath = OUTPUT_DIR / deleted["filename"]
            if fpath.exists():
                fpath.unlink()

        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-file error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao excluir arquivo."}, status_code=500)


# ── Student Channels ─────────────────────────────────────

@router.get("/api/student/download-roteiro-prompt")
@limiter.limit("20/minute")
async def api_student_download_roteiro_prompt(
    request: Request, project_id: str = "", user=Depends(require_auth)
):
    """Baixa so o prompt do agente de roteiro (System Prompt + Template) do SOP
    do projeto do aluno. project_id opcional — se vazio, usa a 1a assignment
    do aluno que tenha projeto."""
    from fastapi.responses import Response
    from database import get_assignments, get_project
    from services import get_project_sop, extract_roteiro_prompt

    pid = (project_id or "").strip()
    niche = ""
    if not pid:
        for a in get_assignments(user["id"]):
            if a.get("project_id"):
                pid = a["project_id"]
                niche = a.get("niche", "")
                break
    if not pid:
        return JSONResponse(
            {"error": "Nenhum projeto atribuido a voce ainda."}, status_code=404
        )

    proj = get_project(pid)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)
    if not niche:
        niche = proj.get("niche_chosen", "") or proj.get("name", "roteiro")

    sop = get_project_sop(pid)
    if not sop:
        return JSONResponse(
            {"error": "SOP do projeto ainda nao foi gerado."}, status_code=404
        )

    body = extract_roteiro_prompt(sop)
    if not body:
        return JSONResponse(
            {"error": "SOP nao tem secao de roteiro (System Prompt / Template)."},
            status_code=404,
        )

    slug = re.sub(r"[^a-z0-9]+", "_", niche.lower()).strip("_") or "roteiro"
    header = (
        f"# Agente de Roteiro — {niche}\n\n"
        f"> Cole o SYSTEM PROMPT em System Instructions da sua IA "
        f"e use o TEMPLATE como esqueleto do roteiro.\n\n---\n\n"
    )
    md = header + body + "\n"
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="agente_roteiro_{slug}.md"'
        },
    )


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
            from protocols.google_export import get_or_create_student_folder
            folder_id = get_or_create_student_folder(user["name"])
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



# ── Improve Script based on Score ──────────────────────



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

    from services import is_valid_youtube_channel_id
    if not is_valid_youtube_channel_id(channel_id):
        return JSONResponse(
            {"error": "Nao foi possivel resolver um channel ID valido do YouTube (use a URL do canal)"},
            status_code=400,
        )

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

            # Auto-detect language from YouTube API
            detected_lang = snippet.get("defaultLanguage", "") or snippet.get("country", "")
            COUNTRY_TO_LANG = {"BR": "pt-BR", "PT": "pt-BR", "US": "en", "GB": "en", "ES": "es", "MX": "es",
                               "FR": "fr", "DE": "de", "IT": "it", "JP": "ja", "KR": "ko"}
            if detected_lang and len(detected_lang) == 2:
                detected_lang = COUNTRY_TO_LANG.get(detected_lang.upper(), detected_lang.lower())

            # Auto-update channel language in DB if detected
            if detected_lang and channel_db_id:
                try:
                    with get_db() as conn:
                        conn.execute("UPDATE student_channels SET language=? WHERE id=? AND student_id=?",
                                    (detected_lang, int(channel_db_id), user["id"]))
                except Exception:
                    pass

            response_data = {
                "ok": True,
                "channel": {
                    "name": snippet.get("title", ""),
                    "subscribers": int(stats.get("subscriberCount", 0)),
                    "total_views": int(stats.get("viewCount", 0)),
                    "total_videos": int(stats.get("videoCount", 0)),
                    "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    "language": detected_lang,
                    "country": snippet.get("country", ""),
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

                from services import is_valid_youtube_channel_id
                if not is_valid_youtube_channel_id(ch_id):
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

    # ── Helpers pra parsing ──
    def _parse_duration_to_minutes(d: str) -> float:
        """Converte ISO 8601 (PT5M32S) ou 'mm:ss' / 'hh:mm:ss' pra minutos decimais."""
        if not d:
            return 0.0
        s = str(d).strip()
        # ISO 8601: PT1H23M45S
        if s.startswith("PT"):
            import re as _re
            h = int((_re.search(r"(\d+)H", s) or [0, 0])[1] or 0) if _re.search(r"(\d+)H", s) else 0
            m = int((_re.search(r"(\d+)M", s) or [0, 0])[1] or 0) if _re.search(r"(\d+)M", s) else 0
            sec = int((_re.search(r"(\d+)S", s) or [0, 0])[1] or 0) if _re.search(r"(\d+)S", s) else 0
            return h * 60 + m + sec / 60
        # hh:mm:ss ou mm:ss
        if ":" in s:
            parts = s.split(":")
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
                if len(parts) == 2:
                    return int(parts[0]) + int(parts[1]) / 60
            except ValueError:
                pass
        return 0.0

    # Calcula duração REAL média dos vídeos trackeados (pra estimativa de watch hours)
    durations_min = [_parse_duration_to_minutes(v.get("duration", "")) for v in videos]
    durations_min = [d for d in durations_min if d > 0]
    avg_duration_min = round(sum(durations_min) / len(durations_min), 1) if durations_min else 12.0

    # ── Resolve channel ID robusto (suporta /@ /channel/ /c/ /user/ + search fallback) ──
    async def _resolve_channel_stats(client, ch_url: str, yt_key: str):
        """Tenta várias estratégias até pegar subs+views. Retorna dict ou None."""
        if not ch_url or not yt_key:
            return None
        try:
            async def _call(params):
                r = await client.get("https://www.googleapis.com/youtube/v3/channels", params={**params, "key": yt_key})
                items = r.json().get("items", [])
                if items:
                    stats = items[0].get("statistics", {})
                    return {
                        "subs": int(stats.get("subscriberCount", 0)),
                        "total_views": int(stats.get("viewCount", 0)),
                        "total_videos": int(stats.get("videoCount", 0)),
                    }
                return None

            # /@handle
            if "/@" in ch_url:
                handle = ch_url.split("/@")[-1].split("/")[0].split("?")[0]
                res = await _call({"part": "statistics", "forHandle": handle})
                if res: return res
                # Fallback: search
                sr = await client.get("https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "type": "channel", "q": handle, "maxResults": 1, "key": yt_key})
                items = sr.json().get("items", [])
                if items:
                    ch_id = items[0].get("snippet", {}).get("channelId") or items[0].get("id", {}).get("channelId")
                    if ch_id:
                        return await _call({"part": "statistics", "id": ch_id})
                return None
            # /channel/UCxxx
            if "/channel/" in ch_url:
                ch_id = ch_url.split("/channel/")[-1].split("/")[0].split("?")[0]
                return await _call({"part": "statistics", "id": ch_id})
            # /c/CustomName ou /user/Username — API deprecou forUsername pra novos canais,
            # mas search funciona
            if "/c/" in ch_url or "/user/" in ch_url:
                name = ch_url.rstrip("/").split("/")[-1].split("?")[0]
                # Tenta forUsername primeiro (canais antigos)
                res = await _call({"part": "statistics", "forUsername": name})
                if res: return res
                # Search fallback
                sr = await client.get("https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "type": "channel", "q": name, "maxResults": 1, "key": yt_key})
                items = sr.json().get("items", [])
                if items:
                    ch_id = items[0].get("snippet", {}).get("channelId") or items[0].get("id", {}).get("channelId")
                    if ch_id:
                        return await _call({"part": "statistics", "id": ch_id})
        except Exception as e:
            import logging
            logging.getLogger("ytcloner").warning(f"Channel resolve failed for {ch_url}: {e}")
        return None

    # Check monetization: API key admin → aluno fallback → cached_stats do canal
    subs = 0
    total_channel_views = 0
    total_channel_videos = 0
    try:
        yt_key = ""
        from database import _decrypt_api_key
        with get_db() as conn:
            yt_row = conn.execute("SELECT value FROM admin_settings WHERE key='youtube_api_key'").fetchone()
            if yt_row and yt_row["value"]:
                yt_key = yt_row["value"]
            # Fallback: API key do próprio aluno
            if not yt_key:
                u = conn.execute("SELECT api_key_encrypted, api_provider FROM users WHERE id=?", (user["id"],)).fetchone()
                if u and u["api_key_encrypted"] and (u["api_provider"] or "").startswith("google"):
                    try:
                        yt_key = _decrypt_api_key(u["api_key_encrypted"])
                    except Exception:
                        pass

        if yt_key and active_ch:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                stats_res = await _resolve_channel_stats(client, active_ch.get("channel_url", ""), yt_key)
                if stats_res:
                    subs = stats_res["subs"]
                    total_channel_views = stats_res["total_views"]
                    total_channel_videos = stats_res["total_videos"]

        # Fallback final: cached_stats salvo no student_channels
        if (subs == 0 or total_channel_views == 0) and active_ch and active_ch.get("cached_stats"):
            try:
                import json as _json
                cached = _json.loads(active_ch["cached_stats"])
                if subs == 0 and cached.get("subscriberCount"):
                    subs = int(cached.get("subscriberCount", 0))
                if total_channel_views == 0 and cached.get("viewCount"):
                    total_channel_views = int(cached.get("viewCount", 0))
                if total_channel_videos == 0 and cached.get("videoCount"):
                    total_channel_videos = int(cached.get("videoCount", 0))
            except Exception:
                pass
    except Exception as e:
        import logging
        logging.getLogger("ytcloner").warning(f"Monetization check failed: {e}")

    # Watch hours: prefere cálculo com total_channel_views + duração real média.
    # Retenção YouTube: ~40% é média histórica (YT internal, docs públicas).
    view_base = total_channel_views if total_channel_views > 0 else total_views
    estimated_watch_hours = round(view_base * avg_duration_min * 0.4 / 60)

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


# ── A/B Title: gera variante B sob demanda + troca A↔B ───────────────────



@router.post("/api/student/ab-decision")
@limiter.limit("30/minute")
async def api_ab_decision(request: Request, user=Depends(require_auth)):
    """Log da decisao do wizard de 6h: manter, trocar, ou esperar (mais dados/retencao baixa).

    Grava em progress.ab_decision pra depois cruzar com analytics (quais decisoes levaram
    a mais views) e alimentar o SOP Vivo."""
    body = await request.json()
    progress_id = body.get("progress_id")
    decision = (body.get("decision") or "").strip().lower()
    reason = (body.get("reason") or "").strip()[:300]

    VALID = {"keep", "swap", "wait_more_data", "content_problem"}
    if not progress_id or decision not in VALID:
        return JSONResponse({
            "error": f"progress_id e decision obrigatorios. decision deve ser: {', '.join(sorted(VALID))}"
        }, status_code=400)

    from database import get_db
    from datetime import datetime
    now = datetime.now().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM progress WHERE id=? AND student_id=?",
            (int(progress_id), user["id"]),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "progress_id invalido"}, status_code=404)
        conn.execute(
            "UPDATE progress SET ab_decision=?, ab_decided_at=?, ab_reason=? WHERE id=?",
            (decision, now, reason, int(progress_id)),
        )
    return JSONResponse({"ok": True, "decision": decision, "decided_at": now})


@router.post("/api/student/swap-title")
@limiter.limit("30/minute")
async def api_swap_title(request: Request, user=Depends(require_auth)):
    """Aluno troca o titulo principal (A) pela variante (B) — LIMITE 1 swap por video.
    Regra Paddy Galloway: uma troca permitida por video; se falhar, aprende no proximo.
    Swap: o antigo title_a vai pra title_b (pra preservar historico) e vice-versa."""
    body = await request.json()
    idea_id = body.get("idea_id")
    progress_id = body.get("progress_id")
    if not idea_id:
        return JSONResponse({"error": "idea_id obrigatorio"}, status_code=400)

    from database import get_db, update_idea_title
    from datetime import datetime, timezone
    with get_db() as conn:
        row = conn.execute(
            """SELECT i.id, i.title, i.title_b
               FROM ideas i
               JOIN assignments a ON a.project_id = i.project_id
               WHERE i.id=? AND a.student_id=?
               LIMIT 1""",
            (int(idea_id), user["id"]),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "Idea nao encontrada ou sem permissao"}, status_code=404)
        idea = dict(row)
        if not idea.get("title_b"):
            return JSONResponse({"error": "Sem titulo B ainda. Peca ao admin para gerar."}, status_code=400)

        # Checa swap count no progress (se progress_id fornecido)
        if progress_id:
            pg = conn.execute(
                "SELECT ab_swap_count FROM progress WHERE id=? AND student_id=?",
                (int(progress_id), user["id"]),
            ).fetchone()
            if pg and (pg["ab_swap_count"] or 0) >= 1:
                return JSONResponse({
                    "error": "Limite atingido: voce ja trocou o titulo desse video 1 vez. Regra Paddy Galloway: uma troca por video — se nao funcionar, aprende e aplica no proximo.",
                    "code": "swap_limit_reached"
                }, status_code=403)

        new_a = idea["title_b"]
        new_b = idea["title"]
        update_idea_title(int(idea_id), new_a, title_b=new_b)

        # Atualiza contador
        if progress_id:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE progress SET ab_swap_count = COALESCE(ab_swap_count,0) + 1, ab_swapped_at=? WHERE id=?",
                (now, int(progress_id)),
            )

    return JSONResponse({"ok": True, "title_a": new_a, "title_b": new_b, "swap_count": 1})


def _auto_mark_checklist(progress_id: int, student_id: int, *keys: str) -> None:
    """Marca chaves do checklist automaticamente quando aluno completa acao (roteiro, narracao, seo, etc).
    Preserva valores existentes (nao sobrescreve False → True nao volta)."""
    import json as _json
    if not progress_id or not keys:
        return
    try:
        from database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT production_checklist FROM progress WHERE id=? AND student_id=?",
                (int(progress_id), int(student_id)),
            ).fetchone()
            if not row:
                return
            current = {}
            try:
                current = _json.loads(row["production_checklist"] or "{}")
            except Exception:
                current = {}
            if not isinstance(current, dict):
                current = {}
            changed = False
            for k in keys:
                if not current.get(k):
                    current[k] = True
                    changed = True
            if changed:
                conn.execute(
                    "UPDATE progress SET production_checklist=? WHERE id=?",
                    (_json.dumps(current), int(progress_id)),
                )
    except Exception as e:
        logger.warning(f"_auto_mark_checklist({progress_id}, {keys}) failed: {e}")


@router.post("/api/student/update-card-extras")
@limiter.limit("60/minute")
async def api_update_card_extras(request: Request, user=Depends(require_auth)):
    """Atualiza notes e/ou production_checklist de um card (progress).
    Body: { progress_id, notes?, checklist?: {roteiro, narracao, cenas_agente, cenas_flow, edicao, thumb, seo} }"""
    import json as _json
    body = await request.json()
    progress_id = body.get("progress_id")
    if not progress_id:
        return JSONResponse({"error": "progress_id obrigatorio"}, status_code=400)

    notes = body.get("notes")
    checklist = body.get("checklist")

    from database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM progress WHERE id=? AND student_id=?",
            (int(progress_id), user["id"]),
        ).fetchone()
        if not row:
            return JSONResponse({"error": "card nao encontrado ou sem permissao"}, status_code=404)

        updates: list[str] = []
        params: list = []
        if notes is not None:
            updates.append("notes=?")
            params.append(str(notes)[:5000])
        if checklist is not None and isinstance(checklist, dict):
            # So aceita chaves conhecidas (+ _order pra customizacao)
            valid_keys = {"roteiro", "narracao", "cenas_agente", "cenas_flow", "edicao", "thumb", "seo", "musica", "teaser"}
            clean = {k: bool(v) for k, v in checklist.items() if k in valid_keys}
            # Aceita ordem customizada (array de keys)
            if isinstance(checklist.get("_order"), list):
                clean["_order"] = [k for k in checklist["_order"] if k in valid_keys]
            updates.append("production_checklist=?")
            params.append(_json.dumps(clean))
        if not updates:
            return JSONResponse({"error": "Nada pra atualizar (envie notes ou checklist)"}, status_code=400)
        params.append(int(progress_id))
        conn.execute(f"UPDATE progress SET {','.join(updates)} WHERE id=?", params)

    return JSONResponse({"ok": True})
