"""
Keyword Volume API — DataForSEO integration for real search volume data.

Pay-as-you-go: $0.0006-$0.002 per keyword. No monthly fee. $50 min deposit.
Credits never expire.

Used for:
1. Pre-research before title generation (demand-driven titles)
2. Title scoring (volume component of composite score)
3. Enriching titles with volume/CPC/competition data

Functions maintain same signatures as previous Keywords Everywhere integration
so no other code changes needed.
"""

import logging
import math
import re
import unicodedata
import requests

logger = logging.getLogger("ytcloner.keyword_volume")

_DATAFORSEO_LOGIN = ""
_DATAFORSEO_PASSWORD = ""


def _get_credentials() -> tuple[str, str]:
    """Get DataForSEO credentials from DB or env vars."""
    global _DATAFORSEO_LOGIN, _DATAFORSEO_PASSWORD

    if _DATAFORSEO_LOGIN and _DATAFORSEO_PASSWORD:
        return _DATAFORSEO_LOGIN, _DATAFORSEO_PASSWORD

    import os
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    password = os.environ.get("DATAFORSEO_PASSWORD", "")

    if not login or not password:
        try:
            from database import get_setting
            login = login or get_setting("dataforseo_login") or ""
            password = password or get_setting("dataforseo_password") or ""
        except Exception:
            pass

    if login and password:
        _DATAFORSEO_LOGIN = login
        _DATAFORSEO_PASSWORD = password

    return login, password


LOCATION_MAP = {
    "us": 2840, "br": 2076, "es": 2724, "mx": 2484, "gb": 2826,
    "fr": 2250, "de": 2276, "it": 2380, "pt": 2620, "jp": 2392,
    "kr": 2410, "ar": 2032, "co": 2170, "cl": 2152,
}
# DataForSEO uses language_name, NOT language_code
LANG_NAME_MAP = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French",
    "de": "German", "it": "Italian", "ja": "Japanese", "ko": "Korean",
}


def get_keyword_data(keywords: list[str], country: str = "us", language: str = "en") -> list[dict]:
    """
    Get search volume, CPC, and competition via DataForSEO.
    ~$0.05 per request (up to 700 keywords per request).

    Returns: [{"keyword": "...", "vol": 12400, "cpc": 0.45, "competition": 0.32}]
    """
    login, password = _get_credentials()
    if not login or not password:
        logger.warning("DataForSEO credentials not configured — set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD")
        return []

    if not keywords:
        return []

    location_code = LOCATION_MAP.get(country.lower(), 2840)
    language_name = LANG_NAME_MAP.get(language.lower()[:2], "English")

    try:
        resp = requests.post(
            "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
            json=[{
                "keywords": keywords[:700],
                "location_code": location_code,
                "language_name": language_name,
            }],
            auth=(login, password),
            timeout=30,
        )

        if resp.status_code != 200:
            logger.warning(f"DataForSEO error: {resp.status_code}")
            return []

        results = []
        for task in resp.json().get("tasks", []):
            if task.get("status_code") != 20000:
                continue
            for item in task.get("result", []):
                comp = item.get("competition", "")
                comp_index = item.get("competition_index", 0) or 0
                comp_val = comp_index / 100 if isinstance(comp_index, (int, float)) else 0
                results.append({
                    "keyword": item.get("keyword", ""),
                    "vol": item.get("search_volume", 0) or 0,
                    "cpc": round(item.get("cpc", 0) or 0, 2),
                    "competition": round(comp_val, 2),
                    "competition_level": comp if isinstance(comp, str) else "",
                })

        logger.info(f"DataForSEO: {len(results)} results for {len(keywords)} keywords ({country})")
        return results

    except Exception as e:
        logger.warning(f"DataForSEO failed: {e}")
        return []


def get_youtube_keyword_data(keywords: list[str], country: str = "us") -> list[dict]:
    """Get keyword data (Google Ads volume correlates with YouTube demand)."""
    country_lang = {
        "br": "pt", "us": "en", "es": "es", "mx": "es", "gb": "en",
        "fr": "fr", "de": "de", "it": "it", "jp": "ja", "kr": "ko",
    }
    return get_keyword_data(keywords, country=country, language=country_lang.get(country.lower(), "en"))


def _strip_accents(text: str) -> str:
    """Remove accents/diacritics for keyword matching (e.g. tecnología → tecnologia)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def enrich_titles_with_volume(titles: list[dict], country: str = "us") -> list[dict]:
    """Add vol, cpc, competition, volume_score to each title.

    Uses -1 as marker for 'checked but no volume data' so the UI can
    distinguish from 'never checked' (default 0).
    """
    if not titles:
        return titles

    phrases = []
    for t in titles:
        clean = re.sub(r'[^\w\s]', ' ', t.get("title", "").lower()).strip()
        clean = _strip_accents(clean)
        words = [w for w in clean.split() if len(w) > 3]
        phrases.append(" ".join(words[:5]) if len(words) >= 2 else (words[0] if words else ""))

    if not any(phrases):
        # Mark all as checked even if no phrases could be extracted
        for t in titles:
            t["vol"] = -1
        return titles

    vol_data = get_keyword_data([p for p in phrases if p], country=country)
    # Normalize returned keywords for accent-insensitive matching
    vol_map = {_strip_accents(v["keyword"].lower()): v for v in vol_data}

    for i, t in enumerate(titles):
        if i < len(phrases) and phrases[i] and phrases[i] in vol_map:
            info = vol_map[phrases[i]]
            t["vol"] = info.get("vol", 0) or 0
            t["cpc"] = info.get("cpc", 0)
            t["competition"] = info.get("competition", 0)
            t["volume_score"] = _volume_to_score(t["vol"])
        else:
            # Checked but no match / no volume → mark as -1
            t.setdefault("vol", -1)

    return titles


def _volume_to_score(vol: int) -> int:
    """Convert monthly volume to 0-100 score (logarithmic)."""
    if vol <= 0:
        return 0
    return min(100, max(0, int(math.log10(max(vol, 1)) * 20)))


def check_credits() -> dict:
    """Check DataForSEO account balance."""
    login, password = _get_credentials()
    if not login or not password:
        return {"error": "Credentials not configured"}
    try:
        resp = requests.get(
            "https://api.dataforseo.com/v3/appendix/user_data",
            auth=(login, password),
            timeout=10,
        )
        if resp.status_code == 200:
            tasks = resp.json().get("tasks", [])
            if tasks and tasks[0].get("result"):
                ud = tasks[0]["result"][0]
                return {
                    "balance": ud.get("money", {}).get("balance", 0),
                    "total_spent": ud.get("money", {}).get("total", 0),
                }
        return {"error": f"Status {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}
