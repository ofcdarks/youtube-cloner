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

# In-memory translation cache: {language_code: [translated_niches]}
_NICHE_TRANSLATIONS_CACHE: dict[str, list[dict[str, Any]]] = {}

# In-memory regional niches cache: {(country, language): [validated_niches]}
_REGIONAL_NICHES_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}

COUNTRY_NAMES = {
    "us": "United States",
    "br": "Brazil",
    "gb": "United Kingdom",
    "es": "Spain",
    "mx": "Mexico",
    "de": "Germany",
    "fr": "France",
    "it": "Italy",
    "jp": "Japan",
    "kr": "South Korea",
    "ar": "Argentina",
    "co": "Colombia",
    "cl": "Chile",
    "pt": "Portugal",
}

LANGUAGE_FULL_NAMES = {
    "en": "English",
    "pt": "Brazilian Portuguese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
}


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


# Pre-baked PT-BR translation (instant, no AI call)
_NICHE_TRANSLATIONS_PT: dict[int, dict[str, str]] = {
    1: {
        "name": "Histórias de Traição & Vingança",
        "desc": "Narração com IA sobre stock footage. Histórias de traição, karma e justiça. Espectadores fazem maratona de 8-15 min. ~200 mil canais nesse espaço.",
        "format": "Voz IA + stock footage + texto sobreposto",
        "tools": "ChatGPT (scripts), ElevenLabs (voz), CapCut/Premiere",
        "tip": "Posta 1 vídeo/dia. Hooks de cliffhanger nos primeiros 5s. 'Meu chefe me demitiu... Depois implorou pra eu voltar'",
        "affiliate": "Baixo — foco em RPM do AdSense",
    },
    2: {
        "name": "Finanças Pessoais & Investimentos",
        "desc": "O REI do CPM. Bancos, cartões de crédito e plataformas de investimento pagam valores massivos. Sub-nichos: orçamento, cripto, renda passiva.",
        "format": "Locução + gráficos + stock footage de cidades/lifestyle",
        "tools": "Canva, voz IA, bibliotecas de stock footage",
        "tip": "Niche DOWN forte: 'Investir para Artistas' ou 'Finanças para Gen Z'.",
        "affiliate": "ENORME — cartões, corretoras, cursos ($50-200/venda)",
    },
    3: {
        "name": "Ferramentas de IA & Renda Online",
        "desc": "O nicho de 2026. Ensina como usar ferramentas de IA pra ganhar dinheiro. Gravação de tela + locução. Ferramentas novas todo dia = conteúdo infinito.",
        "format": "Tutoriais com gravação de tela + locução IA",
        "tools": "OBS, ElevenLabs, CapCut",
        "tip": "Cobre ferramentas NOVAS primeiro. Velocidade é tudo. Pegue a onda do algoritmo.",
        "affiliate": "MASSIVO — afiliados SaaS pagam $20-100/cadastro recorrente",
    },
    4: {
        "name": "Podcasts de Inglês",
        "desc": "Apenas ~10 mil canais competindo. Apps como Duolingo e Cambly pagam CPMs premium. Audiência global massiva querendo aprender inglês.",
        "format": "Estilo podcast com legendas + visuais simples",
        "tools": "Voz IA (inglês natural), Canva, editor simples",
        "tip": "Foque em países específicos: 'Inglês pra Brasileiros', 'Inglês pra Japoneses'.",
        "affiliate": "Bom — apps de idioma, cursos, livros",
    },
    5: {
        "name": "Direito / Drama de Tribunal",
        "desc": "Escritórios de advocacia pagam o MAIOR valor. Cobre casos bizarros de tribunal, breakdowns jurídicos, conteúdo estilo AITA.",
        "format": "Narração IA + stock footage de tribunal + animações",
        "tools": "ChatGPT, voz IA, stock footage",
        "tip": "Histórias jurídicas do Reddit + casos reais = conteúdo infinito.",
        "affiliate": "Médio — serviços jurídicos, seguros",
    },
    6: {
        "name": "Recaps de Manhwa / Anime",
        "desc": "Apenas ~10 mil canais. Recapitula histórias de manhwa/mangá com narração dramática. Audiência Gen Z massiva. Milhões de views.",
        "format": "Painéis de manhwa + efeitos de zoom + narração IA",
        "tools": "CapCut, voz IA, material de manhwa",
        "tip": "Séries populares com tramas dramáticas. Formato Parte 1, Parte 2 gera retenção.",
        "affiliate": "Baixo — merch, assinaturas de mangá",
    },
    7: {
        "name": "Sons Ambientes & Conteúdo de Sono",
        "desc": "Lives 24/7 de chuva, lareira, sons de floresta. Máquina de renda passiva. Configurou uma vez, roda pra sempre. ~20 mil canais.",
        "format": "Vídeos longos (8-12h) ou lives",
        "tools": "Bibliotecas de sons grátis, stock footage de natureza, OBS",
        "tip": "Vídeos de 8-10 horas. YouTube AMA watch time. Um vídeo gera receita por anos.",
        "affiliate": "Baixo — patrocínios de marcas de sono/wellness",
    },
    8: {
        "name": "Cultura Pop & Análises de Celebridades",
        "desc": "Velocidade é o REI. Cobre drama, términos, momentos virais em horas. CPM menor mas potencial massivo de views. Estratégia de volume.",
        "format": "Comentário + clipes + screenshots + legendas",
        "tools": "CapCut, voz IA, screenshots de redes sociais",
        "tip": "Google Alerts pra celebs em alta. Quem posta primeiro vence.",
        "affiliate": "Baixo — jogada de AdSense por volume",
    },
}


