"""
Script Stealing Protocol - Geração de Roteiros
Cruza SOPs do Clerk com nicho escolhido para gerar roteiros completos.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


OUTPUT_DIR = Path(__file__).parent.parent / "output"


def load_file(path: str, pattern: str = "") -> str:
    """Carrega arquivo ou busca o mais recente."""
    p = Path(path) if path else None
    if p and p.exists():
        return p.read_text(encoding="utf-8")

    if pattern:
        files = sorted(OUTPUT_DIR.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        if files:
            print(f"  Usando arquivo mais recente: {files[0].name}")
            return files[0].read_text(encoding="utf-8")

    return ""


def generate_video_ideas(sop: str, niche_doc: str, chosen_niche: str, num_ideas: int = 30) -> str:
    """Gera ideias de vídeos cruzando SOP com nicho."""
    client = Anthropic()

    prompt = f"""Você é um estrategista de conteúdo YouTube. Sua tarefa é gerar {num_ideas} ideias de vídeos para um novo canal.

REGRAS:
- Cada ideia deve seguir EXATAMENTE a mesma estrutura dos vídeos do canal analisado no SOP
- Os títulos devem usar os MESMOS padrões de títulos identificados
- As ideias devem ser do NOVO NICHO, não do nicho original
- Organize por prioridade (vídeos com maior potencial viral primeiro)
- Para cada ideia inclua: título, hook dos primeiros 30 segundos, e um resumo de 2 linhas do roteiro

NICHO ESCOLHIDO: {chosen_niche}

---

SOP DO CANAL ORIGINAL:
{sop[:8000]}

---

DOCUMENTO DE NICHOS:
{niche_doc[:4000]}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def generate_full_script(sop: str, video_idea: str, niche: str, script_num: int = 1) -> str:
    """Gera um roteiro completo baseado no SOP e ideia."""
    client = Anthropic()

    prompt = f"""Você é um roteirista profissional de YouTube. Escreva um roteiro COMPLETO seguindo RIGOROSAMENTE as regras do SOP abaixo.

O roteiro deve ter:
1. **HOOK** (primeiros 30 segundos - capturar atenção imediata)
2. **CONTEXTO** (setup da história/problema)
3. **DESENVOLVIMENTO** (com open loops, cliffhangers, transições)
4. **CLÍMAX** (momento mais impactante)
5. **RESOLUÇÃO** (conclusão satisfatória)
6. **CTA** (call to action natural)

REGRAS DO SOP:
- Siga TODAS as "Regras de Ouro" listadas
- Use o mesmo estilo de narração
- Aplique os padrões de hooks identificados
- Mantenha o mesmo ritmo e pacing
- Duração alvo: 8-12 minutos de narração

NICHO: {niche}

IDEIA DO VÍDEO:
{video_idea}

---

SOP:
{sop[:10000]}

---

Escreva o roteiro completo agora. Inclua indicações de [B-ROLL], [TRANSIÇÃO], [PAUSA DRAMÁTICA] onde apropriado."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def run_script_stealer(
    sop_path: str = "",
    niches_path: str = "",
    chosen_niche: str = "",
    num_ideas: int = 30,
    num_scripts: int = 3,
    output_name: str = None
):
    """Executa o Script Stealing Protocol completo."""
    print("=" * 60)
    print("  SCRIPT STEALING PROTOCOL - Geração de Roteiros")
    print("=" * 60)

    # 1. Carregar arquivos
    print("\n[1/3] Carregando SOPs e nichos...")
    sop = load_file(sop_path, "*_sop.md")
    niche_doc = load_file(niches_path, "niches_*.md")

    if not sop:
        print("ERRO: SOP não encontrado. Execute o Protocol Clerk primeiro.")
        return
    print(f"  SOP: {len(sop)} chars")
    print(f"  Nichos: {len(niche_doc)} chars")

    if not chosen_niche:
        chosen_niche = input("\nDigite o nicho escolhido: ").strip()
        if not chosen_niche:
            print("Nicho não informado.")
            return

    # 2. Gerar ideias
    print(f"\n[2/3] Gerando {num_ideas} ideias de vídeos para '{chosen_niche}'...")
    ideas = generate_video_ideas(sop, niche_doc, chosen_niche, num_ideas)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = output_name or f"scripts_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    ideas_path = OUTPUT_DIR / f"{name}_ideas.md"
    ideas_path.write_text(ideas, encoding="utf-8")
    print(f"  Ideias salvas em: {ideas_path}")

    # 3. Gerar roteiros completos
    print(f"\n[3/3] Gerando {num_scripts} roteiros completos...")

    idea_blocks = ideas.split("\n\n")
    top_ideas = []
    current = ""
    for block in idea_blocks:
        if block.strip().startswith(("#", "1.", "2.", "3.", "**1", "**2", "**3")):
            if current:
                top_ideas.append(current)
            current = block
        else:
            current += "\n" + block
    if current:
        top_ideas.append(current)

    scripts = []
    for i in range(min(num_scripts, len(top_ideas))):
        print(f"\n  Escrevendo roteiro {i+1}/{num_scripts}...")
        script = generate_full_script(sop, top_ideas[i], chosen_niche, i + 1)
        scripts.append(script)

        script_path = OUTPUT_DIR / f"{name}_roteiro_{i+1}.md"
        script_path.write_text(script, encoding="utf-8")
        print(f"  Salvo: {script_path}")

    # Resumo final
    print(f"\n{'=' * 60}")
    print(f"  CONCLUÍDO!")
    print(f"  Nicho: {chosen_niche}")
    print(f"  Ideias geradas: {ideas_path}")
    for i in range(len(scripts)):
        print(f"  Roteiro {i+1}: {name}_roteiro_{i+1}.md")
    print(f"{'=' * 60}")

    return {
        "ideas_path": str(ideas_path),
        "scripts": [f"{name}_roteiro_{i+1}.md" for i in range(len(scripts))],
        "niche": chosen_niche
    }


if __name__ == "__main__":
    sop_path = sys.argv[1] if len(sys.argv) > 1 else ""
    niches_path = sys.argv[2] if len(sys.argv) > 2 else ""
    chosen_niche = sys.argv[3] if len(sys.argv) > 3 else ""
    num_scripts = int(sys.argv[4]) if len(sys.argv) > 4 else 3

    run_script_stealer(sop_path, niches_path, chosen_niche, num_scripts=num_scripts)
