"""
Keywords Everywhere API integration — search volume, CPC, and competition data.

Supports both Google Keyword Planner and YouTube-specific data sources.
API key is loaded from admin_settings DB, falling back to env var.
On first successful use the key is persisted to admin_settings.
"""

import logging
import re
from typing import Any

import requests

logger = logging.getLogger("ytcloner.keywords_everywhere")

_API_BASE = "https://api.keywordseverywhere.com/v1"
_TIMEOUT = 15


def _get_api_key() -> str:
    """
    Resolve API key with priority:
      1. admin_settings DB
      2. Environment variable via config.py
    On first use, persist env-var key into DB so future lookups hit DB.
    """
    try:
        from database import get_setting, set_setting

        db_key = get_setting("keywords_everywhere_api_key")
        if db_key:
            return db_key
    except Exception as exc:
        logger.debug(f"Could not read admin_settings: {exc}")

    from config import KEYWORDS_EVERYWHERE_API_KEY

    env_key = KEYWORDS_EVERYWHERE_API_KEY
    if env_key:
        # Persist to DB for future lookups
        try:
            from database import set_setting
            set_setting("keywords_everywhere_api_key", env_key)
            logger.info("Keywords Everywhere API key saved to admin_settings")
        except Exception as exc:
            logger.warning(f"Could not persist API key to DB: {exc}")
    return env_key


# ── Public API functions ────────────────────────────────


