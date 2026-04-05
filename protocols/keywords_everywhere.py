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


def _extract_sop_keywords(sop_text: str) -> list[str]:
    """
    Extract potential search keywords from SOP content.
    Finds proper nouns (capitalized words), recurring terms, and topic-specific words.
    """
    if not sop_text:
        return []

    # Clean and normalize
    clean = re.sub(r'[#*_\-=>{}\[\]|]', ' ', sop_text)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = re.sub(r'\d{4,}', '', clean)  # Remove long numbers (years ok)

    # Extract capitalized proper nouns (civilization names, places, etc.)
    # e.g. "Aztecas", "Teotihuacán", "Pirámides", "Olmecas"
    proper_nouns = re.findall(r'\b([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{3,})\b', clean)
    # Also extract ALL-CAPS words (often important terms in SOP)
    caps_words = re.findall(r'\b([A-ZÁÉÍÓÚÑÜ]{4,})\b', clean)

    # Count frequency to find recurring topics
    from collections import Counter
    word_counts = Counter()
    for w in proper_nouns:
        word_counts[_strip_accents(w.lower())] += 1
    for w in caps_words:
        word_counts[_strip_accents(w.lower())] += 1

    # Common non-topic words to exclude
    noise = {
        "como", "para", "pero", "cada", "esta", "este", "todo", "todos",
        "tiene", "hace", "puede", "solo", "entre", "sobre", "desde", "hasta",
        "donde", "quien", "cual", "sido", "sera", "debe", "caso", "tipo",
        "forma", "parte", "modo", "gran", "cosas", "otros", "otras",
        "these", "those", "their", "about", "which", "would", "could",
        "from", "with", "that", "this", "they", "have", "been", "will",
        "canal", "video", "titulo", "hook", "content", "contenido",
        "seccion", "pilar", "resumo", "prioridade", "alta", "media", "baixa",
        "importante", "regra", "reglas", "formato", "estilo",
    }

    # Get unique keywords sorted by frequency (most recurring = most relevant)
    keywords = []
    for word, count in word_counts.most_common(100):
        if word not in noise and len(word) >= 4 and count >= 1:
            keywords.append(word)

    return keywords[:60]


def _extract_title_keywords(titles: list[str]) -> list[str]:
    """Extract recurring keywords from existing channel titles."""
    if not titles:
        return []

    from collections import Counter
    word_counts = Counter()
    noise = _STOP_WORDS | {
        "canal", "video", "parte", "capitulo", "episodio",
    }

    for title in titles:
        clean = re.sub(r'[^\w\s]', ' ', title.lower())
        clean = _strip_accents(clean)
        words = [w for w in clean.split() if len(w) >= 4 and w not in noise]
        word_counts.update(words)

    # Words appearing in 2+ titles are recurring topics
    keywords = [w for w, c in word_counts.most_common(50) if c >= 2]
    return keywords


def research_niche_keywords(
    niches: list[str],
    language: str = "es",
    country: str = "es",
    sop_text: str = "",
    existing_titles: list[str] | None = None,
) -> list[dict]:
    """
    Research high-volume keywords for given niches.

    Extracts seed keywords from 3 sources:
    1. Niche names + modifiers
    2. SOP content (proper nouns, recurring terms = real channel topics)
    3. Existing title keywords (what already works for the channel)

    Returns sorted list: [{"keyword": "...", "vol": 12400, "cpc": 0.45, ...}]
    Only returns keywords with vol > 0, sorted by volume descending.
    """
    seeds = set()

    # Source 1: Niche names + modifiers
    modifiers_by_lang = {
        "es": ["historia", "misterios", "secretos", "documental", "antiguos",
               "perdidos", "ocultos", "prohibido", "descubrimiento"],
        "pt": ["historia", "misterios", "segredos", "documentario", "antigos",
               "perdidos", "ocultos", "proibido", "descoberta"],
        "en": ["history", "mysteries", "secrets", "documentary", "ancient",
               "lost", "hidden", "forbidden", "discovery"],
    }
    lang_code = language[:2]
    modifiers = modifiers_by_lang.get(lang_code, modifiers_by_lang["en"])

    for niche in (niches or []):
        niche_clean = _strip_accents(niche.lower().strip())
        seeds.add(niche_clean)
        for mod in modifiers:
            seeds.add(f"{niche_clean} {mod}")
        # Each word of multi-word niches
        for w in niche_clean.split():
            if len(w) >= 4:
                seeds.add(w)

    # Source 2: SOP keywords (the real channel topics)
    sop_keywords = _extract_sop_keywords(sop_text)
    for kw in sop_keywords:
        seeds.add(kw)
        # Also try keyword + niche modifier
        for niche in (niches or [])[:2]:
            niche_word = _strip_accents(niche.lower().split()[0]) if niche else ""
            if niche_word and len(niche_word) >= 4:
                seeds.add(f"{kw} {niche_word}")

    # Source 3: Existing title keywords (what already works)
    title_keywords = _extract_title_keywords(existing_titles or [])
    for kw in title_keywords:
        seeds.add(kw)

    if not seeds:
        return []

    unique_seeds = sorted(seeds)[:300]  # DataForSEO limit: 700/call, stay safe

    # Batch lookup
    country_lang = {
        "br": "pt", "us": "en", "es": "es", "mx": "es", "gb": "en",
        "fr": "fr", "de": "de", "it": "it", "jp": "ja", "kr": "ko",
    }
    results = get_keyword_data(
        unique_seeds,
        country=country,
        language=country_lang.get(country.lower(), lang_code),
    )

    # Filter to only keywords with volume and sort
    with_volume = [r for r in results if r.get("vol", 0) > 0]
    with_volume.sort(key=lambda x: x.get("vol", 0), reverse=True)

    logger.info(f"Niche research: {len(unique_seeds)} seeds → {len(with_volume)} with volume ({country})")
    return with_volume


