"""
Idea Bender v2 — Multi-phase niche/idea bending with market research.

Phases:
1. URL Classification — detects video vs channel vs playlist URL
2. Metadata Fetch — yt-dlp with mode-specific flags
   - Video: single video metadata
   - Channel: top 10 videos by views (picks viral outlier)
   - Playlist: all videos
3. Success Signal Extraction — viral_score, engagement_rate, views_per_day
4. Trend Crossover — Google Trends + YouTube search for adjacent niches
5. DNA + Variation Generation — LLM call with enriched prompt
6. Post-processing — RPM tier sorting, competition flags

Modes:
- internal: bend an idea already in the DB (uses project SOP as context)
- external: bend a YouTube video or channel URL
- manual: bend a hand-typed title + SOP
"""

import json
import logging
import re
import subprocess
from datetime import datetime
from typing import Optional

from protocols.ai_client import chat

logger = logging.getLogger("ytcloner.idea_bender")


# ═══════════════════════════════════════════════════════════════════
# PROMPT ENGINEERING — v2 with market research context
# ═══════════════════════════════════════════════════════════════════

BENDER_SYSTEM_PROMPT = """Voce e um estrategista de canais YouTube especialista em Idea Bending — a arte de pegar uma ideia que JA funcionou (views comprovadas) e criar variacoes ELEVADAS que preservam o DNA do sucesso mas atacam novos nichos/audiencias com ROI superior.

Sua missao: maximizar potencial comercial mantendo o formato-que-funciona.

Principio central: FIXO vs VARIAVEL
- FIXO (nunca mudar): estrutura narrativa, formato de hook, pacing, padrao de titulo, emotional driver, padrao de retencao
- VARIAVEL (troca): tema, personagem, estetica, ambientacao, angulo cultural, nicho de aplicacao

Criterios de elevacao:
- RPM: priorizar nichos de CPM mais alto (financas, tech, educacao, medicina) quando o formato permite
- Competicao: preferir nichos sub-atendidos (gap de mercado) com demanda comprovada
- Producao: equilibrar complexidade vs ROI — nao sugerir algo que exige 3D fotorrealista se o original era simples
- Timing: aproveitar tendencias em alta (rising trends, current events)
- Diferenciacao: cada variacao deve ser DISTINTA — nao 5 versoes do mesmo angulo

Retorne SEMPRE um JSON valido — sem markdown, sem comentarios, sem texto fora do JSON."""


