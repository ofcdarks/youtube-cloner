"""
Niches Lab — Top Niches playbook + Deep Dive analysis turbinado com DataForSEO.

Combina:
1. Curated Top 8 Niches (faceless / international / monetização rápida)
2. Real-time enrichment via DataForSEO (search volume, competition, CPC → CPM, trends)
3. Deep Dive: análise profunda de qualquer nicho com sub-nichos derivados de
   keyword suggestions + related keywords da DataForSEO Labs API.

DataForSEO endpoints usados:
- /v3/keywords_data/google_ads/search_volume/live  (volume + competition + CPC)
- /v3/dataforseo_labs/google/keyword_suggestions/live  (sub-niches a partir de seed)
- /v3/dataforseo_labs/google/related_keywords/live  (related para descoberta)
"""

from __future__ import annotations

import logging
import requests
from dataclasses import dataclass, field
from typing import Any

from protocols.keywords_everywhere import _get_credentials, LOCATION_MAP, LANG_NAME_MAP

logger = logging.getLogger("ytcloner.niches_lab")


# ── Curated Top Niches (base playbook — abr/2026) ────────────────────
_TOP_NICHES_RAW: list[dict[str, Any]] = [
    {
        "rank": 1,
        "name": "Betrayal & Revenge Stories",
        "seed": "revenge story reddit",
        "emoji": "🗡️",
        "cpm_est": "$18-30",
        "competition": "LOW",
        "growth": "21x",
        "difficulty": 2,
        "virality": 5,
        "monetization": 5,
        "desc": "AI narration over stock footage. Stories of betrayal, karma, and justice. Viewers binge-watch 8-15 min stories. ~200K channels in this space.",
        "format": "AI voice + stock footage + text overlays",
        "tools": "ChatGPT (scripts), ElevenLabs (voice), CapCut/Premiere",
        "tip": "Post 1 video/day. Cliffhanger hooks first 5s. 'My Boss Fired Me... Then Begged Me to Come Back'",
        "affiliate": "Low — focus on AdSense RPM",
        "color": "#FF4136",
        "accent": "#FFD700",
    },
    {
        "rank": 2,
        "name": "Personal Finance & Investing",
        "seed": "personal finance investing",
        "emoji": "💰",
        "cpm_est": "$15-50",
        "competition": "HIGH",
        "growth": "8x",
        "difficulty": 3,
        "virality": 3,
        "monetization": 5,
        "desc": "The KING of CPM. Banks, credit cards, investing platforms pay massive amounts. Sub-niches: budgeting, crypto, passive income.",
        "format": "Voiceover + charts + stock footage of cities/lifestyle",
        "tools": "Canva, AI voice, stock footage libraries",
        "tip": "Niche DOWN hard: 'Investing for Artists' or 'Finance for Gen Z'.",
        "affiliate": "HUGE — credit cards, brokers, courses ($50-200/sale)",
        "color": "#2ECC40",
        "accent": "#01FF70",
    },
    {
        "rank": 3,
        "name": "AI Tools & Make Money Online",
        "seed": "ai tools tutorial",
        "emoji": "🤖",
        "cpm_est": "$15-20",
        "competition": "MEDIUM",
        "growth": "15x",
        "difficulty": 2,
        "virality": 5,
        "monetization": 5,
        "desc": "THE 2026 niche. Teach how to use AI tools to earn money. Screen recordings + voiceover. New tools daily = infinite content.",
        "format": "Screen recording tutorials + AI voiceover",
        "tools": "OBS, ElevenLabs, CapCut",
        "tip": "Review NEW tools first. Speed is everything. Ride the algorithm wave.",
        "affiliate": "MASSIVE — SaaS affiliate $20-100/signup recurring",
        "color": "#7B2FBE",
        "accent": "#B388FF",
    },
    {
        "rank": 4,
        "name": "English Learning Podcasts",
        "seed": "learn english podcast",
        "emoji": "🎧",
        "cpm_est": "$15-22",
        "competition": "VERY LOW",
        "growth": "21x",
        "difficulty": 1,
        "virality": 3,
        "monetization": 4,
        "desc": "Only ~10K competing channels. Language apps like Duolingo and Cambly pay premium CPMs. Massive global audience.",
        "format": "Podcast-style with subtitles + simple visuals",
        "tools": "AI voice (natural English), Canva, simple editor",
        "tip": "Target specific countries: 'English for Brazilians', 'English for Japanese'.",
        "affiliate": "Good — language apps, courses, books",
        "color": "#0074D9",
        "accent": "#7FDBFF",
    },
    {
        "rank": 5,
        "name": "Legal / Court Drama",
        "seed": "court drama legal stories",
        "emoji": "⚖️",
        "cpm_est": "$12-35",
        "competition": "LOW",
        "growth": "12x",
        "difficulty": 3,
        "virality": 4,
        "monetization": 5,
        "desc": "Law firms and legal services pay TOP dollar. Cover bizarre court cases, legal breakdowns, AITA-style content.",
        "format": "AI narration + courtroom stock footage + animations",
        "tools": "ChatGPT, AI voice, stock footage",
        "tip": "Reddit legal stories + real court cases = endless content.",
        "affiliate": "Medium — legal services, insurance",
        "color": "#FF851B",
        "accent": "#FFDC00",
    },
    {
        "rank": 6,
        "name": "Manhwa / Anime Recaps",
        "seed": "manhwa recap anime",
        "emoji": "📚",
        "cpm_est": "$8-15",
        "competition": "VERY LOW",
        "growth": "18x",
        "difficulty": 2,
        "virality": 5,
        "monetization": 3,
        "desc": "Only ~10K channels. Recap manhwa/manga stories with dramatic narration. Massive Gen Z audience. Millions of views.",
        "format": "Manhwa panels + zoom effects + AI narration",
        "tools": "CapCut, AI voice, manhwa source material",
        "tip": "Popular series with dramatic plots. Part 1, Part 2 format builds retention.",
        "affiliate": "Low — merch, manga subscriptions",
        "color": "#E91E63",
        "accent": "#FF80AB",
    },
    {
        "rank": 7,
        "name": "Soundscapes & Sleep Content",
        "seed": "rain sounds sleep",
        "emoji": "🌙",
        "cpm_est": "$8-15",
        "competition": "LOW",
        "growth": "10x",
        "difficulty": 1,
        "virality": 2,
        "monetization": 4,
        "desc": "24/7 livestreams of rain, fireplace, forest sounds. Passive income machine. Once set up, run forever. ~20K channels.",
        "format": "Long-form ambient (8-12h) or livestreams",
        "tools": "Free sound libraries, stock nature footage, OBS",
        "tip": "8-10 hour videos. YouTube LOVES watch time. One video earns for years.",
        "affiliate": "Low — sleep/wellness brand sponsorships",
        "color": "#001F3F",
        "accent": "#7FDBFF",
    },
    {
        "rank": 8,
        "name": "Pop Culture & Celebrity Breakdowns",
        "seed": "celebrity drama news",
        "emoji": "🌟",
        "cpm_est": "$6-12",
        "competition": "MEDIUM",
        "growth": "9x",
        "difficulty": 2,
        "virality": 5,
        "monetization": 3,
        "desc": "Speed is KING. Cover drama, breakups, viral moments within hours. Lower CPM but massive view potential. Volume strategy.",
        "format": "Commentary + clips + screenshots + captions",
        "tools": "CapCut, AI voice, social media screenshots",
        "tip": "Google Alerts for trending celebs. First to post wins.",
        "affiliate": "Low — volume-based AdSense play",
        "color": "#F012BE",
        "accent": "#FF80AB",
    },
]