def match_keyword_in_title(keyword: str, title: str) -> bool:
    """Check if keyword appears in title, handling singular/plural (es/pt/en)."""
    if keyword in title:
        return True
    # Try stem matching: remove common plural suffixes
    # "mayas"→"maya", "aztecas"→"azteca", "piramides"→"piramide", "cities"→"citi"
    for suffix in ("s", "es", "as", "os"):
        stem = keyword.rstrip(suffix) if keyword.endswith(suffix) and len(keyword) > len(suffix) + 3 else ""
        if stem and stem in title:
            return True
    # Also try the reverse: title word is plural of keyword
    for suffix in ("s", "es"):
        if (keyword + suffix) in title:
            return True
    return False


def _strip_accents(text: str) -> str:
    """Remove accents/diacritics for keyword matching (e.g. tecnología → tecnologia)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Generic single words excluded from volume badge matching (too broad)
# Niche-specific words like "piramides", "aztecas", "teotihuacan" are NOT here
_GENERIC_SINGLE_WORDS = {
    "antigua", "antiguas", "antiguo", "antiguos", "ancient",
    "ciudad", "ciudades", "city", "cities",
    "secreto", "secretos", "secret", "secrets", "segredo", "segredos",
    "historia", "history", "historia",
    "misterio", "misterios", "mystery", "mysteries", "misterio", "misterios",
    "mundo", "world",
    "perdida", "perdido", "perdidas", "perdidos", "lost",
    "oculto", "oculta", "ocultos", "ocultas", "hidden",
    "tecnologia", "technology",
    "descubrimiento", "descubrimientos", "discovery",
    "civilizacion", "civilizaciones", "civilization",
    "cultura", "culturas", "culture",
    "temas", "caps", "numeros", "patrones", "numbers", "patterns",
}

_STOP_WORDS = {
    # English
    "the", "and", "for", "that", "this", "with", "from", "have", "will", "what",
    "how", "why", "when", "where", "which", "your", "about", "they", "been", "more",
    "most", "than", "into", "over", "just", "like", "make", "know", "some", "made",
    "were", "ever", "never", "really", "world", "people", "could", "after", "before",
    "changed", "revealed", "discovered", "shocking", "incredible", "amazing",
    # Spanish
    "como", "para", "pero", "cada", "esta", "este", "todo", "todos", "todas", "tiene",
    "hace", "puede", "solo", "tambien", "entre", "sobre", "desde", "hasta", "donde",
    "quien", "cual", "fueron", "siendo", "hecho", "mejor", "peor", "mucho", "poco",
    "otro", "otra", "otros", "nada", "algo", "mismo", "porque", "siempre", "nunca",
    "mundo", "vida", "forma", "parte", "veces",
    "cambiaron", "cambio", "descubrieron", "desaparecieron", "revelaron",
    "brutal", "oscuros", "oscuro", "increible", "impactante", "poderoso",
    "sangrienta", "ocultos", "oculto", "verdadera", "verdadero",
    # Portuguese
    "como", "para", "mais", "qual", "quais", "isso", "esse", "essa", "este", "esta",
    "foram", "pode", "onde", "muito", "tambem", "sobre", "desde", "porque", "outro",
    "outra", "outros", "nada", "algo", "mesmo", "sempre", "nunca", "tudo", "toda",
    "mundo", "vida", "ainda", "depois", "antes", "cada", "pela", "pelo",
    "mudaram", "mudou", "descobriram", "desapareceram", "revelaram",
    "brutal", "escuros", "escuro", "incrivel", "impactante", "poderoso",
    "sangrenta", "ocultos", "oculto", "verdadeira", "verdadeiro",
}


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
        words = [w for w in clean.split() if len(w) > 3 and w not in _STOP_WORDS]
        # Use 2 core words — shorter phrases match real search queries better
        phrases.append(" ".join(words[:2]) if len(words) >= 2 else (words[0] if words else ""))

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
            raw_vol = info.get("vol", 0) or 0
            t["vol"] = raw_vol if raw_vol > 0 else -1  # 0 → -1 (checked, no volume)
            t["cpc"] = info.get("cpc", 0)
            t["competition"] = info.get("competition", 0)
            t["volume_score"] = _volume_to_score(raw_vol)
        else:
            # Checked but no match → mark as -1
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
