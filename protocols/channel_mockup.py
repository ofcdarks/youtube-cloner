"""
Channel Mockup — generates a complete "what your channel could look like"
preview for a project/niche.

Inspired by the LaCasaStudio v2.5 channel-mockup feature, adapted for the
Cloner's Python/SOP-based workflow. Used by admins to give students a clear
visual + textual identity for the niche they were assigned.

Output schema:
{
  "channel_name": "Creator's Edge Lab",
  "tagline": "Domine o YouTube com estratégias de elite para criadores",
  "description": "Texto longo (200 palavras) em PT-BR explicando o canal",
  "whats_better": "Por que este canal é SUPERIOR ao original (3 frases PT-BR)",
  "weaknesses_fixed": ["Fraqueza 1 do original corrigida", ...],
  "strategy_edge": "Em 6 meses este canal vence porque...",
  "logo_prompt": "ImageFX prompt em inglês para logo circular profissional",
  "banner_prompt": "ImageFX prompt em inglês para banner 2560x1440",
  "videos": [
    {"title": "...", "thumbnail_prompt": "...", "views_estimate": "500K", "duration": "12:45"},
    ...4 vídeos
  ],
  "colors": {"primary": "#hex", "secondary": "#hex", "accent": "#hex"},
  "fonts": "Montserrat Bold + Inter",
  "keywords": ["kw1", "kw2", ...]
}
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("ytcloner.channel_mockup")


# Fallback disclaimers per language — used when the AI omits the field
_DEFAULT_DISCLAIMERS: dict[str, str] = {
    "pt-BR": "⚠️ Este canal é faceless e usa inteligência artificial para reconstituir cenas, narrações e visuais com fins educativos e informativos. Os conteúdos não representam gravações reais.",
    "en": "⚠️ This is a faceless channel. All scenes, narration and visuals are AI-reconstructed for educational and informational purposes. Content does not represent real footage.",
    "es": "⚠️ Este es un canal faceless. Las escenas, narraciones y visuales son reconstituidos con inteligencia artificial con fines educativos e informativos. El contenido no representa grabaciones reales.",
    "fr": "⚠️ Cette chaîne est faceless. Les scènes, narrations et visuels sont reconstitués par intelligence artificielle à des fins éducatives et informatives.",
    "de": "⚠️ Dies ist ein faceless Kanal. Szenen, Erzählungen und visuelle Inhalte werden zu Bildungs- und Informationszwecken durch künstliche Intelligenz rekonstruiert.",
    "it": "⚠️ Questo è un canale faceless. Scene, narrazioni e contenuti visivi sono ricostruiti tramite intelligenza artificiale a scopo educativo e informativo.",
    "ja": "⚠️ このチャンネルはフェイスレス（顔出しなし）チャンネルです。映像・ナレーション・ビジュアルは教育・情報目的でAIにより再構成されています。",
    "ko": "⚠️ 이 채널은 페이스리스 채널입니다. 모든 장면, 내레이션 및 시각 자료는 교육 및 정보 제공 목적으로 AI에 의해 재구성된 것입니다.",
    "zh": "⚠️ 本频道为虚拟（faceless）频道，所有场景、旁白与画面均由人工智能为教育与信息目的重构，并非真实录像。",
    "ru": "⚠️ Это faceless-канал. Все сцены, озвучка и визуальные материалы воссозданы искусственным интеллектом в образовательных и информационных целях.",
    "ar": "⚠️ هذه قناة بدون وجه (faceless). جميع المشاهد والسرد والمرئيات مُعاد بناؤها بواسطة الذكاء الاصطناعي لأغراض تعليمية وإعلامية.",
    "hi": "⚠️ यह एक फेसलेस चैनल है। सभी दृश्य, कथन और चित्र शैक्षिक और सूचनात्मक उद्देश्यों के लिए AI द्वारा पुनर्निर्मित किए गए हैं।",
    "tr": "⚠️ Bu bir faceless kanaldır. Sahneler, anlatım ve görseller eğitim ve bilgilendirme amaçlı yapay zekâ tarafından yeniden oluşturulmuştur.",
    "nl": "⚠️ Dit is een faceless kanaal. Alle scènes, voice-overs en beelden zijn met behulp van kunstmatige intelligentie gereconstrueerd voor educatieve en informatieve doeleinden.",
}


_SYSTEM_PROMPT = """Você é um DIRETOR CRIATIVO de canais YouTube de elite. Sua missão é, dado um nicho e contexto, criar a IDENTIDADE COMPLETA de um canal MUITO SUPERIOR aos concorrentes existentes naquele nicho.

