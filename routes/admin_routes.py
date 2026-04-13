"""
Admin Routes — Student management, project management, settings, panel.
Extracted from dashboard.py for modularity.
"""

import json
import logging
import os
import re

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth import require_auth, require_admin
from config import OUTPUT_DIR
from rate_limit import limiter
from services import validate_project_id, validate_url, generate_mindmap_html

logger = logging.getLogger("ytcloner.routes.admin")

router = APIRouter(tags=["admin"])


def _render(request, template, ctx=None, status_code=200):
    from dashboard import render
    return render(request, template, ctx, status_code)


@router.post("/api/admin/link-channel-project")
@limiter.limit("20/minute")
async def api_link_channel_project(request: Request, user=Depends(require_admin)):
    """Link a student channel to a project. Also creates/updates assignment to sync."""
    body = await request.json()
    channel_id = body.get("channel_id")
    project_id = body.get("project_id", "").strip()
    student_id = body.get("student_id")

    if not channel_id or not project_id or not student_id:
        return JSONResponse({"error": "channel_id, project_id e student_id obrigatorios"}, status_code=400)

    from database import get_project, get_db, create_assignment, log_activity
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    niche = proj.get("niche_chosen", proj["name"])

    try:
        # Step 1: Update channel → project link
        with get_db() as conn:
            conn.execute(
                "UPDATE student_channels SET project_id=?, niche=? WHERE id=? AND student_id=?",
                (project_id, niche, int(channel_id), int(student_id)),
            )

        # Step 2: Check/create assignment (separate connection to avoid deadlock)
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM assignments WHERE student_id=? AND project_id=?",
                (int(student_id), project_id),
            ).fetchone()

        if not existing:
            aid = create_assignment(int(student_id), project_id, niche, 5)
            log_activity(project_id, "channel_project_linked",
                         f"Canal {channel_id} vinculado + assignment {aid} criado com 5 titulos")
        else:
            log_activity(project_id, "channel_project_linked",
                         f"Canal {channel_id} vinculado ao projeto (assignment ja existe)")

        return JSONResponse({"ok": True, "project_name": proj["name"]})
    except Exception as e:
        logger.error(f"link-channel-project error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao vincular projeto ao canal."}, status_code=500)


@router.post("/api/admin/assign-project")
@limiter.limit("20/minute")
async def api_assign_project(request: Request, user=Depends(require_admin)):
    """Assign or change the project linked to a student assignment."""
    body = await request.json()
    assignment_id = body.get("assignment_id")
    project_id = body.get("project_id", "").strip()

    if not assignment_id or not project_id:
        return JSONResponse({"error": "assignment_id e project_id obrigatorios"}, status_code=400)

    from database import get_db, get_project
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE assignments SET project_id=?, niche=? WHERE id=?",
                (project_id, proj.get("niche_chosen", proj["name"]), int(assignment_id)),
            )
        from database import log_activity
        log_activity(project_id, "project_assigned", f"Projeto atribuido ao assignment {assignment_id}")
        return JSONResponse({"ok": True, "project_name": proj["name"]})
    except Exception as e:
        logger.error(f"assign-project error: {e}")
        return JSONResponse({"error": "Falha ao atribuir projeto."}, status_code=500)


@router.post("/api/admin/create-assignment")
@limiter.limit("10/minute")
async def api_create_assignment(request: Request, user=Depends(require_admin)):
    """Create a new assignment for a student with a specific project."""
    body = await request.json()
    student_id = body.get("student_id")
    project_id = body.get("project_id", "").strip()
    niche = body.get("niche", "").strip()
    titles_count = int(body.get("titles_count", 5))

    if not student_id or not project_id:
        return JSONResponse({"error": "student_id e project_id obrigatorios"}, status_code=400)

    from database import get_project, create_assignment
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    if not niche:
        niche = proj.get("niche_chosen", proj["name"])

    try:
        aid = create_assignment(int(student_id), project_id, niche, titles_count)
        from database import log_activity
        log_activity(project_id, "assignment_created", f"Aluno {student_id} atribuido com {titles_count} titulos")
        return JSONResponse({"ok": True, "assignment_id": aid})
    except Exception as e:
        logger.error(f"create-assignment error: {e}")
        return JSONResponse({"error": "Falha ao criar atribuicao."}, status_code=500)


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request, user=Depends(require_auth), first: str = ""):
    """Page where the student (or any user) can change their own password."""
    must = bool(user.get("must_change_password")) or first == "1"
    return _render(
        request,
        "change_password.html",
        {"must_change": must, "user_email": user.get("email", "")},
    )