BENDER_USER_TEMPLATE = """Analise a ideia abaixo e gere {num_variations} variacoes dobradas ESTRATEGICAS.

## IDEIA ORIGINAL
**Titulo:** {title}
**Nicho original:** {niche}
**Idioma:** {language}
{extra_context}

## CONTEXTO DO CANAL (SOP)
{sop_excerpt}

## INTELIGENCIA DE MERCADO (dados reais, ultimos 14 dias)
{market_research}

## TAREFA

**Passo 1 — DNA:** Extraia o DNA do sucesso (por que essa ideia funcionou). Considere nao so o titulo mas o formato, emotional driver, e posicao cultural.

**Passo 2 — FIXO vs VARIAVEL:** Separe o que nunca pode mudar do que pode ser trocado.

**Passo 3 — Stratificacao RPM:** Das {num_variations} variacoes, distribua estrategicamente:
- ~30% em RPM ALTO ($15-40 CPM: financas pessoais, investimentos, tech enterprise, saude, educacao profissional, imoveis, cripto)
- ~40% em RPM MEDIO ($5-14 CPM: lifestyle, self-help, hobbies especializados, viagens, food, gaming competitivo)
- ~30% em RPM BAIXO ($1-4 CPM: entretenimento puro, reacao, compilacoes, storytelling simples)

**Passo 4 — Analise competitiva:** Para cada variacao, estime o nivel de competicao (LOW/MEDIUM/HIGH/SATURATED) e flagueie nichos sub-atendidos.

**Passo 5 — Producao:** Avalie complexidade de producao (EASY = talking head/stock/edicao simples, MEDIUM = B-roll + narracao + motion graphics, HARD = 3D, VFX, atores) e tempo estimado por video.

**Passo 6 — Hook temporal:** Se possivel, conecte a variacao com uma tendencia em alta dos dados de mercado fornecidos acima.

Retorne este JSON exato:

{{
  "dna": {{
    "hook_pattern": "descricao do padrao de hook que funcionou",
    "title_formula": "formula do titulo (ex: '[Baby Animal] + [Action] + [Seeking Help]')",
    "emotional_driver": "qual gatilho emocional (empatia, curiosidade, medo, poder, status, FOMO, etc)",
    "structure": "estrutura narrativa em 1 linha",
    "target_audience": "quem assiste e por que",
    "why_it_worked": "3-4 frases explicando o sucesso — considere formato + timing + emocional",
    "format_type": "talking-head | narrative-doc | list | reaction | tutorial | case-study | storytelling | vlog"
  }},
  "fixed_elements": ["elemento 1 preservar sempre", "elemento 2", "elemento 3"],
  "variable_elements": ["elemento 1 pode trocar", "elemento 2", "elemento 3"],
  "variations": [
    {{
      "title": "Titulo novo seguindo a formula",
      "angle": "Qual o novo angulo/tema",
      "preserved_dna": "O que foi mantido do original",
      "changed_elements": "O que mudou",
      "new_niche_suggestion": "Nome do novo nicho/canal",
      "rpm_tier": "HIGH | MEDIUM | LOW",
      "rpm_estimate_usd": "$15-25 por 1000 views",
      "competition_level": "LOW | MEDIUM | HIGH | SATURATED",
      "production_complexity": "EASY | MEDIUM | HARD",
      "estimated_production_hours": 6,
      "potential_score": 85,
      "reasoning": "Por que vai funcionar (3-4 frases). Conecte com dados de mercado quando possivel.",
      "timing_hook": "Por que AGORA — conecte com trend em alta se houver",
      "visual_style": "Sugestao de estilo visual",
      "target_audience": "Novo publico-alvo especifico",
      "example_pillars": ["Pilar de conteudo 1", "Pilar 2", "Pilar 3", "Pilar 4", "Pilar 5"],
      "thumbnail_concepts": [
        "Conceito 1 da thumbnail (descricao visual em 1 frase)",
        "Conceito 2",
        "Conceito 3"
      ],
      "first_3_titles": [
        "Titulo de video 1 pro canal novo",
        "Titulo 2",
        "Titulo 3"
      ]
    }}
  ]
}}

REGRAS CRITICAS:
- Score 0-100 (realista: 55-95 range, 100 apenas para oportunidade excepcional)
- As {num_variations} variacoes DEVEM ser BEM diferentes entre si — angulos distintos, audiencias distintas, nichos distintos
- Pelo menos 1 variacao em RPM alto (tier HIGH)
- Pelo menos 1 variacao com producao EASY (baixa barreira de entrada)
- Pelo menos 1 variacao em nicho com competicao LOW ou MEDIUM (gap de mercado)
- Titulos na LINGUA {language} — nao traduzir literalmente, ADAPTAR culturalmente
- Preserve a FORMULA do titulo — nao invente estruturas novas
- Se os dados de mercado mostram uma keyword/trend em alta, USE ela em pelo menos 1 variacao
- thumbnail_concepts e first_3_titles sao obrigatorios — nao retorne listas vazias"""


# ═══════════════════════════════════════════════════════════════════
# URL CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════

VIDEO_URL_PATTERNS = [
    re.compile(r"youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtu\.be/([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([a-zA-Z0-9_-]{11})"),
]

CHANNEL_URL_PATTERNS = [
    re.compile(r"youtube\.com/@([a-zA-Z0-9_.-]+)"),
    re.compile(r"youtube\.com/c/([a-zA-Z0-9_.-]+)"),
    re.compile(r"youtube\.com/channel/([a-zA-Z0-9_-]+)"),
    re.compile(r"youtube\.com/user/([a-zA-Z0-9_-]+)"),
]

PLAYLIST_URL_PATTERN = re.compile(r"youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)")


def classify_url(url: str) -> str:
    """Return 'video', 'channel', 'playlist', or 'unknown'."""
    url = (url or "").strip()
    if not url:
        return "unknown"
    for pat in VIDEO_URL_PATTERNS:
        if pat.search(url):
            return "video"
    if PLAYLIST_URL_PATTERN.search(url):
        return "playlist"
    for pat in CHANNEL_URL_PATTERNS:
        if pat.search(url):
            return "channel"
    return "unknown"


# ═══════════════════════════════════════════════════════════════════
# METADATA FETCH — supports video, channel, playlist URLs
# ═══════════════════════════════════════════════════════════════════

