"""
Agent Builder — Generates niche-specific agents from BASE template + niche config.

Usage:
    python build_agent.py                              # Build all 16 agents (no visual style)
    python build_agent.py construcao                   # Build one specific agent
    python build_agent.py construcao --style cartoon_meme  # Build with visual style override
    python build_agent.py --style chibi_dark_tech      # Build ALL agents with a style
    python build_agent.py --list                       # List all available niches
    python build_agent.py --list-styles                # List all visual styles

Output: agent/niches/{niche_key}/AGENT_{NAME}_v2.0.md
        agent/niches/{niche_key}/AGENT_{NAME}_v2.0_{STYLE}.md  (when --style used)
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
AGENT_DIR = SCRIPT_DIR.parent
BASE_PATH = AGENT_DIR / "base" / "AGENT_BASE.md"
CONFIG_PATH = AGENT_DIR / "niches" / "niche_configs.json"
STYLES_PATH = AGENT_DIR / "styles" / "visual_styles.json"
OUTPUT_DIR = AGENT_DIR / "niches"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_base() -> str:
    with open(BASE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def load_styles() -> dict:
    if not STYLES_PATH.exists():
        return {}
    with open(STYLES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop("_meta", None)
    return data


def build_act_table(acts: list[dict]) -> str:
    lines = ["| Ato | Nome | % | Emoção |", "|-----|------|---|--------|"]
    symbols = ["1", "2", "3A", "\u26a1", "3B", "4", "5", "6", "7"]
    for i, act in enumerate(acts):
        sym = symbols[i] if i < len(symbols) else str(i + 1)
        lines.append(f"| {sym} | {act['name']} | {act['pct']} | {act['emotion']} |")
    return "\n".join(lines)


def build_immersion_layers(layers: list[str]) -> str:
    out = []
    for i, layer in enumerate(layers, 1):
        out.append(f"{i}. **{layer.split(' — ')[0]}** — {' — '.join(layer.split(' — ')[1:])}" if " — " in layer else f"{i}. {layer}")
    return "\n".join(out)


def build_soundtrack_section(moods: dict) -> str:
    """Build soundtrack section, tolerant of two formats:
    - New: {style, mood, bpm}
    - Old: {mood, bpm} (style derived from mood)
    """
    lines = []
    for key in ["faixa_1", "faixa_2", "faixa_3", "faixa_4"]:
        if key not in moods:
            continue
        m = moods[key]
        idx = key.split("_")[1]
        # Backward compatibility: if no 'style', use mood as the prompt seed
        style = m.get("style") or m.get("mood", "")
        mood = m.get("mood", "")
        bpm = m.get("bpm", "")
        lines.append(f"FAIXA_{idx}:")
        lines.append(f'  NAME: "{key}"')
        lines.append(f'  SUNO_PROMPT: "{style}, no voice, no lyrics, {bpm} BPM"')
        lines.append(f"  MOOD: {mood}")
        lines.append(f"  BPM: {bpm}")
        lines.append("")
    return "\n".join(lines)


def build_arc_export(acts: list[dict]) -> str:
    lines = []
    names_map = {
        0: "ACT_1", 1: "ACT_2", 2: "ACT_3A", 3: "ACT_TWIST",
        4: "ACT_3B", 5: "ACT_4", 6: "ACT_5", 7: "ACT_6", 8: "ACT_7"
    }
    for i, act in enumerate(acts):
        label = names_map.get(i, f"ACT_{i+1}")
        lines.append(
            f'  {label}: {{name: "{act["name"]}", scene_start: N, scene_end: N, '
            f'emotion: "{act["emotion"]}", intensity: "high"}}'
        )
    return "\n".join(lines)


def build_visual_style_block(style_cfg: dict | None) -> str:
    """Build the visual style injection block for the agent template."""
    if not style_cfg:
        return "(Nenhum estilo visual selecionado — usar estilo padrão do nicho conforme VISUAL STATE CHAIN)"

    inj = style_cfg.get("veo3_injection", {})
    editor = style_cfg.get("editor_meta", {})
    palette = inj.get("color_palette", {})

    lines = [
        f"**VISUAL STYLE ATIVO: {style_cfg.get('emoji', '')} {style_cfg.get('label', '')}**",
        "",
        f"> {style_cfg.get('description', '')}",
        "",
        "Quando este estilo está ativo, TODOS os prompts VEO3 devem seguir estas regras visuais:",
        "",
        f"**PERSONAGENS:** {inj.get('character_rule', '')}",
        "",
        f"**ROUPA:** {inj.get('clothing_rule', '')}",
        "",
        f"**CENÁRIO:** {inj.get('environment_rule', '')}",
        "",
        f"**CÂMERA:** {inj.get('camera_rule', '')}",
        "",
        f"**TEXTO EM TELA:** {inj.get('text_overlays', '')}",
        "",
        f"**FRASE OBRIGATÓRIA (incluir em CADA prompt):** \"{inj.get('repeat_phrase', '')}\"",
        "",
        f"**PROIBIDO:** {inj.get('forbidden', '')}",
        "",
        "**PALETA DE CORES:**",
    ]

    for key, val in palette.items():
        if isinstance(val, list):
            lines.append(f"  {key}: {', '.join(val)}")
        else:
            lines.append(f"  {key}: {val}")

    lines.extend([
        "",
        "**EDITOR META DEFAULTS (aplicar quando não especificado):**",
        f"  color_grade: {editor.get('color_grade', 'warm')}",
        f"  transition_style: {editor.get('transition_style', 'cut')}",
        f"  sfx_profile: {editor.get('sfx_profile', 'cinematic')}",
        f"  subtitle_style: {editor.get('subtitle_style', 'cinematic')}",
    ])

    return "\n".join(lines)


def build_agent(niche_key: str, cfg: dict, base: str, style_cfg: dict | None = None) -> str:
    """Replace all {{PLACEHOLDERS}} in base with config values."""
    acts = cfg.get("narrative_arc", {}).get("acts", [])

    style_id = style_cfg.get("style_id", "none") if style_cfg else "none"

    replacements = {
        "{{AGENT_EMOJI}}": cfg.get("agent_emoji", ""),
        "{{AGENT_NAME}}": cfg.get("agent_name", "AGENT"),
        "{{NICHE_TITLE}}": cfg.get("title", ""),
        "{{AGENT_IDENTITY}}": cfg.get("identity", ""),
        "{{NICHO_LCDF}}": cfg.get("nicho_lcdf", niche_key),
        "{{STYLE_CATEGORY}}": cfg.get("style_category", "realistas"),
        "{{SUB_STYLE}}": cfg.get("sub_style", "Documentary"),
        "{{VISUAL_STYLE_ID}}": style_id,
        "{{VISUAL_STYLE_BLOCK}}": build_visual_style_block(style_cfg),
        "{{SUPPORTED_TOPICS}}": cfg.get("supported_topics", ""),
        "{{ACT_TABLE}}": build_act_table(acts),
        "{{ACT_RULES}}": cfg.get("narrative_arc", {}).get("rules", ""),
        "{{IMMERSION_LAYERS}}": build_immersion_layers(
            cfg.get("narrative_arc", {}).get("immersion_layers", [])
        ),
        "{{VISUAL_STATE_CHAIN}}": cfg.get("visual_state_chain", ""),
        "{{ACCUMULATION_PHASES}}": cfg.get("accumulation_phases", ""),
        "{{FACTUAL_VERIFICATION}}": "true" if cfg.get("factual_verification") else "false",
        "{{SOUNDTRACK_PROMPTS}}": build_soundtrack_section(cfg.get("soundtrack_moods", {})),
        "{{ARC_EXPORT}}": build_arc_export(acts),
        "{{PROMPT_EXAMPLES}}": _build_examples(cfg.get("prompt_examples", [])),
    }

    result = base
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    return result


def _build_examples(examples: list[dict]) -> str:
    if not examples:
        return "(Adaptar os exemplos ao nicho — manter os 7 elementos obrigatórios: câmera, estilo, iluminação, sujeito, locação, ação, áudio)"

    lines = []
    for ex in examples:
        lines.append(f"```\nCena {ex['scene']:02d}:")
        lines.append(f'PROMPT: "{ex["prompt"]}"')
        lines.append("---")
        lines.append("EDITOR_META:")
        for k, v in ex.get("editor_meta", {}).items():
            lines.append(f"  {k}: {v}")
        lines.append("```\n")
    return "\n".join(lines)


def main():
    configs = load_config()
    base = load_base()
    styles = load_styles()

    # Parse --style argument
    style_key = None
    for i, arg in enumerate(sys.argv):
        if arg == "--style" and i + 1 < len(sys.argv):
            style_key = sys.argv[i + 1]

    if "--list-styles" in sys.argv:
        print("Available visual styles:")
        for key, scfg in styles.items():
            print(f"  {scfg.get('emoji', '')} {key:35s} → {scfg.get('label', '')} [{scfg.get('style_category', '')}]")
        return

    if "--list" in sys.argv:
        print("Available niches:")
        for key, cfg in configs.items():
            print(f"  {cfg.get('agent_emoji', '')} {key:30s} → {cfg.get('agent_name', '?')} ({cfg.get('title', '')})")
        if styles:
            print(f"\nVisual styles available (use --style <name>):")
            for key in styles:
                print(f"  {styles[key].get('emoji', '')} {key}")
        return

    # Validate style
    style_cfg = None
    if style_key:
        if style_key not in styles:
            print(f"[ERROR] Unknown style: {style_key}")
            print(f"Available: {', '.join(styles.keys())}")
            return
        style_cfg = styles[style_key]
        print(f"\n{style_cfg.get('emoji', '')} Visual Style: {style_cfg.get('label', '')}")
        print(f"  Category: {style_cfg.get('style_category', '')}")
        print()

    # Determine targets (filter out --style and its value)
    skip_next = False
    targets = []
    for i, arg in enumerate(sys.argv[1:], 1):
        if skip_next:
            skip_next = False
            continue
        if arg == "--style":
            skip_next = True
            continue
        if arg.startswith("--"):
            continue
        targets.append(arg)

    if not targets:
        targets = list(configs.keys())

    built = 0
    for niche_key in targets:
        if niche_key not in configs:
            print(f"[SKIP] Unknown niche: {niche_key}")
            continue

        cfg = configs[niche_key]
        agent_name = cfg.get("agent_name", "AGENT")
        out_dir = OUTPUT_DIR / niche_key
        out_dir.mkdir(parents=True, exist_ok=True)

        # File name includes style suffix when style is active
        if style_key:
            out_path = out_dir / f"AGENT_{agent_name}_v2.0_{style_key}.md"
        else:
            out_path = out_dir / f"AGENT_{agent_name}_v2.0.md"

        result = build_agent(niche_key, cfg, base, style_cfg)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result)

        size_kb = len(result.encode("utf-8")) / 1024
        style_tag = f" [{style_key}]" if style_key else ""
        print(f"  {cfg.get('agent_emoji', '')} {agent_name:12s} → {out_path.name} ({size_kb:.1f} KB){style_tag}")
        built += 1

    print(f"\n{'='*50}")
    print(f"Built {built} agents in {OUTPUT_DIR}")
    if style_key:
        print(f"Visual Style: {style_cfg.get('emoji', '')} {style_cfg.get('label', '')}")


if __name__ == "__main__":
    main()
