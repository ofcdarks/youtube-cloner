"""
NotebookLM API routes — sends the 5 prompts sequentially, extracts DNA.

Flow:
1. Admin creates notebook manually on notebooklm.google.com + adds sources
2. GET /api/admin/nlm/notebooks → lists available notebooks
3. POST /api/admin/nlm/extract-dna → sends 5 prompts one by one, waits, adapts
4. POST /api/admin/nlm/ask → free-form question
"""

import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from auth import require_admin

logger = logging.getLogger("ytcloner.routes.nlm_api")

router = APIRouter(prefix="/api/admin/nlm", tags=["notebooklm"])


@router.get("/status")
async def nlm_status(request: Request, user=Depends(require_admin)):
    from protocols.notebooklm_client import get_status
    return JSONResponse(get_status())


@router.get("/notebooks")
async def nlm_list_notebooks(request: Request, user=Depends(require_admin)):
    from protocols.notebooklm_client import is_available, list_notebooks
    if not is_available():
        return JSONResponse({"error": "NotebookLM nao disponivel. Execute: notebooklm login"}, status_code=400)
    try:
        notebooks = await list_notebooks()
        return JSONResponse({"ok": True, "notebooks": notebooks})
    except Exception as e:
        logger.error(f"nlm list notebooks: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/ask")
async def nlm_ask(request: Request, user=Depends(require_admin)):
    body = await request.json()
    notebook_id = body.get("notebook_id", "")
    question = (body.get("question") or "").strip()
    if not notebook_id or not question:
        return JSONResponse({"error": "notebook_id e question obrigatorios"}, status_code=400)

    from protocols.notebooklm_client import ask
    try:
        answer = await ask(notebook_id, question)
        return JSONResponse({"ok": True, "answer": answer})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/extract-dna")
