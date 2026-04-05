"""
Title Scorer - Pontua titulos com Google Trends + YouTube search.
Score 0-100 baseado em interesse de busca e competicao.
Analisa Global + por pais para identificar oportunidades regionais.
"""

import re
import json
import subprocess
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# Paises suportados com codigo ISO para Google Trends
COUNTRIES = {
    "global": {"code": "", "name": "Global", "lang": "en"},
    "BR": {"code": "BR", "name": "Brasil", "lang": "pt"},
    "US": {"code": "US", "name": "Estados Unidos", "lang": "en"},
    "PT": {"code": "PT", "name": "Portugal", "lang": "pt"},
    "ES": {"code": "ES", "name": "Espanha", "lang": "es"},
    "MX": {"code": "MX", "name": "Mexico", "lang": "es"},
    "GB": {"code": "GB", "name": "Reino Unido", "lang": "en"},
    "DE": {"code": "DE", "name": "Alemanha", "lang": "de"},
    "FR": {"code": "FR", "name": "Franca", "lang": "fr"},
    "IN": {"code": "IN", "name": "India", "lang": "en"},
    "JP": {"code": "JP", "name": "Japao", "lang": "ja"},
}


def extract_keywords(title: str, lang: str = "pt") -> list[str]:
    """Extrai 2-5 keywords principais de um titulo."""
    clean = re.sub(r'\$[\d,.]+\s*(milhoes|bilhoes|trilhao|million|billion|M|B|K)?', '', title, flags=re.IGNORECASE)

    stop_words_pt = {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das",
                     "em", "no", "na", "que", "com", "por", "para", "como", "seu", "sua",
                     "e", "ou", "mas", "se", "ao", "ate", "foi", "ser", "ter", "mais",
                     "nao", "sim", "ele", "ela", "isso", "este", "esta", "todo", "toda"}

    stop_words_en = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
                     "have", "has", "had", "do", "does", "did", "will", "would", "shall",
                     "should", "may", "might", "can", "could", "must", "to", "of", "in",
                     "for", "on", "with", "at", "by", "from", "that", "this", "who", "how"}

    stops = stop_words_pt | stop_words_en

    words = [w.lower().strip(".,!?()\"'") for w in clean.split() if len(w) > 2]
    keywords = [w for w in words if w not in stops]
    return keywords[:5]


def translate_keywords_for_region(keywords: list[str], target_lang: str) -> list[str]:
    """Traduz keywords para o idioma do pais alvo (simplificado)."""
    # Mapeamento basico de termos comuns PT -> EN
    pt_to_en = {
        "bug": "bug", "hack": "hack", "glitch": "glitch", "fraude": "fraud",
        "brecha": "loophole", "sistema": "system", "banco": "bank",
        "dinheiro": "money", "milhoes": "million", "bilhoes": "billion",
        "loteria": "lottery", "casino": "casino", "poker": "poker",
        "ethereum": "ethereum", "bitcoin": "bitcoin", "crypto": "crypto",
        "pentagono": "pentagon", "milhas": "airline miles", "roubo": "heist",
        "estagiario": "intern", "estudantes": "students", "programador": "programmer",
    }

    if target_lang == "pt":
        return keywords

    translated = []
    for kw in keywords:
        if kw in pt_to_en:
            translated.append(pt_to_en[kw])
        else:
            translated.append(kw)  # Termos tecnicos sao iguais
    return translated