@router.post("/api/change-password")
@limiter.limit("5/minute")
async def api_change_password(request: Request, user=Depends(require_auth)):
    """Change the current user's password. Clears the must_change_password flag."""
    body = await request.json()
    new_pw = (body.get("new_password") or "").strip()
    confirm = (body.get("confirm_password") or "").strip()
    if not new_pw or len(new_pw) < 8:
        return JSONResponse({"error": "Nova senha deve ter no minimo 8 caracteres"}, status_code=400)
    if new_pw != confirm:
        return JSONResponse({"error": "Senhas nao coincidem"}, status_code=400)
    if new_pw == user.get("email", ""):
        return JSONResponse({"error": "A nova senha nao pode ser igual ao email"}, status_code=400)

    from database import change_user_password
    ok = change_user_password(int(user["id"]), new_pw)
    if not ok:
        return JSONResponse({"error": "Falha ao alterar senha"}, status_code=500)

    redirect = "/" if user.get("role") == "admin" else "/student"
    return JSONResponse({"ok": True, "redirect": redirect})


@router.post("/api/admin/create-student")
@limiter.limit("10/minute")
async def api_create_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    password = (body.get("password") or "").strip()
    niche = (body.get("niche") or "").strip()
    project_id = body.get("project_id", "")

    if not name or len(name) < 2:
        return JSONResponse({"error": "Nome deve ter pelo menos 2 caracteres"}, status_code=400)
    if not email or "@" not in email:
        return JSONResponse({"error": "Email invalido"}, status_code=400)

    # Default password = email when admin doesn't supply one. Student is forced
    # to change it on first login (must_change_password=1).
    must_change = False
    if not password:
        password = email
        must_change = True
    elif password == email:
        must_change = True
    elif len(password) < 12:
        return JSONResponse({"error": "Senha deve ter pelo menos 12 caracteres"}, status_code=400)

    from database import create_user, create_assignment
    uid = create_user(
        name,
        email,
        password,
        role="student",
        created_by=user.get("id"),
        must_change_password=must_change,
    )
    if not uid:
        return JSONResponse({"error": "Email ja cadastrado"}, status_code=400)

    assignment_id = None
    if niche and project_id:
        assignment_id = create_assignment(uid, project_id, niche)

    # Welcome notification
    try:
        from database import create_notification
        create_notification(uid, "welcome", "Bem-vindo ao YT Channel Cloner!",
            f"Seu acesso foi criado. Nicho: {niche or 'a definir'}. Configure sua API key para comecar a gerar roteiros.",
            "/student")
    except Exception:
        pass

    # Google Drive folder for student (auto-sync)
    drive_folder_id = ""
    try:
        from protocols.google_export import get_or_create_student_folder, share_folder
        from database import update_user, log_activity
        drive_folder_id = get_or_create_student_folder(name)
        share_folder(drive_folder_id, email, role="writer")
        update_user(uid, drive_folder_id=drive_folder_id)
        log_activity(project_id or "", "drive_student_folder",
                     f"Pasta Drive criada para aluno {name}: {drive_folder_id}")
        logger.info(f"[CREATE-STUDENT] Drive folder {drive_folder_id} (Aluno - {name}) created and shared with {email}")
    except Exception as e:
        logger.warning(f"[CREATE-STUDENT] Drive folder creation failed (student created without Drive): {e}")

    return JSONResponse({"ok": True, "user_id": uid, "assignment_id": assignment_id})


@router.post("/api/admin/rename-project")
@limiter.limit("30/minute")
async def api_rename_project(request: Request, user=Depends(require_admin)):
    body = await request.json()
    project_id = body.get("project_id", "")
    new_name = (body.get("name") or "").strip()
    if not project_id or not new_name:
        return JSONResponse({"error": "project_id e name obrigatorios"}, status_code=400)
    if len(new_name) > 100:
        return JSONResponse({"error": "Nome muito longo (max 100)"}, status_code=400)
    from database import update_project
    update_project(project_id, name=new_name)
    return JSONResponse({"ok": True, "name": new_name})


