"""
Drive Admin Routes — Google Drive management for projects and students.
Extracted from dashboard.py for modularity.
"""

import logging
import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_admin
from config import OUTPUT_DIR
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.drive_admin")

router = APIRouter(tags=["drive-admin"])


@router.get("/api/admin/gdrive/admin-root-status")
async def api_gdrive_admin_root_status(request: Request, user=Depends(require_admin)):
    """
    Diagnostic endpoint for the Drive admin root folder.
    Returns current state and allows identifying why project folders
    might be failing to nest under the admin root.
    """
    from database import get_setting
    result: dict = {"ok": True}
    try:
        saved_id = get_setting("drive_admin_root_id") or ""
        result["saved_id"] = saved_id
        result["saved_id_present"] = bool(saved_id)

        from protocols.google_export import get_drive_service
        try:
            drive = get_drive_service()
            result["drive_service"] = "connected"
        except Exception as e:
            result["drive_service"] = "error"
            result["drive_error"] = str(e)[:200]
            return JSONResponse(result)

        # Verify saved folder still exists
        if saved_id:
            try:
                info = drive.files().get(fileId=saved_id, fields="id,name,trashed,webViewLink").execute()
                result["saved_folder_exists"] = not info.get("trashed", False)
                result["saved_folder_name"] = info.get("name", "")
                result["saved_folder_url"] = info.get("webViewLink", "")
            except Exception as e:
                result["saved_folder_exists"] = False
                result["saved_folder_error"] = str(e)[:200]

        # Search for any "YT Cloner" folders owned by user (detect duplicates)
        try:
            q = "name='YT Cloner' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            found = drive.files().list(q=q, fields="files(id,name,webViewLink,createdTime)").execute()
            result["all_yt_cloner_folders"] = found.get("files", [])
            result["duplicates_count"] = max(0, len(found.get("files", [])) - 1)
        except Exception as e:
            result["list_error"] = str(e)[:200]
    except Exception as e:
        logger.exception(f"admin-root-status error: {e}")
        result["ok"] = False
        result["error"] = str(e)[:200]

    return JSONResponse(result)


@router.post("/api/admin/gdrive/reset-admin-root")
async def api_gdrive_reset_admin_root(request: Request, user=Depends(require_admin)):
    """
    Force re-creation of the admin root folder. Use if it got deleted or
    if projects are being created as flat folders instead of nested.
    """
    from database import set_setting
    try:
        # Clear cached value
        from protocols import google_export
        google_export._admin_root_id = None
        set_setting("drive_admin_root_id", "")

        # Trigger recreation
        new_id = google_export.get_admin_root_folder()
        return JSONResponse({
            "ok": True,
            "new_admin_root_id": new_id,
            "message": "Admin root recriado — novos projetos vao usar essa pasta",
        })
    except Exception as e:
        logger.exception(f"reset-admin-root error: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/api/admin/connect-drive")
