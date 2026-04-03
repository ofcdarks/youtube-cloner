"""
Services — business logic for channel analysis, mind map generation, data helpers.

This module contains the heavy processing extracted from the monolithic dashboard.
"""

import json
import re
import logging
from pathlib import Path

from config import OUTPUT_DIR, PROJECTS_DIR, MAX_TOKENS_LARGE, MAX_TOKENS_MEDIUM

logger = logging.getLogger("ytcloner.services")


# ── Data Helpers ─────────────────────────────────────────

def get_filesystem_projects() -> list[dict]:
    """Load projects from filesystem (legacy compatibility)."""
    projects = []
    try:
        for p in sorted(PROJECTS_DIR.iterdir(), reverse=True):
            if p.is_dir():
                meta_file = p / "meta.json"
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    meta["path"] = str(p)
                    meta["id"] = p.name
                    meta["file_count"] = len(list(p.glob("*.md")))
                    projects.append(meta)
    except Exception:
        pass
    return projects


def get_project_files(project_id: str) -> list[dict]:
    """List markdown files in a project directory."""
    project_dir = PROJECTS_DIR / project_id
    files = []
    if project_dir.exists():
        for f in sorted(project_dir.glob("*.md")):
            files.append({
                "name": f.stem,
                "path": str(f),
                "size": f.stat().st_size,
                "label": f.stem.replace("_", " ").title(),
            })
    return files


def get_output_files() -> list[dict]:
    """List output files (legacy SOPs, narrations, etc)."""
    files = []
    patterns = [
        "loaded_dice_*.md",
        "narration_roteiro_*.txt",
        "loaded_dice_narration.md",
        "roteiro_*.md",
        "narration_*.txt",
    ]
    seen: set[str] = set()
    try:
        for pattern in patterns:
            for f in sorted(OUTPUT_DIR.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.name not in seen:
                    seen.add(f.name)
                    files.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "mtime": f.stat().st_mtime,
                        "label": f.stem.replace("_", " ").title(),
                        "category": _categorize_file(f.name),
                    })
    except Exception:
        pass
    return files


def _categorize_file(filename: str) -> str:
    """Categorize a file by name pattern."""
    name = filename.lower()
    if "sop" in name:
        return "analise"
    if "narration" in name or "narracao" in name:
        return "narracao"
    if "roteiro" in name or "script" in name:
        return "roteiro"
    if "seo" in name:
        return "seo"
    if "mindmap" in name:
        return "visual"
    return "outro"


def build_categories(output_files: list[dict]) -> dict:
    """Group files by category."""
    categories: dict[str, list] = {}
    for f in output_files:
        cat = f.get("category", "outro")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(f)
    return categories


def load_ideas(project_id: str = "") -> list[dict]:
    """Load ideas from database, falling back to filesystem."""
    from database import get_ideas, get_projects as db_projects

    if project_id:
        return get_ideas(project_id)

    projs = db_projects()
    if projs:
        return get_ideas(projs[0]["id"])

    return _load_legacy_ideas()


def _load_legacy_ideas() -> list[dict]:
    """Load ideas from legacy markdown file."""
    ideas = []
    idea_file = OUTPUT_DIR / "loaded_dice_ideas.md"
    if idea_file.exists():
        content = idea_file.read_text(encoding="utf-8")
        blocks = re.split(r'\n(?=\d+\.\s)', content)
        for block in blocks:
            match = re.match(r'(\d+)\.\s*\*?\*?(.+?)\*?\*?\s*\n', block)
            if match:
                num = int(match.group(1))
                title = match.group(2).strip()
                hook_match = re.search(r'Hook:\s*(.+)', block)
                summary_match = re.search(r'(Resumo|Summary):\s*(.+)', block)
                ideas.append({
                    "id": num,
                    "num": num,
                    "title": title,
                    "hook": hook_match.group(1).strip() if hook_match else "",
                    "summary": summary_match.group(2).strip() if summary_match else "",
                    "pillar": "",
                    "priority": "MEDIA",
                    "score": 0,
                    "rating": "",
                    "used": 0,
                })
    return ideas


