"""
Narration Export - Prepara textos limpos para ElevenLabs e configuracoes ideais.
Remove marcacoes de roteiro e gera arquivos prontos para TTS.
"""

import re
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ── ElevenLabs Config ────────────────────────────────────

ELEVENLABS_CONFIG = {
    "voice_recommendations": [
        {
            "name": "Adam",
            "voice_id": "pNInz6obpgDQGcFmaJgB",
            "style": "Narracao dramatica, voz grave masculina",
            "best_for": "Roteiros de storytelling intenso",
        },
        {
            "name": "Antoni",
            "voice_id": "ErXwobaYiN019PkySvjV",
            "style": "Narrativa calma mas envolvente",
            "best_for": "Contexto e explicacoes",
        },
        {
            "name": "Josh",
            "voice_id": "TxGEqnHWrfWFTfGW9XjX",
            "style": "Voz profunda e autoritaria",
            "best_for": "Documentarios e true crime",
        },
        {
            "name": "Daniel",
            "voice_id": "onwK4e9ZLuTAKqWW03F9",
            "style": "Britanico, serio e envolvente",
            "best_for": "Historias sofisticadas",
        },
    ],
    "settings": {
        "model": "eleven_multilingual_v2",
        "stability": 0.35,
        "similarity_boost": 0.75,
        "style": 0.45,
        "use_speaker_boost": True,
    },
    "settings_per_section": {
        "hook": {
            "stability": 0.25,
            "similarity_boost": 0.80,
            "style": 0.60,
            "speed": 1.05,
            "note": "Mais dramatico e intenso para prender atencao",
        },
        "contexto": {
            "stability": 0.45,
            "similarity_boost": 0.70,
            "style": 0.30,
            "speed": 0.95,
            "note": "Mais calmo e explicativo",
        },
        "desenvolvimento": {
            "stability": 0.35,
            "similarity_boost": 0.75,
            "style": 0.45,
            "speed": 1.00,
            "note": "Equilibrado com variacao natural",
        },
        "climax": {
            "stability": 0.20,
            "similarity_boost": 0.85,
            "style": 0.70,
            "speed": 1.10,
            "note": "Maximo drama e intensidade",
        },
        "resolucao": {
            "stability": 0.50,
            "similarity_boost": 0.70,
            "style": 0.25,
            "speed": 0.90,
            "note": "Reflexivo e conclusivo",
        },
    },
    "output_format": "mp3_44100_128",
    "tips": [
        "Use '...' para pausas curtas (0.5s)",
        "Use quebra de paragrafo para pausas medias (1s)",
        "Use '---' entre secoes para pausas longas (2s)",
        "Palavras em MAIUSCULAS recebem enfase natural",
        "Numeros por extenso soam melhor (duzentos milhoes, nao 200M)",
        "Frases curtas = mais dramatico. Frases longas = mais explicativo",
        "Teste com velocidade 1.0x primeiro, ajuste depois",
    ],
}


def clean_for_narration(script_content: str) -> str:
    """Remove marcacoes de roteiro e prepara texto limpo para TTS."""

    text = script_content

    # Remove headers markdown
    text = re.sub(r'^#{1,4}\s+.*$', '', text, flags=re.MULTILINE)

    # Remove marcacoes de roteiro entre colchetes mas mantém PAUSA DRAMATICA como ...
    text = re.sub(r'\[PAUSA DRAMAT?ICA[^\]]*\]', '...', text, flags=re.IGNORECASE)
    text = re.sub(r'\[B-ROLL[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[TRANSICAO[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[TRANSIÇÃO[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[OPEN LOOP\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[PATTERN INTERRUPT[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[SPECIFIC SPIKE[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[TELA FINAL[^\]]*\]', '', text, flags=re.IGNORECASE)

    # Remove qualquer outra marcacao entre colchetes
    text = re.sub(r'\[[^\]]*\]', '', text)

    # Remove linhas de metadados
    text = re.sub(r'^\*\*Canal:\*\*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*Duracao.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*Estilo.*$', '', text, flags=re.MULTILINE)

    # Remove bold/italic markdown
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)

    # Remove linhas de separadores
    text = re.sub(r'^-{3,}$', '\n', text, flags=re.MULTILINE)
    text = re.sub(r'^={3,}$', '', text, flags=re.MULTILINE)

    # Remove linhas com apenas (0:00 - 0:30) timestamps
    text = re.sub(r'^\s*\(\d+:\d+\s*-\s*\d+:\d+\)\s*$', '', text, flags=re.MULTILINE)

    # Remove aspas de dialogo para narracao mais natural
    # Mantém aspas em citacoes diretas curtas
    text = re.sub(r'^"([^"]{1,30})"$', r'\1', text, flags=re.MULTILINE)

    # Limpa espacos extras
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s+$', '', text, flags=re.MULTILINE)

    # Remove linhas vazias no inicio
    text = text.strip()

    return text


def split_into_sections(narration_text: str) -> list[dict]:
    """Divide a narracao em secoes para configuracoes diferentes no ElevenLabs."""

    sections = []
    current_section = {"type": "hook", "text": "", "order": 1}

    lines = narration_text.split('\n')
    word_count = 0

    for line in lines:
        words = len(line.split())
        word_count += words

        # Detectar mudanca de secao por contagem de palavras
        if word_count < 80:
            current_section["type"] = "hook"
        elif word_count < 350:
            if current_section["type"] == "hook" and current_section["text"]:
                sections.append(current_section)
                current_section = {"type": "contexto", "text": "", "order": 2}
        elif word_count < 900:
            if current_section["type"] == "contexto" and current_section["text"]:
                sections.append(current_section)
                current_section = {"type": "desenvolvimento", "text": "", "order": 3}
        elif word_count < 1300:
            if current_section["type"] == "desenvolvimento" and current_section["text"]:
                sections.append(current_section)
                current_section = {"type": "climax", "text": "", "order": 4}
        else:
            if current_section["type"] == "climax" and current_section["text"]:
                sections.append(current_section)
                current_section = {"type": "resolucao", "text": "", "order": 5}

        current_section["text"] += line + "\n"

    if current_section["text"]:
        sections.append(current_section)

    return sections


