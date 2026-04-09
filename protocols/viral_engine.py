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


# ═══════════════════════════════════════════════════════════
# CHANNEL'S OWN BEST VIDEOS — What already works for THIS channel
# ═══════════════════════════════════════════════════════════

def analyze_channel_best_videos(channel_url: str) -> list[dict]:
    """
    Get the channel's own top videos by views using yt-dlp.
    Returns the titles that ALREADY WORK for this specific channel.
    """
    if not channel_url:
        return []

    try:
        import subprocess
        import json as _json

        # Get top videos sorted by view count
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json",
            "--playlist-end", "30", "--no-warnings", "--quiet",
            "--extractor-args", "youtube:player_skip=webpage",
            f"{channel_url}/videos",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if proc.returncode != 0:
            return []

        videos = []
        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = _json.loads(line)
                title = data.get("title", "")
                views = data.get("view_count", 0) or 0
                if title and views > 0:
                    videos.append({"title": title, "views": views})
            except _json.JSONDecodeError:
                pass

        # Sort by views descending, return top 15
        videos.sort(key=lambda x: x["views"], reverse=True)
        logger.info(f"Channel analysis: {len(videos)} videos, top views: {videos[0]['views']:,}" if videos else "No videos found")
        return videos[:15]

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Channel analysis failed: {e}")
        return []


def format_channel_winners(best_videos: list[dict]) -> str:
    """Format the channel's best videos into a prompt block."""
    if not best_videos:
        return ""

    lines = [
        "═══════════════════════════════════════════",
        "TITULOS CAMPEOES DESTE CANAL (os que JA funcionaram):",
        "═══════════════════════════════════════════",
        "Estes sao os titulos com MAIS VIEWS deste canal.",
        "A IA DEVE replicar os padroes que funcionaram aqui.",
        "",
    ]
    for i, v in enumerate(best_videos[:10], 1):
        lines.append(f"  {i}. [{v['views']:>10,} views] {v['title']}")

    lines.append("")
    lines.append("ANALISE: Identifique os padroes em comum destes titulos campeoes")
    lines.append("(formato, CAPS, hooks, estrutura) e REPLIQUE nos novos titulos.")
    lines.append("")

    return "\n".join(lines)


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
# SOP ANALYSIS — Extract the channel's REAL DNA
# ═══════════════════════════════════════════════════════════