@router.post("/api/admin/update-project-channel")
@limiter.limit("30/minute")
async def api_update_project_channel(request: Request, user=Depends(require_admin)):
    """Update or clear the channel_original field of a project.
    Accepts a YouTube URL, a free-text label (e.g. 'Loaded Dice'), or empty string.
    """
    body = await request.json()
    project_id = body.get("project_id", "")
    raw = (body.get("channel_original") or "").strip()
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)
    if len(raw) > 300:
        return JSONResponse({"error": "Valor muito longo (max 300)"}, status_code=400)

    # Light validation: if it looks like a URL, ensure it's youtube; otherwise accept as label
    value = raw
    if raw and ("://" in raw or raw.startswith("www.")):
        try:
            value = validate_url(raw)
        except Exception:
            return JSONResponse({"error": "URL invalida"}, status_code=400)
        if "youtube.com" not in value and "youtu.be" not in value:
            return JSONResponse({"error": "URL deve ser do YouTube"}, status_code=400)

    from database import get_project, update_project
    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)
    update_project(project_id, channel_original=value)
    return JSONResponse({"ok": True, "channel_original": value})


@router.post("/api/admin/delete-project")
@limiter.limit("10/minute")
async def api_delete_project(request: Request, user=Depends(require_admin)):
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)
    try:
        from database import delete_project
        delete_project(str(project_id))
        # Also delete mindmap file
        try:
            mm = OUTPUT_DIR / f"mindmap_{project_id}.html"
            if mm.exists():
                mm.unlink()
        except Exception:
            pass
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"Delete project error: {e}")
        return JSONResponse({"error": "Erro ao excluir projeto."}, status_code=500)


@router.post("/api/admin/delete-file")
@limiter.limit("20/minute")
async def api_admin_delete_file(request: Request, user=Depends(require_admin)):
    """Delete a file from a project."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)
    try:
        from database import delete_file
        deleted = delete_file(int(file_id))
        if deleted and deleted.get("filename"):
            fpath = OUTPUT_DIR / deleted["filename"]
            if fpath.exists():
                fpath.unlink()
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-file error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao excluir arquivo."}, status_code=500)


@router.post("/api/admin/remove-title")
@limiter.limit("20/minute")
async def api_remove_title(request: Request, user=Depends(require_admin)):
    body = await request.json()
    idea_id = body.get("idea_id")
    progress_id = body.get("progress_id")

    if not idea_id and not progress_id:
        return JSONResponse({"error": "idea_id ou progress_id obrigatorio"}, status_code=400)

    from database import delete_idea, get_db

    if progress_id:
        # Remove assignment from student (delete progress entry), keep the idea
        with get_db() as conn:
            conn.execute("DELETE FROM progress WHERE id=?", (int(progress_id),))
        return JSONResponse({"ok": True})

    if idea_id:
        # Delete the idea entirely
        delete_idea(int(idea_id))
        return JSONResponse({"ok": True})


@router.post("/api/admin/release-titles")
@limiter.limit("20/minute")
async def api_release_titles(request: Request, user=Depends(require_admin)):
    body = await request.json()
    assignment_id = body.get("assignment_id")
    count = body.get("count", 5)
    if not assignment_id:
        return JSONResponse({"error": "assignment_id obrigatorio"}, status_code=400)
    from database import release_more_titles, get_db, create_notification
    added = release_more_titles(int(assignment_id), int(count))

    # Notify student
    try:
        with get_db() as conn:
            row = conn.execute("SELECT student_id, niche FROM assignments WHERE id=?", (int(assignment_id),)).fetchone()
            if row:
                create_notification(row["student_id"], "titles_released",
                    f"{added} novos titulos liberados!",
                    f"Voce recebeu {added} novos titulos no nicho {row['niche']}. Acesse seu painel para comecar.",
                    "/student")
    except Exception:
        pass

    return JSONResponse({"ok": True, "added": added})


@router.post("/api/admin/assign-niche")
@limiter.limit("20/minute")
async def api_assign_niche(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    project_id = body.get("project_id", "")
    niche = (body.get("niche") or "").strip()
    titles = body.get("titles", 5)
    if not student_id or not niche:
        return JSONResponse({"error": "student_id e niche obrigatorios"}, status_code=400)
    from database import create_assignment
    aid = create_assignment(int(student_id), project_id, niche, int(titles))
    return JSONResponse({"ok": True, "assignment_id": aid})


@router.post("/api/admin/toggle-student")
@limiter.limit("20/minute")
async def api_toggle_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)
    from database import get_user, update_user
    student = get_user(int(student_id))
    if student:
        update_user(int(student_id), active=0 if student["active"] else 1)
    return JSONResponse({"ok": True})


@router.post("/api/admin/set-project-language")
@limiter.limit("20/minute")
async def api_set_project_language(request: Request, user=Depends(require_admin)):
    """Change the language of a project. Affects title/niche generation."""
    body = await request.json()
    project_id = body.get("project_id", "").strip()
    language = body.get("language", "").strip()
    if not project_id or not language:
        return JSONResponse({"error": "project_id e language obrigatorios"}, status_code=400)
    from database import get_db
    with get_db() as conn:
        conn.execute("UPDATE projects SET language=? WHERE id=?", (language, project_id))
    return JSONResponse({"ok": True, "language": language})


@router.post("/api/admin/set-ai-model")
@limiter.limit("10/minute")
async def api_set_ai_model(request: Request, user=Depends(require_admin)):
    """Set the AI model used when admin shares API with students."""
    body = await request.json()
    model = body.get("model", "").strip()
    if not model:
        return JSONResponse({"error": "model obrigatorio"}, status_code=400)
    from database import set_setting
    set_setting("admin_ai_model", model)
    return JSONResponse({"ok": True})


@router.post("/api/admin/toggle-admin-api")
@limiter.limit("20/minute")
async def api_toggle_admin_api(request: Request, user=Depends(require_admin)):
    """Toggle whether a student can use the admin's LaoZhang API key."""
    body = await request.json()
    student_id = body.get("student_id")
    enable = body.get("enable", False)

    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import update_user, log_activity
    update_user(int(student_id), use_admin_api=1 if enable else 0)
    log_activity("", "admin_api_toggle",
                 f"API admin {'liberada' if enable else 'revogada'} para aluno {student_id}")
    return JSONResponse({"ok": True})