@limiter.limit("5/minute")
async def api_connect_drive(request: Request, user=Depends(require_admin)):
    """Create Google Drive folder for an existing project that doesn't have one."""
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    from database import get_project, update_project, get_files, save_file, log_activity

    proj = get_project(project_id)
    if not proj:
        return JSONResponse({"error": "Projeto nao encontrado"}, status_code=404)

    if proj.get("drive_folder_id"):
        return JSONResponse({
            "ok": True,
            "already_connected": True,
            "drive_folder_url": proj.get("drive_folder_url", ""),
        })

    try:
        from protocols.google_export import create_folder, create_doc, create_sheet
        import json as _json

        niche_name = proj.get("niche_chosen") or proj.get("name", "Projeto")

        # Get or create project folder (no duplicates)
        from protocols.google_export import get_or_create_project_folder
        folder_id = get_or_create_project_folder(niche_name)
        drive_url = f"https://drive.google.com/drive/folders/{folder_id}"
        update_project(project_id, drive_folder_id=folder_id, drive_folder_url=drive_url)

        # Upload existing files to Drive
        files = get_files(project_id)
        uploaded = 0
        for f in files:
            content = f.get("content", "") or ""
            if not content or len(content) < 50:
                continue
            cat = f.get("category", "")
            label = f.get("label", f.get("filename", ""))
            try:
                if cat in ("analise", "seo", "roteiro", "narracao", "outros", "visual"):
                    create_doc(label, content, folder_id)
                    uploaded += 1
            except Exception as e:
                logger.warning(f"Drive upload failed for {label}: {e}")

        # Upload ideas as Sheet
        try:
            from database import get_ideas
            ideas = get_ideas(project_id)
            if ideas:
                data = [["#", "Titulo", "Hook", "Pilar", "Prioridade", "Score"]]
                for i, idea in enumerate(ideas, 1):
                    data.append([str(i), idea.get("title", ""), idea.get("hook", "")[:100],
                                idea.get("pillar", ""), idea.get("priority", ""), str(idea.get("score", 0))])
                create_sheet(f"Titulos - {niche_name}", data, folder_id)
                uploaded += 1
        except Exception:
            pass

        # Upload niches as Sheet
        try:
            from database import get_niches
            niches = get_niches(project_id)
            if niches:
                data = [["Nome", "Descricao", "RPM", "Competicao", "Escolhido"]]
                for n in niches:
                    pillars = n.get("pillars", "")
                    if isinstance(pillars, str):
                        try:
                            import json as _j2
                            pillars = ", ".join(_j2.loads(pillars))
                        except Exception:
                            pass
                    data.append([n.get("name", ""), n.get("description", "")[:100],
                                n.get("rpm_range", ""), n.get("competition", ""),
                                "Sim" if n.get("chosen") else ""])
                create_sheet(f"5 Nichos Derivados - {niche_name}", data, folder_id)
                uploaded += 1
        except Exception:
            pass

        # Upload SEO details as Sheet
        try:
            from database import get_ideas as _gi2
            ideas2 = _gi2(project_id)
            seo_data = [["#", "Titulo", "Score", "Rating", "Pilar", "Prioridade"]]
            for i, idea in enumerate(ideas2[:15], 1):
                seo_data.append([str(i), idea.get("title", ""), str(idea.get("score", 0)),
                                idea.get("rating", ""), idea.get("pillar", ""), idea.get("priority", "")])
            if len(seo_data) > 1:
                create_sheet(f"SEO Sheet - Titulos e Tags ({len(seo_data)-1} videos)", seo_data, folder_id)
                uploaded += 1
        except Exception:
            pass

        # Mind Map as standalone doc
        try:
            mindmap_file = OUTPUT_DIR / f"mindmap_{project_id}.html"
            if mindmap_file.exists():
                mm_content = mindmap_file.read_text(encoding="utf-8")
                if len(mm_content) > 100:
                    create_doc(f"MIND MAP - Visao Geral do Projeto", mm_content[:50000], folder_id)
                    uploaded += 1
        except Exception:
            pass

        log_activity(project_id, "drive_connected", f"Google Drive conectado: {uploaded} arquivos enviados")

        return JSONResponse({
            "ok": True,
            "drive_folder_url": drive_url,
            "uploaded": uploaded,
        })
    except Exception as e:
        logger.error(f"connect-drive error: {e}", exc_info=True)
        msg = str(e)
        if "nao conectado" in msg.lower() or "not connected" in msg.lower():
            return JSONResponse({"error": "Google Drive nao conectado. Va em Admin Panel > Google Drive para autenticar."}, status_code=400)
        if "expired" in msg.lower() or "invalid_grant" in msg.lower():
            return JSONResponse({"error": "Token do Google Drive expirado. Reconecte em Admin Panel > Google Drive."}, status_code=400)
        return JSONResponse({"error": f"Falha ao conectar Google Drive: {msg[:200]}"}, status_code=500)