def _apply_translation(niches: list[dict], translation_map: dict[int, dict[str, str]]) -> list[dict]:
    """Merge a translation map into the base niches list (immutable)."""
    out = []
    for n in niches:
        t = translation_map.get(n["rank"], {})
        out.append({**n, **t})
    return out


def _ai_translate_niches(language: str) -> list[dict] | None:
    """Translate niches via AI for any language. Returns None on failure."""
    try:
        from protocols.ai_client import chat
    except Exception as e:
        logger.warning(f"ai_client unavailable: {e}")
        return None

    target_lang = LANGUAGE_FULL_NAMES.get(language, language)
    translatable = [
        {
            "rank": n["rank"],
            "name": n["name"],
            "desc": n["desc"],
            "format": n["format"],
            "tools": n["tools"],
            "tip": n["tip"],
            "affiliate": n["affiliate"],
        }
        for n in TOP_NICHES
    ]

    import json as _json
    prompt = (
        f"Translate the following YouTube niche playbook entries to {target_lang}. "
        "Keep brand names, tool names, and tech terms in English (e.g. ChatGPT, ElevenLabs, AdSense, CPM, RPM). "
        "Translate naturally — not literally. Keep the same JSON structure.\n\n"
        f"Input:\n{_json.dumps(translatable, ensure_ascii=False)}\n\n"
        "Return ONLY a JSON array with the same structure. No markdown, no code fences, no commentary."
    )

    try:
        response = chat(prompt, max_tokens=4000, temperature=0.3, timeout=120)
        # Strip potential code fences
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip("` \n")
        translated = _json.loads(text)
        if not isinstance(translated, list):
            return None
        translation_map = {int(t["rank"]): t for t in translated if "rank" in t}
        return _apply_translation(TOP_NICHES, translation_map)
    except Exception as e:
        logger.warning(f"AI translation to {language} failed: {e}")
        return None


def get_translated_niches(language: str = "en") -> list[dict]:
    """
    Return TOP_NICHES translated to the target language.
    - English: returns TOP_NICHES as-is
    - Portuguese: uses pre-baked translation (instant)
    - Other languages: AI-translated on first call, cached in memory
    """
    lang = (language or "en").lower()[:2]
    if lang == "en":
        return TOP_NICHES
    if lang in _NICHE_TRANSLATIONS_CACHE:
        return _NICHE_TRANSLATIONS_CACHE[lang]
    if lang == "pt":
        translated = _apply_translation(TOP_NICHES, _NICHE_TRANSLATIONS_PT)
        _NICHE_TRANSLATIONS_CACHE[lang] = translated
        return translated
    # AI-translate for other languages
    ai_result = _ai_translate_niches(lang)
    if ai_result:
        _NICHE_TRANSLATIONS_CACHE[lang] = ai_result
        return ai_result
    return TOP_NICHES


