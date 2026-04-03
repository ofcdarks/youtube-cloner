"""
Creative Prompts Generator
Gera prompts para musica de fundo (Suno/Udio), teasers e thumbnails.
"""

from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ── MUSIC PROMPTS ─────────────────────────────────────────

MUSIC_STYLES = {
    "tension_build": {
        "name": "Tensao Crescente",
        "use": "Para momentos de build-up antes de revelacoes",
        "suno": "dark cinematic tension, building suspense, deep bass, electronic pulses, mysterious synths, no vocals, film score style, 120bpm",
        "udio": "cinematic tension builder, dark electronic, pulsing bass, mysterious atmosphere, Hans Zimmer style, instrumental only",
        "musicgpt": "Create a dark cinematic tension track with deep bass pulses, mysterious synth layers, building suspense. No vocals. 120 BPM. Film score quality.",
    },
    "reveal": {
        "name": "Revelacao / Plot Twist",
        "use": "Para momentos de revelacao ou plot twist",
        "suno": "epic cinematic reveal, dramatic orchestra hit, tension release, powerful brass, electronic bass drop, film score climax, no vocals",
        "udio": "dramatic reveal moment, orchestral hit with electronic bass drop, cinematic climax, powerful and shocking, instrumental",
        "musicgpt": "Create a dramatic cinematic reveal moment - starts quiet then hits with powerful orchestral brass and electronic bass drop. Shocking and impactful. No vocals.",
    },
    "investigation": {
        "name": "Investigacao / Mistério",
        "use": "Para partes de contexto e investigacao",
        "suno": "detective noir, mysterious piano, dark ambient, subtle electronic beats, investigation theme, lo-fi cinematic, no vocals, 90bpm",
        "udio": "mysterious investigation theme, noir piano, dark ambient textures, subtle beats, documentary style, instrumental",
        "musicgpt": "Create a mysterious investigation theme with noir piano, dark ambient textures, and subtle electronic beats. Documentary style. No vocals. 90 BPM.",
    },
    "hook_intro": {
        "name": "Hook / Intro",
        "use": "Para os primeiros 30 segundos do video",
        "suno": "intense cinematic intro, dark electronic, glitch effects, powerful bass, attention grabbing, short stinger, no vocals, 130bpm",
        "udio": "intense opening stinger, dark electronic glitch, powerful cinematic bass, attention-grabbing intro, 10-15 seconds, instrumental",
        "musicgpt": "Create an intense 15-second opening stinger with dark electronic glitch effects, powerful bass hit, and cinematic tension. Grabs attention immediately. No vocals.",
    },
    "aftermath": {
        "name": "Aftermath / Consequencias",
        "use": "Para a resolucao e consequencias da historia",
        "suno": "melancholic piano, reflective ambient, soft strings, documentary conclusion, emotional resolution, no vocals, 80bpm",
        "udio": "reflective aftermath theme, melancholic piano with soft strings, documentary conclusion, emotional but restrained, instrumental",
        "musicgpt": "Create a reflective aftermath theme with melancholic piano, soft strings, and ambient textures. Emotional conclusion feel. No vocals. 80 BPM.",
    },
    "chaos": {
        "name": "Caos / Urgencia",
        "use": "Para momentos de panico e urgencia",
        "suno": "chaotic electronic, urgent drums, alarm sounds, fast tempo, cyberpunk chase, glitch bass, no vocals, 150bpm",
        "udio": "urgent chaotic electronic, fast cyberpunk drums, alarm tones, panic atmosphere, chase scene energy, instrumental",
        "musicgpt": "Create an urgent chaotic track with fast electronic drums, alarm-like synths, and cyberpunk bass. Panic and urgency feeling. No vocals. 150 BPM.",
    },
    "background_ambient": {
        "name": "Background Ambient",
        "use": "Musica de fundo continua durante narracao",
        "suno": "dark ambient background, subtle electronic, low key mysterious, gentle pulse, perfect for narration, not distracting, no vocals, 100bpm",
        "udio": "subtle dark ambient background, gentle electronic pulse, non-distracting, perfect under narration, mysterious mood, instrumental",
        "musicgpt": "Create a subtle dark ambient background track with gentle electronic pulses. Should sit perfectly under narration without being distracting. Mysterious mood. No vocals. 100 BPM.",
    },
}


