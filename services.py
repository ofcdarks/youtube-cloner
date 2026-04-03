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
    """Analyze channel using NotebookLM."""
    try:
        from notebooklm import NotebookLM

        nlm = NotebookLM()
        response = nlm.chat(
            notebook_id=notebook_id,
            message=f"""Analise este canal do YouTube e crie um SOP completo para o nicho "{niche_name}".

Inclua: tom, estilo, estrutura de video, hooks, storytelling, visual, CTA, SEO, pilares de conteudo.
Seja detalhado e especifico.""",
        )
        return response.text if hasattr(response, "text") else str(response)
    except Exception as e:
        logger.error(f"NotebookLM analysis failed: {e}")
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

        sop_prompt = f"""Analise estas transcricoes de videos do canal e crie um SOP completo para o nicho "{niche_name}".

TRANSCRICOES:
{combined[:12000]}

Crie um SOP detalhado incluindo:
1. CONCEITO DO CANAL - Tom, estilo, audiencia-alvo
2. ESTRUTURA DE VIDEO - Formato padrao, duracao, secoes
3. HOOKS - Como capturar atencao nos primeiros 30 segundos
4. STORYTELLING - Tecnicas narrativas (open loops, pattern interrupts, specific spikes)
5. VISUAL - Estilo visual, B-roll, transicoes
6. CTA - Estrategia de call-to-action
7. SEO - Estrategia de titulos, tags, thumbnails
8. PILARES DE CONTEUDO - 5 categorias principais de videos

Escreva o SOP completo baseado nos PADROES REAIS encontrados nas transcricoes."""

        return chat(sop_prompt, system="Voce e um estrategista de YouTube analisando transcricoes reais.", max_tokens=MAX_TOKENS_MEDIUM)

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
    """Generate a visual HTML mind map for a project."""
    import html as html_mod
    from datetime import date

    def esc(text):
        return html_mod.escape(str(text)) if text else ""

    # Extract data from niches
    chosen_niche = niches[0] if niches else {"name": niche_name, "description": "", "rpm_range": "", "competition": ""}
    alt_niches = niches[1:5] if len(niches) > 1 else []

    chosen_name = esc(chosen_niche.get("name", niche_name))
    chosen_desc = esc(chosen_niche.get("description", ""))
    chosen_rpm = esc(chosen_niche.get("rpm_range", "$5-15"))
    chosen_comp = esc(chosen_niche.get("competition", "Media"))
    chosen_pillars = chosen_niche.get("pillars", [])

    # Extract key SOP points
    sop_text = sop or ""
    sop_lines = [line.strip() for line in sop_text.split('\n') if line.strip() and len(line.strip()) > 10]

    production_lines = []
    for line in sop_lines[:80]:
        lower = line.lower()
        if any(kw in lower for kw in ['frequen', 'custo', 'animac', 'producao', 'freelanc', 'pipeline', 'receita', 'ferramenta']):
            clean = line.lstrip('-').lstrip('*').lstrip('#').lstrip(' ').lstrip('0123456789.').strip()
            if clean and len(clean) < 120:
                production_lines.append(clean)
    production_lines = production_lines[:5] or [
        "Roteirista: IA (Claude) + SOP automatizado",
        "Animacao: Freelancers Upwork ($80-300/video)",
        "Frequencia: 2-3 videos/semana",
        "Pipeline: 100% automatizado com Claude Code",
    ]

    canal_lines = []
    for line in sop_lines[:60]:
        lower = line.lower()
        stripped = line.strip().lstrip('-').lstrip('*').lstrip('#').lstrip(' ').lstrip('0123456789.)').strip()
        if not stripped or len(stripped) < 20 or stripped.isupper():
            continue
        if any(kw in lower for kw in ['estilo do canal', 'formato dos video', 'tom do canal', 'duracao media',
                                       'publico-alvo', 'publico alvo', 'audiencia', 'nicho principal',
                                       'frequencia de upload', 'tipo de conteudo']):
            if len(stripped) < 120:
                canal_lines.append(stripped)
    canal_lines = canal_lines[:6] or [
        f"Canal: {esc(channel_url[:80])}",
        f"Nicho: {esc(niche_name)}",
        chosen_desc[:100] if chosen_desc else "Analise de conteudo via IA",
    ]

    num_ideas = len(top_ideas)
    num_niches = len(niches)

    # Build stats
    stats_html = f'''
    <div class="stat-card"><div class="number">{num_ideas}</div><div class="label">Ideias de Videos</div></div>
    <div class="stat-card"><div class="number">{esc(chosen_rpm)}</div><div class="label">RPM Estimado</div></div>
    <div class="stat-card"><div class="number">{scripts_count}</div><div class="label">Roteiros Prontos</div></div>
    <div class="stat-card"><div class="number">{num_niches}</div><div class="label">Nichos Gerados</div></div>
    <div class="stat-card"><div class="number">$80-300</div><div class="label">Custo por Video</div></div>'''

    # Pipeline
    pipeline_html = f'''
    <div class="pipe-step active"><h4>Protocol Clerk</h4><p>Analise de concorrencia</p></div>
    <div class="pipe-arrow">&#10132;</div>
    <div class="pipe-step active"><h4>Niche Bending</h4><p>{num_niches} nichos derivados</p></div>
    <div class="pipe-arrow">&#10132;</div>
    <div class="pipe-step active"><h4>Script Stealing</h4><p>{num_ideas} ideias + {scripts_count} roteiros</p></div>
    <div class="pipe-arrow">&#10132;</div>
    <div class="pipe-step active"><h4>Google Export</h4><p>Drive / Docs / Sheets</p></div>'''

    # Branches
    canal_leaves = "".join(f'\n          <div class="leaf">{esc(line)}</div>' for line in canal_lines[:6])

    comp_tag = ""
    if chosen_comp:
        comp_lower = chosen_comp.lower()
        if "baixa" in comp_lower:
            comp_tag = '<span class="tag tag-success">OPORTUNIDADE</span>'
        elif "media" in comp_lower:
            comp_tag = '<span class="tag tag-warning">COMPETITIVO</span>'
        else:
            comp_tag = '<span class="tag tag-danger">SATURADO</span>'

    nicho_leaves = f'''
          <div class="leaf">Nome: {chosen_name}</div>
          <div class="leaf">Descricao: {chosen_desc}</div>
          <div class="leaf">RPM: {chosen_rpm}</div>
          <div class="leaf">Competicao: {esc(chosen_comp)} {comp_tag}</div>'''

    pilares_leaves = ""
    if chosen_pillars:
        for i, p in enumerate(chosen_pillars[:5], 1):
            pilares_leaves += f'\n          <div class="leaf">{i}. {esc(p)}</div>'
    else:
        pillar_lines = []
        for line in sop_lines[:100]:
            lower = line.lower()
            if any(kw in lower for kw in ['pilar', 'categoria', 'tipo de video', 'serie']):
                clean = line.lstrip('-').lstrip('*').lstrip('#').lstrip(' ').lstrip('0123456789.').strip()
                if clean and len(clean) < 120:
                    pillar_lines.append(clean)
        for i, p in enumerate(pillar_lines[:5], 1):
            pilares_leaves += f'\n          <div class="leaf">{i}. {esc(p)}</div>'
        if not pilares_leaves:
            pilares_leaves = '\n          <div class="leaf">Pilares serao definidos com base no SOP</div>'

    roteiros_leaves = ""
    if scripts_count > 0:
        roteiros_leaves += f'\n          <div class="leaf">{scripts_count} roteiros prontos para producao</div>'
    high_priority = [idea for idea in top_ideas[:10] if idea.get("priority", "").upper() == "ALTA"]
    for i, idea in enumerate(high_priority[:3], 1):
        title = esc(idea.get("title", f"Roteiro {i}"))
        roteiros_leaves += f'\n          <div class="leaf">{i}. {title} <span class="tag tag-warning">PRONTO</span></div>'
    roteiros_leaves += '\n          <div class="leaf">Estrutura: Hook > Contexto > 3 Atos > Climax > CTA</div>'
    roteiros_leaves += '\n          <div class="leaf">Tecnicas: Open Loops, Pattern Interrupts, Specific Spikes</div>'

    producao_leaves = "".join(f'\n          <div class="leaf">{esc(line)}</div>' for line in production_lines[:5])

    alt_leaves = ""
    for n in alt_niches[:4]:
        n_name = esc(n.get("name", ""))
        n_desc = esc(n.get("description", ""))
        alt_leaves += f'\n          <div class="leaf">{n_name} - {n_desc}</div>'
    if not alt_leaves:
        alt_leaves = '\n          <div class="leaf">Nichos alternativos serao gerados pela IA</div>'

    # Ideas
    ideas_html = ""
    for i, idea in enumerate(top_ideas[:15], 1):
        title = esc(idea.get("title", f"Ideia {i}"))
        summary = esc(idea.get("summary", idea.get("hook", "")))
        priority = idea.get("priority", "MEDIA").upper()
        pcls = {"ALTA": "alta", "MEDIA": "media"}.get(priority, "baixa")
        ideas_html += f'''
      <div class="idea-card">
        <div class="idea-num">{i}</div>
        <div class="idea-content">
          <h4>{title}</h4>
          <p>{summary}</p>
          <span class="priority {pcls}">{priority}</span>
        </div>
      </div>'''

    today = date.today().strftime("%Y-%m-%d")

    return _MINDMAP_TEMPLATE.format(
        niche_upper=esc(niche_name).upper(),
        niche_esc=esc(niche_name),
        chosen_desc=chosen_desc,
        stats_html=stats_html,
        pipeline_html=pipeline_html,
        canal_leaves=canal_leaves,
        nicho_leaves=nicho_leaves,
        pilares_leaves=pilares_leaves,
        scripts_count=scripts_count,
        roteiros_leaves=roteiros_leaves,
        producao_leaves=producao_leaves,
        alt_leaves=alt_leaves,
        num_ideas=min(len(top_ideas), 15),
        ideas_html=ideas_html,
        today=today,
    )