async def nlm_extract_dna(request: Request, user=Depends(require_admin)):
    """Send all 5 prompts to the notebook, one by one, wait for each response.

    Adapts follow-up prompts if responses are thin. Saves everything to project.

    Body: {notebook_id, project_id (optional), niche_name}
    """
    body = await request.json()
    notebook_id = body.get("notebook_id", "")
    project_id = body.get("project_id", "")
    niche_name = (body.get("niche_name") or "Canal").strip()

    if not notebook_id:
        return JSONResponse({"error": "notebook_id obrigatorio. Liste seus notebooks em GET /api/admin/nlm/notebooks"}, status_code=400)

    from protocols.notebooklm_client import is_available, extract_dna, compile_sop, extract_rpm, extract_schedule

    if not is_available():
        return JSONResponse({"error": "NotebookLM nao disponivel"}, status_code=400)

    try:
        # Send all 5 prompts sequentially (waits for each response)
        dna = await extract_dna(notebook_id, niche_name)

        # Compile into single SOP
        sop_text = compile_sop(dna, niche_name)

        # Extract RPM and schedule
        rpm = extract_rpm(dna)
        schedule = extract_schedule(dna)

        # Save to project
        if project_id:
            from database import save_file, log_activity

            # Save complete SOP
            save_file(project_id, "analise", f"SOP — {niche_name} (NotebookLM)",
                      f"sop_nlm_{project_id}.md", sop_text)

            # Save each part individually
            for key, entry in dna.items():
                content = entry.get("content", "")
                label = entry.get("label", key)
                if content and not content.startswith("Erro:"):
                    save_file(project_id, "analise", label,
                              f"dna_{key}_{project_id}.md", content)

            words_total = sum(e.get("words", 0) for e in dna.values())
            parts_ok = sum(1 for e in dna.values() if not e.get("content", "").startswith("Erro:"))
            followups = sum(1 for e in dna.values() if e.get("had_followup"))

            log_activity(project_id, "nlm_dna_extracted",
                         f"DNA: {parts_ok}/5 partes, {words_total} palavras, {followups} follow-ups")

        # Response summary
        summary = {}
        for key, entry in dna.items():
            summary[key] = {
                "label": entry["label"],
                "words": entry.get("words", 0),
                "had_followup": entry.get("had_followup", False),
                "ok": not entry.get("content", "").startswith("Erro:"),
            }

        return JSONResponse({
            "ok": True,
            "parts": summary,
            "total_words": sum(e.get("words", 0) for e in dna.values()),
            "rpm": rpm,
            "schedule": schedule,
            "sop_preview": sop_text[:1000],
        })
    except Exception as e:
        logger.error(f"nlm extract-dna: {e}")
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/build-channel")
async def nlm_build_channel(request: Request, user=Depends(require_admin)):
    """FULL ORCHESTRATION: NLM DNA → Claude analysis → complete channel strategy.

    1. Sends 5 prompts to NotebookLM (waits for each)
    2. Claude analyzes all responses and fills gaps
    3. Generates: enhanced SOP, launch plan, channel identity, first 10 titles
    4. Saves everything to the project

    Body: {notebook_id, project_id, niche_name, channel_url}
    """
    body = await request.json()
    notebook_id = body.get("notebook_id", "")
    project_id = body.get("project_id", "")
    niche_name = (body.get("niche_name") or "Canal").strip()
    channel_url = (body.get("channel_url") or "").strip()

    if not notebook_id:
        return JSONResponse({"error": "notebook_id obrigatorio"}, status_code=400)

    from protocols.notebooklm_client import is_available, extract_dna
    from protocols.channel_strategist import analyze_and_build_strategy

    if not is_available():
        return JSONResponse({"error": "NotebookLM nao disponivel"}, status_code=400)

    try:
        # ── Step 1: Extract DNA from NotebookLM (5 prompts) ──
        logger.info(f"[BUILD] Step 1/2: Extracting DNA from NLM for '{niche_name}'")
        dna = await extract_dna(notebook_id, niche_name)

        parts_ok = sum(1 for e in dna.values() if not e.get("content", "").startswith("Erro:"))
        if parts_ok == 0:
            return JSONResponse({"error": "NotebookLM nao retornou nenhuma resposta valida"}, status_code=500)

        # ── Step 2: Claude processes everything ──
        logger.info(f"[BUILD] Step 2/2: Claude analyzing {parts_ok}/5 parts")

        # Get AI chat function
        from protocols.ai_client import chat as ai_chat
        def chat_fn(prompt, system=""):
            return ai_chat(prompt, system=system, max_tokens=8000)

        strategy = analyze_and_build_strategy(dna, niche_name, channel_url, ai_chat_fn=chat_fn)

        # ── Step 3: Save everything to project ──
        saved_files = []
        if project_id:
            from database import save_file, log_activity

            # Enhanced SOP
            if strategy.get("enhanced_sop"):
                save_file(project_id, "analise", f"SOP Completo — {niche_name}",
                          f"sop_{project_id}.md", strategy["enhanced_sop"])
                saved_files.append("SOP Completo")

            # Launch plan
            if strategy.get("launch_plan"):
                save_file(project_id, "analise", f"Plano de Lancamento — {niche_name}",
                          f"launch_plan_{project_id}.md", strategy["launch_plan"])
                saved_files.append("Plano de Lancamento")

            # Channel identity
            if strategy.get("channel_identity"):
                save_file(project_id, "analise", f"Identidade do Canal — {niche_name}",
                          f"channel_identity_{project_id}.md", strategy["channel_identity"])
                saved_files.append("Identidade do Canal")

            # First 10 titles
            if strategy.get("first_titles"):
                save_file(project_id, "analise", f"Primeiros 10 Videos — {niche_name}",
                          f"first_titles_{project_id}.md", strategy["first_titles"])
                saved_files.append("Primeiros 10 Videos")

            # Raw NLM responses (reference)
            if strategy.get("raw_sop"):
                save_file(project_id, "analise", f"DNA Bruto (NotebookLM) — {niche_name}",
                          f"dna_raw_{project_id}.md", strategy["raw_sop"])
                saved_files.append("DNA Bruto")

            log_activity(project_id, "channel_built",
                         f"Canal '{niche_name}' construido: {len(saved_files)} arquivos gerados")

        return JSONResponse({
            "ok": True,
            "niche": niche_name,
            "nlm_parts": parts_ok,
            "files_generated": saved_files,
            "metrics": strategy.get("metrics", {}),
            "sop_preview": (strategy.get("enhanced_sop") or "")[:800],
            "launch_preview": (strategy.get("launch_plan") or "")[:500],
            "identity_preview": (strategy.get("channel_identity") or "")[:500],
        })

    except Exception as e:
        logger.error(f"nlm build-channel: {e}")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)