def get_keyword_data(
    keywords: list[str],
    country: str = "us",
    data_source: str = "gkp",
) -> list[dict[str, Any]]:
    """
    Get search volume, CPC, and competition for keywords.

    Args:
        keywords: List of keyword strings.
        country: ISO country code (default "us").
        data_source: "gkp" for Google Keyword Planner, "yt" for YouTube.

    Returns:
        List of dicts: [{"keyword": "...", "vol": 12400, "cpc": 0.45, "competition": 0.32}]
        Returns empty list on any error (non-blocking).
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("Keywords Everywhere API key not configured — skipping")
        return []

    if not keywords:
        return []

    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        data: dict[str, Any] = {
            "dataSource": data_source,
            "country": country,
            "currency": "USD",
        }
        # requests encodes repeated keys when value is a list
        kw_params = [("kw[]", kw) for kw in keywords[:100]]

        resp = requests.post(
            f"{_API_BASE}/get_keyword_data",
            headers=headers,
            data=data,
            params=kw_params,
            timeout=_TIMEOUT,
        )

        if resp.status_code != 200:
            logger.warning(
                f"Keywords Everywhere API error {resp.status_code}: {resp.text[:200]}"
            )
            return []

        body = resp.json()
        results: list[dict[str, Any]] = []

        for item in body.get("data", []):
            results.append({
                "keyword": item.get("keyword", ""),
                "vol": item.get("vol", 0),
                "cpc": item.get("cpc", {}).get("value", 0) if isinstance(item.get("cpc"), dict) else item.get("cpc", 0),
                "competition": item.get("competition", 0),
            })

        logger.info(
            f"Keywords Everywhere: {len(results)} results for {len(keywords)} keywords "
            f"(source={data_source}, country={country})"
        )
        return results

    except requests.RequestException as exc:
        logger.warning(f"Keywords Everywhere request failed: {exc}")
        return []
    except Exception as exc:
        logger.warning(f"Keywords Everywhere unexpected error: {exc}")
        return []


def get_youtube_keyword_data(
    keywords: list[str],
    country: str = "us",
) -> list[dict[str, Any]]:
    """
    Get YouTube-specific search volume, CPC, and competition.

    Same interface as get_keyword_data but uses dataSource=yt.
    """
    return get_keyword_data(keywords, country=country, data_source="yt")


def enrich_titles_with_volume(
    titles: list[dict[str, Any]],
    country: str = "us",
) -> list[dict[str, Any]]:
    """
    Enrich a list of title dicts with Keywords Everywhere volume data.

    Args:
        titles: List of dicts with at least a "title" key.
                Expected shape: [{title, hook, summary, pillar, priority, ...}]
        country: ISO country code for volume lookup.

    Returns:
        Same list with added keys: vol, cpc, competition, volume_score.
        Original list is NOT mutated; new dicts are returned.
    """
    if not titles:
        return []

    # Extract key phrases from each title
    keyword_to_indices: dict[str, list[int]] = {}
    all_keywords: list[str] = []

    for idx, item in enumerate(titles):
        title_text = item.get("title", "")
        phrases = _extract_search_phrases(title_text)
        for phrase in phrases:
            lower = phrase.lower()
            if lower not in keyword_to_indices:
                keyword_to_indices[lower] = []
                all_keywords.append(lower)
            keyword_to_indices[lower].append(idx)

    if not all_keywords:
        return [dict(t, vol=0, cpc=0, competition=0, volume_score=0) for t in titles]

    # Call API (YouTube-specific volume)
    kw_data = get_youtube_keyword_data(all_keywords, country=country)

    # Build lookup
    vol_lookup: dict[str, dict[str, Any]] = {}
    for entry in kw_data:
        vol_lookup[entry["keyword"].lower()] = entry

    # Enrich each title — pick best keyword match
    enriched: list[dict[str, Any]] = []
    for idx, item in enumerate(titles):
        best_vol = 0
        best_cpc = 0.0
        best_comp = 0.0

        title_text = item.get("title", "")
        phrases = _extract_search_phrases(title_text)

        for phrase in phrases:
            entry = vol_lookup.get(phrase.lower())
            if entry and entry.get("vol", 0) > best_vol:
                best_vol = entry["vol"]
                best_cpc = entry.get("cpc", 0)
                best_comp = entry.get("competition", 0)

        volume_score = _volume_to_score(best_vol)

        enriched.append({
            **item,
            "vol": best_vol,
            "cpc": best_cpc,
            "competition": best_comp,
            "volume_score": volume_score,
        })

    return enriched


# ── Helpers ─────────────────────────────────────────────


def _extract_search_phrases(title: str) -> list[str]:
    """
    Extract 2-4 search-worthy phrases from a title.
    Returns both the full cleaned title and key bigrams/trigrams.
    """
    stop_words = {
        "o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das",
        "em", "no", "na", "que", "com", "por", "para", "como", "seu", "sua",
        "e", "ou", "mas", "se", "ao", "ate", "foi", "ser", "ter", "mais",
        "the", "a", "an", "is", "are", "was", "were", "be", "to", "of",
        "in", "for", "on", "with", "at", "by", "from", "that", "this",
        "how", "who", "what", "why", "when", "which",
    }

    # Clean title
    clean = re.sub(r"[^\w\s]", " ", title.lower())
    words = [w for w in clean.split() if len(w) > 2 and w not in stop_words]

    phrases: list[str] = []

    # Full meaningful phrase (first 5 content words)
    if len(words) >= 2:
        phrases.append(" ".join(words[:5]))

    # Bigrams
    for i in range(len(words) - 1):
        phrases.append(f"{words[i]} {words[i + 1]}")
        if len(phrases) >= 4:
            break

    return phrases


def _volume_to_score(vol: int) -> int:
    """
    Convert monthly search volume to a 0-100 score.

    Scale:
        0       → 0
        100     → 10
        1,000   → 30
        10,000  → 60
        50,000  → 80
        100,000+→ 100
    """
    if vol <= 0:
        return 0
    if vol >= 100_000:
        return 100

    import math
    # Logarithmic scale: log10(vol) mapped to 0-100
    # log10(100) = 2 → 10, log10(1000) = 3 → 30, log10(10000) = 4 → 60
    # log10(100000) = 5 → 100
    log_val = math.log10(max(vol, 1))
    score = int((log_val - 2) * (100 / 3))  # 2..5 → 0..100
    return max(0, min(100, score))