_MINDMAP_TEMPLATE = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mind Map - {niche_esc}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{--bg-deep:#020617;--bg-base:#0a0f1e;--bg-elevated:#0e1223;--bg-surface:#131a2e;--border:#1e293b;--border-hover:#334155;--fg-primary:#f8fafc;--fg-secondary:#94a3b8;--fg-muted:#64748b;--fg-dim:#475569;--accent:#7c3aed;--success:#22c55e;--danger:#ef4444;--info:#3b82f6;--warning:#eab308;--cyan:#06b6d4;--font-ui:'Inter',system-ui,sans-serif;--font-mono:'JetBrains Mono',monospace;--ease:cubic-bezier(.16,1,.3,1)}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:var(--bg-deep);font-family:var(--font-ui);color:var(--fg-secondary);overflow-x:hidden;-webkit-font-smoothing:antialiased;font-size:14px;line-height:1.5}}
  ::selection{{background:rgba(124,58,237,.2);color:#fff}}
  .header{{text-align:center;padding:36px 20px;background:var(--bg-deep);border-bottom:1px solid var(--border)}}
  .header h1{{font-size:2em;font-weight:700;color:var(--fg-primary);letter-spacing:-.5px;margin-bottom:6px}}
  .header p{{color:var(--fg-muted);font-size:14px}}
  .container{{max-width:1400px;margin:0 auto;padding:32px 24px}}
  .mindmap{{display:flex;flex-direction:column;gap:28px}}
  .level-0{{background:var(--bg-elevated);border:1px solid var(--border);border-radius:12px;padding:24px;text-align:center}}
  .level-0 h2{{font-size:1.5em;color:var(--fg-primary);font-weight:700;letter-spacing:-.3px}}
  .level-0 .subtitle{{color:var(--fg-muted);margin-top:8px;font-size:13px;max-width:800px;margin-left:auto;margin-right:auto}}
  .branches{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
  .branch{{background:var(--bg-elevated);border-radius:10px;overflow:hidden;border:1px solid var(--border);transition:all 180ms var(--ease)}}
  .branch:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3);border-color:var(--border-hover)}}
  .branch-header{{padding:14px 18px;font-size:13px;font-weight:600;display:flex;align-items:center;gap:10px;text-transform:uppercase;letter-spacing:.5px}}
  .branch-header .icon{{font-size:16px;opacity:.7}}
  .branch-body{{padding:0 16px 16px}}
  .leaf{{padding:10px 14px;margin:6px 0;background:var(--bg-surface);border-radius:6px;border-left:3px solid;font-size:13px;line-height:1.5;color:var(--fg-secondary)}}
  .leaf .tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-left:6px;letter-spacing:.3px}}
  .tag-success{{background:rgba(34,197,94,.1);color:#22c55e}}.tag-warning{{background:rgba(234,179,8,.1);color:#eab308}}.tag-danger{{background:rgba(239,68,68,.1);color:#ef4444}}.tag-info{{background:rgba(6,182,212,.1);color:#06b6d4}}
  .b-original .branch-header{{background:rgba(34,197,94,.08);color:var(--success);border-bottom:1px solid rgba(34,197,94,.15)}}.b-original .leaf{{border-color:rgba(34,197,94,.4)}}
  .b-nicho .branch-header{{background:rgba(124,58,237,.08);color:#a78bfa;border-bottom:1px solid rgba(124,58,237,.15)}}.b-nicho .leaf{{border-color:rgba(124,58,237,.4)}}
  .b-pilares .branch-header{{background:rgba(59,130,246,.08);color:var(--info);border-bottom:1px solid rgba(59,130,246,.15)}}.b-pilares .leaf{{border-color:rgba(59,130,246,.4)}}
  .b-roteiros .branch-header{{background:rgba(234,179,8,.08);color:var(--warning);border-bottom:1px solid rgba(234,179,8,.15)}}.b-roteiros .leaf{{border-color:rgba(234,179,8,.4)}}
  .b-producao .branch-header{{background:rgba(239,68,68,.08);color:var(--danger);border-bottom:1px solid rgba(239,68,68,.15)}}.b-producao .leaf{{border-color:rgba(239,68,68,.4)}}
  .b-alternativas .branch-header{{background:rgba(6,182,212,.08);color:var(--cyan);border-bottom:1px solid rgba(6,182,212,.15)}}.b-alternativas .leaf{{border-color:rgba(6,182,212,.4)}}
  .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:28px}}
  .stat-card{{background:var(--bg-elevated);border-radius:10px;padding:20px;text-align:center;border:1px solid var(--border);transition:border-color 180ms var(--ease)}}
  .stat-card:hover{{border-color:var(--border-hover)}}
  .stat-card .number{{font-family:var(--font-mono);font-size:1.8em;font-weight:700;color:var(--fg-primary);letter-spacing:-1px}}
  .stat-card .label{{color:var(--fg-muted);margin-top:4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
  .ideas-section{{margin-top:40px}}.ideas-section h2{{font-size:16px;font-weight:600;color:var(--fg-primary);margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)}}
  .ideas-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:10px}}
  .idea-card{{background:var(--bg-elevated);border-radius:8px;padding:14px 16px;border:1px solid var(--border);display:flex;gap:14px;align-items:flex-start;transition:border-color 180ms var(--ease)}}
  .idea-card:hover{{border-color:var(--border-hover)}}
  .idea-num{{background:var(--accent);color:white;width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;font-family:var(--font-mono);flex-shrink:0}}
  .idea-content h4{{color:var(--fg-primary);font-size:13px;font-weight:600;margin-bottom:4px}}
  .idea-content p{{color:var(--fg-muted);font-size:12px;line-height:1.4}}
  .idea-content .priority{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;margin-top:6px;letter-spacing:.3px}}
  .priority.alta{{background:rgba(239,68,68,.1);color:var(--danger);border:1px solid rgba(239,68,68,.25)}}
  .priority.media{{background:rgba(234,179,8,.1);color:var(--warning);border:1px solid rgba(234,179,8,.25)}}
  .priority.baixa{{background:rgba(34,197,94,.1);color:var(--success);border:1px solid rgba(34,197,94,.25)}}
  .pipeline{{display:flex;justify-content:center;align-items:center;gap:0;margin:28px 0;flex-wrap:wrap}}
  .pipe-step{{background:var(--bg-elevated);border:1px solid var(--border);border-radius:10px;padding:14px 24px;text-align:center;min-width:170px;transition:all 180ms var(--ease)}}
  .pipe-step.active{{border-color:rgba(34,197,94,.3);background:rgba(34,197,94,.06)}}
  .pipe-step h4{{color:var(--fg-primary);font-size:13px;font-weight:600}}.pipe-step p{{color:var(--fg-muted);font-size:12px;margin-top:3px}}
  .pipe-arrow{{font-size:14px;color:var(--fg-dim);padding:0 8px}}
  .footer{{text-align:center;padding:28px;color:var(--fg-dim);font-size:12px;border-top:1px solid var(--border);margin-top:40px}}
  @media(max-width:900px){{.branches{{grid-template-columns:1fr}}.ideas-grid{{grid-template-columns:1fr}}.stats{{grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}}.container{{padding:20px 16px}}}}
