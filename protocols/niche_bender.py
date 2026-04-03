"""
Niche Bending Protocol - Criação de Nichos Derivados
Pega um nicho de sucesso e sugere novos nichos com potencial viral.
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


def load_clerk_data(sop_path: str) -> str:
    """Carrega o SOP gerado pelo Clerk."""
    path = Path(sop_path)
    if not path.exists():
        output_files = sorted(OUTPUT_DIR.glob("*_sop.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if output_files:
            path = output_files[0]
            print(f"  Usando SOP mais recente: {path.name}")
        else:
            raise FileNotFoundError("Nenhum SOP encontrado. Execute o Protocol Clerk primeiro.")
    return path.read_text(encoding="utf-8")


def generate_niches(sop_content: str, original_niche: str = "", num_niches: int = 5) -> dict:
    """Usa Claude para gerar nichos derivados."""
    client = Anthropic()

    prompt = f"""Você é um estrategista de canais YouTube especialista em "Niche Bending" — a arte de pegar a fórmula de sucesso de um nicho e aplicar em um mercado completamente novo.

Baseado na análise do canal abaixo, gere {num_niches} conceitos de nichos derivados.

Para CADA nicho, forneça:

1. **NOME DO CANAL** (sugestão criativa e memorável)
2. **CONCEITO** (1 parágrafo explicando a ideia)
3. **POR QUE FUNCIONA** (por que esse formato transfere bem para esse novo nicho)
4. **PÚBLICO-ALVO** (quem vai assistir e por quê)
5. **PILARES DE CONTEÚDO** (3-5 categorias de vídeos)
6. **10 IDEIAS DE VÍDEOS** (títulos prontos no estilo viral do canal original)
7. **ESTILO VISUAL** (que tipo de visual/animação usar)
8. **ESTIMATIVA DE RPM** (potencial de monetização do nicho: baixo/médio/alto/muito alto)
9. **COMPETIÇÃO** (baixa/média/alta — baseado em quantos canais similares existem)
10. **FONTES DE PESQUISA** (onde encontrar histórias: Reddit, podcasts, livros, etc.)

REGRAS:
- Os nichos devem ser DIFERENTES entre si
- Pelo menos 1 nicho deve ser de RPM alto (finanças, tech, legal)
- Pelo menos 1 nicho deve ser fácil de produzir (sem necessidade de animação 3D complexa)
- Cada nicho deve ter potencial para 100+ vídeos (não pode ser muito restrito)
- Os títulos devem seguir a MESMA estrutura de títulos do canal original

{f"Nicho original: {original_niche}" if original_niche else ""}

---

SOP DO CANAL ANALISADO:

{sop_content[:12000]}"""

    response = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    return {"niches": response.content[0].text}


def run_niche_bender(sop_path: str = "", original_niche: str = "", num_niches: int = 5, output_name: str = None):
    """Executa o Niche Bending Protocol."""
    print("=" * 60)
    print("  NICHE BENDING PROTOCOL - Criação de Nichos")
    print("=" * 60)

    # 1. Carregar SOP
    print("\n[1/2] Carregando SOP do Clerk...")
    sop_content = load_clerk_data(sop_path)
    print(f"  SOP carregado: {len(sop_content)} caracteres")

    # 2. Gerar nichos
    print(f"\n[2/2] Gerando {num_niches} nichos derivados com Claude...")
    result = generate_niches(sop_content, original_niche, num_niches)

    # Salvar
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = output_name or f"niches_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    niches_path = OUTPUT_DIR / f"{name}.md"
    niches_path.write_text(result["niches"], encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  CONCLUÍDO!")
    print(f"  Nichos salvos em: {niches_path}")
    print(f"{'=' * 60}")

    return {"niches_path": str(niches_path), "content": result["niches"]}


if __name__ == "__main__":
    sop_path = sys.argv[1] if len(sys.argv) > 1 else ""
    original_niche = sys.argv[2] if len(sys.argv) > 2 else ""
    num_niches = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    output_name = sys.argv[4] if len(sys.argv) > 4 else None

    run_niche_bender(sop_path, original_niche, num_niches, output_name)