def analyze_sop(sop_text: str, existing_titles: list[str] | None = None) -> dict:
    """
    Deep-analyze the SOP to extract the channel's unique DNA:
    - Title formulas (patterns used by THIS channel)
    - Power words (CAPS words this channel favors)
    - Hook patterns (how this channel opens titles)
    - Recurring themes/entities
    - Tone and style markers

    This ensures generated titles feel like they come FROM this channel,
    not from a generic template.
    """
    result = {
        "title_formulas": [],
        "power_words": [],
        "hook_patterns": [],
        "entities": [],       # Specific names, places, civilizations
        "tone_markers": [],
        "style_rules": [],
    }

    titles = existing_titles or []

    # ── Extract title formulas from existing titles ──
    if titles:
        # Analyze structural patterns
        patterns_found = {}
        for title in titles:
            pattern = _extract_title_structure(title)
            if pattern:
                patterns_found[pattern] = patterns_found.get(pattern, 0) + 1

        # Top patterns (most frequent first, include all)
        result["title_formulas"] = [
            p for p, count in sorted(patterns_found.items(), key=lambda x: -x[1])
        ][:10]

        # Extract CAPS words from titles (the channel's own power words)
        caps_freq = {}
        noise_caps = {"LOS", "LAS", "DEL", "QUE", "POR", "THE", "AND", "FOR", "UNA", "UNO"}
        for title in titles:
            caps = re.findall(r'\b([A-ZÁÉÍÓÚÑÜ]{3,})\b', title)
            for w in caps:
                if len(w) >= 4 and w not in noise_caps:
                    caps_freq[w] = caps_freq.get(w, 0) + 1
        # Include ALL caps words that appear (even once) — they define the channel's style
        result["power_words"] = [
            w for w, c in sorted(caps_freq.items(), key=lambda x: -x[1])
        ][:20]

        # Extract hook patterns (first 3-5 words)
        hooks = {}
        for title in titles:
            # Remove specific names, keep structure
            first_words = title.split()[:4]
            if len(first_words) >= 3:
                hook = " ".join(first_words)
                # Generalize: replace proper nouns with [KEYWORD]
                generalized = re.sub(r'\b[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+\b', '[X]', hook)
                hooks[generalized] = hooks.get(generalized, 0) + 1
        result["hook_patterns"] = [
            h for h, c in sorted(hooks.items(), key=lambda x: -x[1])
        ][:5]

    # ── Extract entities from SOP (names, places, topics) ──
    if sop_text:
        # Proper nouns (capitalized, 4+ chars)
        proper_nouns = re.findall(r'\b([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{3,})\b', sop_text)
        entity_freq = {}
        noise = {
            "Como", "Para", "Cada", "Esta", "Este", "Todo", "Tiene",
            "Puede", "Solo", "Entre", "Sobre", "Desde", "Donde", "Canal",
            "Video", "Titulo", "Content", "Formato", "Estilo", "Regla",
            "Importante", "Seccion", "Pilar",
        }
        for e in proper_nouns:
            if e not in noise:
                entity_freq[e] = entity_freq.get(e, 0) + 1
        result["entities"] = [
            e for e, c in sorted(entity_freq.items(), key=lambda x: -x[1])
        ][:25]

        # Extract tone markers from SOP
        tone_indicators = []
        if re.search(r'CAPS|MAYUSCULAS|capslock', sop_text, re.IGNORECASE):
            tone_indicators.append("Usa CAPS para enfasis emocional")
        if re.search(r'pregunta|interroga|\?', sop_text, re.IGNORECASE):
            tone_indicators.append("Usa preguntas retoricas")
        if re.search(r'numero|cifra|\d+', sop_text, re.IGNORECASE):
            tone_indicators.append("Usa numeros para especificidad")
        if re.search(r'misterio|secreto|oculto|prohibido', sop_text, re.IGNORECASE):
            tone_indicators.append("Tono de misterio y revelacion")
        if re.search(r'historia|antiguo|civilizaci', sop_text, re.IGNORECASE):
            tone_indicators.append("Enfoque historico-educativo")
        if re.search(r'nadie|nunca|imposible|increible', sop_text, re.IGNORECASE):
            tone_indicators.append("Usa superlativos y absolutos")
        result["tone_markers"] = tone_indicators

    return result


def _extract_title_structure(title: str) -> str:
    """
    Extract the structural pattern from a title.
    E.g.: "TEOTIHUACÁN: El MISTERIO que Nadie Puede Explicar"
       → "[KEYWORD]: El [POWER] que [HOOK]"
    """
    # Replace ALL-CAPS words (4+ chars) with [POWER]
    structure = re.sub(r'\b[A-ZÁÉÍÓÚÑÜ]{4,}\b', '[POWER]', title)
    # Replace capitalized proper nouns with [KEYWORD]
    structure = re.sub(r'\b[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{3,}\b', '[Nombre]', structure)
    # Replace numbers with [NUM]
    structure = re.sub(r'\b\d+\b', '[NUM]', structure)
    # Collapse multiple [POWER] or [Nombre]
    structure = re.sub(r'(\[POWER\]\s*)+', '[POWER] ', structure)
    structure = re.sub(r'(\[Nombre\]\s*)+', '[Nombre] ', structure)
    return structure.strip()


