"""
Viral Title Engine — The science of YouTube titles that get clicked.

This module orchestrates everything needed to generate titles that are
BORN viral: high search volume + proven click patterns + emotional triggers.

Data sources:
1. YouTube Autocomplete (FREE — real user search intent)
2. DataForSEO keyword volume + related keywords
3. Competitor top videos (title formulas that got millions of views)
4. Google Trends rising queries

Output: A comprehensive prompt block that teaches the AI exactly HOW
to build titles that rank AND get clicked.
"""

import logging
import re
import requests
import unicodedata

logger = logging.getLogger("ytcloner.viral_engine")


# ═══════════════════════════════════════════════════════════
# YOUTUBE AUTOCOMPLETE — What people ACTUALLY type
# ═══════════════════════════════════════════════════════════

def get_youtube_autocomplete(query: str, lang: str = "es") -> list[str]:
    """
    Get YouTube search suggestions (autocomplete).
    FREE — no API key needed. Shows REAL user search intent.
    """
    try:
        resp = requests.get(
            "https://suggestqueries-clients6.youtube.com/complete/search",
            params={
                "client": "youtube",
                "hl": lang,
                "gl": lang.upper() if len(lang) == 2 else "US",
                "q": query,
                "ds": "yt",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if resp.status_code != 200:
            return []

        # Response is JSONP — extract suggestions
        text = resp.text
        suggestions = []
        try:
            import json
            # Find the outermost JSON array
            start = text.index("[")
            # Find matching end bracket
            depth = 0
            end = start
            for i, c in enumerate(text[start:], start):
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            data = json.loads(text[start:end])
            if len(data) > 1 and isinstance(data[1], list):
                for item in data[1]:
                    if isinstance(item, (list, tuple)) and len(item) > 0:
                        suggestions.append(str(item[0]))
                    elif isinstance(item, str):
                        suggestions.append(item)
        except (ValueError, json.JSONDecodeError) as e:
            # Fallback: regex extract quoted strings after the query
            suggestions = re.findall(r'"([^"]{4,60})"', text)[1:16]

        return suggestions[:15]
    except Exception as e:
        logger.warning(f"YouTube autocomplete failed for '{query}': {e}")
        return []


def research_autocomplete_keywords(seed_keywords: list[str], lang: str = "es") -> list[str]:
    """
    Expand seed keywords using YouTube autocomplete.
    Each seed generates 10-15 real search suggestions.
    """
    all_suggestions = set()
    for seed in seed_keywords[:10]:  # Max 10 seeds to keep it fast
        suggestions = get_youtube_autocomplete(seed, lang)
        all_suggestions.update(suggestions)
        # Also try with question prefixes
        for prefix in _get_question_prefixes(lang):
            q_suggestions = get_youtube_autocomplete(f"{prefix} {seed}", lang)
            all_suggestions.update(q_suggestions[:5])

    # Clean and deduplicate
    clean = set()
    for s in all_suggestions:
        s = s.strip().lower()
        if s and len(s) > 3:
            clean.add(s)

    logger.info(f"YouTube autocomplete: {len(clean)} unique suggestions from {len(seed_keywords)} seeds")
    return list(clean)


def _get_question_prefixes(lang: str) -> list[str]:
    """Question prefixes that reveal high-intent searches."""
    prefixes = {
        "es": ["por qué", "cómo", "qué es", "dónde"],
        "pt": ["por que", "como", "o que é", "onde"],
        "en": ["why", "how", "what is", "where"],
    }
    return prefixes.get(lang[:2], prefixes["en"])


# ═══════════════════════════════════════════════════════════
# VIRAL TITLE FORMULAS — Proven click patterns
# ═══════════════════════════════════════════════════════════

VIRAL_FORMULAS = {
    "es": {
        "power_words": [
            "SECRETO", "PROHIBIDO", "IMPOSIBLE", "OCULTO", "PERDIDO",
            "OLVIDADO", "MISTERIO", "VERDAD", "REVELADO", "DESTRUIDO",
            "INCREÍBLE", "BRUTAL", "IMPACTANTE", "DESCONOCIDO", "SAGRADO",
            "MALDITO", "ENTERRADO", "BORRADO", "CENSURADO", "LEGENDARIO",
        ],
        "formulas": [
            "[KEYWORD]: El SECRETO que [ENTIDAD] No Quiere que Sepas",
            "[KEYWORD]: La VERDAD OCULTA que Borraron de la Historia",
            "¿Por qué OCULTARON [KEYWORD] durante [NÚMERO] años?",
            "Los [NÚMERO] MISTERIOS de [KEYWORD] que NADIE puede Explicar",
            "[KEYWORD]: Lo que NUNCA te Contaron sobre [TEMA]",
            "Descubrieron [KEYWORD] y lo que Encontraron CAMBIA TODO",
            "La VERDADERA Historia de [KEYWORD] que los Libros OMITEN",
            "[KEYWORD] — El Descubrimiento que DESTRUYE la Historia Oficial",
            "¿Cómo es POSIBLE que [KEYWORD] existiera hace [NÚMERO] años?",
            "[KEYWORD]: La Civilización PERDIDA más AVANZADA que [REFERENCIA]",
        ],
        "hooks": [
            "que nadie conoce", "que cambió todo", "que no debería existir",
            "que borraron de la historia", "que la ciencia no puede explicar",
            "que estuvo oculto por siglos", "que desafía toda lógica",
            "que reescribe la historia", "más antiguo del mundo",
            "que los arqueólogos no esperaban encontrar",
        ],
        "emotional_triggers": [
            "NUNCA te contaron", "NADIE puede explicar", "NO deberías saber",
            "cambia TODO lo que sabías", "estuvieron MINTIENDO",
            "la ciencia NO puede explicar", "estuvo OCULTO por siglos",
            "DESTRUYE la historia oficial", "PROHIBIDO hablar de esto",
        ],
    },
    "pt": {
        "power_words": [
            "SECRETO", "PROIBIDO", "IMPOSSÍVEL", "OCULTO", "PERDIDO",
            "ESQUECIDO", "MISTÉRIO", "VERDADE", "REVELADO", "DESTRUÍDO",
            "INCRÍVEL", "BRUTAL", "IMPACTANTE", "DESCONHECIDO", "SAGRADO",
            "AMALDIÇOADO", "ENTERRADO", "APAGADO", "CENSURADO", "LENDÁRIO",
        ],
        "formulas": [
            "[KEYWORD]: O SEGREDO que [ENTIDADE] Não Quer que Você Saiba",
            "[KEYWORD]: A VERDADE OCULTA que Apagaram da História",
            "Por que ESCONDERAM [KEYWORD] durante [NÚMERO] anos?",
            "Os [NÚMERO] MISTÉRIOS de [KEYWORD] que NINGUÉM consegue Explicar",
            "[KEYWORD]: O que NUNCA te Contaram sobre [TEMA]",
            "Descobriram [KEYWORD] e o que Encontraram MUDA TUDO",
        ],
        "hooks": [
            "que ninguém conhece", "que mudou tudo", "que não deveria existir",
            "que apagaram da história", "que a ciência não explica",
        ],
        "emotional_triggers": [
            "NUNCA te contaram", "NINGUÉM pode explicar",
            "muda TUDO que você sabia", "estiveram MENTINDO",
        ],
    },
    "en": {
        "power_words": [
            "SECRET", "FORBIDDEN", "IMPOSSIBLE", "HIDDEN", "LOST",
            "FORGOTTEN", "MYSTERY", "TRUTH", "REVEALED", "DESTROYED",
            "INCREDIBLE", "BRUTAL", "SHOCKING", "UNKNOWN", "SACRED",
        ],
        "formulas": [
            "[KEYWORD]: The SECRET They Don't Want You to Know",
            "[KEYWORD]: The HIDDEN TRUTH Erased from History",
            "Why Did They HIDE [KEYWORD] for [NUMBER] Years?",
            "The [NUMBER] MYSTERIES of [KEYWORD] Nobody Can Explain",
        ],
        "hooks": [
            "nobody knows about", "that changed everything",
            "that shouldn't exist", "erased from history",
        ],
        "emotional_triggers": [
            "They NEVER told you", "NOBODY can explain",
            "changes EVERYTHING you knew", "they've been LYING",
        ],
    },
}


def get_viral_formulas(lang: str = "es") -> dict:
    """Get viral title formulas for the given language."""
    return VIRAL_FORMULAS.get(lang[:2], VIRAL_FORMULAS["en"])


# ═══════════════════════════════════════════════════════════
# VIRAL PROMPT BUILDER — The comprehensive prompt
# ═══════════════════════════════════════════════════════════

def build_viral_prompt(
    channel_name: str,
    niches: list[dict],
    sop_text: str,
    keywords_with_volume: list[dict],
    autocomplete_suggestions: list[str],
    demand_summary: str,
    lang: str = "es",
    count: int = 30,
) -> tuple[str, str]:
    """
    Build the ultimate viral title generation prompt.

    Returns: (system_prompt, user_prompt)
    """
    lang_code = lang[:2]
    formulas = get_viral_formulas(lang_code)

    lang_labels = {
        "es": "Español", "pt": "Português (BR)", "en": "English",
        "fr": "Français", "de": "Deutsch",
    }
    lang_label = lang_labels.get(lang_code, lang)

    # Build niches text
    niches_text = "\n".join([f"- {n['name']}: {n.get('description', '')}" for n in niches])

    # Build keywords block (top 30 by volume)
    kw_lines = []
    for kw in keywords_with_volume[:30]:
        vol = kw.get("vol", 0)
        comp = kw.get("competition", 0)
        comp_label = "BAIXA" if comp < 0.3 else ("MEDIA" if comp < 0.6 else "ALTA")
        kw_lines.append(f'  "{kw["keyword"]}": {vol:,}/mes (comp: {comp_label})')

    # Build autocomplete block (what people actually search)
    auto_lines = []
    for s in sorted(autocomplete_suggestions)[:30]:
        auto_lines.append(f'  - "{s}"')

    # Highlight golden keywords: high volume + low competition
    golden = [kw for kw in keywords_with_volume if kw.get("vol", 0) >= 100 and kw.get("competition", 1) < 0.4]
    golden_lines = [f'  ⭐ "{kw["keyword"]}": {kw["vol"]:,}/mes (competição BAIXA!)' for kw in golden[:10]]

    # ═══════════════════════════════════════════════════
    # SYSTEM PROMPT — makes the AI think like a viral expert
    # ═══════════════════════════════════════════════════
    system_prompt = f"""Você é um ESPECIALISTA MUNDIAL em títulos virais para YouTube com 15 anos de experiência.

Sua especialidade: criar títulos que combinam DEMANDA DE BUSCA REAL com GATILHOS EMOCIONAIS que geram cliques compulsivos.

PRINCÍPIOS FUNDAMENTAIS de títulos virais:

1. CURIOSITY GAP — O título promete informação que o espectador PRECISA saber, mas não revela tudo
   ✅ "TEOTIHUACÁN: El MISTERIO que la Ciencia NO Puede Explicar"
   ❌ "Historia de Teotihuacán explicada"

2. POWER WORDS — Palavras em CAPS que disparam emoções fortes
   Palavras comprovadas: {', '.join(formulas['power_words'][:12])}

3. KEYWORD-FIRST — O título COMEÇA com a keyword de alto volume para SEO
   ✅ "PIRÁMIDES AZTECAS: El Secreto que México Oculta"
   ❌ "El secreto que México oculta sobre las pirámides"

4. PATTERN INTERRUPT — Algo inesperado que quebra o padrão mental
   ✅ "Los MAYAS tenían INTERNET hace 2000 Años"
   ❌ "Tecnología avanzada de los Mayas"

5. SPECIFICITY — Números e dados específicos geram credibilidade
   ✅ "Las 7 CIUDADES que Desaparecieron en UNA NOCHE"
   ❌ "Ciudades que desaparecieron"

6. EMOTIONAL TRIGGERS que comprovadamente geram cliques:
{chr(10).join(f'   - "{t}"' for t in formulas['emotional_triggers'][:8])}

FÓRMULAS COMPROVADAS (use como base):
{chr(10).join(f'   {i+1}. {f}' for i, f in enumerate(formulas['formulas']))}

REGRAS ABSOLUTAS:
- Idioma: {lang_label}
- CADA título DEVE conter pelo menos 1 keyword com volume de busca real
- A keyword principal deve estar nos PRIMEIROS 40 caracteres
- Mínimo 1 POWER WORD em CAPS por título
- Máximo 80 caracteres (ideal: 50-70)
- O título deve criar DESEJO IRRESISTÍVEL de clicar
- NUNCA use título genérico ou descritivo — sempre viral e emocional"""

    # ═══════════════════════════════════════════════════
    # USER PROMPT — the specific request with all data
    # ═══════════════════════════════════════════════════
    user_prompt = f"""Gere {count} títulos VIRAIS para o canal "{channel_name}".

═══════════════════════════════════════════
NICHOS (títulos EXCLUSIVAMENTE sobre estes):
═══════════════════════════════════════════
{niches_text}

═══════════════════════════════════════════
KEYWORDS COM VOLUME DE BUSCA REAL (DataForSEO):
═══════════════════════════════════════════
{chr(10).join(kw_lines) if kw_lines else '(sem dados de volume)'}

{f'''═══════════════════════════════════════════
OPORTUNIDADES DE OURO (volume alto + competição baixa):
═══════════════════════════════════════════
{chr(10).join(golden_lines)}''' if golden_lines else ''}

═══════════════════════════════════════════
O QUE AS PESSOAS REALMENTE BUSCAM NO YOUTUBE:
(YouTube Autocomplete — buscas reais dos usuários)
═══════════════════════════════════════════
{chr(10).join(auto_lines) if auto_lines else '(sem dados de autocomplete)'}

{demand_summary}

═══════════════════════════════════════════
SOP DO CANAL (tom e estilo — referência):
═══════════════════════════════════════════
{sop_text[:3000]}

═══════════════════════════════════════════
INSTRUÇÕES FINAIS:
═══════════════════════════════════════════

1. CADA título DEVE:
   - Conter pelo menos 1 keyword da lista de volume
   - Ter 1+ POWER WORD em CAPS
   - Criar um CURIOSITY GAP irresistível
   - A keyword principal nos primeiros 40 caracteres
   - Máximo 80 caracteres

2. PRIORIZE:
   - Keywords de "OPORTUNIDADES DE OURO" (alto volume + baixa competição)
   - Buscas reais do YouTube Autocomplete (as pessoas JÁ buscam isso)
   - Fórmulas que combinam KEYWORD + EMOÇÃO + ESPECIFICIDADE

3. DISTRIBUA igualmente entre os sub-nichos

4. Para as 10 ideias ALTA, gere uma VARIANTE B (title_b) com ângulo diferente

5. O campo "pillar" DEVE ser o nome do sub-nicho

6. MISTURE: ~10 ALTA, ~12 MEDIA, ~8 BAIXA

Retorne APENAS JSON válido:
[{{"title":"...","title_b":"...(opcional para ALTA)","hook":"primeiros 30s do video","summary":"2 linhas","pillar":"nome do sub-nicho","priority":"ALTA"}}]"""

    return system_prompt, user_prompt


# ═══════════════════════════════════════════════════════════
# TITLE QUALITY GATE — Score before saving
# ═══════════════════════════════════════════════════════════

def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def score_viral_title(
    title: str,
    keywords_with_volume: list[dict],
    lang: str = "es",
) -> dict:
    """
    Score a title for viral potential BEFORE saving.

    Returns: {"score": 0-100, "keyword_match": str, "volume": int, "issues": [...]}
    """
    formulas = get_viral_formulas(lang[:2])
    title_lower = _strip_accents(title.lower())
    title_original = title
    issues = []
    score = 0

    # 1. Length check (ideal: 50-80 chars) — max 15 points
    length = len(title)
    if 50 <= length <= 80:
        score += 15
    elif 40 <= length <= 90:
        score += 10
    elif length > 100:
        score += 0
        issues.append("titulo muito longo")
    else:
        score += 5
        issues.append("titulo muito curto")

    # 2. Contains high-volume keyword — max 30 points
    best_vol = 0
    best_kw = ""
    for kw in keywords_with_volume:
        kw_text = _strip_accents(kw.get("keyword", "").lower())
        if not kw_text:
            continue
        # Check exact match or stem match
        if kw_text in title_lower:
            if kw.get("vol", 0) > best_vol:
                best_vol = kw["vol"]
                best_kw = kw["keyword"]
        else:
            # Try stem: remove trailing s/es
            for suffix in ("s", "es"):
                stem = kw_text[:-len(suffix)] if kw_text.endswith(suffix) and len(kw_text) > len(suffix) + 3 else ""
                if stem and stem in title_lower:
                    if kw.get("vol", 0) > best_vol:
                        best_vol = kw["vol"]
                        best_kw = kw["keyword"]

    if best_vol >= 10000:
        score += 30
    elif best_vol >= 1000:
        score += 25
    elif best_vol >= 100:
        score += 18
    elif best_vol > 0:
        score += 10
    else:
        issues.append("sem keyword de volume")

    # 3. Has power word in CAPS — max 15 points
    caps_words = re.findall(r'\b[A-ZÁÉÍÓÚÑÜ]{4,}\b', title_original)
    power_words_lower = {w.lower() for w in formulas.get("power_words", [])}
    has_power = any(_strip_accents(w.lower()) in power_words_lower or len(w) >= 5 for w in caps_words)
    if caps_words and has_power:
        score += 15
    elif caps_words:
        score += 10
    else:
        score += 0
        issues.append("sem CAPS/power word")

    # 4. Curiosity gap indicators — max 15 points
    curiosity_patterns = [
        r'\?', r'que\s+(nadie|ninguem|nobody)', r'que\s+(nunca|never)',
        r'(secreto|segredo|secret)', r'(oculto|hidden)', r'(prohibido|proibido|forbidden)',
        r'(misterio|mystery)', r'(verdad|verdade|truth)',
        r'no\s+(puede|podem|can)', r'(cambio|mudou|changed)\s+todo',
    ]
    curiosity_score = sum(1 for p in curiosity_patterns if re.search(p, title_lower))
    score += min(15, curiosity_score * 5)
    if curiosity_score == 0:
        issues.append("sem curiosity gap")

    # 5. Keyword position — max 10 points (keyword in first 40 chars = better SEO)
    if best_kw:
        kw_pos = title_lower.find(_strip_accents(best_kw.lower()))
        if kw_pos >= 0 and kw_pos < 40:
            score += 10
        elif kw_pos >= 0:
            score += 5

    # 6. Has number/specificity — max 10 points
    if re.search(r'\d+', title):
        score += 10
    elif re.search(r'(primero|ultimo|mayor|mejor|peor|unico|first|last|biggest|only)', title_lower):
        score += 5

    # 7. Emotional hook check — max 5 points
    hooks = formulas.get("hooks", [])
    for hook in hooks:
        if _strip_accents(hook.lower()) in title_lower:
            score += 5
            break

    return {
        "score": min(100, score),
        "keyword_match": best_kw,
        "volume": best_vol,
        "caps_count": len(caps_words),
        "length": length,
        "issues": issues,
    }


def filter_best_titles(
    titles: list[dict],
    keywords_with_volume: list[dict],
    lang: str = "es",
    min_score: int = 35,
) -> tuple[list[dict], list[dict]]:
    """
    Score all titles and separate into accepted (above min_score) and rejected.
    Also sorts accepted by score descending.
    """
    accepted = []
    rejected = []

    for title_data in titles:
        title = title_data.get("title", "")
        result = score_viral_title(title, keywords_with_volume, lang)
        title_data["_viral_score"] = result["score"]
        title_data["_viral_issues"] = result["issues"]
        title_data["_matched_keyword"] = result["keyword_match"]
        title_data["_matched_volume"] = result["volume"]

        if result["score"] >= min_score:
            accepted.append(title_data)
        else:
            rejected.append(title_data)

    # Sort accepted by viral score (highest first)
    accepted.sort(key=lambda x: x.get("_viral_score", 0), reverse=True)

    logger.info(
        f"Quality gate: {len(accepted)} accepted, {len(rejected)} rejected "
        f"(min_score={min_score}, avg_score={sum(t.get('_viral_score', 0) for t in accepted) / max(len(accepted), 1):.0f})"
    )

    return accepted, rejected