# ── Path Validation ──────────────────────────────────────

def validate_file_path(path: str) -> Path | None:
    """Validate and resolve a file path within the output directory.
    Returns the resolved path if valid, None otherwise."""
    if not path:
        return None

    # Block traversal patterns
    if ".." in path or "\\" in path:
        return None

    # Block dangerous prefixes
    dangerous = ["javascript:", "data:", "file://", "<script", "/etc", "/proc", "/sys"]
    if any(d in path.lower() for d in dangerous):
        return None

    allowed = OUTPUT_DIR.resolve()

    # Try as absolute path first
    resolved = Path(path).resolve()
    if str(resolved).startswith(str(allowed)) and resolved.exists():
        return resolved

    # Try as filename within output
    if not Path(path).is_absolute():
        filename = Path(path).name
        resolved = (OUTPUT_DIR / filename).resolve()
        if str(resolved).startswith(str(allowed)) and resolved.exists():
            return resolved

    return None


def validate_project_id(project_id: str) -> bool:
    """Validate project ID to prevent path traversal."""
    if not project_id:
        return False
    # Only allow alphanumeric, underscore, dash, dot
    return bool(re.match(r'^[\w\-\.]+$', project_id))


# ── Channel Analysis ─────────────────────────────────────

def analyze_via_notebooklm(notebook_id: str, niche_name: str) -> str:
    """Analyze channel using NotebookLM — correct async API from notebooklm-py docs.
    
    API: NotebookLMClient.from_storage() → async context manager → client.chat.ask()
    Auth: ~/.notebooklm/storage_state.json OR NOTEBOOKLM_AUTH_JSON env var
    Requires SID cookie (httpOnly) — must use 'notebooklm login' CLI, not bookmarklet.
    """
    import asyncio

    async def _run():
        from notebooklm import NotebookLMClient

        storage_path = Path.home() / ".notebooklm" / "storage_state.json"
        path_arg = str(storage_path) if storage_path.exists() else None

        async with await NotebookLMClient.from_storage(path=path_arg) as client:
            logger.info(f"NotebookLM client connected. Sending prompt to notebook {notebook_id[:12]}...")

            prompt = f"""Voce e um analista de canais do YouTube de elite. Faca uma analise COMPLETA, PROFUNDA e EXTREMAMENTE DETALHADA deste canal. O objetivo e criar um manual que permita replicar a formula de sucesso em outro nicho ("{niche_name}").

═══════════════════════════════════════════
PARTE 1 — DNA DO CANAL
═══════════════════════════════════════════

1. IDENTIDADE DO CANAL
- Nicho exato e sub-nicho
- Publico-alvo (idade, genero, interesses, dores, desejos)
- Proposta de valor unica (por que alguem assistiria ESTE canal e nao outro?)
- Tom de voz (serio, sarcastico, dramatico, educativo, misterioso?)
- Nivel de linguagem (formal, coloquial, tecnico?)
- Persona do narrador (quem "fala"? expert, investigador, contador de historias?)

2. FORMATO E PRODUCAO
- Tipo de canal (faceless, talking head, animacao, misto?)
- Duracao media dos videos (curtos, medios, longos)
- Frequencia de upload ideal
- Estilo visual (dark, colorido, minimalista, cinematico?)
- Tipo de B-roll usado (stock footage, animacao, screen recording, fotos?)
- Estilo de edicao (cortes rapidos, transicoes suaves, jump cuts?)
- Musica e sound design (que tipo de musica? quando muda? efeitos sonoros?)

═══════════════════════════════════════════
PARTE 2 — ENGENHARIA DE ROTEIRO
═══════════════════════════════════════════

3. ESTRUTURA DE ROTEIRO (anatomia completa)
- HOOK (0:00-0:30): Como capturam atencao nos PRIMEIROS 5 SEGUNDOS? E nos primeiros 30?
- CONTEXTO (0:30-2:30): Como fazem o setup sem perder o espectador?
- DESENVOLVIMENTO: Quantos "atos" tem? Como e a progressao da tensao?
- CLIMAX: Onde fica o ponto alto? Como constroem ate la?
- RESOLUCAO: Como terminam a historia?
- CTA: Como pedem like/subscribe/comentario sem ser chato?
- Cite exemplos REAIS de cada secao.

4. PLAYBOOK DE HOOKS (todos os tipos usados)
Para cada tipo, de 3 exemplos reais:
- Choque, Curiosidade, Pergunta impossivel, Numero impactante, Contraste, Urgencia, Segredo
- Outros tipos que o canal usa

5. TECNICAS DE STORYTELLING (com exemplos concretos)
- OPEN LOOPS, PATTERN INTERRUPTS, SPECIFIC SPIKES, CLIFFHANGERS — 5 exemplos de cada
- ARCO EMOCIONAL: Como a emocao muda durante o video
- RITMO NARRATIVO: Quando acelera/desacelera/faz pausa dramatica

6. REGRAS DE OURO (minimo 15 regras)
O que este canal SEMPRE faz e NUNCA quebra.

═══════════════════════════════════════════
PARTE 3 — ESTRATEGIA DE CONTEUDO
═══════════════════════════════════════════

7. PILARES DE CONTEUDO (5-7 categorias com % e exemplos)

8. FORMULA DE TITULOS (padroes + 10 exemplos reais + template)

9. ESTILO DE THUMBNAIL (cores, tipografia, composicao, template)

10. SEO E ALGORITMO (tags, descricao, hashtags, end screens, playlists)

═══════════════════════════════════════════
PARTE 4 — MANUAL DE REPLICACAO
═══════════════════════════════════════════

11. VERSAO IA — System prompt, 30 palavras do vocabulario, vocabulario proibido, exemplo no estilo exato

12. CHECKLIST DE QUALIDADE — 10 perguntas de verificacao

Seja EXTREMAMENTE detalhado. Use exemplos REAIS. O resultado e um SOP para o nicho "{niche_name}"."""

            result = await client.chat.ask(notebook_id, prompt)
            answer = result.answer if hasattr(result, 'answer') else str(result)
            logger.info(f"NotebookLM response: {len(answer)} chars")
            return answer

    try:
        # Run async function — handle existing event loop in FastAPI
        try:
            loop = asyncio.get_running_loop()
            # Already in async context (FastAPI) — create task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = loop.run_in_executor(pool, lambda: asyncio.run(_run()))
                # Can't await from sync function, use thread
                import threading
                container = [None, None]
                def run_in_thread():
                    try:
                        container[0] = asyncio.run(_run())
                    except Exception as e:
                        container[1] = e
                t = threading.Thread(target=run_in_thread)
                t.start()
                t.join(timeout=120)  # 2 min timeout
                if container[1]:
                    raise container[1]
                return container[0] or ""
        except RuntimeError:
            # No running loop — run directly
            return asyncio.run(_run())

    except Exception as e:
        import traceback
        logger.error(f"NotebookLM analysis failed: {type(e).__name__}: {e}")
        logger.error(f"NotebookLM traceback: {traceback.format_exc()}")

        try:
            _sp = Path.home() / ".notebooklm" / "storage_state.json"
            if _sp.exists():
                import json as _json
                state = _json.loads(_sp.read_text())
                cookie_count = len(state.get("cookies", []))
                cookie_names = [c.get("name", "?") for c in state.get("cookies", [])]
                has_sid = any(c.get("name") == "SID" for c in state.get("cookies", []))
                logger.error(f"Storage state: {cookie_count} cookies, names={cookie_names}")
                if not has_sid:
                    logger.error("MISSING SID cookie! Bookmarklet cannot capture httpOnly cookies. Use 'notebooklm login' CLI on your PC to generate proper storage_state.json, then upload it.")
            else:
                logger.error("storage_state.json not found")
        except Exception:
            pass

        return ""