@router.post("/api/admin/sync-drive")
@limiter.limit("5/minute")
async def api_sync_drive(request: Request, user=Depends(require_admin)):
    """Re-sync all project files to Google Drive (14 standard files)."""
    body = await request.json()
    project_id = body.get("project_id", "")
    if not project_id:
        return JSONResponse({"error": "project_id obrigatorio"}, status_code=400)

    import asyncio

    def _sync():
        from database import get_project, get_files, get_ideas, get_niches, log_activity, update_project
        from protocols.google_export import (
            create_doc, create_sheet, get_drive_service,
            get_or_create_project_folder,
        )

        proj = get_project(project_id)
        if not proj:
            return {"error": "Projeto nao encontrado"}

        niche_name = proj.get("niche_chosen") or proj.get("name", "Projeto")
        folder_id = proj.get("drive_folder_id", "") or ""
        folder_created = False
        folder_recreated = False

        # Verify folder still exists in Drive (it may have been deleted manually).
        # If it doesn't exist OR project never had one, create it now via the
        # admin-root-aware helper (no flat folders, no duplicates).
        try:
            drive = get_drive_service()
        except Exception as e:
            logger.error(f"Drive sync: drive_service unavailable: {e}")
            return {"error": "Google Drive nao conectado. Conecte em Admin > Drive."}

        folder_valid = False
        if folder_id:
            try:
                info = drive.files().get(
                    fileId=folder_id, fields="id,trashed"
                ).execute()
                folder_valid = not info.get("trashed", False)
            except Exception as e:
                logger.warning(f"Drive sync: saved folder {folder_id} not found ({e}) — will recreate")
                folder_valid = False

        if not folder_valid:
            try:
                folder_id = get_or_create_project_folder(niche_name)
                if not folder_id:
                    return {"error": "Falha ao criar pasta no Drive."}
                update_project(
                    project_id,
                    drive_folder_id=folder_id,
                    drive_folder_url=f"https://drive.google.com/drive/folders/{folder_id}",
                )
                folder_created = not bool(proj.get("drive_folder_id"))
                folder_recreated = bool(proj.get("drive_folder_id")) and not folder_created
                logger.info(f"Drive sync: {'created' if folder_created else 'recreated'} folder {folder_id} for {niche_name}")
            except Exception as e:
                logger.error(f"Drive sync: failed to create folder: {e}")
                return {"error": f"Falha ao criar pasta no Drive: {str(e)[:120]}"}

        uploaded = 0
        skipped = 0

        # List existing files in Drive folder to avoid duplicates
        existing_names = set()
        try:
            results = drive.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(name)",
                pageSize=100,
            ).execute()
            existing_names = {f["name"] for f in results.get("files", [])}
            logger.info(f"Drive sync: {len(existing_names)} existing files in folder")
        except Exception as e:
            logger.warning(f"Drive sync: could not list existing files: {e}")

        def _doc(title, content):
            nonlocal uploaded, skipped
            if content and len(content) > 50:
                if title in existing_names:
                    skipped += 1
                    return
                try:
                    create_doc(title, content, folder_id)
                    uploaded += 1
                    existing_names.add(title)
                except Exception as e:
                    logger.warning(f"Sync doc '{title}': {e}")

        def _sheet(title, data):
            nonlocal uploaded, skipped
            if data and len(data) > 1:
                if title in existing_names:
                    skipped += 1
                    return
                try:
                    create_sheet(title, data, folder_id)
                    uploaded += 1
                    existing_names.add(title)
                except Exception as e:
                    logger.warning(f"Sync sheet '{title}': {e}")

        files = get_files(project_id)
        ideas = get_ideas(project_id)
        niches = get_niches(project_id)

        # 1. SOP
        sop = next((f for f in files if f.get("category") == "analise"), None)
        if sop:
            _doc(f"SOP - {niche_name}", sop.get("content", ""))

        # 2. SEO Pack
        seo = next((f for f in files if f.get("category") == "seo"), None)
        if seo:
            _doc(f"SEO Pack - {niche_name}", seo.get("content", ""))

        # 3-5. Roteiros
        roteiros = [f for f in files if f.get("category") == "roteiro"]
        for i, rf in enumerate(roteiros[:3], 1):
            _doc(f"Roteiro {i} - {rf.get('label', '').replace('Roteiro - ', '')}", rf.get("content", ""))

        # 6. Thumbnails
        thumb = next((f for f in files if "thumbnail" in (f.get("filename", "") or "").lower()), None)
        if thumb:
            _doc("Thumbnail Prompts - Midjourney DALL-E", thumb.get("content", ""))

        # 7. Music
        music = next((f for f in files if "music" in (f.get("filename", "") or "").lower()), None)
        if music:
            _doc("Music Prompts - Suno Udio MusicGPT", music.get("content", ""))

        # 8. Teaser
        teaser = next((f for f in files if "teaser" in (f.get("filename", "") or "").lower()), None)
        if teaser:
            _doc("Teaser Prompts - Shorts Reels TikTok", teaser.get("content", ""))

        # 9. Mind Map
        mindmap = next((f for f in files if f.get("category") == "visual"), None)
        if mindmap:
            _doc("MIND MAP - Visao Geral do Projeto", mindmap.get("content", ""))
        else:
            mm_file = OUTPUT_DIR / f"mindmap_{project_id}.html"
            if mm_file.exists():
                _doc("MIND MAP - Visao Geral do Projeto", mm_file.read_text(encoding="utf-8")[:50000])

        # 10. 30 Ideias (Doc)
        if ideas:
            ideas_text = f"# 30 Ideias de Videos - {niche_name}\n\n"
            for idx, idea in enumerate(ideas, 1):
                ideas_text += f"## {idx}. {idea.get('title', '')}\n"
                ideas_text += f"**Hook:** {idea.get('hook', '')}\n"
                ideas_text += f"**Pilar:** {idea.get('pillar', '')} | **Prioridade:** {idea.get('priority', '')}\n\n"
            _doc(f"30 Ideias de Videos - {niche_name}", ideas_text)

        # 11. Titulos (Sheet)
        if ideas:
            td = [["#", "Titulo", "Hook", "Pilar", "Prioridade", "Score"]]
            for idx, idea in enumerate(ideas, 1):
                td.append([str(idx), idea.get("title",""), idea.get("hook","")[:100],
                          idea.get("pillar",""), idea.get("priority",""), str(idea.get("score",0))])
            _sheet(f"Titulos - {niche_name}", td)

        # 12. Nichos (Sheet)
        if niches:
            nd = [["Nome", "Descricao", "RPM", "Competicao"]]
            for n in niches:
                nd.append([n.get("name",""), n.get("description","")[:100],
                          n.get("rpm_range",""), n.get("competition","")])
            _sheet("5 Nichos Derivados - Niche Bending", nd)

        # 13. SEO Sheet
        if ideas:
            sd = [["#", "Titulo", "Score", "Rating", "Pilar", "Prioridade"]]
            for idx, idea in enumerate(ideas[:15], 1):
                sd.append([str(idx), idea.get("title",""), str(idea.get("score",0)),
                          idea.get("rating",""), idea.get("pillar",""), idea.get("priority","")])
            _sheet(f"SEO Sheet - Titulos e Tags ({len(sd)-1} videos)", sd)

        # 14. Narracoes
        narracoes = [f for f in files if f.get("category") == "narracao"]
        if narracoes:
            combined = ""
            for idx, nf in enumerate(narracoes[:3], 1):
                combined += f"\n{'='*60}\nNARRACAO {idx}: {nf.get('label', '')}\n{'='*60}\n\n"
                combined += (nf.get("content", "") or "") + "\n\n"
            _doc(f"Narracoes Completas - {niche_name}", combined)

        action_label = "drive_folder_created" if folder_created else ("drive_folder_recreated" if folder_recreated else "drive_synced")
        log_activity(project_id, action_label, f"{uploaded} novos + {skipped} ja existentes no Drive")
        return {
            "ok": True,
            "uploaded": uploaded,
            "skipped": skipped,
            "folder_id": folder_id,
            "folder_created": folder_created,
            "folder_recreated": folder_recreated,
        }

    try:
        result = await asyncio.to_thread(_sync)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"sync-drive error: {e}")
        return JSONResponse({"error": "Falha ao sincronizar com Google Drive."}, status_code=500)