@router.post("/api/admin/delete-student")
@limiter.limit("10/minute")
async def api_delete_student(request: Request, user=Depends(require_admin)):
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)
    try:
        from database import delete_user
        delete_user(int(student_id))
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-student error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao excluir aluno."}, status_code=500)


@router.post("/api/admin/add-student-channel")
@limiter.limit("20/minute")
async def api_admin_add_student_channel(request: Request, user=Depends(require_admin)):
    """Admin adds a YouTube channel to a student."""
    body = await request.json()
    student_id = body.get("student_id")
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    niche = (body.get("niche") or "").strip()
    language = (body.get("language") or "pt-BR").strip()

    if not student_id or not name:
        return JSONResponse({"error": "student_id e nome do canal obrigatorios"}, status_code=400)

    from database import create_student_channel
    project_id = (body.get("project_id") or "").strip()
    try:
        cid = create_student_channel(int(student_id), name, url, niche, language, project_id=project_id)
        return JSONResponse({"ok": True, "channel_id": cid})
    except ValueError as e:
        return JSONResponse({"error": "Falha ao cadastrar canal."}, status_code=400)


@router.post("/api/admin/remove-student-channel")
@limiter.limit("20/minute")
async def api_admin_remove_student_channel(request: Request, user=Depends(require_admin)):
    """Admin removes a channel from a student."""
    body = await request.json()
    channel_id = body.get("channel_id")
    student_id = body.get("student_id")
    if not channel_id:
        return JSONResponse({"error": "channel_id obrigatorio"}, status_code=400)
    from database import delete_student_channel
    delete_student_channel(int(channel_id), int(student_id) if student_id else 0)
    return JSONResponse({"ok": True})


