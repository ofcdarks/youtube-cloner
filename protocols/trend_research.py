"""
Trend Research — Pre-research module for data-driven title generation.

Collects real demand data BEFORE generating titles:
1. YouTube trending videos in the niche (last 14 days)
2. Google Trends rising queries
3. Extracts winning patterns (keywords, formats, hooks)

This data feeds into the AI prompt so titles are born with high demand.
"""

import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger("ytcloner.trend_research")


def research_niche_demand(niche: str, language: str = "pt-BR", youtube_api_key: str = "") -> dict:
    """
    Collect real demand data for a niche.

    Returns:
    {
        "trending_titles": ["title1", "title2", ...],     # Top 15 viral titles
        "trending_keywords": ["keyword1", "keyword2"],     # Extracted high-freq words
        "rising_searches": ["query1", "query2"],           # Google Trends rising
        "title_patterns": ["pattern1", "pattern2"],        # Common title formats
        "avg_views": 50000,                                # Average views of trending
        "top_hooks": ["hook1", "hook2"],                   # First words of top titles
        "summary": "text summary for AI prompt"            # Ready-to-use text block
    }
    """
    result = {
        "trending_titles": [],
        "trending_keywords": [],
        "rising_searches": [],
        "title_patterns": [],
        "avg_views": 0,
        "top_hooks": [],
        "summary": "",
    }

    lang_code = language[:2]  # "pt-BR" -> "pt"

    # 1. YouTube Search — trending videos in niche (last 14 days)
    if youtube_api_key:
        try:
            result.update(_fetch_youtube_trending(niche, youtube_api_key, lang_code))
        except Exception as e:
            logger.warning(f"YouTube trending fetch failed: {e}")

    # 2. Google Trends — rising queries
    try:
        result.update(_fetch_google_trends(niche, lang_code))
    except Exception as e:
        logger.warning(f"Google Trends fetch failed: {e}")

    # 3. Extract patterns from titles
    if result["trending_titles"]:
        result.update(_extract_patterns(result["trending_titles"]))

    # 4. Build summary for AI prompt
    result["summary"] = _build_summary(result, niche, language)

    logger.info(f"Research complete: {len(result['trending_titles'])} titles, "
                f"{len(result['rising_searches'])} trends, "
                f"{len(result['trending_keywords'])} keywords")

    return result


def _fetch_youtube_trending(niche: str, api_key: str, lang: str) -> dict:
    """Fetch trending YouTube videos in the niche."""
    import requests

    # Calculate date 14 days ago
    after = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")

    resp = requests.get("https://www.googleapis.com/youtube/v3/search", params={
        "part": "snippet",
        "q": niche,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": after,
        "maxResults": 20,
        "key": api_key,
        "relevanceLanguage": lang,
    }, timeout=15)

    if resp.status_code != 200:
        return {}

    items = resp.json().get("items", [])
    titles = []
    video_ids = []

    for item in items:
        s = item.get("snippet", {})
        titles.append(s.get("title", ""))
        vid = item.get("id", {}).get("videoId", "")
        if vid:
            video_ids.append(vid)

    # Get view counts for calculating average
    avg_views = 0
    if video_ids and api_key:
        try:
            stats_resp = requests.get("https://www.googleapis.com/youtube/v3/videos", params={
                "part": "statistics",
                "id": ",".join(video_ids[:15]),
                "key": api_key,
            }, timeout=15)
            if stats_resp.status_code == 200:
                views = []
                for v in stats_resp.json().get("items", []):
                    vc = int(v.get("statistics", {}).get("viewCount", 0))
                    if vc > 0:
                        views.append(vc)
                if views:
                    avg_views = sum(views) // len(views)
        except Exception:
            pass

    return {
        "trending_titles": titles[:15],
        "avg_views": avg_views,
    }


