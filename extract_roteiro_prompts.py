"""
Extrai os prompts de geracao de ROTEIRO de cada SOP por nicho.

Cada SOP tem 1+ secoes relevantes pra escrever o roteiro:
  - "SYSTEM PROMPT COMPLETO" / "System Prompt Completo"
  - "INSTRUCOES PARA IA (System Prompt ...)"
  - "TEMPLATE DE ROTEIRO PREENCHIVEL"

Junta essas secoes por nicho e salva em output/roteiro_prompts/<nicho>.md
(ignora secoes de imagem/SEO/lancamento/monetizacao).
"""
import re
import unicodedata
from pathlib import Path

OUT_DIR = Path(__file__).parent / "output"
DEST = OUT_DIR / "roteiro_prompts"

# arquivo SOP -> nome de nicho limpo
NICHE_MAP = {
    "sop_anacron_complete.md": "anacron",
    "sop_biblico_complete.md": "biblico",
    "sop_ghibli_cozy_life.md": "ghibli_cozy_life",
    "enhanced_sop_ghibli.md": "ghibli_enhanced",
    "sop_pov_complete.md": "pov",
    "sop_pov_rudy.md": "pov_rudy",
    "sop_pov_storytelling.md": "pov_storytelling",
    "sop_rescue_complete.md": "rescue",
    "sop_robos_encantados_floresta.md": "robos_encantados_floresta",
    "sop_sacred_lessons_wealth.md": "sacred_lessons_wealth",
    "SOP_RELATOS_FAMILIARES.md": "relatos_familiares",
    "sop_relatos_familiares_parte3.md": "relatos_familiares_parte3",
}

# titulo de secao relevante p/ roteiro
KEEP = re.compile(
    r"(system\s*prompt|instru[cç][õo]es?\s+para\s+ia|template\s+de\s+roteiro|"
    r"prompt\s+completo|gera[cç][aã]o\s+de\s+roteiro)",
    re.IGNORECASE,
)
# titulo que encerra a parte de roteiro (imagem/seo/etc) — nunca manter
STOP = re.compile(
    r"(imagefx|midjourney|prompt\s+base|seo|launch|lan[cç]amento|monetiz|"
    r"thumbnail|channel\s+identity|identidade)",
    re.IGNORECASE,
)
HEADER = re.compile(r"^(#{1,4})\s+(.*)$")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def extract(md: str) -> str:
    """Quebra por header e mantem so blocos cujo titulo casa KEEP e nao casa STOP."""
    lines = md.splitlines()
    blocks: list[tuple[int, str, list[str]]] = []  # (level, title, body_lines)
    cur: tuple[int, str, list[str]] | None = None
    preamble: list[str] = []
    for ln in lines:
        m = HEADER.match(ln)
        if m:
            if cur:
                blocks.append((cur[0], cur[1], cur[2]))
            cur = (len(m.group(1)), m.group(2).strip(), [ln])
        else:
            (cur[2] if cur else preamble).append(ln)
    if cur:
        blocks.append((cur[0], cur[1], cur[2]))

    out: list[str] = []
    for level, title, body in blocks:
        if STOP.search(title):
            continue
        if KEEP.search(title):
            out.append("\n".join(body).rstrip())
    return "\n\n".join(out).strip()


def main() -> None:
    DEST.mkdir(exist_ok=True)
    index: list[str] = ["# Prompts de Roteiro por Nicho", "",
                        "Extraido automaticamente dos SOPs em `cloner/output/`.", ""]
    done = 0
    for fname, niche in NICHE_MAP.items():
        src = OUT_DIR / fname
        if not src.exists():
            print(f"SKIP {fname} (nao existe)")
            continue
        md = src.read_text(encoding="utf-8", errors="replace")
        content = extract(md)
        if not content:
            print(f"VAZIO {fname} — nenhuma secao de roteiro encontrada")
            continue
        header = (
            f"# Roteiro Prompt — {niche}\n\n"
            f"> Fonte: `cloner/output/{fname}`\n"
            f"> Use o SYSTEM PROMPT em System Instructions da IA e o TEMPLATE como esqueleto.\n\n"
            f"---\n\n"
        )
        (DEST / f"{niche}.md").write_text(header + content + "\n", encoding="utf-8")
        words = len(content.split())
        index.append(f"- [{niche}]({niche}.md) — fonte `{fname}` ({words} palavras)")
        print(f"OK  {niche:32s} <- {fname} ({words} palavras)")
        done += 1

    (DEST / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"\n{done} nichos extraidos -> {DEST}")


if __name__ == "__main__":
    main()