def generate_narration_pack(script_path: str, script_num: int = 1) -> dict:
    """Gera pacote completo de narracao para um roteiro."""

    content = Path(script_path).read_text(encoding="utf-8")

    # Texto limpo
    clean_text = clean_for_narration(content)

    # Dividir em secoes
    sections = split_into_sections(clean_text)

    # Contar palavras e estimar duracao
    word_count = len(clean_text.split())
    duration_estimate = word_count / 150  # ~150 palavras por minuto

    return {
        "script_num": script_num,
        "full_narration": clean_text,
        "sections": sections,
        "word_count": word_count,
        "duration_minutes": round(duration_estimate, 1),
        "config": ELEVENLABS_CONFIG,
    }


def export_narration_files(script_paths: list[str], project_name: str = "System Breakers"):
    """Exporta todos os arquivos de narracao."""

    output = f"# NARRACAO PACK - {project_name}\n"
    output += f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    output += f"Pronto para colar no ElevenLabs\n\n"

    # Config geral
    output += "=" * 60 + "\n"
    output += "## CONFIGURACOES ELEVENLABS\n"
    output += "=" * 60 + "\n\n"

    output += "### Vozes Recomendadas:\n"
    for v in ELEVENLABS_CONFIG["voice_recommendations"]:
        output += f"- **{v['name']}** ({v['voice_id']}): {v['style']} - {v['best_for']}\n"

    output += f"\n### Configuracao Base:\n"
    output += f"- Model: {ELEVENLABS_CONFIG['settings']['model']}\n"
    output += f"- Stability: {ELEVENLABS_CONFIG['settings']['stability']}\n"
    output += f"- Similarity Boost: {ELEVENLABS_CONFIG['settings']['similarity_boost']}\n"
    output += f"- Style: {ELEVENLABS_CONFIG['settings']['style']}\n"
    output += f"- Speaker Boost: ON\n"
    output += f"- Output: {ELEVENLABS_CONFIG['output_format']}\n"

    output += f"\n### Configuracao por Secao do Video:\n\n"
    output += "| Secao | Stability | Similarity | Style | Speed | Nota |\n"
    output += "|---|---|---|---|---|---|\n"
    for sec, cfg in ELEVENLABS_CONFIG["settings_per_section"].items():
        output += f"| {sec.title()} | {cfg['stability']} | {cfg['similarity_boost']} | {cfg['style']} | {cfg['speed']}x | {cfg['note']} |\n"

    output += "\n### Dicas:\n"
    for tip in ELEVENLABS_CONFIG["tips"]:
        output += f"- {tip}\n"

    # Narracoes
    for i, path in enumerate(script_paths, 1):
        if not Path(path).exists():
            continue

        pack = generate_narration_pack(path, i)

        output += f"\n\n{'=' * 60}\n"
        output += f"## ROTEIRO {i} - NARRACAO COMPLETA\n"
        output += f"Palavras: {pack['word_count']} | Duracao estimada: {pack['duration_minutes']} min\n"
        output += f"{'=' * 60}\n\n"

        # Texto completo (para colar direto no ElevenLabs)
        output += "### TEXTO COMPLETO (copie e cole no ElevenLabs):\n\n"
        output += "```\n"
        output += pack["full_narration"]
        output += "\n```\n\n"

        # Secoes individuais com configs
        output += "### SECOES INDIVIDUAIS (para ajuste fino):\n\n"
        for sec in pack["sections"]:
            cfg = ELEVENLABS_CONFIG["settings_per_section"].get(sec["type"], {})
            output += f"#### {sec['order']}. {sec['type'].upper()}\n"
            if cfg:
                output += f"Config: Stability={cfg.get('stability','-')} | Similarity={cfg.get('similarity_boost','-')} | Style={cfg.get('style','-')} | Speed={cfg.get('speed','-')}x\n\n"
            output += "```\n"
            output += sec["text"].strip()
            output += "\n```\n\n"

        # Arquivo individual limpo
        narr_path = OUTPUT_DIR / f"narration_roteiro_{i}.txt"
        narr_path.write_text(pack["full_narration"], encoding="utf-8")
        output += f"Arquivo limpo salvo: {narr_path.name}\n"

    return output


if __name__ == "__main__":
    scripts = [
        str(OUTPUT_DIR / "loaded_dice_roteiro_1.md"),
        str(OUTPUT_DIR / "loaded_dice_roteiro_2.md"),
        str(OUTPUT_DIR / "loaded_dice_roteiro_3.md"),
    ]

    result = export_narration_files(scripts, "System Breakers")

    out_path = OUTPUT_DIR / "loaded_dice_narration.md"
    out_path.write_text(result, encoding="utf-8")

    print(f"Narracao pack gerado: {out_path}")
    print(f"Arquivos individuais:")
    for i in range(1, 4):
        p = OUTPUT_DIR / f"narration_roteiro_{i}.txt"
        if p.exists():
            words = len(p.read_text(encoding="utf-8").split())
            print(f"  {p.name} - {words} palavras (~{words/150:.1f} min)")