def _fetch_google_trends(niche: str, lang: str) -> dict:
    """Fetch Google Trends rising queries for the niche."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return {"rising_searches": []}

    try:
        pytrends = TrendReq(hl=lang, tz=360, timeout=(10, 25))
        pytrends.build_payload([niche], timeframe="now 7-d")

        related = pytrends.related_queries()
        rising = []

        if niche in related and related[niche].get("rising") is not None:
            df = related[niche]["rising"].head(15)
            for _, row in df.iterrows():
                rising.append({
                    "query": row["query"],
                    "growth": row["value"],
                })

        return {"rising_searches": rising}
    except Exception as e:
        logger.warning(f"Google Trends error: {e}")
        return {"rising_searches": []}


def _extract_patterns(titles: list[str]) -> dict:
    """Extract winning patterns from trending titles."""
    if not titles:
        return {}

    # Stop words per language
    stop_words = {
        "que", "de", "la", "el", "los", "las", "un", "una", "en", "del", "por", "con",
        "para", "como", "mas", "pero", "the", "and", "for", "that", "this", "with",
        "you", "are", "was", "not", "has", "had", "its", "from", "o", "a", "do", "da",
        "no", "na", "os", "as", "ao", "dos", "das", "um", "uma", "se", "ou", "e",
        "es", "y", "lo", "al", "su", "si", "te", "tu", "yo", "nos", "le",
    }

    # Count word frequency
    word_freq = {}
    for title in titles:
        words = re.findall(r'[a-záéíóúñçãõâêîôûü]+', title.lower())
        for w in words:
            if len(w) > 3 and w not in stop_words:
                word_freq[w] = word_freq.get(w, 0) + 1

    # Top keywords (appear in 3+ titles)
    keywords = sorted(
        [(w, c) for w, c in word_freq.items() if c >= 2],
        key=lambda x: x[1], reverse=True
    )[:20]

    # Title format patterns
    patterns = []
    num_with_numbers = sum(1 for t in titles if re.search(r'\d+', t))
    num_with_questions = sum(1 for t in titles if "?" in t)
    num_with_caps = sum(1 for t in titles if re.search(r'[A-ZÁÉÍÓÚ]{3,}', t))
    num_with_ellipsis = sum(1 for t in titles if "..." in t)

    total = len(titles)
    if num_with_numbers / total > 0.3:
        patterns.append(f"Numeros nos titulos ({num_with_numbers}/{total} = {num_with_numbers*100//total}%)")
    if num_with_questions / total > 0.2:
        patterns.append(f"Perguntas ({num_with_questions}/{total} = {num_with_questions*100//total}%)")
    if num_with_caps / total > 0.3:
        patterns.append(f"Palavras em CAPS ({num_with_caps}/{total} = {num_with_caps*100//total}%)")
    if num_with_ellipsis / total > 0.2:
        patterns.append(f"Suspense com ... ({num_with_ellipsis}/{total} = {num_with_ellipsis*100//total}%)")

    # Extract hooks (first 5-8 words of top titles)
    hooks = []
    for t in titles[:8]:
        words = t.split()[:6]
        if len(words) >= 3:
            hooks.append(" ".join(words))

    return {
        "trending_keywords": [w for w, _ in keywords],
        "title_patterns": patterns,
        "top_hooks": hooks,
    }


def _build_summary(data: dict, niche: str, language: str) -> str:
    """Build a text summary ready to inject into AI prompt."""
    lines = []

    lines.append(f"=== PRE-PESQUISA DE DEMANDA: {niche.upper()} ===\n")

    if data["trending_titles"]:
        lines.append(f"TITULOS VIRAIS NAS ULTIMAS 2 SEMANAS ({len(data['trending_titles'])} videos):")
        for i, t in enumerate(data["trending_titles"][:10], 1):
            lines.append(f"  {i}. {t}")
        if data["avg_views"]:
            lines.append(f"  Media de views: {data['avg_views']:,}")
        lines.append("")

    if data["trending_keywords"]:
        lines.append(f"KEYWORDS DE ALTA FREQUENCIA (aparecem em multiplos titulos virais):")
        lines.append(f"  {', '.join(data['trending_keywords'][:15])}")
        lines.append("")

    if data["rising_searches"]:
        lines.append(f"BUSCAS EM ALTA NO GOOGLE TRENDS (ultimos 7 dias):")
        for rs in data["rising_searches"][:10]:
            growth = rs.get("growth", "")
            lines.append(f"  - {rs['query']} (crescimento: {growth}%)")
        lines.append("")

    if data["title_patterns"]:
        lines.append(f"PADROES DE TITULO QUE FUNCIONAM:")
        for p in data["title_patterns"]:
            lines.append(f"  - {p}")
        lines.append("")

    if data["top_hooks"]:
        lines.append(f"HOOKS QUE FUNCIONAM (primeiras palavras dos titulos virais):")
        for h in data["top_hooks"][:5]:
            lines.append(f'  - "{h}..."')
        lines.append("")

    lines.append("INSTRUCAO: Use estes dados REAIS para criar titulos que combinam DEMANDA COMPROVADA + estilo do SOP.")
    lines.append("Cada titulo deve conter pelo menos 1 keyword de alta frequencia ou seguir 1 padrao identificado.")
    lines.append(f"=== FIM DA PRE-PESQUISA ===")

    return "\n".join(lines)
