"""
Idea Bender Protocol - Takes a validated idea and generates N variations.

Mode A (internal): bend an idea already in the database (uses project SOP as context).
Mode B (external): bend an external YouTube video (fetches metadata first).

Returns structured JSON with variations that preserve the success DNA
but change the angle/theme/aesthetic.
"""

import json
import logging
import re
from typing import Optional

from protocols.ai_client import chat

logger = logging.getLogger("ytcloner.idea_bender")


BENDER_SYSTEM_PROMPT = """Voce e um estrategista de canais YouTube especialista em Idea Bending — a arte de pegar uma ideia/titulo que JA funcionou (views comprovadas) e criar variacoes que preservam o DNA do sucesso mas trocam o angulo/tema/estetica.

Seu trabalho: analisar por que a ideia original funcionou e gerar N variacoes ELEVADAS que mantenham o formato-que-funciona mas ataquem novos nichos/audiencias.

Princípio central: FIXO vs VARIAVEL
- FIXO (nunca mudar): estrutura narrativa, formato de hook, pacing, padrao de titulo, emotional driver, padrao de retencao
- VARIAVEL (troca): tema, personagem, estetica, ambientacao, angulo cultural

Retorne SEMPRE um JSON valido — sem markdown, sem comentarios, sem texto fora do JSON."""