def fetch_youtube_metadata(url: str) -> dict:
    """
    Fetch YouTube metadata using yt-dlp.

    For video URLs: returns single video info
    For channel URLs: returns TOP video by views + list of top 10 candidates
    For playlist URLs: returns top video in playlist + candidate list

    Response shape:
    - Success (video): {title, views, ..., url_type: 'video'}
    - Success (channel): {title, views, ..., url_type: 'channel',
                          candidates: [...], channel_url: '...'}
    - Failure: {error: '...'}
    """
    url = (url or "").strip()
    if not url:
        return {"error": "URL vazia"}

    url_type = classify_url(url)
    if url_type == "unknown":
        return {"error": f"URL nao reconhecida como YouTube: {url[:100]}"}

    logger.info(f"[IDEA_BENDER] Fetching metadata: type={url_type}, url={url[:80]}")

    try:
        if url_type == "video":
            return _fetch_single_video(url)
        elif url_type == "channel":
            return _fetch_channel_top_videos(url)
        elif url_type == "playlist":
            return _fetch_playlist_top_videos(url)
    except subprocess.TimeoutExpired:
        return {"error": "yt-dlp timeout (90s) — canal muito grande ou rede lenta"}
    except FileNotFoundError:
        return {"error": "yt-dlp nao instalado no servidor"}
    except Exception as e:
        logger.exception(f"[IDEA_BENDER] fetch failed: {e}")
        return {"error": f"Falha ao buscar metadata: {str(e)[:200]}"}

    return {"error": "Tipo de URL nao suportado"}


def _fetch_single_video(url: str) -> dict:
    """Fetch metadata for a single video URL."""
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-warnings", "--no-playlist", url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        return {"error": f"yt-dlp falhou: {result.stderr[:200]}"}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"yt-dlp retornou JSON invalido: {e}"}

    return _normalize_video_info(data, url_type="video")


def _fetch_channel_top_videos(url: str, max_videos: int = 10) -> dict:
    """
    Fetch top N videos from a channel URL, sorted by views.
    Returns the top-viewed video as primary + list of candidates.
    """
    # Normalize channel URL to /videos tab for consistent behavior
    videos_url = url.rstrip("/")
    if "/videos" not in videos_url and "/watch" not in videos_url:
        videos_url = f"{videos_url}/videos"

    # Use --flat-playlist to get lightweight list, then fetch top video fully
    result = subprocess.run(
        [
            "yt-dlp",
            "--dump-json",
            "--flat-playlist",
            "--no-warnings",
            "--playlist-end", str(max_videos * 3),  # fetch extras to sort
            videos_url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )

    if result.returncode != 0:
        stderr = result.stderr[:300]
        logger.warning(f"[IDEA_BENDER] channel fetch returncode={result.returncode}: {stderr}")
        # Retry without /videos suffix in case yt-dlp doesnt like it
        if "/videos" in videos_url:
            videos_url_retry = videos_url.replace("/videos", "")
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--dump-json",
                    "--flat-playlist",
                    "--no-warnings",
                    "--playlist-end", str(max_videos * 3),
                    videos_url_retry,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            if result.returncode != 0:
                return {"error": f"yt-dlp falhou no canal: {result.stderr[:200]}"}

    # Parse line-delimited JSON (one per video in flat playlist)
    candidates = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not entry.get("id"):
            continue
        candidates.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", ""),
            "views": entry.get("view_count", 0) or 0,
            "duration": entry.get("duration", 0) or 0,
            "upload_date": entry.get("upload_date", ""),
            "webpage_url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
        })

    if not candidates:
        return {"error": "Nenhum video encontrado no canal. Verifique se a URL esta correta e o canal tem videos publicos."}

    # Sort by views descending
    candidates.sort(key=lambda c: c["views"], reverse=True)
    top_candidates = candidates[:max_videos]

    # Pick the best video (highest views, skip shorts < 60s if longer videos available)
    primary = None
    for c in top_candidates:
        if c["duration"] >= 60:
            primary = c
            break
    if primary is None:
        primary = top_candidates[0]

    # Fetch full metadata for the primary video
    full = _fetch_single_video(primary["webpage_url"])
    if "error" in full:
        # Fallback: use the flat metadata we already have
        full = {
            "title": primary["title"],
            "views": primary["views"],
            "duration_sec": primary["duration"],
            "description": "",
            "channel": "",
            "uploader": "",
            "like_count": 0,
            "comment_count": 0,
            "upload_date": primary["upload_date"],
            "thumbnail": "",
            "webpage_url": primary["webpage_url"],
        }

    full["url_type"] = "channel"
    full["channel_url"] = url
    full["candidates"] = top_candidates
    full["candidates_count"] = len(candidates)
    return full