@router.post("/api/admin/create-student-drive")
@limiter.limit("5/minute")
async def api_create_student_drive(request: Request, user=Depends(require_admin)):
    """Create Google Drive folder for a student and share with their email."""
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import get_user, set_student_drive_folder, log_activity
    student = get_user(int(student_id))
    if not student:
        return JSONResponse({"error": "Aluno nao encontrado"}, status_code=404)

    if student.get("drive_folder_id"):
        return JSONResponse({"error": "Aluno ja tem pasta Drive"}, status_code=400)

    try:
        from protocols.google_export import get_or_create_student_folder, share_folder, find_or_create_subfolder, create_doc
        from database import get_student_channels, get_db, save_student_drive_file

        # 1. Create root folder + share
        folder_id = get_or_create_student_folder(student["name"])
        share_folder(folder_id, student["email"], "writer")
        set_student_drive_folder(int(student_id), folder_id)

        # 2. Create channel subfolders
        channels = get_student_channels(int(student_id))
        synced = 0
        for ch in channels:
            ch_name = ch.get("channel_name", "Canal")
            find_or_create_subfolder(ch_name, folder_id)
            logger.info(f"[DRIVE] Channel folder created: {ch_name}")

        # 3. Auto-sync existing files
        with get_db() as conn:
            assignments = conn.execute(
                "SELECT DISTINCT project_id FROM assignments WHERE student_id=?",
                (int(student_id),),
            ).fetchall()
            project_ids = [a["project_id"] for a in assignments]

            if project_ids:
                placeholders = ",".join("?" * len(project_ids))
                files = conn.execute(f"""
                    SELECT f.id, f.category, f.label, f.filename, f.content, f.project_id
                    FROM files f
                    WHERE f.project_id IN ({placeholders})
                    AND f.category NOT IN ('analise', 'visual')
                    AND f.content IS NOT NULL AND f.content != ''
                    AND LENGTH(f.content) > 50
                    ORDER BY f.created_at
                """, project_ids).fetchall()

                # Check already synced
                existing_synced = set()
                for row in conn.execute(
                    "SELECT file_id FROM student_drive_files WHERE student_id=?",
                    (int(student_id),),
                ).fetchall():
                    existing_synced.add(row["file_id"])

                # Map channels to projects
                channel_by_project = {}
                for ch in channels:
                    if ch.get("project_id"):
                        channel_by_project[ch["project_id"]] = ch.get("channel_name", "Canal")

                for f in files:
                    f = dict(f)
                    if f["id"] in existing_synced:
                        continue
                    try:
                        ch_name = channel_by_project.get(f["project_id"], "Projeto")
                        ch_folder = find_or_create_subfolder(ch_name, folder_id)
                        doc_id = create_doc(f["label"], f["content"], ch_folder)
                        if doc_id:
                            save_student_drive_file(int(student_id), f["id"], doc_id, ch_folder,
                                                   f["filename"], f["label"], f["category"])
                            synced += 1
                    except Exception as e:
                        logger.warning(f"[DRIVE] Sync file failed: {f['filename']}: {e}")

        log_activity("", "drive_student_created",
                     f"Pasta Drive criada para {student['name']} + {synced} arquivos sincronizados")
        return JSONResponse({
            "ok": True,
            "folder_id": folder_id,
            "folder_url": f"https://drive.google.com/drive/folders/{folder_id}",
            "channels_created": len(channels),
            "files_synced": synced,
        })
    except Exception as e:
        logger.error(f"create-student-drive error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao criar pasta Drive. Verifique a conexao Google Drive."}, status_code=500)


