"""
One-shot tool: rewrites the ROBOS ENCANTADOS SOP to remove all robot terminology
and replace it with chibi character terminology, preserving the enchanted
miniature macro aesthetic.

Run once:  python cloner/tools/derobotize_sop.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ROOT / "output" / "sop_robos_encantados_floresta.md",
    ROOT / "output" / "agent_faelar_enchanted_miniature_3d.md",
]

# Ordered list: (regex_pattern, replacement). Case-insensitive where marked.
# Order matters — more-specific phrases first.
REPLACEMENTS: list[tuple[str, str, int]] = [
    # ── SECOND PASS: fix artifacts from initial naive swaps ────────────
    # These run first so subsequent passes don't re-break them.
    (r"personagens miniatura mec[âa]nicos", "personagens chibi artesanais", re.IGNORECASE),
    (r"criaturinhas de metal", "criaturinhas artesanais", re.IGNORECASE),
    (r"criaturinhas mec[âa]nicas", "criaturinhas artesanais", re.IGNORECASE),
    (r"sorriso mec[âa]nico", "sorriso suave", re.IGNORECASE),
    (r"a(cao|ction) mec[âa]nica", "ação artesanal", re.IGNORECASE),
    (r"acoes mecanicas", "acoes artesanais", re.IGNORECASE),
    (r"movimento mec[âa]nico", "movimento artesanal", re.IGNORECASE),
    (r"corpos mec[âa]nicos?", "corpos de massinha", re.IGNORECASE),
    (r"m[aã]os de cobre", "mãozinhas pequenas", re.IGNORECASE),
    (r"corpo(?:s)? de cobre(?:/bronze)?", "corpo de massinha pintada", re.IGNORECASE),
    (r"personagens de cobre", "personagens chibi", re.IGNORECASE),
    (r"pequenos personagens de cobre", "pequenos personagens chibi", re.IGNORECASE),
    # Over-aggressive "OLHAR" artifact cleanup — the uppercased "LED" became "OLHAR"
    (r"OLHARs? (ambar|âmbar)", "olhos grandes âmbar", re.IGNORECASE),
    (r"OLHARs? azuis", "olhos azulados", re.IGNORECASE),
    (r"OLHARs? brilhantes", "olhos brilhantes", re.IGNORECASE),
    (r"OLHARs?", "olhos", 0),  # catch remaining standalone OLHAR
    (r"OLHAR-sorriso", "sorriso gentil", 0),
    (r"brilho nos OLHAR", "brilho nos olhos", re.IGNORECASE),
    (r"brilho dos OLHAR", "brilho nos olhos", re.IGNORECASE),
    (r"piscando de alegria", "sorrindo de alegria", re.IGNORECASE),
    # "por OLHAR" (translating gesture) → "por gestos"
    (r"se cumprimentando com olhos", "se cumprimentando com aceno", re.IGNORECASE),
    (r"conversando por olhos", "conversando por gestos", re.IGNORECASE),
    (r"interagem por gestos e brilho de olhos", "interagem por gestos suaves e sorrisos", re.IGNORECASE),

    # Body material descriptors in remaining places
    (r"engrenagens no peito parcialmente cobertas por musgo, vapor dos narizinhos, antena fina",
     "chapéu de folha ou casca de cogumelo, broches de madeira, cachecol de lã crua", 0),
    (r"olhos: olhos grandes ambar quente \(expressam emocao via brilho\)",
     "Olhos: grandes e expressivos, cor âmbar ou verde (transmitem calma e curiosidade)", re.IGNORECASE),

    # Palette line — copper/bronze words
    (r"cores: ambar, dourado, cobre, verde musgo, vermelho cogumelo",
     "cores: âmbar, dourado, mel, verde musgo, vermelho cogumelo, lavanda suave", re.IGNORECASE),
    (r"paleta: cobre #B87333, dourado #DAA520, musgo #4A7C59, ambar #FFB84D, terra #3E2723",
     "Paleta: verde sálvia #8FB285, dourado #C9A961, marrom quente #B5651D, caramelo #D4A574, musgo #6B8E4A, âmbar #FFB84D, terra #3E2723", re.IGNORECASE),

    # ASMR / audio — swap mechanical sounds for organic ones
    (r"clique (?:mec[âa]nico)? ?\+ ?vapor sibilando",
     "faca cortando em tábua + líquido sendo despejado", re.IGNORECASE),
    (r"ASMR (?:PURO|mecanico)?: geleia borbulhando, cogumelo brilhando, gota pingando, engrenagem girando, vapor subindo",
     "ASMR PURO: geleia borbulhando, cogumelo brilhando, gota pingando, massa sendo cortada, chá fumegando", re.IGNORECASE),
    (r"clicks?, vapor, engrenagens", "facas, líquidos, madeira estalando", re.IGNORECASE),
    (r"sons (?:mec[âa]nicos )?de engrenagem, vapor, metal sincronizados",
     "sons orgânicos (faca, líquido, madeira, tecido) sincronizados", re.IGNORECASE),
    (r"engrenagens?(?: girando)?", "utensílios de madeira", re.IGNORECASE),
    (r"vapor sibilando", "líquido despejando", re.IGNORECASE),
    (r"vapor saindo", "vapor do chá", re.IGNORECASE),
    (r"clique (?:de )?madeira estalando", "madeira estalando", re.IGNORECASE),
    (r"vapor subindo", "vapor do chá subindo", re.IGNORECASE),
    (r"sorriso mec[âa]nico", "sorriso sutil", re.IGNORECASE),
    (r"vapor (?:coletivo )?de alegria", "suspiro coletivo de alegria", re.IGNORECASE),

    # Prose: "precisao artisanal de personagens miniatura mecanicos"
    (r"precisao artesanal de personagens (?:miniatura )?(?:mec[âa]nicos )?",
     "precisao artesanal de personagens chibi em miniatura ", re.IGNORECASE),
    (r"a precisao artesanal",
     "a precisao artesanal", 0),
    (r"o contraste entre o mec[âa]nico \(engrenagens, cobre, vapor\) e o organico",
     "o contraste entre o artesanal (madeira, tecido, cerâmica) e o orgânico", re.IGNORECASE),

    # Nicho header line in agent file (keep key, update description)
    (r"Nicho: Cottagecore fantasia ASMR com personagens miniatura de cobre/bronze integrados a floresta",
     "Nicho: Cottagecore fantasia ASMR com personagens chibi artesanais integrados a vilas encantadas e florestas mágicas", 0),

    # ── ORIGINAL PASSES ────────────────────────────────────────────────
    # Titles / banners
    (r"ROBOS ENCANTADOS DA FLORESTA", "VILA ENCANTADA EM MINIATURA", 0),
    (r"Robôs Encantados da Floresta", "Vila Encantada em Miniatura", 0),
    (r"Robos Encantados da Floresta", "Vila Encantada em Miniatura", 0),

    # Compound specific phrases (before generic robot → character swap)
    (r"robôs? miniatura artesana(?:l|is)", "personagens chibi artesanais", re.IGNORECASE),
    (r"robos? miniatura artesana(?:l|is)", "personagens chibi artesanais", re.IGNORECASE),
    (r"tiny (?:artisan )?copper robots?", "tiny artisan chibi characters", re.IGNORECASE),
    (r"tiny robots? ?/ ?tiny folk", "tiny chibi folk / miniature villagers", re.IGNORECASE),
    (r"tiny robots?", "tiny chibi folk", re.IGNORECASE),
    (r"robot(ic)? folk", "chibi folk", re.IGNORECASE),
    (r"artisan robots?", "artisan chibi characters", re.IGNORECASE),
    (r"small (?:artisan )?robots?", "small chibi characters", re.IGNORECASE),
    (r"mushroom cap hats?", "leaf and mushroom cap hats", re.IGNORECASE),

    # Body materials: copper/bronze/metallic → wood/ceramic/linen
    (r"cobre/bronze envelhecido", "madeira envernizada e cerâmica", re.IGNORECASE),
    (r"cobre e bronze", "madeira e cerâmica", re.IGNORECASE),
    (r"copper ?/? ?bronze", "wood and ceramic", re.IGNORECASE),
    (r"weathered copper", "hand-painted wood", re.IGNORECASE),
    (r"metal rangendo", "madeira estalando", re.IGNORECASE),
    (r"clicks? (?:de )?engrenagem(?:s|ns)?", "faca cortando em tábua de madeira", re.IGNORECASE),
    (r"gear whirring", "knife chopping on wood", re.IGNORECASE),
    (r"metallic clicks?", "wooden utensil taps", re.IGNORECASE),
    (r"ASMR MECÂNICO", "ASMR ORGÂNICO", 0),
    (r"asmr mecanico", "ASMR orgânico", re.IGNORECASE),
    (r"ASMR mecânico", "ASMR orgânico", 0),
    (r"steampunk (?:fofo|leve)?", "cottagecore fofo", re.IGNORECASE),
    (r"mecânica steampunk", "artesanato cottagecore", re.IGNORECASE),

    # LED eyes → expressive eyes
    (r"olhos LED", "olhos grandes brilhantes", re.IGNORECASE),
    (r"LED eyes?", "big expressive eyes", re.IGNORECASE),
    (r"LEDs apagados", "olhos entreabertos", re.IGNORECASE),
    (r"LEDs acendendo", "olhos abrindo lentamente", re.IGNORECASE),
    (r"brilho dos LEDs?", "brilho nos olhos", re.IGNORECASE),
    (r"LED", "olhar", 0),  # safer last-catch

    # Mechanical emotion → facial/body emotion
    (r"emoção mecânica", "emoção expressiva", re.IGNORECASE),
    (r"emocao mecanica", "emocao expressiva", re.IGNORECASE),
    (r"mãos mecânicas", "mãos pequenas", re.IGNORECASE),
    (r"maos mecanicas", "maos pequenas", re.IGNORECASE),
    (r"movimentos? mecânicos?", "movimentos suaves", re.IGNORECASE),
    (r"respiradouros?", "narizinhos", re.IGNORECASE),
    (r"vapor saindo dos narizinhos", "suspiro suave", re.IGNORECASE),

    # "Robôs NUNCA falam" → "Personagens NUNCA falam"
    (r"robôs? NUNCA fal(?:am|a)", "Personagens NUNCA falam", re.IGNORECASE),
    (r"robos? NUNCA fal(?:am|a)", "Personagens NUNCA falam", re.IGNORECASE),
    (r"robots? NEVER speak", "characters NEVER speak", re.IGNORECASE),

    # Generic singular/plural — pt
    (r"\brobôzinhos?\b", "personagenzinhos", re.IGNORECASE),
    (r"\brobozinhos?\b", "personagenzinhos", re.IGNORECASE),
    (r"\brobôs?\b", "personagens", re.IGNORECASE),
    (r"\brobos?\b", "personagens", re.IGNORECASE),

    # Generic singular/plural — en
    (r"\brobots?\b", "characters", re.IGNORECASE),
    (r"\brobotic\b", "handcrafted", re.IGNORECASE),

    # Awkward doubles after replacement
    (r"personagens personagens", "personagens", 0),
    (r"characters characters", "characters", 0),
    (r"personagem personagem", "personagem", 0),

    # Anti-pattern list tweaks (forbidden sections)
    (r"futuristic/clean robots?;?", "futuristic sci-fi characters;", re.IGNORECASE),
    (r"clean shiny metal;", "cold industrial surfaces;", re.IGNORECASE),
]


def apply_case_aware(pattern: str, replacement: str, flags: int, text: str) -> str:
    """Preserve initial caps when replacing a lowercase pattern."""
    compiled = re.compile(pattern, flags)

    def _sub(m: re.Match) -> str:
        orig = m.group(0)
        if orig.isupper() and len(orig) > 1:
            return replacement.upper()
        if orig[:1].isupper() and replacement[:1].islower():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    return compiled.sub(_sub, text)


def rewrite(text: str) -> str:
    for pattern, replacement, flags in REPLACEMENTS:
        text = apply_case_aware(pattern, replacement, flags, text)
    return text


def main() -> None:
    for path in FILES:
        if not path.exists():
            print(f"skip (missing): {path}")
            continue
        original = path.read_text(encoding="utf-8")
        updated = rewrite(original)
        if updated == original:
            print(f"no change: {path.name}")
            continue
        backup = path.with_suffix(path.suffix + ".backup")
        if not backup.exists():
            backup.write_text(original, encoding="utf-8")
            print(f"backup saved: {backup.name}")
        path.write_text(updated, encoding="utf-8")
        # Rough diff stats
        old_lines = original.count("\n")
        new_lines = updated.count("\n")
        old_robo = len(re.findall(r"rob[oôó]", original, re.IGNORECASE))
        new_robo = len(re.findall(r"rob[oôó]", updated, re.IGNORECASE))
        print(
            f"rewrote {path.name}: {old_lines} -> {new_lines} lines, "
            f"robot mentions {old_robo} -> {new_robo}"
        )


if __name__ == "__main__":
    main()
