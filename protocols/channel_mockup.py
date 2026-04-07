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


_SYSTEM_PROMPT = """Você é um DIRETOR CRIATIVO de canais YouTube de elite. Sua missão é, dado um nicho e contexto, criar a IDENTIDADE COMPLETA de um canal MUITO SUPERIOR aos concorrentes existentes naquele nicho.

REGRA CRÍTICA DE IDIOMA:
- "tagline", "description", "whats_better", "weaknesses_fixed", "strategy_edge" → SEMPRE em PORTUGUÊS DO BRASIL (PT-BR), o usuário é brasileiro.
- "channel_name" e os "title" dos vídeos → no idioma alvo do canal (definido por language).
- "logo_prompt", "banner_prompt", "thumbnail_prompt" → SEMPRE em INGLÊS (são prompts pra ImageFX/Imagen).
- "keywords" → no idioma alvo do canal.
- NUNCA escreva explicações em inglês fora dos prompts de imagem.

REGRAS DE QUALIDADE:
- Não copie nomes genéricos. Crie nomes ORIGINAIS e memoráveis.
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
Idioma do canal: {language}
País alvo: {country}
Estilo de produção: {style}

═══ CONTEXTO DO PROJETO (do SOP) ═══
{sop_excerpt}

═══ TAREFA ═══
Gere a identidade completa do canal. SUPERE qualquer concorrente típico do nicho. Pense em:
1. Um nome memorável e único (não use clichês como "Top 10", "Daily", "Channel")
2. Tagline curta e impactante (em PT-BR)
3. Descrição rica de ~200 palavras (em PT-BR) que conecte emocionalmente
4. 4 títulos de vídeo VIRAIS com thumbnail prompts visuais
5. Identidade visual coerente (cores, fontes, conceito de logo e banner)
6. Por que este canal vai DOMINAR (em PT-BR, com estratégia clara)

OUTPUT JSON exato (preencha TODOS os campos):
{{
  "channel_name": "Nome criativo e original no idioma {language}",
  "tagline": "Slogan curto e impactante em PT-BR",
  "description": "Descrição completa em PT-BR (~200 palavras) explicando proposta, valor único, e quem é o público-alvo",
  "whats_better": "3 frases em PT-BR explicando por que este canal é OBJETIVAMENTE superior aos concorrentes do nicho",
  "weaknesses_fixed": [
    "Fraqueza típica do nicho 1 — em PT-BR",
    "Fraqueza típica do nicho 2 — em PT-BR",
    "Fraqueza típica do nicho 3 — em PT-BR"
  ],
  "strategy_edge": "Em PT-BR: por que este canal cresce em 6 meses mais do que concorrentes",
  "logo_prompt": "English ImageFX prompt: circular logo, professional vector style, [conceito específico do nicho], [cores], modern minimal, high contrast, 4k",
  "banner_prompt": "English ImageFX prompt: cinematic YouTube channel banner 2560x1440, ultra-wide composition, [conceito do nicho], [cores principais], dramatic volumetric lighting, atmospheric, epic scale, important elements centered (YouTube safe area), no text on edges, 8k professional",
  "videos": [
    {{
      "title": "Título 1 viral no idioma {language}",
      "thumbnail_prompt": "English ImageFX prompt: cinematic movie poster style YouTube thumbnail 1280x720, [cena de fundo épica relacionada ao tema], dramatic volumetric lighting with god rays, hero character on the right side (3/4 view, intense expression, period-accurate clothing), MASSIVE bold serif title text on the left side (2-3 words, white with golden glow and heavy black shadow), shallow depth of field, teal and orange color grading, film grain, hyperrealistic, sharp focus on hero, blurred atmospheric background, lens flare, dust particles, vignette, rule of thirds, 8k ultra detailed, epic composition, NO LOGO, NO WATERMARK, NO 4K BADGE, clean composition",
      "views_estimate": "500K",
      "duration": "12:45"
    }},
    {{
      "title": "Título 2 viral no idioma {language}",
      "thumbnail_prompt": "English ImageFX prompt for thumbnail 2 — DIFERENTE da thumb 1: variar ângulo (close-up extremo OU wide shot), variar lighting (golden hour OU blue hour OU firelight), variar layout do título (esquerda OU direita OU dividido em duas linhas grandes). Mesmo nível cinematográfico de camadas. Inclua: cinematic movie poster, volumetric lighting, hero subject, massive bold title text overlay, color grading, film grain, hyperrealistic, 8k, NO LOGO, NO WATERMARK, NO 4K BADGE.",
      "views_estimate": "350K",
      "duration": "10:22"
    }},
    {{
      "title": "Título 3 viral no idioma {language}",
      "thumbnail_prompt": "English ImageFX prompt for thumbnail 3 — DIFERENTE de 1 e 2: outro ângulo cinematográfico, outro mood, outro arranjo de título. Mantenha as 4 camadas (background plate, hero subject, massive serif title, atmospheric effects). Tema: [adapte ao título]. Inclua: cinematic poster style, dramatic lighting, hyperrealistic, 8k, epic, NO LOGO, NO WATERMARK, NO 4K BADGE, clean.",
      "views_estimate": "420K",
      "duration": "14:30"
    }},
    {{
      "title": "Título 4 viral no idioma {language}",
      "thumbnail_prompt": "English ImageFX prompt for thumbnail 4 — DIFERENTE de 1, 2, 3: novo conceito visual mantendo identidade do canal. Mesmas 4 camadas obrigatórias. Cinematic movie poster, volumetric god rays, hero on one side, massive serif title on the other, teal/orange OR golden grading, film grain, lens flare, dust particles, vignette, hyperrealistic 8k, NO LOGO, NO WATERMARK, NO 4K BADGE, clean composition.",
      "views_estimate": "600K",
      "duration": "18:15"
    }}
  ],
  "colors": {{"primary": "#hex", "secondary": "#hex", "accent": "#hex"}},
  "fonts": "Sugestão de fontes (ex: Montserrat Bold + Inter Regular)",
  "keywords": ["kw1 no idioma {language}", "kw2", "kw3", "kw4", "kw5"]
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


def _normalize(raw: dict, niche_name: str) -> dict[str, Any]:
    """Coerce keys to snake_case + fill defaults so the UI never breaks."""
    out = {
        "channel_name": str(raw.get("channel_name") or raw.get("channelName") or niche_name)[:120],
        "tagline": str(raw.get("tagline") or "")[:200],
        "description": str(raw.get("description") or "")[:2500],
        "whats_better": str(raw.get("whats_better") or raw.get("whatsBetter") or "")[:800],
        "weaknesses_fixed": [],
        "strategy_edge": str(raw.get("strategy_edge") or raw.get("strategyEdge") or "")[:600],
        "logo_prompt": str(raw.get("logo_prompt") or raw.get("logoPrompt") or "")[:600],
        "banner_prompt": str(raw.get("banner_prompt") or raw.get("bannerPrompt") or "")[:600],
        "videos": [],
        "colors": {"primary": "#7c3aed", "secondary": "#1e293b", "accent": "#fbbf24"},
        "fonts": str(raw.get("fonts") or "Inter Bold + Inter Regular")[:200],
        "keywords": [],
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
        out["keywords"] = [str(k)[:60] for k in kws[:10]]

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
) -> dict[str, Any]:
    """
    Generate a full channel mockup for a niche. Returns a normalized dict
    safe to render. Raises Exception if AI fails or returns garbage.
    """
    from protocols.ai_client import chat

    user_prompt = _USER_TEMPLATE.format(
        niche_name=niche_name or "(nicho não nomeado)",
        language=language or "pt-BR",
        country=country or "BR",
        style=style or "faceless",
        sop_excerpt=(sop_excerpt or "(SOP não disponível — gere baseado apenas no nome do nicho)")[:3000],
    )

    response = chat(
        prompt=user_prompt,
        system=_SYSTEM_PROMPT,
        max_tokens=5000,
        temperature=0.7,
        timeout=180,
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

    return _normalize(raw, niche_name)