REGRA CRÍTICA DE IDIOMA (LEIA COM ATENÇÃO):
- TODOS os conteúdos voltados ao público — "channel_name", "tagline", "description", "videos[].title", "tags", "hashtags", "keywords", "disclaimer" — devem estar 100% no IDIOMA ALVO do canal definido pelo campo `language`. Se language=es → tudo em espanhol. Se language=en → tudo em inglês. Se language=ja → tudo em japonês. NUNCA misture idiomas.
- Os campos de meta-análise interna ("whats_better", "weaknesses_fixed", "strategy_edge") devem estar SEMPRE em PORTUGUÊS DO BRASIL (PT-BR), porque são lidos pelo admin brasileiro.
- "logo_prompt", "banner_prompt", "thumbnail_prompt" → SEMPRE em INGLÊS (são prompts pra ImageFX/Imagen).
- NUNCA escreva explicações em inglês fora dos prompts de imagem.
- Os "videos[].title" devem ser EXATAMENTE os títulos sementes que eu fornecer (quando fornecidos). Se o seed_title estiver em outro idioma que não o `language` alvo, TRADUZA culturalmente pro idioma alvo (não literal). Se não houver seeds, crie 4 títulos virais no idioma alvo.

REGRAS DE QUALIDADE:
- NOME DO CANAL É CRÍTICO: deve ser ESTRATÉGICO, ORIGINAL e DIFERENCIADO. Não use clichês como "Top 10", "Daily X", "X Channel", "Mr X", "X Tube", "X Hub", "X World", traduções literais ou nomes que já existam em canais grandes. Pense em nomes que: (1) tenham personalidade única (palavras inventadas, junções inesperadas, referências profundas ao tema); (2) soem premium/cinematográficos (estilo "Vestigium Sacrum", "Corpus Mysterium", "Echoes of Empire", "Veritas Lux"); (3) sejam memoráveis e fáceis de buscar; (4) carreguem o ÂNGULO ÚNICO do canal já no nome. EVITE nomes que poderiam pertencer a qualquer canal genérico do nicho. O nome deve ser uma DECLARAÇÃO de posicionamento.
- Identifique fraquezas típicas do nicho e diga como você corrige cada uma.
- Identifique forças e amplifique 10x.
- Títulos com hooks fortes (curiosity gap, números específicos, urgência).
- Logo prompt: circular, professional, modern, vector style.
- Banner prompt: cinematic, 2560x1440, mood específico do nicho, SEGURO PARA SAFE-AREA do YouTube (elementos importantes centralizados, sem detalhes cruciais nas bordas).

REGRAS CRÍTICAS PARA THUMBNAIL PROMPTS (siga TODAS):
Você está criando thumbnails CINEMATOGRÁFICOS estilo Hollywood — NUNCA fotos genéricas. Cada thumbnail deve ter MÚLTIPLAS CAMADAS visuais:

1. **CAMADA DE FUNDO (background plate)**: cena ampla cinematográfica relacionada ao tema (paisagem épica, ruínas, batalha, cosmos, laboratório, etc.) com lighting dramático (god rays, golden hour, fogo, neblina volumétrica).
2. **CAMADA DE PERSONAGEM (hero subject)**: figura humana em primeiro plano (3/4 view ou perfil), grande, ocupando 30-50% do frame, com expressão intensa OU pose de poder. NÃO centralizado — deslocado pra um lado pra deixar espaço pro título.
3. **CAMADA DE TÍTULO (text overlay)**: texto MASSIVO em FONTE SERIFADA CLÁSSICA (estilo Trajan, Cinzel, Optimus Princeps) ou FONTE SANS BOLD CONDENSED com 2-3 palavras MÁXIMO, ocupando o lado oposto do personagem. Cor: branco com glow dourado/vermelho OU dourado metálico com sombra preta forte.
4. **CAMADA DE EFEITOS**: partículas de luz, fagulhas, poeira volumétrica, lens flares sutis, vinheta nas bordas, color grading cinematográfico (teal & orange / dourado quente / azul frio).

NUNCA inclua: logo do canal, watermark, selo "4K", "ULTRA HD", badges de qualidade, marcas d'água, ou qualquer elemento de branding. A imagem deve ser LIMPA — só fundo + personagem + título + efeitos.

PALAVRAS-CHAVE OBRIGATÓRIAS NO PROMPT (use a maioria): "cinematic movie poster", "dramatic volumetric lighting", "8k ultra detailed", "epic composition", "rule of thirds", "shallow depth of field", "color grading", "film grain", "hyperrealistic", "atmospheric", "moody lighting", "professional photography", "sharp focus on subject", "blurred cinematic background".