def enrich_top_niches(country: str = "us", language: str = "en") -> list[dict]:
    """
    Enriquece a lista curada de Top Niches com dados ao vivo do DataForSEO.
    Para cada nicho, busca search volume + competition + CPC do seed keyword.
    Retorna a lista enriquecida (sempre retorna mesmo que enrichment falhe).
    """
    from protocols.keywords_everywhere import get_keyword_data

    base_niches = get_translated_niches(language)
    seeds = [n["seed"] for n in base_niches]
    try:
        kw_data = get_keyword_data(seeds, country=country, language=language)
    except Exception as e:
        logger.warning(f"enrich_top_niches: get_keyword_data failed: {e}")
        kw_data = []

    by_kw = {item["keyword"].lower(): item for item in kw_data}

    enriched = []
    for niche in base_niches:
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


# ─────────────────────────────────────────────────────────────────────
# REGIONAL VALIDATED NICHES — AI-generated per (country, language)
# ─────────────────────────────────────────────────────────────────────


def _get_youtube_api_key() -> str:
    """Retrieve YouTube Data API key from admin_settings."""
    try:
        from database import get_setting
        return get_setting("youtube_api_key") or ""
    except Exception:
        return ""


def _search_youtube_channel(channel_name: str, api_key: str, region: str = "US") -> dict | None:
    """
    Search YouTube Data API for a channel by name. Returns dict with
    {name, handle, url, subs, thumbnail} or None if not found.
    """
    if not api_key or not channel_name:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": channel_name,
                "type": "channel",
                "maxResults": 1,
                "regionCode": region.upper(),
                "key": api_key,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"YT search HTTP {resp.status_code} for '{channel_name}'")
            return None
        items = resp.json().get("items", [])
        if not items:
            return None
        snippet = items[0].get("snippet", {}) or {}
        channel_id = items[0].get("id", {}).get("channelId", "")
        if not channel_id:
            return None
        # Fetch channel stats
        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "snippet,statistics",
                "id": channel_id,
                "key": api_key,
            },
            timeout=15,
        )
        subs = 0
        handle = ""
        thumbnail = ""
        real_name = snippet.get("channelTitle") or channel_name
        if stats_resp.status_code == 200:
            ch_items = stats_resp.json().get("items", [])
            if ch_items:
                ch = ch_items[0]
                stats = ch.get("statistics", {}) or {}
                snip = ch.get("snippet", {}) or {}
                subs = int(stats.get("subscriberCount", 0) or 0)
                handle = snip.get("customUrl", "") or ""
                real_name = snip.get("title", real_name)
                thumbs = snip.get("thumbnails", {}) or {}
                thumbnail = (thumbs.get("default") or {}).get("url", "")

        # URL: prefer handle (@xxx), fallback to /channel/ID
        if handle:
            url = f"https://www.youtube.com/{handle}" if handle.startswith("@") else f"https://www.youtube.com/@{handle}"
        else:
            url = f"https://www.youtube.com/channel/{channel_id}"

        return {
            "name": real_name,
            "handle": handle,
            "url": url,
            "subs": subs,
            "subs_formatted": _format_subs(subs),
            "thumbnail": thumbnail,
            "channel_id": channel_id,
        }
    except Exception as e:
        logger.warning(f"_search_youtube_channel('{channel_name}') failed: {e}")
        return None


def _format_subs(n: int) -> str:
    """Format subscriber count: 1.2M, 450K, etc."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _build_regional_prompt(country: str, language: str) -> str:
    """Build the AI prompt for generating validated regional niches."""
    country_name = COUNTRY_NAMES.get(country.lower(), country.upper())
    language_name = LANGUAGE_FULL_NAMES.get(language.lower()[:2], language)

    return f"""You are a YouTube niche research strategist with 10 years of experience in faceless channels, regional content markets, and ad-rate analysis. You have personally studied thousands of thriving faceless channels across 15+ countries.