BENDER_USER_TEMPLATE = """Analise a ideia abaixo e gere {num_variations} variacoes dobradas.

## IDEIA ORIGINAL
**Titulo:** {title}
**Nicho original:** {niche}
**Idioma:** {language}
{extra_context}

## CONTEXTO DO CANAL (SOP)
{sop_excerpt}

## TAREFA

Passo 1: Extraia o DNA do sucesso (por que essa ideia funciona)
Passo 2: Identifique o FIXO (nao pode mudar) vs VARIAVEL (pode trocar)
Passo 3: Gere {num_variations} variacoes com angulos/temas diferentes mas preservando o FIXO

Retorne este JSON exato:

{{
  "dna": {{
    "hook_pattern": "descricao do padrao de hook que funcionou",
    "title_formula": "formula do titulo (ex: '[Baby Animal] + [Action] + [Seeking Help]')",
    "emotional_driver": "qual gatilho emocional (empatia, curiosidade, medo, poder, etc)",
    "structure": "estrutura narrativa em 1 linha",
    "target_audience": "quem assiste e por que",
    "why_it_worked": "2-3 frases explicando o sucesso"
  }},
  "fixed_elements": ["elemento 1", "elemento 2", "elemento 3"],
  "variable_elements": ["elemento 1", "elemento 2", "elemento 3"],
  "variations": [
    {{
      "title": "Titulo novo seguindo a formula",
      "angle": "Qual o novo angulo/tema",
      "preserved_dna": "O que foi mantido do original",
      "changed_elements": "O que mudou",
      "new_niche_suggestion": "Nome do novo nicho/canal",
      "potential_score": 85,
      "reasoning": "Por que vai funcionar (2-3 frases)",
      "visual_style": "Sugestao de estilo visual",
      "target_audience": "Novo publico-alvo",
      "example_pillars": ["Pilar 1", "Pilar 2", "Pilar 3"]
    }}
  ]
}}

REGRAS:
- Score 0-100 (realista: 60-95 range)
- As {num_variations} variacoes devem ser BEM diferentes entre si
- Pelo menos 1 variacao em RPM alto (finanças, tech, educacao)
- Pelo menos 1 variacao facil de produzir (sem 3D complexo)
- Titulos na mesma LINGUA do original ({language})
- Preserve a formula — nao invente estruturas novas"""


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from AI response (handles markdown code blocks)."""
    if not text:
        return None
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding the first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def bend_idea(
    title: str,
    sop: str,
    niche: str = "",
    language: str = "en",
    num_variations: int = 5,
    extra_context: str = "",
) -> dict:
    """
    Generate N bent variations of a validated idea.

    Args:
        title: Original idea title (the "winning" one)
        sop: Project SOP content (context about the channel DNA)
        niche: Original niche name
        language: Target language for generated titles
        num_variations: How many variations to generate (3-10)
        extra_context: Optional extra info (views, engagement, etc)

    Returns:
        dict with keys: dna, fixed_elements, variable_elements, variations
        On failure: returns dict with error key.
    """
    if not title or not title.strip():
        return {"error": "Title is required"}

    num_variations = max(3, min(num_variations, 10))
    sop_excerpt = (sop or "")[:6000]  # limit context size

    prompt = BENDER_USER_TEMPLATE.format(
        title=title.strip(),
        niche=niche or "Unknown",
        language=language or "en",
        sop_excerpt=sop_excerpt or "(no SOP available)",
        num_variations=num_variations,
        extra_context=f"\n**Extra context:** {extra_context}" if extra_context else "",
    )

    logger.info(f"[IDEA_BENDER] Bending idea: {title[:60]}... ({num_variations} variations)")

    try:
        response = chat(
            prompt=prompt,
            system=BENDER_SYSTEM_PROMPT,
            max_tokens=8000,
            temperature=0.8,
            timeout=180,
        )
    except Exception as e:
        logger.error(f"[IDEA_BENDER] AI call failed: {e}")
        return {"error": f"AI request failed: {str(e)[:200]}"}

    parsed = _extract_json(response)
    if not parsed:
        logger.error(f"[IDEA_BENDER] Could not parse JSON from response: {response[:300]}")
        return {"error": "AI returned invalid JSON", "raw": response[:1000]}

    # Validate shape
    if "variations" not in parsed or not isinstance(parsed.get("variations"), list):
        return {"error": "Response missing 'variations' list", "raw": parsed}

    # Ensure each variation has required fields
    for i, v in enumerate(parsed["variations"]):
        v.setdefault("title", f"Variation {i+1}")
        v.setdefault("angle", "")
        v.setdefault("preserved_dna", "")
        v.setdefault("changed_elements", "")
        v.setdefault("new_niche_suggestion", "")
        v.setdefault("potential_score", 70)
        v.setdefault("reasoning", "")
        v.setdefault("visual_style", "")
        v.setdefault("target_audience", "")
        v.setdefault("example_pillars", [])
        # Clamp score
        try:
            v["potential_score"] = max(0, min(100, int(v["potential_score"])))
        except (ValueError, TypeError):
            v["potential_score"] = 70

    parsed.setdefault("dna", {})
    parsed.setdefault("fixed_elements", [])
    parsed.setdefault("variable_elements", [])

    logger.info(f"[IDEA_BENDER] Generated {len(parsed['variations'])} variations successfully")
    return parsed


def fetch_youtube_metadata(url: str) -> dict:
    """
    Fetch basic metadata from a YouTube URL using yt-dlp.
    Returns title, views, duration, description, channel.
    """
    try:
        import subprocess

        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-warnings", "--no-playlist", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"error": f"yt-dlp failed: {result.stderr[:200]}"}
        data = json.loads(result.stdout)
        return {
            "title": data.get("title", ""),
            "views": data.get("view_count", 0),
            "duration_sec": data.get("duration", 0),
            "description": (data.get("description") or "")[:2000],
            "channel": data.get("channel", ""),
            "uploader": data.get("uploader", ""),
            "like_count": data.get("like_count", 0),
            "comment_count": data.get("comment_count", 0),
            "upload_date": data.get("upload_date", ""),
            "thumbnail": data.get("thumbnail", ""),
            "webpage_url": data.get("webpage_url", url),
        }
    except subprocess.TimeoutExpired:
        return {"error": "yt-dlp timeout (60s)"}
    except FileNotFoundError:
        return {"error": "yt-dlp not installed on server"}
    except Exception as e:
        logger.error(f"[IDEA_BENDER] fetch_youtube_metadata failed: {e}")
        return {"error": f"Metadata fetch failed: {str(e)[:200]}"}