def generate_music_pack(project_name: str = "System Breakers") -> str:
    """Gera pacote completo de prompts de musica."""
    output = f"# MUSIC PROMPTS PACK - {project_name}\n"
    output += f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    output += "\nPrompts prontos para Suno AI, Udio, e MusicGPT.\n"
    output += "Use cada estilo no momento certo do video conforme indicado.\n\n"

    for key, style in MUSIC_STYLES.items():
        output += f"{'='*60}\n"
        output += f"## {style['name']}\n"
        output += f"**Quando usar:** {style['use']}\n\n"
        output += f"### Suno AI:\n```\n{style['suno']}\n```\n\n"
        output += f"### Udio:\n```\n{style['udio']}\n```\n\n"
        output += f"### MusicGPT:\n```\n{style['musicgpt']}\n```\n\n"

    # Guia de uso por momento do roteiro
    output += f"\n{'='*60}\n"
    output += "## GUIA: Qual musica usar em cada parte do roteiro\n\n"
    output += "| Momento do Video | Estilo de Musica | Duracao |\n"
    output += "|---|---|---|\n"
    output += "| 0:00 - 0:30 (Hook) | Hook / Intro | 15-30s |\n"
    output += "| 0:30 - 2:30 (Contexto) | Investigacao / Misterio | 2 min |\n"
    output += "| 2:30 - 4:30 (Ato 1) | Background Ambient | 2 min |\n"
    output += "| 4:30 - 6:30 (Ato 2) | Tensao Crescente | 2 min |\n"
    output += "| 6:30 - 8:00 (Ato 3) | Caos / Urgencia | 1.5 min |\n"
    output += "| 8:00 - 9:30 (Climax) | Revelacao / Plot Twist | 1.5 min |\n"
    output += "| 9:30 - 11:00 (Resolucao) | Aftermath / Consequencias | 1.5 min |\n"

    return output


# ── TEASER PROMPTS ────────────────────────────────────────

def generate_teaser_prompts(ideas: list[dict], project_name: str = "System Breakers") -> str:
    """Gera prompts de teaser/trailer para cada video."""
    output = f"# TEASER PROMPTS - {project_name}\n"
    output += f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    output += "\nPrompts para gerar teasers de 15-30s para Shorts/Reels/TikTok.\n\n"

    for idea in ideas[:15]:  # Top 15
        num = idea.get("num", "?")
        title = idea.get("title", "")
        hook = idea.get("hook", "")

        output += f"{'='*60}\n"
        output += f"## Teaser {num}: {title}\n\n"

        # Script do teaser
        output += f"### Roteiro do Teaser (15s):\n"
        output += f'"{hook[:150]}..."\n'
        output += f'"Link do video completo na bio."\n\n'

        # Prompt de video IA
        output += f"### Prompt para Video IA (Runway/Kling/Pika):\n"
        output += f"```\nCinematic low poly 3D animation. Dark moody atmosphere. "
        output += f"Scene related to: {title}. "
        output += f"Camera slowly zooming in. Dramatic lighting with cyan and purple accents. "
        output += f"Glitch effects. Text overlay space at top. "
        output += f"15 seconds, 1080x1920 vertical format.\n```\n\n"

        # Prompt de narração
        output += f"### Prompt de Narracao (ElevenLabs/PlayHT):\n"
        output += f"```\nVoz: masculina, grave, dramatica, estilo documentario.\n"
        output += f"Tom: misterioso, com pausas dramaticas.\n"
        output += f"Texto: \"{hook[:200]}\"\n```\n\n"

        # Prompt de thumbnail do teaser
        output += f"### Thumbnail do Short:\n"
        output += f"```\nVertical YouTube Short thumbnail. Bold red/yellow text: key number or phrase from title. "
        output += f"Low poly 3D character with shocked expression. Dark background with glitch effects. "
        output += f"1080x1920. High contrast.\n```\n\n"

    return output


# ── THUMBNAIL PROMPTS ─────────────────────────────────────

def generate_thumbnail_prompts(ideas: list[dict], project_name: str = "System Breakers") -> str:
    """Gera prompts detalhados de thumbnail para cada video."""
    output = f"# THUMBNAIL PROMPTS - {project_name}\n"
    output += f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    for idea in ideas[:15]:
        num = idea.get("num", "?")
        title = idea.get("title", "")

        # Extract key number/phrase for thumbnail text
        import re
        numbers = re.findall(r'\$[\d,.]+\s*(?:milhoes|bilhoes|trilhao|M|B|K)?', title, re.IGNORECASE)
        key_phrase = numbers[0] if numbers else title.split("que")[0].strip() if "que" in title else title[:30]

        output += f"## Thumbnail {num}: {title}\n\n"

        output += f"### Midjourney / DALL-E:\n"
        output += f"```\nYouTube thumbnail, 1280x720, cinematic low poly 3D style.\n"
        output += f"Scene: dramatic visualization of \"{title}\".\n"
        output += f"Big bold text overlay: \"{key_phrase}\".\n"
        output += f"Colors: dark background, cyan and red accents, dramatic lighting.\n"
        output += f"Low poly character with shocked/intense expression.\n"
        output += f"Professional clickbait style. High contrast. Vignette effect.\n```\n\n"

        output += f"### Canva/Photoshop Notes:\n"
        output += f"- Texto principal: \"{key_phrase}\" (amarelo bold, outline preto)\n"
        output += f"- Subtexto: frase de impacto em branco\n"
        output += f"- Background: dark gradient + low poly scene\n"
        output += f"- Setas/circulos vermelhos apontando para elemento chave\n\n"

    return output