@router.post("/api/admin/sync-student-drive")
@limiter.limit("3/minute")
async def api_sync_student_drive(request: Request, user=Depends(require_admin)):
    """Sync all existing student files to their Google Drive folder."""
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import get_user, get_db, get_student_drive_folder

    student = get_user(int(student_id))
    if not student:
        return JSONResponse({"error": "Aluno nao encontrado"}, status_code=404)

    folder_id = get_student_drive_folder(int(student_id))
    if not folder_id:
        return JSONResponse({"error": "Aluno nao tem pasta Drive. Crie primeiro."}, status_code=400)

    try:
        from protocols.google_export import create_doc, find_or_create_subfolder
        from database import get_student_channels, save_student_drive_file

        synced = 0

        # Get all visible files for projects this student is assigned to
        with get_db() as conn:
            assignments = conn.execute(
                "SELECT DISTINCT project_id FROM assignments WHERE student_id=?",
                (int(student_id),),
            ).fetchall()
            project_ids = [a["project_id"] for a in assignments]

            if not project_ids:
                return JSONResponse({"ok": True, "synced": 0, "message": "Nenhum projeto atribuido"})

            placeholders = ",".join("?" * len(project_ids))
            # Sync student-accessible files to Drive:
            # INCLUDE: roteiros, narracoes, SEO, thumbnails, music, teasers, trends, disclaimers
            # EXCLUDE: SOP/analise (admin-only), mind maps (visual), nichos brutos
            files = conn.execute(f"""
                SELECT f.id, f.category, f.label, f.filename, f.content, f.project_id
                FROM files f
                WHERE f.project_id IN ({placeholders})
                AND f.content IS NOT NULL AND f.content != ''
                AND LENGTH(f.content) > 50
                AND f.category NOT IN ('analise', 'visual')
                ORDER BY f.created_at
            """, project_ids).fetchall()

        # Get channels for subfolder naming
        channels = get_student_channels(int(student_id))
        channel_by_project = {}
        for ch in channels:
            if ch.get("project_id"):
                channel_by_project[ch["project_id"]] = ch.get("channel_name", "Canal")

        # Check which files are already synced
        with get_db() as conn:
            existing = set()
            for row in conn.execute(
                "SELECT file_id FROM student_drive_files WHERE student_id=?",
                (int(student_id),),
            ).fetchall():
                existing.add(row["file_id"])

        # Sync each file
        for f in files:
            f = dict(f)
            if f["id"] in existing:
                continue  # Already synced

            try:
                # Create channel subfolder
                channel_name = channel_by_project.get(f["project_id"], "Projeto")
                channel_folder = find_or_create_subfolder(channel_name, folder_id)

                # Create doc in Drive
                doc_id = create_doc(f["label"], f["content"], channel_folder)
                if doc_id:
                    save_student_drive_file(
                        int(student_id), f["id"], doc_id, channel_folder,
                        f["filename"], f["label"], f["category"],
                    )
                    synced += 1
            except Exception as e:
                logger.warning(f"Sync file {f['filename']} failed: {e}")
                continue

        return JSONResponse({"ok": True, "synced": synced})
    except Exception as e:
        logger.error(f"sync-student-drive error: {e}", exc_info=True)
        return JSONResponse({"error": "Falha ao sincronizar arquivos."}, status_code=500)


@router.post("/api/admin/delete-student-drive")
@limiter.limit("5/minute")
async def api_delete_student_drive(request: Request, user=Depends(require_admin)):
    """Delete a student's Google Drive folder."""
    body = await request.json()
    student_id = body.get("student_id")
    if not student_id:
        return JSONResponse({"error": "student_id obrigatorio"}, status_code=400)

    from database import get_user, set_student_drive_folder, log_activity
    student = get_user(int(student_id))
    if not student:
        return JSONResponse({"error": "Aluno nao encontrado"}, status_code=404)

    folder_id = student.get("drive_folder_id", "")
    if not folder_id:
        return JSONResponse({"error": "Aluno nao tem pasta Drive"}, status_code=400)

    try:
        from protocols.google_export import delete_drive_file
        delete_drive_file(folder_id)  # Deleting a folder deletes all contents
        set_student_drive_folder(int(student_id), "")
        log_activity("", "drive_student_deleted",
                     f"Pasta Drive removida de {student['name']}")
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"delete-student-drive error: {e}", exc_info=True)
        # Even if Drive delete fails, clear the reference
        set_student_drive_folder(int(student_id), "")
        return JSONResponse({"ok": True, "warning": "Pasta pode nao ter sido removida do Drive"})