def _fetch_playlist_top_videos(url: str, max_videos: int = 20) -> dict:
    """Similar to channel fetch but for playlists."""
    result = subprocess.run(
        [
            "yt-dlp",
            "--dump-json",
            "--flat-playlist",
            "--no-warnings",
            "--playlist-end", str(max_videos),
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    if result.returncode != 0:
        return {"error": f"yt-dlp falhou na playlist: {result.stderr[:200]}"}

    candidates = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not entry.get("id"):
            continue
        candidates.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", ""),
            "views": entry.get("view_count", 0) or 0,
            "duration": entry.get("duration", 0) or 0,
            "webpage_url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}",
        })

    if not candidates:
        return {"error": "Playlist vazia ou inacessivel"}

    candidates.sort(key=lambda c: c["views"], reverse=True)
    primary = candidates[0]
    full = _fetch_single_video(primary["webpage_url"])
    if "error" in full:
        return {"error": f"Falha ao buscar video top da playlist: {full['error']}"}
    full["url_type"] = "playlist"
    full["playlist_url"] = url
    full["candidates"] = candidates[:10]
    return full


def _normalize_video_info(data: dict, url_type: str = "video") -> dict:
    """Normalize yt-dlp video info dict to our standard shape."""
    return {
        "title": data.get("title", ""),
        "views": data.get("view_count", 0) or 0,
        "duration_sec": data.get("duration", 0) or 0,
        "description": (data.get("description") or "")[:2500],
        "channel": data.get("channel", "") or data.get("uploader", ""),
        "uploader": data.get("uploader", ""),
        "like_count": data.get("like_count", 0) or 0,
        "comment_count": data.get("comment_count", 0) or 0,
        "upload_date": data.get("upload_date", ""),
        "thumbnail": data.get("thumbnail", ""),
        "webpage_url": data.get("webpage_url", ""),
        "tags": (data.get("tags") or [])[:20],
        "categories": data.get("categories") or [],
        "url_type": url_type,
    }


# ═══════════════════════════════════════════════════════════════════
# SIGNAL EXTRACTION — compute virality metrics
# ═══════════════════════════════════════════════════════════════════

def extract_success_signals(meta: dict) -> dict:
    """
    Compute virality signals from video metadata.

    Returns metrics dict that enriches the LLM prompt.
    """
    views = int(meta.get("views", 0) or 0)
    likes = int(meta.get("like_count", 0) or 0)
    comments = int(meta.get("comment_count", 0) or 0)
    duration_sec = int(meta.get("duration_sec", 0) or 0)
    upload_date = meta.get("upload_date", "") or ""  # YYYYMMDD

    signals = {
        "views": views,
        "likes": likes,
        "comments": comments,
        "duration_sec": duration_sec,
        "duration_label": _format_duration(duration_sec),
        "engagement_rate_pct": 0.0,
        "views_per_day": 0,
        "days_since_upload": 0,
        "virality_tier": "UNKNOWN",
    }

    if views > 0:
        signals["engagement_rate_pct"] = round(((likes + comments * 3) / views) * 100, 2)

    if upload_date and len(upload_date) == 8:
        try:
            dt = datetime.strptime(upload_date, "%Y%m%d")
            days = max(1, (datetime.now() - dt).days)
            signals["days_since_upload"] = days
            signals["views_per_day"] = views // days if days > 0 else views
        except ValueError:
            pass

    # Virality tier based on views
    if views >= 10_000_000:
        signals["virality_tier"] = "MEGA_VIRAL"
    elif views >= 1_000_000:
        signals["virality_tier"] = "VIRAL"
    elif views >= 100_000:
        signals["virality_tier"] = "PERFORMING"
    elif views >= 10_000:
        signals["virality_tier"] = "MODEST"
    elif views > 0:
        signals["virality_tier"] = "LOW"

    return signals


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "?"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


# ═══════════════════════════════════════════════════════════════════
# MARKET RESEARCH — Google Trends + YouTube search integration
# ═══════════════════════════════════════════════════════════════════