@router.post("/api/regenerate-mindmap")
@limiter.limit("5/minute")
async def api_regenerate_mindmap(request: Request, user=Depends(require_admin)):
    """Regenerate mind map HTML for a project."""
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id or not validate_project_id(project_id):
        return JSONResponse({"error": "project_id invalido"}, status_code=400)

    from database import get_project, get_niches, get_ideas, get_scripts, get_files as db_get_files, save_file, log_activity

    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    niches = get_niches(project_id)
    ideas = get_ideas(project_id)
    scripts = get_scripts(project_id)

    sop = ""
    for f in db_get_files(project_id, "analise"):
        if "sop" in f.get("label", "").lower() and f.get("content"):
            sop = f["content"]
            break

    niche_name = proj.get("niche_chosen") or proj.get("name", "Canal")
    niche_list = [{"name": n["name"], "description": n.get("description", ""),
                   "rpm_range": n.get("rpm_range", ""), "competition": n.get("competition", ""),
                   "pillars": json.loads(n["pillars"]) if isinstance(n.get("pillars"), str) else n.get("pillars", [])}
                  for n in niches]

    idea_list = [{"title": i["title"], "hook": i.get("hook", ""), "summary": i.get("summary", ""),
                  "priority": i.get("priority", "MEDIA")} for i in ideas]

    try:
        mindmap_html = generate_mindmap_html(
            niche_name, proj.get("channel_original", ""), sop,
            niche_list, idea_list[:15], len(scripts),
        )
        mindmap_filename = f"mindmap_{project_id}.html"
        (OUTPUT_DIR / mindmap_filename).write_text(mindmap_html, encoding="utf-8")
        log_activity(project_id, "mindmap_regenerated", "Mind Map atualizado")
        return JSONResponse({"ok": True, "path": f"/output-file?name={mindmap_filename}"})
    except Exception as e:
        logger.error(f"regenerate-mindmap error: {e}")
        return JSONResponse({"error": "Falha ao gerar mind map"}, status_code=500)


@router.post("/api/admin/toggle-file-visibility")
@limiter.limit("20/minute")
async def api_toggle_file_visibility(request: Request, user=Depends(require_admin)):
    """Toggle whether a file is visible to students."""
    body = await request.json()
    file_id = body.get("file_id")
    if not file_id:
        return JSONResponse({"error": "file_id obrigatorio"}, status_code=400)

    from database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT id, visible_to_students FROM files WHERE id=?", (int(file_id),)).fetchone()
        if not row:
            return JSONResponse({"error": "Arquivo nao encontrado"}, status_code=404)
        new_val = 0 if row["visible_to_students"] else 1
        conn.execute("UPDATE files SET visible_to_students=? WHERE id=?", (new_val, int(file_id)))

        # Notify students if file made visible
        if new_val == 1:
            try:
                file_row = conn.execute("SELECT label, project_id FROM files WHERE id=?", (int(file_id),)).fetchone()
                if file_row:
                    students = conn.execute("SELECT DISTINCT student_id FROM assignments WHERE project_id=?",
                                           (file_row["project_id"],)).fetchall()
                    from database import create_notification
                    for s in students:
                        create_notification(s["student_id"], "file_available",
                            "Novo arquivo disponivel!",
                            f"O arquivo '{file_row['label']}' foi liberado para voce.",
                            "/student")
            except Exception:
                pass

    return JSONResponse({"ok": True, "visible": bool(new_val)})


@router.post("/api/admin/bulk-file-visibility")
@limiter.limit("20/minute")
async def api_bulk_file_visibility(request: Request, user=Depends(require_admin)):
    """Set visibility for all files in a project."""
    body = await request.json()
    project_id = body.get("project_id", "")
    visible = body.get("visible", False)
    category = body.get("category", "")

    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_db
    with get_db() as conn:
        if category:
            conn.execute(
                "UPDATE files SET visible_to_students=? WHERE project_id=? AND category=?",
                (1 if visible else 0, project_id, category),
            )
        else:
            conn.execute(
                "UPDATE files SET visible_to_students=? WHERE project_id=?",
                (1 if visible else 0, project_id),
            )

    return JSONResponse({"ok": True})


@router.post("/api/admin/youtube-settings")
@limiter.limit("5/minute")
async def api_admin_youtube_settings(request: Request, user=Depends(require_admin)):
    """Save YouTube API settings."""
    body = await request.json()
    api_key = (body.get("api_key") or "").strip()
    channel_id = (body.get("channel_id") or "").strip()

    from database import set_setting, _encrypt_api_key
    if api_key:
        set_setting("youtube_api_key", _encrypt_api_key(api_key))
    if channel_id:
        # Clean up: extract handle or ID from full URL
        cleaned = _extract_channel_identifier(channel_id)
        set_setting("youtube_channel_id", cleaned)
    return JSONResponse({"ok": True})