def analyze_via_transcripts(channel_url: str, niche_name: str) -> str:
    """Analyze channel using YouTube transcripts."""
    try:
        import subprocess

        # Get video IDs from channel
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "id", channel_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return ""

        video_ids = result.stdout.strip().split("\n")[:10]
        if not video_ids:
            return ""

        # Get transcripts
        from youtube_transcript_api import YouTubeTranscriptApi

        all_transcripts = []
        for vid in video_ids:
            vid = vid.strip()
            if not vid:
                continue
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(vid)
                transcript = transcript_list.find_manually_created_transcript(["pt", "en"])
                text = " ".join([t["text"] for t in transcript.fetch()])
                all_transcripts.append(text[:2000])
            except Exception:
                try:
                    transcript = YouTubeTranscriptApi.get_transcript(vid, languages=["pt", "en"])
                    text = " ".join([t["text"] for t in transcript])
                    all_transcripts.append(text[:2000])
                except Exception:
                    continue

        if not all_transcripts:
            return ""

        combined = "\n\n---\n\n".join(all_transcripts)

        from protocols.ai_client import chat

        sop_prompt = f"""Analise estas transcricoes REAIS de videos do canal e crie um SOP completo para o nicho "{niche_name}".

TRANSCRICOES DOS VIDEOS:
{combined[:12000]}

Baseado nos PADROES REAIS encontrados nas transcricoes, crie um SOP detalhado com:

1. VISAO GERAL DO CANAL: Nicho exato, publico-alvo, estilo, formato dos videos, duracao media
2. FORMULA DE TITULOS: Padroes encontrados nos titulos com exemplos reais extraidos
3. ESTRUTURA DE ROTEIRO: Como comecam (hook dos primeiros 30s), como mantem atencao, como terminam
4. PLAYBOOK DE HOOKS: Tipos de ganchos usados com exemplos reais das transcricoes
5. TECNICAS DE STORYTELLING: Open loops, pattern interrupts, cliffhangers, specific spikes — com exemplos concretos
6. REGRAS DE OURO: 10 regras que NUNCA sao quebradas nesses roteiros
7. PILARES DE CONTEUDO: 5 categorias principais de videos com exemplos
8. ESTILO DE THUMBNAIL: Padroes visuais sugeridos baseados no estilo do canal
9. VERSAO IA: Instrucoes para uma IA replicar EXATAMENTE este estilo de escrita

IMPORTANTE: Baseie TUDO em evidencias reais das transcricoes. Cite trechos especificos como exemplos."""

        return chat(sop_prompt, system="Voce e um estrategista de YouTube analisando transcricoes reais de videos. Seja extremamente detalhado.", max_tokens=MAX_TOKENS_LARGE)

    except Exception as e:
        logger.error(f"Transcript analysis failed: {e}")
        return ""