def gather_market_research(niche: str, title: str, language: str = "en",
                           youtube_api_key: str = "") -> str:
    """
    Collect real market data for the niche/title to feed into the LLM prompt.

    Returns a text block ready to paste into the prompt.
    Gracefully degrades if trend research fails.
    """
    if not niche and not title:
        return "(sem dados de mercado disponiveis)"

    # Use the existing trend_research module
    try:
        from protocols.trend_research import research_niche_demand
    except ImportError:
        return "(trend_research nao disponivel)"

    # Use title keywords as the search term if no niche
    search_term = niche or _extract_keywords_from_title(title)

    try:
        demand = research_niche_demand(
            niche=search_term,
            language=language,
            youtube_api_key=youtube_api_key,
        )
    except Exception as e:
        logger.warning(f"[IDEA_BENDER] market research failed: {e}")
        return f"(pesquisa de mercado falhou: {str(e)[:100]})"

    # Format the result as a text block
    lines = []
    trending_titles = demand.get("trending_titles", [])[:8]
    rising = demand.get("rising_searches", [])[:6]
    keywords = demand.get("trending_keywords", [])[:10]
    hooks = demand.get("top_hooks", [])[:5]
    avg_views = demand.get("avg_views", 0)

    if trending_titles:
        lines.append("**Top titulos virais no nicho (ultimos 14 dias):**")
        for t in trending_titles:
            if isinstance(t, str):
                lines.append(f"  - {t[:100]}")
        if avg_views:
            lines.append(f"  (media de views: {avg_views:,})")

    if rising:
        lines.append("\n**Queries em alta no Google Trends:**")
        for s in rising:
            if isinstance(s, dict):
                q = s.get("query", "")
                g = s.get("growth", "")
                region = s.get("region", "")
                lines.append(f"  - {q} ({g}{' ' + region if region else ''})")
            elif isinstance(s, str):
                lines.append(f"  - {s}")

    if keywords:
        lines.append(f"\n**Keywords de alta frequencia:** {', '.join(str(k) for k in keywords)}")

    if hooks:
        lines.append(f"\n**Hooks dos tops videos:** {', '.join(str(h) for h in hooks)}")

    if not lines:
        return "(sem dados de mercado — proceda com analise baseada apenas no titulo original)"

    return "\n".join(lines)


def _extract_keywords_from_title(title: str) -> str:
    """Extract the most meaningful keywords from a title for search."""
    # Remove common stopwords and short words
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "up", "about", "into", "over", "after",
        "o", "a", "os", "as", "de", "da", "do", "e", "é", "com", "por", "para",
        "um", "uma", "no", "na", "nos", "nas", "se", "que",
    }
    words = re.findall(r"\b[a-zA-Z\u00C0-\u017F]{4,}\b", title.lower())
    meaningful = [w for w in words if w not in stopwords]
    return " ".join(meaningful[:5])


# ═══════════════════════════════════════════════════════════════════
# JSON EXTRACTION — handle LLM output variations
# ═══════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from AI response (handles markdown code blocks and extra text)."""
    if not text:
        return None
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding the first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════
# MAIN BEND FUNCTION — orchestrates all phases
# ═══════════════════════════════════════════════════════════════════