def format_sop_analysis(analysis: dict) -> str:
    """Format SOP analysis into a prompt block."""
    lines = []

    lines.append("═══════════════════════════════════════════")
    lines.append("DNA DO CANAL (extraido do SOP e titulos existentes):")
    lines.append("═══════════════════════════════════════════")

    if analysis["title_formulas"]:
        lines.append("\nFORMULAS DE TITULO QUE ESTE CANAL USA (replique estas estruturas):")
        for i, f in enumerate(analysis["title_formulas"], 1):
            lines.append(f"  {i}. {f}")

    if analysis["power_words"]:
        lines.append(f"\nPALAVRAS DE IMPACTO DO CANAL (use estas em CAPS):")
        lines.append(f"  {', '.join(analysis['power_words'])}")

    if analysis["hook_patterns"]:
        lines.append(f"\nPADROES DE ABERTURA DO CANAL:")
        for h in analysis["hook_patterns"]:
            lines.append(f"  - \"{h}...\"")

    if analysis["entities"]:
        lines.append(f"\nENTIDADES/TEMAS DO CANAL (nomes que o canal cobre):")
        lines.append(f"  {', '.join(analysis['entities'])}")

    if analysis["tone_markers"]:
        lines.append(f"\nTOM E ESTILO:")
        for t in analysis["tone_markers"]:
            lines.append(f"  - {t}")

    lines.append("")
    lines.append("REGRA FUNDAMENTAL: Os titulos gerados DEVEM parecer que foram criados")
    lines.append("pelo DONO deste canal. Use as MESMAS formulas, MESMAS power words,")
    lines.append("MESMO tom. A unica diferenca: agora com keywords de ALTO VOLUME.")
    lines.append("")

    return "\n".join(lines)


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
    existing_titles: list[str] | None = None,
    channel_best_videos: list[dict] | None = None,
) -> tuple[str, str]:
    """
    Build the ultimate viral title generation prompt.
    SOP is the VOICE — the AI becomes the channel owner.

    Returns: (system_prompt, user_prompt)
    """
    lang_code = lang[:2]
    formulas = get_viral_formulas(lang_code)

    lang_labels = {
        "es": "Español", "pt": "Português (BR)", "en": "English",
        "fr": "Français", "de": "Deutsch",
    }
    lang_label = lang_labels.get(lang_code, lang)

    # Analyze SOP — extract the channel's real DNA
    sop_analysis = analyze_sop(sop_text, existing_titles)
    sop_analysis_block = format_sop_analysis(sop_analysis)

    # Channel's own power words OVERRIDE generic
    channel_power_words = sop_analysis.get("power_words", [])
    if channel_power_words:
        formulas["power_words"] = channel_power_words + [
            w for w in formulas["power_words"] if w not in channel_power_words
        ]

    # Build data blocks
    niches_text = "\n".join([f"- {n['name']}: {n.get('description', '')}" for n in niches])

    kw_lines = []
    for kw in keywords_with_volume[:30]:
        vol = kw.get("vol", 0)
        comp = kw.get("competition", 0)
        comp_label = "BAIXA" if comp < 0.3 else ("MEDIA" if comp < 0.6 else "ALTA")
        kw_lines.append(f'  "{kw["keyword"]}": {vol:,}/mes (comp: {comp_label})')

    auto_lines = [f'  - "{s}"' for s in sorted(autocomplete_suggestions)[:25]]

    golden = [kw for kw in keywords_with_volume if kw.get("vol", 0) >= 100 and kw.get("competition", 1) < 0.4]
    golden_lines = [f'  "{kw["keyword"]}": {kw["vol"]:,}/mes' for kw in golden[:10]]

    # Format channel's best videos
    winners_block = format_channel_winners(channel_best_videos or [])

    # ═══════════════════════════════════════════════════
    # SYSTEM PROMPT — short, surgical, SOP-driven
    # ═══════════════════════════════════════════════════
    system_prompt = f"""Voce E o dono do canal "{channel_name}". Voce nao esta ajudando — voce esta ESCREVENDO seus proprios titulos.

Seu SOP (seu estilo, sua voz, seu DNA) esta abaixo. Cada titulo que voce cria DEVE soar como se VOCE tivesse escrito — porque voce escreveu.

REGRA #0 (MAIS IMPORTANTE): O SOP contem uma FORMULA DE TITULOS especifica (secao 8).
Voce DEVE seguir essa formula EXATA. Se o SOP diz que o canal usa "Your life as...",
"POV:", "What Its Like to be...", CADA titulo deve usar essas estruturas.
NAO invente formulas genericas — copie a estrutura do SOP.

Suas power words favoritas: {', '.join(formulas['power_words'][:15])}

4 regras inviolaveis:
1. SEGUIR A FORMULA DE TITULOS DO SOP (estrutura identica aos titulos do canal)
2. Keyword de ALTO VOLUME nos primeiros 40 caracteres (SEO)
3. Pelo menos 1 POWER WORD em CAPS (emocao)
4. CURIOSITY GAP — prometa sem revelar (o espectador PRECISA clicar)

Idioma: {lang_label}. Maximo 80 caracteres por titulo."""

    # ═══════════════════════════════════════════════════
    # USER PROMPT — structured data, SOP as foundation
    # ═══════════════════════════════════════════════════
    # Extract title formula section from SOP (section 8) if present
    title_formula_block = ""
    try:
        # Try to find title formula / formula de titulos section in SOP
        for pattern in [r'(?i)(F[OÓo]RMULA DE T[IÍi]TULOS.*?)(?=\n\*\*\d+\.|---|\n##)', r'(?i)(TITLE FORMULA.*?)(?=\n\*\*\d+\.|---|\n##)', r'(?i)(8\.\s*F[OÓo]RMULA.*?)(?=\n\*\*\d+\.|---|\n##)']:
            m = re.search(pattern, sop_text, re.DOTALL)
            if m and len(m.group(1)) > 50:
                title_formula_block = m.group(1).strip()[:1500]
                break
        # Also try to find top performing titles
        if not title_formula_block:
            m = re.search(r'(?i)(10 Melhores T[ií]tulos.*?)(?=\n\*\*|\n##|---)', sop_text, re.DOTALL)
            if m:
                title_formula_block = m.group(1).strip()[:1500]
    except Exception:
        pass

    user_prompt = f"""Gere {count} titulos para meu canal.

{sop_analysis_block}

{winners_block}

{f'''═══════════════════════════════════════════
FORMULA DE TITULOS DO CANAL (EXTRAIDA DO SOP — SIGA ESTAS ESTRUTURAS):
═══════════════════════════════════════════
{title_formula_block}

REGRA CRITICA: Os titulos DEVEM seguir estas formulas EXATAS do canal.
Se o canal usa "Your life as...", "POV:", "What Its Like to be...",
TODOS os titulos devem comecar com essas estruturas.
NÃO invente formulas novas — use as do SOP acima.
''' if title_formula_block else ''}

═══════════════════════════════════════════
MEU SOP (minha voz, meu estilo — SIGA FIELMENTE):
═══════════════════════════════════════════
{sop_text[:3000]}

═══════════════════════════════════════════
NICHOS (titulos EXCLUSIVAMENTE sobre estes):
═══════════════════════════════════════════
{niches_text}

═══════════════════════════════════════════
KEYWORDS COM VOLUME REAL ({len(kw_lines)} keywords):
═══════════════════════════════════════════
{chr(10).join(kw_lines) if kw_lines else '(sem dados)'}

{f'''OPORTUNIDADES DE OURO (volume alto + competicao baixa — PRIORIZE):
{chr(10).join(golden_lines)}''' if golden_lines else ''}

═══════════════════════════════════════════
BUSCAS REAIS NO YOUTUBE (autocomplete):
═══════════════════════════════════════════
{chr(10).join(auto_lines) if auto_lines else '(sem dados)'}

{demand_summary}

═══════════════════════════════════════════
INSTRUCOES (GERE EXATAMENTE {count} TITULOS):
═══════════════════════════════════════════
QUANTIDADE: Voce DEVE gerar EXATAMENTE {count} titulos. Nem mais, nem menos. Conte antes de entregar.

1. CADA titulo DEVE conter pelo menos 1 keyword da lista de volume
2. Keyword nos PRIMEIROS 40 caracteres
3. 1+ POWER WORD em CAPS (use as MINHAS: {', '.join(formulas['power_words'][:8])})
4. CURIOSITY GAP em cada titulo
5. Distribua igualmente entre os sub-nichos
6. Para os 10 primeiros (ALTA prioridade), inclua variante B (title_b)
7. O campo "pillar" = nome do sub-nicho
8. Mix: ~10 ALTA, ~12 MEDIA, ~{count - 22} BAIXA = {count} TOTAL
9. Maximo 80 caracteres por titulo

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
