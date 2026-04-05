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

    # 1. YouTube Search — trending videos in MULTIPLE languages
    # Search in: channel language + English (where most model channels operate) + global
    if youtube_api_key:
        all_titles = []
        search_langs = list(dict.fromkeys([lang_code, "en"]))  # dedupe, channel lang first

        for sl in search_langs:
            try:
                yt_data = _fetch_youtube_trending(niche, youtube_api_key, sl)
                new_titles = yt_data.get("trending_titles", [])
                all_titles.extend(new_titles)
                if sl == lang_code:
                    result["avg_views"] = yt_data.get("avg_views", 0)
                logger.info(f"YouTube [{sl}]: {len(new_titles)} videos found")
            except Exception as e:
                logger.warning(f"YouTube trending [{sl}] failed: {e}")

        # Deduplicate titles
        seen = set()
        unique_titles = []
        for t in all_titles:
            if t.lower() not in seen:
                seen.add(t.lower())
                unique_titles.append(t)
        result["trending_titles"] = unique_titles[:20]

    # 2. Google Trends — rising queries in MULTIPLE regions
    all_searches = []
    trend_regions = list(dict.fromkeys([lang_code, "en"]))

    for tr in trend_regions:
        try:
            trends = _fetch_google_trends(niche, tr)
            new_searches = trends.get("rising_searches", [])
            for s in new_searches:
                s["region"] = tr
            all_searches.extend(new_searches)
            logger.info(f"Trends [{tr}]: {len(new_searches)} rising queries")
        except Exception as e:
            logger.warning(f"Google Trends [{tr}] failed: {e}")

    # Deduplicate and sort by growth
    seen_queries = set()
    unique_searches = []
    for s in sorted(all_searches, key=lambda x: int(str(x.get("growth", 0)).replace("%", "").replace(",", "") or 0), reverse=True):
        q = s.get("query", "").lower()
        if q not in seen_queries:
            seen_queries.add(q)
            unique_searches.append(s)
    result["rising_searches"] = unique_searches[:20]

    # 3. Extract patterns from titles
    if result["trending_titles"]:
        result.update(_extract_patterns(result["trending_titles"]))

    # 4. Keywords Everywhere — search volume for top keywords (non-blocking)
    result["keyword_volumes"] = []
    try:
        from protocols.keywords_everywhere import get_youtube_keyword_data

        volume_keywords = result["trending_keywords"][:15]
        if not volume_keywords and result["trending_titles"]:
            # Fallback: extract keywords from titles
            from protocols.title_scorer import extract_keywords
            for t in result["trending_titles"][:5]:
                volume_keywords.extend(extract_keywords(t, language[:2]))
            volume_keywords = list(dict.fromkeys(volume_keywords))[:15]

        if volume_keywords:
            lang_to_country = {
                "pt": "br", "en": "us", "es": "es", "fr": "fr", "de": "de",
                "it": "it", "ja": "jp", "ko": "kr",
            }
            # Search in BOTH: channel country + US (global/english)
            countries_to_search = list(dict.fromkeys([
                lang_to_country.get(language[:2], "us"),
                "us",  # Always include US/English (where most SOPs originate)
            ]))
            all_kw_data = []
            for country in countries_to_search:
                try:
                    kw_data = get_youtube_keyword_data(volume_keywords, country=country)
                    for kw in kw_data:
                        kw["country"] = country
                    all_kw_data.extend(kw_data)
                    logger.info(f"DataForSEO [{country}]: {len(kw_data)} volume results")
                except Exception:
                    pass
            # Deduplicate keeping highest volume per keyword
            best_per_kw = {}
            for kw in all_kw_data:
                key = kw.get("keyword", "")
                if key not in best_per_kw or kw.get("vol", 0) > best_per_kw[key].get("vol", 0):
                    best_per_kw[key] = kw
            result["keyword_volumes"] = sorted(
                best_per_kw.values(), key=lambda x: x.get("vol", 0), reverse=True
            )
            logger.info(f"DataForSEO total: {len(result['keyword_volumes'])} unique keywords with volume")
    except Exception as e:
        logger.warning(f"Keywords Everywhere integration failed: {e}")

    # 5. Build summary for AI prompt
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
        lines.append(f"BUSCAS EM ALTA NO GOOGLE TRENDS (ultimos 7 dias — multi-regiao):")
        for rs in data["rising_searches"][:15]:
            growth = rs.get("growth", "")
            region = rs.get("region", "")
            region_label = {"en": "EN", "es": "ES", "pt": "BR", "fr": "FR", "de": "DE"}.get(region, region.upper())
            lines.append(f"  - [{region_label}] {rs['query']} (crescimento: {growth}%)")
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

    if data.get("keyword_volumes"):
        high_vol = [kv for kv in data["keyword_volumes"] if kv.get("vol", 0) > 0]
        if high_vol:
            lines.append("VOLUME DE BUSCA NO YOUTUBE (Keywords Everywhere):")
            for kv in high_vol[:10]:
                vol = kv.get("vol", 0)
                cpc = kv.get("cpc", 0)
                comp = kv.get("competition", 0)
                lines.append(f"  - \"{kv['keyword']}\": {vol:,} buscas/mes (CPC ${cpc:.2f}, competicao {comp:.2f})")
            lines.append("")

    lines.append("INSTRUCAO: Use estes dados REAIS para criar titulos que combinam DEMANDA COMPROVADA + estilo do SOP.")
    lines.append("Cada titulo deve conter pelo menos 1 keyword de alta frequencia ou seguir 1 padrao identificado.")
    if data.get("keyword_volumes"):
        lines.append("PRIORIZE keywords com alto volume de busca no YouTube para maximizar alcance organico.")
    lines.append(f"=== FIM DA PRE-PESQUISA ===")

    return "\n".join(lines)