def bend_idea(
    title: str,
    sop: str,
    niche: str = "",
    language: str = "en",
    num_variations: int = 5,
    extra_context: str = "",
    market_research: str = "",
    youtube_api_key: str = "",
) -> dict:
    """
    Generate N bent variations of a validated idea with multi-phase strategy.

    Args:
        title: Original idea title (the "winning" one)
        sop: Project SOP content (context about the channel DNA)
        niche: Original niche name
        language: Target language for generated titles
        num_variations: How many variations to generate (3-10)
        extra_context: Optional extra info (views, engagement, etc)
        market_research: Pre-computed market research text block (optional)
        youtube_api_key: For trend research fallback if market_research is empty

    Returns:
        dict with keys: dna, fixed_elements, variable_elements, variations, market_research_used
        On failure: returns dict with error key.
    """
    if not title or not title.strip():
        return {"error": "Title is required"}

    num_variations = max(3, min(num_variations, 10))
    sop_excerpt = (sop or "")[:6000]

    # If market_research wasn't pre-computed, try to gather it now
    if not market_research:
        market_research = gather_market_research(
            niche=niche,
            title=title,
            language=language,
            youtube_api_key=youtube_api_key,
        )

    prompt = BENDER_USER_TEMPLATE.format(
        title=title.strip(),
        niche=niche or "Unknown",
        language=language or "en",
        sop_excerpt=sop_excerpt or "(no SOP available)",
        num_variations=num_variations,
        extra_context=f"\n**Extra context:** {extra_context}" if extra_context else "",
        market_research=market_research or "(sem dados de mercado disponiveis)",
    )

    logger.info(
        f"[IDEA_BENDER v2] Bending: '{title[:60]}' ({num_variations}x), "
        f"niche={niche}, market_research={len(market_research)} chars"
    )

    try:
        response = chat(
            prompt=prompt,
            system=BENDER_SYSTEM_PROMPT,
            max_tokens=12000,
            temperature=0.85,
            timeout=240,
        )
    except Exception as e:
        logger.error(f"[IDEA_BENDER] AI call failed: {e}")
        return {"error": f"Falha na chamada de IA: {str(e)[:200]}"}

    parsed = _extract_json(response)
    if not parsed:
        logger.error(f"[IDEA_BENDER] Could not parse JSON: {response[:300]}")
        return {"error": "IA retornou JSON invalido", "raw": response[:1500]}

    if "variations" not in parsed or not isinstance(parsed.get("variations"), list):
        return {"error": "Resposta sem lista 'variations'", "raw": parsed}

    # Normalize each variation
    for i, v in enumerate(parsed["variations"]):
        v.setdefault("title", f"Variation {i + 1}")
        v.setdefault("angle", "")
        v.setdefault("preserved_dna", "")
        v.setdefault("changed_elements", "")
        v.setdefault("new_niche_suggestion", "")
        v.setdefault("rpm_tier", "MEDIUM")
        v.setdefault("rpm_estimate_usd", "")
        v.setdefault("competition_level", "MEDIUM")
        v.setdefault("production_complexity", "MEDIUM")
        v.setdefault("estimated_production_hours", 0)
        v.setdefault("potential_score", 70)
        v.setdefault("reasoning", "")
        v.setdefault("timing_hook", "")
        v.setdefault("visual_style", "")
        v.setdefault("target_audience", "")
        v.setdefault("example_pillars", [])
        v.setdefault("thumbnail_concepts", [])
        v.setdefault("first_3_titles", [])

        # Clamp/normalize
        try:
            v["potential_score"] = max(0, min(100, int(v["potential_score"])))
        except (ValueError, TypeError):
            v["potential_score"] = 70
        try:
            v["estimated_production_hours"] = max(0, int(v["estimated_production_hours"]))
        except (ValueError, TypeError):
            v["estimated_production_hours"] = 0

        # Normalize tier/level/complexity enums
        v["rpm_tier"] = str(v.get("rpm_tier", "")).upper() or "MEDIUM"
        if v["rpm_tier"] not in ("HIGH", "MEDIUM", "LOW"):
            v["rpm_tier"] = "MEDIUM"
        v["competition_level"] = str(v.get("competition_level", "")).upper() or "MEDIUM"
        if v["competition_level"] not in ("LOW", "MEDIUM", "HIGH", "SATURATED"):
            v["competition_level"] = "MEDIUM"
        v["production_complexity"] = str(v.get("production_complexity", "")).upper() or "MEDIUM"
        if v["production_complexity"] not in ("EASY", "MEDIUM", "HARD"):
            v["production_complexity"] = "MEDIUM"

    parsed.setdefault("dna", {})
    parsed.setdefault("fixed_elements", [])
    parsed.setdefault("variable_elements", [])
    parsed["market_research_used"] = bool(market_research and "(sem dados" not in market_research)

    # Sort variations: composite score = potential × RPM multiplier × (1/competition)
    rpm_mult = {"HIGH": 1.3, "MEDIUM": 1.0, "LOW": 0.7}
    comp_div = {"LOW": 0.8, "MEDIUM": 1.0, "HIGH": 1.3, "SATURATED": 1.8}
    for v in parsed["variations"]:
        base = v.get("potential_score", 70)
        tier_mult = rpm_mult.get(v.get("rpm_tier", "MEDIUM"), 1.0)
        comp_penalty = comp_div.get(v.get("competition_level", "MEDIUM"), 1.0)
        v["composite_score"] = round((base * tier_mult) / comp_penalty, 1)

    parsed["variations"].sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    logger.info(
        f"[IDEA_BENDER v2] Generated {len(parsed['variations'])} variations, "
        f"top composite score: {parsed['variations'][0].get('composite_score', 0) if parsed['variations'] else 0}"
    )
    return parsed