@router.post("/api/admin/save-dataforseo")
@limiter.limit("10/minute")
async def api_save_dataforseo(request: Request, user=Depends(require_admin)):
    """Save DataForSEO credentials to admin_settings."""
    body = await request.json()
    login = (body.get("login") or "").strip()
    password = (body.get("password") or "").strip()

    if not login or not password:
        return JSONResponse({"error": "Login e password obrigatorios"}, status_code=400)

    from database import set_setting
    set_setting("dataforseo_login", login)
    set_setting("dataforseo_password", password)

    # Clear cached credentials so next call picks up new ones
    from protocols.keywords_everywhere import _DATAFORSEO_LOGIN
    import protocols.keywords_everywhere as kw_mod
    kw_mod._DATAFORSEO_LOGIN = ""
    kw_mod._DATAFORSEO_PASSWORD = ""

    # Quick validation — check balance
    from protocols.keywords_everywhere import check_credits
    result = check_credits()
    if "error" in result:
        return JSONResponse({"ok": True, "warning": f"Salvo, mas verificacao falhou: {result['error']}"})

    return JSONResponse({"ok": True, "balance": result.get("balance", 0)})


def _extract_channel_identifier(raw: str) -> str:
    """Extract @handle or UCxxx from various YouTube URL formats."""
    import re as _re
    raw = raw.strip().rstrip("/")
    # https://youtube.com/@Handle or https://www.youtube.com/@Handle
    m = _re.search(r'youtube\.com/(@[\w.-]+)', raw)
    if m:
        return m.group(1)
    # https://youtube.com/channel/UCxxxxxx
    m = _re.search(r'youtube\.com/channel/(UC[\w-]+)', raw)
    if m:
        return m.group(1)
    # https://youtube.com/c/ChannelName
    m = _re.search(r'youtube\.com/c/([\w.-]+)', raw)
    if m:
        return m.group(1)
    # Already a bare @handle or UCxxx
    return raw


@router.get("/api/admin/youtube-stats")
@limiter.limit("5/minute")
async def api_admin_youtube_stats(request: Request, user=Depends(require_admin)):
    """Fetch YouTube channel stats using YouTube Data API.
    Resolves @handle to channel ID automatically.
    """
    from database import get_setting, _decrypt_api_key, set_setting

    yt_key = _decrypt_api_key(get_setting("youtube_api_key"))
    channel_id = get_setting("youtube_channel_id")

    if not yt_key or not channel_id:
        return JSONResponse({"error": "Configure YouTube API key e Channel ID primeiro"}, status_code=400)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:

            # If it's a @handle, resolve to channel ID first
            if channel_id.startswith("@"):
                search_resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "q": channel_id, "type": "channel", "maxResults": 1, "key": yt_key},
                )
                search_data = search_resp.json()
                items = search_data.get("items", [])
                if not items:
                    # Try channels list with forHandle
                    handle_resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/channels",
                        params={"part": "id", "forHandle": channel_id.lstrip("@"), "key": yt_key},
                    )
                    handle_data = handle_resp.json()
                    h_items = handle_data.get("items", [])
                    if h_items:
                        channel_id = h_items[0]["id"]
                        set_setting("youtube_channel_id", channel_id)
                    else:
                        return JSONResponse({"error": f"Handle {channel_id} nao encontrado"}, status_code=404)
                else:
                    channel_id = items[0]["snippet"]["channelId"]
                    set_setting("youtube_channel_id", channel_id)

            # Fetch channel stats
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "statistics,snippet", "id": channel_id, "key": yt_key},
            )
            data = resp.json()

        if "items" not in data or not data["items"]:
            return JSONResponse({"error": "Canal nao encontrado. Verifique o Channel ID."}, status_code=404)

        ch = data["items"][0]
        stats = ch.get("statistics", {})
        snippet = ch.get("snippet", {})

        return JSONResponse({
            "ok": True,
            "channel": snippet.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
            "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
        })
    except Exception as e:
        logger.error(f"youtube-stats error: {e}")
        return JSONResponse({"error": "Falha ao buscar estatisticas"}, status_code=500)