ESTILO DE REFERÊNCIA: pense em pôster de filme histórico premium (estilo "Gladiator", "300", "Vikings", "House of the Dragon"). NÃO use clichês de YouTube como "shocked face emoji", "red arrows", "circles", "MrBeast style" — esse mockup deve parecer um TRAILER DE CINEMA, não um vídeo viral genérico.

ADAPTE o tema visual ao nicho: nicho histórico → ruínas + togas + ouro; nicho de mistério → névoa + sombras + frio; nicho de tecnologia → neon + circuitos + ciano; nicho bíblico → desertos + raios divinos + texturas de pergaminho. Use as cores primárias do canal no color grading.

OUTPUT: APENAS JSON válido. Sem markdown, sem ```, sem comentários, sem preâmbulo. Comece direto com { e termine com }."""


_USER_TEMPLATE = """Crie a identidade completa de um canal YouTube SUPERIOR para o nicho abaixo.

═══ NICHO ALVO ═══
Nome do nicho: {niche_name}
Idioma do canal (TODOS os textos públicos devem estar neste idioma): {language}
País alvo: {country}
Estilo de produção: {style}

═══ CONTEXTO DO PROJETO (do SOP) ═══
{sop_excerpt}

═══ TÍTULOS SEMENTES (use EXATAMENTE estes 4 títulos, traduzindo culturalmente pra {language} se necessário) ═══
{seed_titles_block}

═══ TAREFA ═══
Gere a identidade completa do canal. SUPERE qualquer concorrente típico do nicho. Lembre:
1. Nome memorável e único no idioma {language} (sem clichês "Top 10", "Daily", "Channel")
2. Tagline curta e impactante NO IDIOMA {language}
3. Descrição rica de ~200 palavras NO IDIOMA {language} que conecte emocionalmente
4. Os 4 títulos de vídeo são FIXOS — use os títulos sementes acima (traduzidos pra {language} se necessário). Crie thumbnail_prompt CINEMATOGRÁFICO específico pra cada um.
5. Tags YouTube (10-15) e hashtags (8-10) NO IDIOMA {language}, otimizados pra SEO no país {country}
6. Disclaimer CURTO no idioma {language} avisando que o canal é faceless e que conteúdo/visuais são RECONSTITUÍDOS por inteligência artificial pra fins informativos/educativos
7. whats_better/weaknesses_fixed/strategy_edge em PT-BR (são pro admin brasileiro ler)

OUTPUT JSON exato (preencha TODOS os campos):
{{
  "channel_name": "Nome ESTRATÉGICO, ORIGINAL e premium no idioma {language} (NÃO genérico — siga regras críticas no system prompt)",
  "tagline": "Slogan no idioma {language}",
  "description": "Descrição completa NO IDIOMA {language} (~200 palavras)",
  "disclaimer": "Aviso curto NO IDIOMA {language}: este canal é faceless e usa IA para reconstituir cenas/narrações com fins educativos. (~30-50 palavras)",
  "subscriber_estimate": "Estimativa realista de inscritos em 6 meses se o canal seguir o SOP perfeitamente (ex: '120K', '45K', '500K') — baseada em tamanho do nicho e força dos títulos sementes",
  "subscriber_estimate_12m": "Estimativa em 12 meses (ex: '450K', '1.2M')",
  "whats_better": "3 frases EM PT-BR explicando por que este canal é OBJETIVAMENTE superior aos concorrentes do nicho",
  "weaknesses_fixed": [
    "Fraqueza típica do nicho 1 — em PT-BR",
    "Fraqueza típica do nicho 2 — em PT-BR",
    "Fraqueza típica do nicho 3 — em PT-BR"
  ],
  "strategy_edge": "Em PT-BR: por que este canal cresce em 6 meses mais do que concorrentes",
  "logo_prompt": "English ImageFX prompt: square YouTube channel logo icon, [conceito específico do nicho], [cores], bold modern emblem design, fills the entire canvas edge-to-edge, NO white background, NO padding, NO whitespace borders, centered subject covering 95 percent of the frame, high contrast, premium vector style, 4k",
  "banner_prompt": "English ImageFX prompt: ultra-wide cinematic YouTube channel banner, aspect ratio 16:9, [conceito do nicho], [cores principais], dramatic volumetric lighting, atmospheric, epic horizontal scale, important elements centered in the safe area (middle 33 percent), no text on edges, fills the entire frame edge-to-edge with rich detail, 8k professional",
  "videos": [
    {{
      "title": "Título 1 — use o seed 1 traduzido culturalmente para {language}",
      "thumbnail_prompt": "English ImageFX prompt: cinematic movie poster style YouTube thumbnail 1280x720, [cena de fundo épica RELACIONADA AO TÍTULO acima], dramatic volumetric lighting with god rays, hero character on the right side (3/4 view, intense expression, period-accurate clothing), MASSIVE bold serif title text on the left side (2-3 words, white with golden glow and heavy black shadow), shallow depth of field, teal and orange color grading, film grain, hyperrealistic, sharp focus on hero, blurred atmospheric background, lens flare, dust particles, vignette, rule of thirds, 8k ultra detailed, epic composition, NO LOGO, NO WATERMARK, NO 4K BADGE, clean composition",
      "views_estimate": "500K",
      "duration": "12:45"
    }},
    {{
      "title": "Título 2 — use o seed 2 traduzido culturalmente para {language}",
      "thumbnail_prompt": "English ImageFX prompt for thumbnail 2 — DIFERENTE da thumb 1, RELACIONADO AO TÍTULO 2: variar ângulo, lighting, layout do título. Cinematic movie poster, volumetric lighting, hero subject, massive bold title text overlay, color grading, film grain, hyperrealistic, 8k, NO LOGO, NO WATERMARK, NO 4K BADGE.",
      "views_estimate": "350K",
      "duration": "10:22"
    }},
    {{
      "title": "Título 3 — use o seed 3 traduzido culturalmente para {language}",
      "thumbnail_prompt": "English ImageFX prompt for thumbnail 3 — DIFERENTE de 1 e 2, RELACIONADO AO TÍTULO 3: outro ângulo cinematográfico, outro mood, outro arranjo de título. Mantenha as 4 camadas (background plate, hero subject, massive serif title, atmospheric effects). Cinematic poster style, dramatic lighting, hyperrealistic, 8k, epic, NO LOGO, NO WATERMARK, NO 4K BADGE, clean.",
      "views_estimate": "420K",
      "duration": "14:30"
    }},
    {{
      "title": "Título 4 — use o seed 4 traduzido culturalmente para {language}",
      "thumbnail_prompt": "English ImageFX prompt for thumbnail 4 — DIFERENTE de 1, 2, 3, RELACIONADO AO TÍTULO 4. Mesmas 4 camadas. Cinematic movie poster, volumetric god rays, hero on one side, massive serif title on the other, teal/orange OR golden grading, film grain, lens flare, dust particles, vignette, hyperrealistic 8k, NO LOGO, NO WATERMARK, NO 4K BADGE, clean composition.",
      "views_estimate": "600K",
      "duration": "18:15"
    }}
  ],
  "colors": {{"primary": "#hex", "secondary": "#hex", "accent": "#hex"}},
  "fonts": "Sugestão de fontes (ex: Montserrat Bold + Inter Regular)",
  "keywords": ["palavra-chave 1 no idioma {language}", "...", "...10 palavras"],
  "tags": ["tag YouTube 1 no idioma {language}", "tag 2", "...", "12-15 tags otimizadas SEO"],
  "hashtags": ["#hashtag1 no idioma {language}", "#hashtag2", "...", "8-10 hashtags"]
}}"""


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        # remove first fence (with optional language tag)
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text[3:]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    return text


def _extract_json(text: str) -> dict:
    """Find first { and last } and parse. Raises ValueError if invalid."""
    text = _strip_code_fences(text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response has no JSON object")
    return json.loads(text[start : end + 1])


def _normalize(raw: dict, niche_name: str, language: str = "pt-BR") -> dict[str, Any]:
    """Coerce keys to snake_case + fill defaults so the UI never breaks."""
    out = {
        "channel_name": str(raw.get("channel_name") or raw.get("channelName") or niche_name)[:120],
        "tagline": str(raw.get("tagline") or "")[:200],
        "description": str(raw.get("description") or "")[:2500],
        "description_language": language,
        "disclaimer": str(raw.get("disclaimer") or "")[:600],
        "subscriber_estimate": str(raw.get("subscriber_estimate") or raw.get("subscriberEstimate") or "")[:30],
        "subscriber_estimate_12m": str(raw.get("subscriber_estimate_12m") or raw.get("subscriberEstimate12m") or "")[:30],
        "whats_better": str(raw.get("whats_better") or raw.get("whatsBetter") or "")[:800],
        "weaknesses_fixed": [],
        "strategy_edge": str(raw.get("strategy_edge") or raw.get("strategyEdge") or "")[:600],
        "logo_prompt": str(raw.get("logo_prompt") or raw.get("logoPrompt") or "")[:600],
        "banner_prompt": str(raw.get("banner_prompt") or raw.get("bannerPrompt") or "")[:600],
        "videos": [],
        "colors": {"primary": "#7c3aed", "secondary": "#1e293b", "accent": "#fbbf24"},
        "fonts": str(raw.get("fonts") or "Inter Bold + Inter Regular")[:200],
        "keywords": [],
        "tags": [],
        "hashtags": [],
        "language": language,
        "images": {},
    }

    wf = raw.get("weaknesses_fixed") or raw.get("weaknessesFixed") or []
    if isinstance(wf, list):
        out["weaknesses_fixed"] = [str(w)[:200] for w in wf[:6]]

    colors = raw.get("colors") or {}
    if isinstance(colors, dict):
        out["colors"] = {
            "primary": str(colors.get("primary") or out["colors"]["primary"])[:8],
            "secondary": str(colors.get("secondary") or out["colors"]["secondary"])[:8],
            "accent": str(colors.get("accent") or out["colors"]["accent"])[:8],
        }

    kws = raw.get("keywords") or []
    if isinstance(kws, list):
        out["keywords"] = [str(k)[:60] for k in kws[:15]]

    tags = raw.get("tags") or []
    if isinstance(tags, list):
        out["tags"] = [str(t).lstrip("#")[:60] for t in tags[:20]]

    hts = raw.get("hashtags") or []
    if isinstance(hts, list):
        out["hashtags"] = [
            ("#" + str(h).lstrip("#")[:50]) for h in hts[:15] if str(h).strip()
        ]

    # Fallback: if AI didn't return a disclaimer, build a minimal one in the target language
    if not out["disclaimer"]:
        out["disclaimer"] = _DEFAULT_DISCLAIMERS.get(
            language, _DEFAULT_DISCLAIMERS["en"]
        )

    videos = raw.get("videos") or []
    if isinstance(videos, list):
        for v in videos[:4]:
            if not isinstance(v, dict):
                continue
            out["videos"].append(
                {
                    "title": str(v.get("title") or "")[:120],
                    "thumbnail_prompt": str(
                        v.get("thumbnail_prompt") or v.get("thumbnailPrompt") or ""
                    )[:600],
                    "views_estimate": str(v.get("views_estimate") or v.get("views") or "")[:30],
                    "duration": str(v.get("duration") or "12:00")[:10],
                }
            )

    # ensure 4 video slots so the YouTube preview grid always renders
    while len(out["videos"]) < 4:
        out["videos"].append(
            {
                "title": f"Vídeo {len(out['videos']) + 1} (gerado parcialmente)",
                "thumbnail_prompt": "",
                "views_estimate": "",
                "duration": "12:00",
            }
        )

    return out


def generate_channel_mockup(
    niche_name: str,
    sop_excerpt: str = "",
    language: str = "pt-BR",
    country: str = "BR",
    style: str = "faceless",
    seed_titles: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generate a full channel mockup for a niche. Returns a normalized dict
    safe to render. Raises Exception if AI fails or returns garbage.

    seed_titles: optional 4 SOP-derived titles to anchor the mockup. The AI
    will translate them culturally to the target language and build matching
    cinematic thumbnails.
    """
    from protocols.ai_client import chat

    seeds = [t.strip() for t in (seed_titles or []) if t and t.strip()][:4]
    if seeds:
        seed_titles_block = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(seeds))
    else:
        seed_titles_block = "(sem títulos sementes — crie 4 títulos virais novos no idioma alvo)"

    user_prompt = _USER_TEMPLATE.format(
        niche_name=niche_name or "(nicho não nomeado)",
        language=language or "pt-BR",
        country=country or "BR",
        style=style or "faceless",
        sop_excerpt=(sop_excerpt or "(SOP não disponível — gere baseado apenas no nome do nicho)")[:3000],
        seed_titles_block=seed_titles_block,
    )

    response = chat(
        prompt=user_prompt,
        system=_SYSTEM_PROMPT,
        max_tokens=5500,
        temperature=0.7,
        timeout=200,
    )

    if not response or not response.strip():
        raise RuntimeError("AI retornou resposta vazia")

    try:
        raw = _extract_json(response)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"channel_mockup: JSON parse failed ({e}). Raw start: {response[:200]}")
        raise RuntimeError(f"AI retornou JSON inválido: {e}")

    if not isinstance(raw, dict):
        raise RuntimeError("AI retornou estrutura inválida (esperado objeto JSON)")

    return _normalize(raw, niche_name, language or "pt-BR")