# ── Input Validation ─────────────────────────────────────

def sanitize_niche_name(name: str) -> str:
    """Sanitize niche name — remove potentially dangerous characters."""
    clean = re.sub(r'[<>"\';{}()]', '', name).strip()
    return clean[:100]


def validate_url(url: str) -> str | None:
    """Validate a URL. Returns cleaned URL or None if invalid."""
    url = url.strip()
    if not url or not url.startswith(("http://", "https://")):
        return None
    if len(url) > 500:
        return None
    dangerous = ["javascript:", "data:", "file://", "<script", "localhost", "127.0.0.1", "0.0.0.0"]
    if any(bad in url.lower() for bad in dangerous):
        return None
    return url


# ── Mind Map Generation ──────────────────────────────────

def generate_mindmap_html(
    niche_name: str,
    channel_url: str,
    sop: str,
    niches: list[dict],
    top_ideas: list[dict],
    scripts_count: int = 0,
) -> str:
    """Generate a visual HTML mind map matching the System Breakers design."""
    import html as html_mod
    from datetime import date

    def esc(t):
        return html_mod.escape(str(t)) if t else ""

    today = date.today().isoformat()
    chosen = niches[0] if niches else {"name": niche_name, "description": "", "rpm_range": "$5-15", "competition": "Media", "pillars": []}
    alt_niches = niches[1:5] if len(niches) > 1 else []
    chosen_name = esc(chosen.get("name", niche_name))
    chosen_desc = esc(chosen.get("description", ""))
    chosen_rpm = esc(chosen.get("rpm_range", "$5-15"))
    chosen_comp = esc(chosen.get("competition", "Media"))
    pillars = chosen.get("pillars", [])[:5]

    # Extract SOP data
    sop_text = sop or ""
    sop_lines = [l.strip() for l in sop_text.split('\n') if l.strip() and len(l.strip()) > 10]

    # Channel info
    canal_info = []
    for line in sop_lines[:60]:
        lo = line.lower()
        clean = line.lstrip('-*#0123456789. ').strip()
        if any(k in lo for k in ['nicho:', 'estilo:', 'formato:', 'hook', 'storytelling', 'duracao', 'frequen', 'views', 'videos']):
            if clean and len(clean) < 100:
                canal_info.append(clean)
    canal_info = canal_info[:6] or [f"Nicho: {niche_name}", f"Canal: {channel_url[:40]}"]

    # Production info
    prod_info = []
    for line in sop_lines[:80]:
        lo = line.lower()
        clean = line.lstrip('-*#0123456789. ').strip()
        if any(k in lo for k in ['roteirista', 'animac', 'freelanc', 'custo', 'frequen', 'pipeline', 'receita', 'ferramenta', 'ia ', 'claude', 'automatiz']):
            if clean and len(clean) < 100:
                prod_info.append(clean)
    prod_info = prod_info[:5] or [
        "Roteirista: IA (Claude) + SOP automatizado",
        "Animacao: Freelancers Upwork ($80-300/video)",
        "Frequencia: 2-3 videos/semana",
        "Receita estimada: $5K-15K/mes (apos 10 videos)",
        "Pipeline: 100% automatizado com Claude Code",
    ]

    # Roteiros info
    roteiros_html = ""
    for i, idea in enumerate(top_ideas[:3]):
        t = esc(idea.get("title", f"Titulo {i+1}"))[:45]
        dur = f"{8 + i*2}-{10 + i*2} min"
        roteiros_html += f'<div class="roteiro-item"><span class="r-num">{i+1}.</span> {t} <span class="r-dur">{dur}</span></div>'
    if not roteiros_html:
        roteiros_html = '<div class="roteiro-item">Nenhum roteiro gerado ainda</div>'
    roteiros_html += '<div class="roteiro-meta">Estrutura: Hook → Contexto → 3 Atos → Climax → CTA</div>'
    roteiros_html += '<div class="roteiro-meta">Tecnicas: Open Loops, Pattern Interrupts, Specific Spikes</div>'

    # Pillars HTML
    pillars_html = ""
    for i, p in enumerate(pillars):
        pillars_html += f'<div class="pillar-item"><span class="p-num">{i+1}.</span> {esc(p)}</div>'
    if not pillars_html:
        pillars_html = '<div class="pillar-item">Definidos no SOP</div>'

    # Alt niches HTML
    alt_html = ""
    comp_colors = {"Baixa": "#22c55e", "Media": "#eab308", "Alta": "#ef4444", "Muito Alta": "#dc2626"}
    for n in alt_niches:
        nm = esc(n.get("name", ""))
        desc = esc(n.get("description", ""))[:50]
        rpm = esc(n.get("rpm_range", ""))
        comp = n.get("competition", "Media")
        cc = comp_colors.get(comp, "#eab308")
        alt_html += f'<div class="alt-niche"><b>{nm}</b> - {desc} <span class="rpm-badge" style="background:{cc}">{rpm} {comp}</span></div>'

    # Canal info HTML
    canal_html = "".join(f'<div class="info-item">{esc(c)}</div>' for c in canal_info)
    prod_html = "".join(f'<div class="info-item">{esc(p)}</div>' for p in prod_info)

    # Top ideas (up to 15)
    ideas_html = ""
    for i, idea in enumerate(top_ideas[:15]):
        t = esc(idea.get("title", ""))[:60]
        desc = esc(idea.get("description", ""))[:80]
        pri = idea.get("priority", "MEDIA")
        pri_c = {"ALTA": "#ef4444", "MEDIA": "#eab308", "BAIXA": "#22c55e"}.get(pri, "#eab308")
        ideas_html += f'''<div class="idea-card"><div class="idea-num">{i+1}</div><div class="idea-body"><b>{t}</b><p>{desc}</p><span class="pri-badge" style="background:{pri_c}">{pri}</span></div></div>'''

    num_ideas = min(15, len(top_ideas))
    sc = scripts_count or min(3, len(top_ideas))

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(niche_name)} - Mind Map</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0f14;color:#e4e4e7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px;min-height:100vh}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:28px;text-align:center;text-transform:uppercase;letter-spacing:3px;margin-bottom:4px}}
.subtitle{{text-align:center;color:#a1a1aa;font-size:13px;margin-bottom:28px}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:24px}}
.stat{{background:#1a1a24;border-radius:8px;padding:16px 12px;text-align:center;border-top:3px solid #22c55e}}
.stat-val{{font-size:22px;font-weight:700;color:#fff}}
.stat-label{{font-size:10px;color:#71717a;text-transform:uppercase;letter-spacing:1px;margin-top:4px}}
.pipeline{{display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:28px;flex-wrap:wrap}}
.pipe-box{{background:#1a1a24;border:1px solid #27272a;border-radius:8px;padding:10px 18px;text-align:center}}
.pipe-box b{{display:block;font-size:13px;color:#a78bfa}}
.pipe-box span{{font-size:10px;color:#71717a}}
.pipe-arrow{{color:#3f3f46;font-size:20px}}
.grid4{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:28px}}
.card{{background:#1a1a24;border-radius:8px;padding:16px;border-left:3px solid #3f3f46}}
.card.c-canal{{border-color:#3b82f6}}
.card.c-nicho{{border-color:#22c55e}}
.card.c-pilares{{border-color:#f59e0b}}
.card.c-roteiros{{border-color:#ef4444}}
.card.c-prod{{border-color:#f59e0b}}
.card.c-alt{{border-color:#a78bfa}}
.card-title{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}}
.card.c-canal .card-title{{color:#3b82f6}}
.card.c-nicho .card-title{{color:#22c55e}}
.card.c-pilares .card-title{{color:#f59e0b}}
.card.c-roteiros .card-title{{color:#ef4444}}
.card.c-prod .card-title{{color:#f59e0b}}
.card.c-alt .card-title{{color:#a78bfa}}
.info-item{{font-size:12px;color:#d4d4d8;margin-bottom:6px;padding-left:8px;border-left:2px solid #27272a}}
.pillar-item{{font-size:12px;color:#d4d4d8;margin-bottom:6px}}
.p-num{{color:#f59e0b;font-weight:700}}
.roteiro-item{{font-size:12px;color:#d4d4d8;margin-bottom:6px}}
.r-num{{color:#ef4444;font-weight:700}}
.r-dur{{font-size:10px;color:#71717a;background:#27272a;padding:2px 6px;border-radius:3px;margin-left:4px}}
.roteiro-meta{{font-size:10px;color:#71717a;margin-top:8px;padding-top:6px;border-top:1px solid #27272a}}
.alt-niche{{font-size:12px;margin-bottom:8px}}
.rpm-badge{{font-size:9px;padding:2px 6px;border-radius:3px;color:#000;font-weight:600;margin-left:4px}}
.ideas-section{{margin-top:8px}}
.ideas-section h2{{font-size:16px;margin-bottom:14px;text-align:center}}
.ideas-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.idea-card{{background:#1a1a24;border-radius:8px;padding:12px;display:flex;gap:10px;align-items:flex-start}}
.idea-num{{background:#7c3aed;color:#fff;font-size:11px;font-weight:700;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.idea-body b{{font-size:12px;display:block;margin-bottom:4px}}
.idea-body p{{font-size:10px;color:#a1a1aa;margin-bottom:4px}}
.pri-badge{{font-size:9px;padding:2px 8px;border-radius:3px;color:#fff;font-weight:600}}
.footer{{text-align:center;color:#3f3f46;font-size:11px;margin-top:24px;padding-top:12px;border-top:1px solid #1a1a24}}
@media(max-width:900px){{.grid4,.stats{{grid-template-columns:repeat(2,1fr)}}.ideas-grid{{grid-template-columns:1fr 1fr}}.grid2{{grid-template-columns:1fr}}}}
@media(max-width:500px){{.stats,.ideas-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="container">
  <h1>{esc(niche_name)}</h1>
  <p class="subtitle">YouTube Channel Blueprint - Clonado de {esc(channel_url[:50])} via AI Protocols</p>

  <div class="stats">
    <div class="stat"><div class="stat-val">{chosen_rpm}</div><div class="stat-label">RPM Estimado</div></div>
    <div class="stat" style="border-color:#3b82f6"><div class="stat-val">{len(top_ideas)}</div><div class="stat-label">Ideias de Videos</div></div>
    <div class="stat" style="border-color:#ef4444"><div class="stat-val">{sc}</div><div class="stat-label">Roteiros Prontos</div></div>
    <div class="stat" style="border-color:#a78bfa"><div class="stat-val">{len(niches)}</div><div class="stat-label">Nichos Gerados</div></div>
    <div class="stat" style="border-color:#f59e0b"><div class="stat-val">{len(pillars)}</div><div class="stat-label">Pilares</div></div>
    <div class="stat" style="border-color:#ec4899"><div class="stat-val">$80-300</div><div class="stat-label">Custo por Video</div></div>
  </div>

  <div class="pipeline">
    <div class="pipe-box"><b>Protocol Clerk</b><span>Analise de concorrencia</span></div>
    <span class="pipe-arrow">→</span>
    <div class="pipe-box"><b>Niche Bending</b><span>5 nichos derivados</span></div>
    <span class="pipe-arrow">→</span>
    <div class="pipe-box"><b>Script Stealing</b><span>{len(top_ideas)} ideias + {sc} roteiros</span></div>
    <span class="pipe-arrow">→</span>
    <div class="pipe-box"><b>Google Export</b><span>Drive / Docs / Sheets</span></div>
  </div>

  <div class="grid4">
    <div class="card c-canal"><div class="card-title">&#128308; Canal Original</div>{canal_html}</div>
    <div class="card c-nicho"><div class="card-title">&#128994; Nicho Escolhido</div>
      <div class="info-item"><b>Nome:</b> {chosen_name}</div>
      <div class="info-item"><b>Desc:</b> {chosen_desc[:80]}</div>
      <div class="info-item"><b>RPM:</b> {chosen_rpm} <b style="color:{'#22c55e' if 'Baixa' in chosen_comp else '#eab308'}">{chosen_comp}</b></div>
    </div>
    <div class="card c-pilares"><div class="card-title">&#127919; {len(pillars)} Pilares de Conteudo</div>{pillars_html}</div>
    <div class="card c-roteiros"><div class="card-title">&#128196; {sc} Roteiros Prontos</div>{roteiros_html}</div>
  </div>

  <div class="grid2">
    <div class="card c-prod"><div class="card-title">&#9881; Producao</div>{prod_html}</div>
    <div class="card c-alt"><div class="card-title">&#128640; Nichos Alternativos</div>{alt_html if alt_html else '<div class="info-item">Nenhum nicho alternativo</div>'}</div>
  </div>

  <div class="ideas-section">
    <h2>Top {num_ideas} Ideias de Videos (por potencial viral)</h2>
    <div class="ideas-grid">{ideas_html}</div>
  </div>
</div>
<div class="footer">Gerado por YouTube Channel Cloner | Claude Code + NotebookLM | {today}</div>
</body>
</html>'''
