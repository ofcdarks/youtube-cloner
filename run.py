"""
YouTube Channel Cloner - Pipeline Completo
Executa os 3 protocolos em sequência ou individualmente.
"""

import sys
import argparse
from pathlib import Path
from protocols.clerk import run_clerk
from protocols.niche_bender import run_niche_bender
from protocols.script_stealer import run_script_stealer
from protocols.google_export import export_project


def run_full_pipeline(channel_url: str, niche: str = "", num_scripts: int = 3):
    """Executa o pipeline completo: Clerk → Niche Bender → Script Stealer."""
    print("\n" + "=" * 60)
    print("  YOUTUBE CHANNEL CLONER - Pipeline Completo")
    print("=" * 60)

    # Etapa 1: Clerk
    print("\n\n>>> ETAPA 1: PROTOCOL CLERK <<<\n")
    clerk_result = run_clerk(channel_url, "pipeline")
    if not clerk_result:
        print("Falha no Protocol Clerk. Abortando.")
        return

    # Etapa 2: Niche Bender
    print("\n\n>>> ETAPA 2: NICHE BENDING PROTOCOL <<<\n")
    niche_result = run_niche_bender(
        sop_path=clerk_result["sop_path"],
        original_niche=niche,
        output_name="pipeline_niches"
    )
    if not niche_result:
        print("Falha no Niche Bending. Abortando.")
        return

    # Mostrar nichos e pedir escolha
    print("\n" + niche_result["content"][:3000])

    if not niche:
        niche = input("\n\nDigite o NICHO escolhido para gerar roteiros: ").strip()

    # Etapa 3: Script Stealer
    print("\n\n>>> ETAPA 3: SCRIPT STEALING PROTOCOL <<<\n")
    script_result = run_script_stealer(
        sop_path=clerk_result["sop_path"],
        niches_path=niche_result["niches_path"],
        chosen_niche=niche,
        num_scripts=num_scripts,
        output_name="pipeline_scripts"
    )

    # Etapa 4: Export para Google Drive
    print("\n\n>>> ETAPA 4: GOOGLE EXPORT <<<\n")
    output_dir = Path(clerk_result["sop_path"]).parent
    export_files = {
        "sop": clerk_result["sop_path"],
        "niches": niche_result["niches_path"],
    }
    if script_result:
        export_files["ideas"] = script_result["ideas_path"]
        export_files["scripts"] = [
            str(output_dir / s) for s in script_result.get("scripts", [])
        ]

    export_result = export_project(niche or "YouTube Clone", export_files)

    print("\n\n" + "=" * 60)
    print("  PIPELINE COMPLETO!")
    print("=" * 60)
    print(f"  SOP: {clerk_result['sop_path']}")
    print(f"  Nichos: {niche_result['niches_path']}")
    if script_result:
        print(f"  Ideias: {script_result['ideas_path']}")
        for s in script_result.get("scripts", []):
            print(f"  Roteiro: {s}")
    print(f"  Google Drive: https://drive.google.com/drive/folders/{export_result['folder_id']}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="YouTube Channel Cloner")
    subparsers = parser.add_subparsers(dest="command")

    # Pipeline completo
    full = subparsers.add_parser("full", help="Pipeline completo (Clerk → Niche → Scripts)")
    full.add_argument("url", help="URL do canal ou vídeo")
    full.add_argument("--niche", default="", help="Nicho pré-escolhido")
    full.add_argument("--scripts", type=int, default=3, help="Número de roteiros")

    # Clerk individual
    clerk = subparsers.add_parser("clerk", help="Apenas análise de concorrência")
    clerk.add_argument("url", help="URL do canal ou vídeo")
    clerk.add_argument("--name", default=None, help="Nome do output")

    # Niche Bender individual
    niche = subparsers.add_parser("niche", help="Apenas geração de nichos")
    niche.add_argument("--sop", default="", help="Caminho do SOP")
    niche.add_argument("--original", default="", help="Nicho original")
    niche.add_argument("--count", type=int, default=5, help="Número de nichos")

    # Script Stealer individual
    script = subparsers.add_parser("script", help="Apenas geração de roteiros")
    script.add_argument("--sop", default="", help="Caminho do SOP")
    script.add_argument("--niches", default="", help="Caminho do doc de nichos")
    script.add_argument("--niche", default="", help="Nicho escolhido")
    script.add_argument("--count", type=int, default=3, help="Número de roteiros")

    # Export individual
    export = subparsers.add_parser("export", help="Exportar arquivos para Google Drive/Docs/Sheets")
    export.add_argument("--name", default="YouTube Clone", help="Nome do projeto")
    export.add_argument("--sop", default="", help="Caminho do SOP")
    export.add_argument("--niches", default="", help="Caminho dos nichos")
    export.add_argument("--ideas", default="", help="Caminho das ideias")
    export.add_argument("--scripts", nargs="*", default=[], help="Caminhos dos roteiros")

    args = parser.parse_args()

    if args.command == "full":
        run_full_pipeline(args.url, args.niche, args.scripts)
    elif args.command == "clerk":
        run_clerk(args.url, args.name)
    elif args.command == "niche":
        run_niche_bender(args.sop, args.original, args.count)
    elif args.command == "script":
        run_script_stealer(args.sop, args.niches, args.niche, num_scripts=args.count)
    elif args.command == "export":
        files = {
            "sop": args.sop,
            "niches": args.niches,
            "ideas": args.ideas,
            "scripts": args.scripts,
        }
        export_project(args.name, files)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
