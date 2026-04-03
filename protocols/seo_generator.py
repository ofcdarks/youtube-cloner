"""
SEO Generator - Gera SEO completo para cada vídeo.
Títulos A/B, descrições otimizadas, tags, hashtags, timestamps.
"""

import json
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate_seo_for_video(video_num: int, title: str, hook: str, summary: str, niche: str, pillar: str) -> dict:
    """Gera pacote SEO completo para um vídeo."""

    # Variações de título (A/B testing)
    titles = _generate_title_variants(title)

    # Descrição otimizada
    description = _generate_description(title, hook, summary, niche)

    # Tags
    tags = _generate_tags(title, niche, pillar)

    # Hashtags
    hashtags = _generate_hashtags(niche, pillar)

    # Timestamps sugeridos
    timestamps = _generate_timestamps()

    # Prompt de thumbnail
    thumbnail_prompt = _generate_thumbnail_prompt(title, niche)

    return {
        "video_num": video_num,
        "titles": titles,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "timestamps": timestamps,
        "thumbnail_prompt": thumbnail_prompt,
    }


def _generate_title_variants(original: str) -> list[str]:
    """Gera 5 variações de título para A/B testing."""
    base = original.replace("O ", "").replace("A ", "").replace("Como ", "")

    variants = [
        original,
        f"COMO {base}",
        f"{original} (Historia Real)",
        f"{original} | E Ninguem Percebeu",
        f"A Historia Insana: {base}",
    ]
    return variants


def _generate_description(title: str, hook: str, summary: str, niche: str) -> str:
    """Gera descrição otimizada para YouTube SEO."""
    return f"""{hook}

Neste video, voce vai descobrir a historia real de {title.lower()}. Uma historia que parece impossivel, mas aconteceu de verdade.

===================================
TIMESTAMPS:
0:00 - Introducao
0:30 - O que aconteceu
2:30 - Como foi possivel
5:00 - A descoberta
7:00 - As consequencias
9:00 - O que aprendemos

===================================
SOBRE O CANAL:
System Breakers conta historias reais de pessoas que encontraram falhas, glitches e brechas em sistemas que ninguem acreditava serem vulneraveis. De bugs que valeram milhoes a brechas legais que mudaram industrias inteiras.

Se inscreva e ative o sininho para nao perder nenhuma historia!

===================================
TAGS:
#{niche.replace(' ', '')} #systembreakers #historiareal #glitch #brecha #hack #exploits

===================================
FONTES E REFERENCIAS:
[Adicionar fontes apos pesquisa]

===================================
Business: systembreakers@email.com
"""


def _generate_tags(title: str, niche: str, pillar: str) -> list[str]:
    """Gera lista de tags SEO."""
    base_tags = [
        "system breakers", "historia real", "glitch", "brecha",
        "hack", "exploit", "bug", "falha no sistema",
        "como hackear", "fraude", "dinheiro", "milhoes",
    ]

    niche_tags = {
        "Bugs Tech": ["bug", "programacao", "codigo", "software", "ethereum", "crypto", "tecnologia", "hacker"],
        "Exploits Financeiros": ["banco", "financas", "wall street", "fraude financeira", "dinheiro facil", "investimento"],
        "Glitches Legais": ["brecha legal", "lei", "contrato", "direito", "loophole", "milhas aereas"],
        "Fraudes Geniais": ["fraude", "golpe", "esquema", "crime", "true crime", "casino", "las vegas"],
        "Engenharia Social": ["engenharia social", "manipulacao", "psicologia", "persuasao", "hack social"],
    }

    # Extract keywords from title
    title_words = [w.lower() for w in title.split() if len(w) > 3]

    tags = base_tags + niche_tags.get(pillar, []) + title_words[:5]
    return list(dict.fromkeys(tags))[:30]  # Max 30, no duplicates


def _generate_hashtags(niche: str, pillar: str) -> list[str]:
    """Gera hashtags para a descrição."""
    return [
        "#SystemBreakers", "#HistoriaReal", "#Glitch",
        "#HackDoSistema", "#Exploit", "#BrechaLegal",
        "#TrueCrime", "#Milhoes", "#BugReport",
        f"#{pillar.replace(' ', '')}", "#Shorts", "#YouTube"
    ]


def _generate_timestamps() -> list[str]:
    """Template de timestamps."""
    return [
        "0:00 - Hook / Introducao",
        "0:30 - Contexto",
        "2:30 - A Descoberta",
        "4:30 - O Plano / A Execucao",
        "6:30 - A Reacao / O Caos",
        "8:00 - Climax",
        "9:30 - O Que Aconteceu Depois",
        "10:30 - Licao / CTA",
    ]


def _generate_thumbnail_prompt(title: str, niche: str) -> str:
    """Gera prompt para criar thumbnail com IA."""
    return f"""YouTube thumbnail, clickbait style, dark dramatic background.
Low poly 3D style illustration related to: {title}.
Big bold yellow/white text overlay saying a shocking number or key phrase.
Red and cyan accent colors. Shocked expression on low poly character face.
Dark vignette. High contrast. 1280x720 resolution.
Style: cinematic, dramatic lighting, professional YouTube thumbnail."""


def generate_seo_pack(ideas_data: list[dict], project_name: str = "System Breakers") -> str:
    """Gera pacote SEO completo para todas as ideias."""
    output = f"# SEO PACK - {project_name}\n"
    output += f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    for idea in ideas_data:
        seo = generate_seo_for_video(
            video_num=idea.get("num", 0),
            title=idea.get("title", ""),
            hook=idea.get("hook", ""),
            summary=idea.get("summary", ""),
            niche=idea.get("niche", project_name),
            pillar=idea.get("pillar", ""),
        )

        output += f"\n{'='*70}\n"
        output += f"## VIDEO {seo['video_num']}: {idea['title']}\n"
        output += f"{'='*70}\n\n"

        output += "### Titulos (A/B Testing):\n"
        for i, t in enumerate(seo["titles"], 1):
            output += f"  {i}. {t}\n"

        output += f"\n### Tags ({len(seo['tags'])}):\n"
        output += ", ".join(seo["tags"]) + "\n"

        output += f"\n### Hashtags:\n"
        output += " ".join(seo["hashtags"]) + "\n"

        output += f"\n### Thumbnail Prompt:\n{seo['thumbnail_prompt']}\n"

        output += f"\n### Descricao:\n{seo['description']}\n"

    return output