</style>
</head>
<body>
<div class="header"><h1>{niche_upper}</h1><p>YouTube Channel Blueprint - Clonado via AI Protocols</p></div>
<div class="container">
  <div class="stats">{stats_html}</div>
  <div class="pipeline">{pipeline_html}</div>
  <div class="mindmap">
    <div class="level-0"><h2>{niche_upper}</h2><div class="subtitle">{chosen_desc}</div></div>
    <div class="branches">
      <div class="branch b-original"><div class="branch-header"><span class="icon">&#127922;</span> Canal Original</div><div class="branch-body">{canal_leaves}</div></div>
      <div class="branch b-nicho"><div class="branch-header"><span class="icon">&#128161;</span> Nicho Escolhido</div><div class="branch-body">{nicho_leaves}</div></div>
      <div class="branch b-pilares"><div class="branch-header"><span class="icon">&#127919;</span> 5 Pilares de Conteudo</div><div class="branch-body">{pilares_leaves}</div></div>
      <div class="branch b-roteiros"><div class="branch-header"><span class="icon">&#127916;</span> {scripts_count} Roteiros Prontos</div><div class="branch-body">{roteiros_leaves}</div></div>
      <div class="branch b-producao"><div class="branch-header"><span class="icon">&#9881;</span> Producao</div><div class="branch-body">{producao_leaves}</div></div>
      <div class="branch b-alternativas"><div class="branch-header"><span class="icon">&#128640;</span> Nichos Alternativos</div><div class="branch-body">{alt_leaves}</div></div>
    </div>
  </div>
  <div class="ideas-section"><h2>Top {num_ideas} Ideias de Videos</h2><div class="ideas-grid">{ideas_html}</div></div>
</div>
<div class="footer">Gerado por YouTube Channel Cloner | {today}</div>
</body>
</html>'''