TASK: Generate 8 VALIDATED, CHAMPIONSHIP-LEVEL faceless YouTube niches that are:
- Currently EXPLODING in {country_name} specifically (not generic US/global niches)
- Proven monetization: actual creators earning $1K-50K/month right now
- Have a clear gap (NOT oversaturated — avoid generic "motivation", "top 10 lists", "facts you didn't know")
- 100% faceless production (AI voice + stock/screen recording/compilations/animation)
- Culturally/linguistically relevant to {country_name} specifically

CRITICAL RULES — failure to follow these = unacceptable output:
1. Each niche MUST be DIFFERENT from typical US/English niches when country is not US
2. Include at least 3 niches UNIQUE to {country_name} culture, market, or language
3. Focus on niches with REALISTIC CPM for {country_name} ad rates (don't inflate)
4. Avoid generic "storytelling"/"history"/"facts" unless you have a very specific angle
5. Think about what {language_name}-speaking audiences WANT that English channels DON'T cover
6. Example channels MUST be real, currently active, in {language_name}, and >100K subs
7. Do NOT repeat the same 8 niches if I ask again for a different region — each region has distinct winners

For each niche provide (content in {language_name}, EXCEPT brand/tool names which stay in English):
- name: catchy niche name in {language_name}
- emoji: 1 emoji
- seed: English search query for SEO/keyword lookup (3-5 words)
- desc: 2-3 sentences explaining WHY it's valid NOW in {country_name} (what's driving demand)
- cpm_est: realistic CPM range in USD for {country_name} (e.g. "$6-14", NOT "$20-50" for low-ad-rate regions)
- competition: one of "VERY LOW" | "LOW" | "MEDIUM" | "HIGH" (be honest)
- growth: growth multiplier last 12 months (e.g. "12x")
- difficulty: 1-5 integer (1=easiest to start, 5=hardest)
- virality: 1-5 integer (5=most viral potential)
- monetization: 1-5 integer (5=highest monetization)
- format: 1 sentence — production format
- tools: 1 sentence — list of tools (English names: ChatGPT, ElevenLabs, CapCut, etc.)
- tip: 1 sentence actionable pro tip in {language_name}
- affiliate: 1 sentence affiliate/sponsor angle in {language_name}
- color: unique hex color per niche (different from the others)
- accent: matching hex accent
- example_channels: ARRAY of EXACTLY 3 real YouTube channel names currently thriving in this niche targeting {country_name} audiences. BE PRECISE — these will be searched on YouTube API. Prefer 100K-10M subs range. Use the EXACT channel display name (not @handle).