def _parse_cpm_low(cpm_str: str) -> int:
    """Extract the low end of a CPM string like '$15-50' → 15."""
    try:
        digits = cpm_str.replace("$", "").replace("+", "").split("-")[0].strip()
        return int(digits)
    except (ValueError, IndexError):
        return 0


# Pre-computed Top Niches with cpm_low for client-side filtering
TOP_NICHES: list[dict[str, Any]] = [
    {**n, "cpm_low": _parse_cpm_low(n["cpm_est"])} for n in _TOP_NICHES_RAW
]


def _competition_label(competition_index: float) -> str:
    """Map DataForSEO competition_index (0-100) to human label."""
    if competition_index < 25:
        return "VERY LOW"
    if competition_index < 50:
        return "LOW"
    if competition_index < 75:
        return "MEDIUM"
    return "HIGH"


def _cpm_from_cpc(cpc: float) -> str:
    """Estimate CPM range from CPC (Google Ads CPC ≈ 0.4-0.7x of YouTube CPM)."""
    if not cpc or cpc <= 0:
        return "—"
    low = cpc * 1.4
    high = cpc * 2.8
    return f"${low:.1f}-{high:.1f}"


def _post_dataforseo(endpoint: str, payload: list[dict], timeout: int = 30) -> dict | None:
    """Generic DataForSEO POST helper. Returns parsed JSON or None."""
    login, password = _get_credentials()
    if not login or not password:
        logger.warning("DataForSEO credentials not configured")
        return None
    try:
        resp = requests.post(
            f"https://api.dataforseo.com/v3{endpoint}",
            json=payload,
            auth=(login, password),
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning(f"DataForSEO {endpoint} HTTP {resp.status_code}")
            return None
        return resp.json()
    except Exception as e:
        logger.warning(f"DataForSEO {endpoint} failed: {e}")
        return None


def enrich_top_niches(country: str = "us", language: str = "en") -> list[dict]:
    """
    Enriquece a lista curada de Top Niches com dados ao vivo do DataForSEO.
    Para cada nicho, busca search volume + competition + CPC do seed keyword.
    Retorna a lista enriquecida (sempre retorna mesmo que enrichment falhe).
    """
    from protocols.keywords_everywhere import get_keyword_data

    seeds = [n["seed"] for n in TOP_NICHES]
    try:
        kw_data = get_keyword_data(seeds, country=country, language=language)
    except Exception as e:
        logger.warning(f"enrich_top_niches: get_keyword_data failed: {e}")
        kw_data = []

    by_kw = {item["keyword"].lower(): item for item in kw_data}

    enriched = []
    for niche in TOP_NICHES:
        item = dict(niche)  # copy (immutable)
        kd = by_kw.get(niche["seed"].lower(), {})
        vol = kd.get("vol", 0) or 0
        cpc = kd.get("cpc", 0) or 0
        comp = kd.get("competition", 0) or 0  # 0..1
        comp_pct = comp * 100

        item["live"] = {
            "search_volume": vol,
            "cpc": cpc,
            "competition_index": round(comp_pct, 1),
            "competition_real": _competition_label(comp_pct) if vol > 0 else niche["competition"],
            "cpm_real": _cpm_from_cpc(cpc),
            "has_data": vol > 0 or cpc > 0,
        }
        enriched.append(item)

    return enriched


def deep_dive_niche(
    niche_name: str,
    country: str = "us",
    language: str = "en",
    max_subniches: int = 8,
) -> dict:
    """
    Análise profunda de um nicho específico, turbinada com DataForSEO.

    Pipeline:
    1. Keyword suggestions (seed → top related keywords by volume)
    2. Group into sub-nichos (top N by composite score = volume * (1 + cpc/10))
    3. Pull volume/competition/CPC data for sub-niche keywords
    4. Generate strategy section based on real data

    Retorna dict com niche, summary stats, sub_niches[], formula sections.
    """
    seed = niche_name.strip().lower()
    if not seed:
        return {"error": "Niche vazio"}

    location_code = LOCATION_MAP.get(country.lower(), 2840)
    language_name = LANG_NAME_MAP.get(language.lower()[:2], "English")

    # Step 1: Keyword Suggestions (DataForSEO Labs)
    suggestions: list[dict] = []
    sugg_resp = _post_dataforseo(
        "/dataforseo_labs/google/keyword_suggestions/live",
        [{
            "keyword": seed,
            "location_code": location_code,
            "language_code": language.lower()[:2],
            "limit": 50,
            "include_seed_keyword": True,
            "order_by": ["keyword_info.search_volume,desc"],
        }],
        timeout=45,
    )

    if sugg_resp:
        for task in sugg_resp.get("tasks", []) or []:
            if task.get("status_code") != 20000:
                continue
            for result in task.get("result", []) or []:
                for item in result.get("items", []) or []:
                    kw = item.get("keyword", "")
                    info = item.get("keyword_info", {}) or {}
                    vol = info.get("search_volume", 0) or 0
                    cpc = info.get("cpc", 0) or 0
                    comp_idx = info.get("competition_index", 0) or 0
                    if not kw or vol == 0:
                        continue
                    suggestions.append({
                        "keyword": kw,
                        "search_volume": vol,
                        "cpc": round(cpc, 2),
                        "competition_index": comp_idx,
                        "competition": _competition_label(comp_idx),
                        "cpm_est": _cpm_from_cpc(cpc),
                        "score": round(vol * (1 + (cpc or 0) / 10), 1),
                    })

    # Sort by composite score (volume × cpc weight)
    suggestions.sort(key=lambda x: x["score"], reverse=True)

    sub_niches = suggestions[:max_subniches]
    long_tail = suggestions[max_subniches:max_subniches + 20]

    # Aggregate stats
    total_volume = sum(s["search_volume"] for s in suggestions) if suggestions else 0
    avg_cpc = (
        round(sum(s["cpc"] for s in suggestions) / len(suggestions), 2)
        if suggestions else 0
    )
    avg_competition = (
        round(sum(s["competition_index"] for s in suggestions) / len(suggestions), 1)
        if suggestions else 0
    )

    # Verdict heuristic
    verdict = _build_verdict(total_volume, avg_cpc, avg_competition, len(suggestions))

    return {
        "ok": True,
        "niche": niche_name,
        "country": country,
        "language": language,
        "summary": {
            "total_search_volume": total_volume,
            "avg_cpc": avg_cpc,
            "avg_competition_index": avg_competition,
            "competition_label": _competition_label(avg_competition),
            "cpm_estimate_range": _cpm_from_cpc(avg_cpc),
            "keyword_count": len(suggestions),
        },
        "sub_niches": sub_niches,
        "long_tail": long_tail,
        "verdict": verdict,
        "action_plan": _build_action_plan(niche_name, sub_niches),
    }


def _build_verdict(volume: int, cpc: float, comp: float, kw_count: int) -> dict:
    """Heuristica simples para gerar veredicto baseado em dados reais."""
    score = 0
    notes = []

    if volume > 500_000:
        score += 30
        notes.append(f"Demanda massiva ({volume:,}/mês total)")
    elif volume > 100_000:
        score += 20
        notes.append(f"Boa demanda ({volume:,}/mês total)")
    elif volume > 20_000:
        score += 10
        notes.append(f"Demanda moderada ({volume:,}/mês total)")
    else:
        notes.append(f"Demanda baixa ({volume:,}/mês total) — talvez muito de nicho")

    if cpc > 5:
        score += 30
        notes.append(f"CPC PREMIUM (${cpc:.2f}) — anunciantes pagam alto")
    elif cpc > 2:
        score += 20
        notes.append(f"CPC bom (${cpc:.2f})")
    elif cpc > 0.5:
        score += 10
        notes.append(f"CPC modesto (${cpc:.2f})")
    else:
        notes.append(f"CPC baixo (${cpc:.2f}) — monetização desafiadora")

    if comp < 33:
        score += 30
        notes.append(f"Competição BAIXA ({comp:.0f}/100) — janela aberta")
    elif comp < 66:
        score += 15
        notes.append(f"Competição média ({comp:.0f}/100)")
    else:
        notes.append(f"Competição ALTA ({comp:.0f}/100) — precisa diferenciar muito")

    if kw_count < 10:
        notes.append("Poucas keywords relacionadas — pode indicar nicho muito estreito")
    elif kw_count > 30:
        score += 10
        notes.append(f"Universo de keywords amplo ({kw_count}+) — conteúdo infinito")

    if score >= 70:
        rating = "EXCELENTE"
        color = "#2ECC40"
    elif score >= 50:
        rating = "BOM"
        color = "#FFD700"
    elif score >= 30:
        rating = "MEDIO"
        color = "#FF851B"
    else:
        rating = "DIFICIL"
        color = "#FF4136"

    return {
        "rating": rating,
        "score": score,
        "color": color,
        "notes": notes,
    }


def _build_action_plan(niche: str, sub_niches: list[dict]) -> list[dict]:
    """Gera plano 30 dias contextualizado pelo nicho."""
    top_kw = sub_niches[0]["keyword"] if sub_niches else niche
    second_kw = sub_niches[1]["keyword"] if len(sub_niches) > 1 else niche

    return [
        {
            "week": "Semana 1",
            "title": "SETUP & PRIMEIROS 5 VÍDEOS",
            "color": "#7B68EE",
            "tasks": [
                f"Criar canal focado em '{niche}' com branding forte",
                f"Estudar top 5 canais que cobrem '{top_kw}' — copiar formato, NÃO conteúdo",
                "Configurar ChatGPT/Claude (scripts) + ElevenLabs (voz) + CapCut (edição)",
                f"Garimpar 10 ângulos a partir das sub-keywords: {', '.join(s['keyword'] for s in sub_niches[:3])}",
                "Publicar 5 vídeos (1/dia) — hooks fortes nos primeiros 5 segundos",
            ],
        },
        {
            "week": "Semana 2",
            "title": "VOLUME + SHORTS",
            "color": "#FF6B6B",
            "tasks": [
                "Mais 5 vídeos longos (8-15 min cada)",
                f"Criar 10 Shorts focados em '{second_kw}' cortando os melhores momentos",
                "Estudar Analytics: qual título/thumbnail teve mais CTR?",
                "Testar 2 formatos: narração pura vs. narração + comentário",
                "Thumbnails com expressões faciais + texto bold em 3-5 palavras",
            ],
        },
        {
            "week": "Semana 3",
            "title": "OTIMIZAR O QUE FUNCIONA",
            "color": "#FFD700",
            "tasks": [
                "Análise de retenção: qual minuto os viewers saem? Cortar gordura",
                "Dobrar o formato que mais reteve audiência",
                "5-7 vídeos longos + 10 Shorts",
                "Adicionar 'Part 2' nos vídeos que performaram melhor",
                "Engajar nos comments — perguntar opinião pra gerar discussão",
            ],
        },
        {
            "week": "Semana 4",
            "title": "ESCALAR + MONETIZAÇÃO",
            "color": "#2ECC40",
            "tasks": [
                "Meta: 20+ vídeos no canal + 30+ Shorts",
                "Se elegível (1K subs + 4K horas): aplicar para monetização",
                "Criar playlists temáticas para aumentar watch time",
                "Postar simultaneamente em YouTube + TikTok",
                "Planejar mês 2: séries, collabs, trends",
            ],
        },
    ]