def search_youtube_competition(title: str, lang: str = "pt", max_results: int = 10) -> dict:
    """Busca no YouTube por titulos similares e analisa competicao."""
    try:
        keywords = " ".join(extract_keywords(title, lang)[:3])
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "%(view_count)s %(title)s",
             f"ytsearch{max_results}:{keywords}"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return {"error": result.stderr, "score": 50}

        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        views = []
        titles = []

        for line in lines:
            parts = line.split(" ", 1)
            if len(parts) == 2:
                try:
                    v = int(parts[0])
                    views.append(v)
                    titles.append(parts[1])
                except ValueError:
                    titles.append(line)

        if not views:
            return {"avg_views": 0, "max_views": 0, "competition": 0, "results": len(lines), "score": 50}

        avg_views = sum(views) / len(views)
        max_views = max(views)

        demand_score = min(100, (avg_views / 100000) * 20)
        competition_score = max(0, 100 - (len(views) * 10))

        yt_score = int((demand_score * 0.6) + (competition_score * 0.4))
        yt_score = max(0, min(100, yt_score))

        return {
            "avg_views": int(avg_views),
            "max_views": max_views,
            "results_found": len(views),
            "demand_score": int(demand_score),
            "competition_score": int(competition_score),
            "score": yt_score,
            "top_titles": titles[:3],
        }

    except subprocess.TimeoutExpired:
        return {"error": "timeout", "score": 50}
    except Exception as e:
        return {"error": str(e), "score": 50}


def search_google_trends(keywords: list[str], geo: str = "") -> dict:
    """Busca interesse no Google Trends para uma regiao."""
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl='pt-BR', tz=180, timeout=(10, 25))

        kw_list = keywords[:3]
        if not kw_list:
            return {"score": 50, "error": "no keywords", "geo": geo}

        pytrends.build_payload(kw_list, cat=0, timeframe='today 3-m', geo=geo)
        interest = pytrends.interest_over_time()

        if interest.empty:
            return {"score": 40, "trend": "sem dados", "geo": geo}

        avg_interest = interest[kw_list].mean().mean()
        max_interest = interest[kw_list].max().max()

        recent = interest[kw_list].tail(4).mean().mean()
        older = interest[kw_list].head(4).mean().mean()

        if older > 0:
            trend_ratio = recent / older
        else:
            trend_ratio = 1.0

        if trend_ratio > 1.2:
            trend = "subindo"
            trend_bonus = 15
        elif trend_ratio < 0.8:
            trend = "descendo"
            trend_bonus = -10
        else:
            trend = "estavel"
            trend_bonus = 0

        gt_score = int(min(100, avg_interest + trend_bonus))

        return {
            "avg_interest": int(avg_interest),
            "max_interest": int(max_interest),
            "trend": trend,
            "trend_ratio": round(trend_ratio, 2),
            "score": gt_score,
            "keywords_used": kw_list,
            "geo": geo or "global",
        }

    except Exception as e:
        return {"score": 50, "error": str(e), "geo": geo}


def search_trends_by_region(keywords: list[str]) -> dict:
    """Busca interesse por regiao no Google Trends."""
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl='pt-BR', tz=180, timeout=(10, 25))

        kw_list = keywords[:1]  # Usar 1 keyword pra interest by region
        if not kw_list:
            return {}

        pytrends.build_payload(kw_list, cat=0, timeframe='today 3-m')
        regions = pytrends.interest_by_region(resolution='COUNTRY', inc_low_vol=False)

        if regions.empty:
            return {}

        # Top 10 paises com mais interesse
        top = regions[kw_list[0]].sort_values(ascending=False).head(10)
        result = {}
        for country, value in top.items():
            if value > 0:
                result[country] = int(value)

        return result

    except Exception:
        return {}