OUTPUT FORMAT: Return ONLY a valid JSON array of exactly 8 objects. No markdown code fences, no preamble, no commentary. Start with [ and end with ]."""


def _fetch_regional_niches_from_ai(country: str, language: str) -> list[dict] | None:
    """Call AI to generate regional niches. Returns parsed list or None on failure."""
    try:
        from protocols.ai_client import chat
    except Exception as e:
        logger.warning(f"ai_client unavailable for regional niches: {e}")
        return None

    prompt = _build_regional_prompt(country, language)
    try:
        response = chat(
            prompt,
            system="You are a world-class YouTube niche research expert. Always return valid JSON when asked.",
            max_tokens=6000,
            temperature=0.85,  # higher creativity for diverse regional niches
            timeout=180,
        )
    except Exception as e:
        logger.warning(f"AI regional niches call failed: {e}")
        return None

    import json as _json
    text = (response or "").strip()
    # Strip code fences if AI ignored instructions
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    # Find first [ and last ]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        logger.warning("AI regional niches: no JSON array found")
        return None
    try:
        data = _json.loads(text[start : end + 1])
    except Exception as e:
        logger.warning(f"AI regional niches JSON parse failed: {e}")
        return None

    if not isinstance(data, list) or len(data) == 0:
        return None

    # Validate and normalize
    normalized = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        normalized.append({
            "rank": i + 1,
            "name": str(item.get("name", ""))[:80],
            "emoji": str(item.get("emoji", "🔥"))[:4],
            "seed": str(item.get("seed", item.get("name", "")))[:80],
            "desc": str(item.get("desc", ""))[:500],
            "cpm_est": str(item.get("cpm_est", "$5-15")),
            "competition": str(item.get("competition", "MEDIUM")).upper(),
            "growth": str(item.get("growth", "5x")),
            "difficulty": int(item.get("difficulty", 3) or 3),
            "virality": int(item.get("virality", 3) or 3),
            "monetization": int(item.get("monetization", 3) or 3),
            "format": str(item.get("format", ""))[:200],
            "tools": str(item.get("tools", ""))[:200],
            "tip": str(item.get("tip", ""))[:300],
            "affiliate": str(item.get("affiliate", ""))[:200],
            "color": str(item.get("color", "#7B68EE"))[:8],
            "accent": str(item.get("accent", "#B388FF"))[:8],
            "example_channels": [str(c) for c in (item.get("example_channels") or [])[:3]],
            "cpm_low": _parse_cpm_low(str(item.get("cpm_est", "$5-15"))),
        })

    if len(normalized) < 4:  # sanity check
        logger.warning(f"AI regional niches: only {len(normalized)} valid items")
        return None

    return normalized


def _enrich_niches_with_channels(niches: list[dict], region_code: str) -> list[dict]:
    """For each niche, lookup example_channels on YouTube API and attach real URLs."""
    api_key = _get_youtube_api_key()
    if not api_key:
        logger.info("YT API key not set — skipping channel enrichment")
        for n in niches:
            n["channels"] = []
        return niches

    for niche in niches:
        channels_found = []
        for name in (niche.get("example_channels") or [])[:3]:
            if not name or not name.strip():
                continue
            ch = _search_youtube_channel(name.strip(), api_key, region=region_code)
            if ch:
                channels_found.append(ch)
        niche["channels"] = channels_found
    return niches


def get_regional_niches(country: str, language: str, force_refresh: bool = False) -> list[dict]:
    """
    Get validated regional niches for a (country, language) combo.
    AI-generated + YouTube channel enriched. Cached in memory.

    Fallback chain:
    1. Cache hit → return cached
    2. AI generates niches → YT enrichment → cache
    3. AI fails → return translated TOP_NICHES (graceful degradation)
    """
    country = (country or "us").lower()
    language = (language or "en").lower()[:2]
    cache_key = (country, language)

    if not force_refresh and cache_key in _REGIONAL_NICHES_CACHE:
        return _REGIONAL_NICHES_CACHE[cache_key]

    ai_niches = _fetch_regional_niches_from_ai(country, language)
    if ai_niches:
        enriched = _enrich_niches_with_channels(ai_niches, country)
        _REGIONAL_NICHES_CACHE[cache_key] = enriched
        logger.info(f"Regional niches generated for ({country},{language}): {len(enriched)} niches")
        return enriched

    # Fallback: return translated base niches (no channels)
    logger.info(f"Regional niches fallback to TOP_NICHES for ({country},{language})")
    fallback = get_translated_niches(language)
    for n in fallback:
        n.setdefault("channels", [])
    return fallback


def clear_regional_cache(country: str | None = None, language: str | None = None) -> int:
    """Clear regional niches cache. If both params None, clear all. Returns count cleared."""
    global _REGIONAL_NICHES_CACHE
    if country is None and language is None:
        count = len(_REGIONAL_NICHES_CACHE)
        _REGIONAL_NICHES_CACHE = {}
        return count
    keys_to_remove = [
        k for k in _REGIONAL_NICHES_CACHE.keys()
        if (country is None or k[0] == country.lower())
        and (language is None or k[1] == language.lower()[:2])
    ]
    for k in keys_to_remove:
        del _REGIONAL_NICHES_CACHE[k]
    return len(keys_to_remove)