def score_title(title: str, target_countries: list[str] = None, search_volume: int = 0) -> dict:
    """Pontua um titulo combinando YouTube + Google Trends + Volume, global e por pais."""

    if target_countries is None:
        target_countries = ["global", "BR", "US"]

    keywords_pt = extract_keywords(title, "pt")
    keywords_en = translate_keywords_for_region(keywords_pt, "en")

    # YouTube analysis (global) — com fallback
    try:
        yt = search_youtube_competition(title)
    except Exception:
        yt = {"score": 50, "error": "yt-dlp unavailable"}

    # Google Trends por regiao — com fallback
    regional_scores = {}
    for country_code in target_countries:
        country = COUNTRIES.get(country_code, {"code": country_code, "name": country_code, "lang": "en"})
        geo = country["code"]

        if country["lang"] == "pt":
            kw = keywords_pt
        else:
            kw = keywords_en

        try:
            gt = search_google_trends(kw, geo)
        except Exception:
            gt = {"score": 50, "error": "trends unavailable", "geo": geo}

        regional_scores[country_code] = {
            "name": country["name"],
            "trends_score": gt.get("score", 50),
            "trend": gt.get("trend", "?"),
            "trend_ratio": gt.get("trend_ratio", 1.0),
            "avg_interest": gt.get("avg_interest", 0),
            "keywords": kw,
        }

    # Interest by region — com fallback
    try:
        top_countries = search_trends_by_region(keywords_en if keywords_en else keywords_pt)
    except Exception:
        top_countries = {}

    # Volume data is collected in PRE-RESEARCH (1 batch call), not per-title
    # This saves DataForSEO credits (1 call vs 15+ calls)
    volume_data = {}

    # Volume bonus: titles with proven search volume get a boost
    # 0 or -1 = no bonus, 1-100 = +3, 100-1000 = +5, 1000-10000 = +8, 10000+ = +12
    import math
    vol = max(search_volume, 0)
    if vol >= 10000:
        volume_bonus = 12
    elif vol >= 1000:
        volume_bonus = 8
    elif vol >= 100:
        volume_bonus = 5
    elif vol > 0:
        volume_bonus = 3
    else:
        volume_bonus = 0

    # Score global
    all_trend_scores = [r["trends_score"] for r in regional_scores.values()]
    avg_trends = sum(all_trend_scores) / len(all_trend_scores) if all_trend_scores else 50

    # Formula: YouTube 50% + Trends 35% + Volume 15%
    base_score = int((yt["score"] * 0.50) + (avg_trends * 0.35) + (volume_bonus * 1.25))
    final_score = max(0, min(100, base_score))

    if final_score >= 80:
        rating = "EXCELENTE"
    elif final_score >= 60:
        rating = "BOM"
    elif final_score >= 40:
        rating = "MEDIO"
    else:
        rating = "BAIXO"

    best_country = ""
    best_country_score = 0
    for code, data in regional_scores.items():
        if data["trends_score"] > best_country_score:
            best_country_score = data["trends_score"]
            best_country = f"{data['name']} ({data['trends_score']})"

    return {
        "title": title,
        "keywords_pt": keywords_pt,
        "keywords_en": keywords_en,
        "final_score": final_score,
        "rating": rating,
        "youtube": yt,
        "volume": volume_data,
        "volume_bonus": volume_bonus,
        "search_volume": vol,
        "regional_scores": regional_scores,
        "top_countries": top_countries,
        "best_opportunity": best_country,
        "scored_at": datetime.now().isoformat(),
    }


def format_score_summary(result: dict) -> str:
    """Formata resultado do score para exibicao."""
    out = f"Score: {result['final_score']}/100 ({result['rating']})\n"
    out += f"YouTube: {result['youtube'].get('score','?')}/100 (avg {result['youtube'].get('avg_views','?')} views)\n"

    vol = result.get("volume", {})
    if vol and not vol.get("error"):
        out += f"Volume: {vol.get('volume_score', 0)}/100 (best {vol.get('best_volume', 0):,} monthly searches)\n"
    elif vol.get("error"):
        out += f"Volume: unavailable ({vol['error']})\n"

    out += "\nPor regiao:\n"
    for code, data in result.get("regional_scores", {}).items():
        arrow = {"subindo": "^", "descendo": "v", "estavel": "=", "?": "?"}.get(data["trend"], "?")
        out += f"  {data['name']}: {data['trends_score']}/100 {arrow} ({data['trend']})\n"

    if result.get("top_countries"):
        out += "\nTop paises (interesse):\n"
        for country, value in list(result["top_countries"].items())[:5]:
            out += f"  {country}: {value}\n"

    if result.get("best_opportunity"):
        out += f"\nMelhor oportunidade: {result['best_opportunity']}\n"

    return out


if __name__ == "__main__":
    test_titles = [
        "O estagiario que encontrou um bug de $200M na Ethereum",
        "3 estudantes do MIT quebraram Las Vegas",
    ]

    for t in test_titles:
        print(f"\n{'='*50}")
        print(f"{t}")
        print(f"{'='*50}")
        result = score_title(t, ["global", "BR", "US"])
        print(format_score_summary(result))
