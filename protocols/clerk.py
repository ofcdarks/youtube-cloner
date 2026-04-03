"""
Protocol Clerk - Análise de Concorrência de Canais YouTube
Extrai transcrições, analisa estrutura de roteiros e gera SOPs.
"""

import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None
    print("Instale: pip install anthropic")


OUTPUT_DIR = Path(__file__).parent.parent / "output"


def extract_video_ids_from_channel(channel_url: str) -> list[str]:
    """Extrai IDs de vídeos de um canal usando yt-dlp."""
    import subprocess
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--print", "id", channel_url],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"Erro yt-dlp: {result.stderr}")
        return []
    return [vid.strip() for vid in result.stdout.strip().split("\n") if vid.strip()]


def extract_video_ids_from_input(input_str: str) -> list[str]:
    """Aceita URL de canal, lista de URLs de vídeos, ou arquivo com URLs."""
    video_ids = []

    if os.path.isfile(input_str):
        with open(input_str) as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line:
                vid = extract_single_video_id(line)
                if vid:
                    video_ids.append(vid)
        return video_ids

    if "/@" in input_str or "/channel/" in input_str or "/c/" in input_str:
        print(f"Detectado canal. Extraindo vídeos com yt-dlp...")
        return extract_video_ids_from_channel(input_str)

    vid = extract_single_video_id(input_str)
    if vid:
        return [vid]

    parts = [p.strip() for p in input_str.replace(",", "\n").split("\n") if p.strip()]
    for part in parts:
        vid = extract_single_video_id(part)
        if vid:
            video_ids.append(vid)

    return video_ids


def extract_single_video_id(url: str) -> str | None:
    """Extrai video ID de uma URL do YouTube."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_transcript(video_id: str, languages=("pt", "en", "es")) -> dict:
    """Busca transcrição de um vídeo."""
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=list(languages))
        full_text = " ".join(snippet.text for snippet in transcript.snippets)
        return {
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
            "transcript": full_text,
            "duration_seconds": transcript.snippets[-1].start + transcript.snippets[-1].duration if transcript.snippets else 0,
            "language": transcript.language,
            "status": "ok"
        }
    except Exception as e:
        return {
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
            "transcript": "",
            "error": str(e),
            "status": "error"
        }


def get_video_metadata(video_id: str) -> dict:
    """Busca metadados do vídeo via yt-dlp."""
    import subprocess
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", f"https://youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {
                "title": data.get("title", ""),
                "view_count": data.get("view_count", 0),
                "like_count": data.get("like_count", 0),
                "upload_date": data.get("upload_date", ""),
                "description": data.get("description", "")[:500],
                "duration": data.get("duration", 0),
                "channel": data.get("channel", ""),
            }
    except Exception:
        pass
    return {"title": f"Video {video_id}"}


def analyze_with_claude(transcripts: list[dict], metadata: list[dict]) -> dict:
    """Usa Claude para analisar transcrições e gerar SOPs."""
    client = Anthropic()

    combined = []
    for t, m in zip(transcripts, metadata):
        if t["status"] == "ok":
            views = m.get("view_count", "N/A")
            combined.append(
                f"### {m.get('title', t['video_id'])} | Views: {views}\n\n{t['transcript'][:8000]}"
            )

    if not combined:
        return {"error": "Nenhuma transcrição válida encontrada"}

    all_transcripts = "\n\n---\n\n".join(combined)

    prompt = f"""Você é um especialista em análise de canais do YouTube e engenharia reversa de roteiros virais.

Analise as transcrições abaixo e produza DOIS documentos:

## DOCUMENTO 1: SOP HUMANO
Um documento claro e detalhado para um roteirista humano entender o que faz esse canal funcionar. Inclua:

1. **VISÃO GERAL DO CANAL**: Nicho, público-alvo, estilo visual, frequência de postagem
2. **FÓRMULA DE TÍTULOS**: Padrões encontrados nos títulos (números, power words, estrutura)
3. **ESTRUTURA DE ROTEIRO**:
   - Como começam (hook dos primeiros 30 segundos)
   - Como mantêm atenção (open loops, cliffhangers)
   - Ritmo e pacing (quando mudam de assunto)
   - Como terminam (call to action)
4. **PLAYBOOK DE HOOKS**: Liste todos os tipos de ganchos usados com exemplos
5. **TÉCNICAS DE STORYTELLING**: Narrativa, personagens, conflito, resolução
6. **REGRAS DE OURO**: 5-10 regras que NUNCA são quebradas nesses roteiros

## DOCUMENTO 2: SOP PARA IA
Uma versão técnica e estruturada do mesmo conteúdo, formatada como instruções que uma IA deve seguir para escrever roteiros no mesmo estilo. Use formato de prompt/instrução com regras claras, templates e exemplos.

---

TRANSCRIÇÕES:

{all_transcripts}"""

    response = client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "analysis": response.content[0].text,
        "videos_analyzed": len(combined),
        "total_videos": len(transcripts),
    }


def run_clerk(input_str: str, output_name: str = None):
    """Executa o Protocol Clerk completo."""
    print("=" * 60)
    print("  PROTOCOL CLERK - Análise de Concorrência")
    print("=" * 60)

    # 1. Extrair video IDs
    print("\n[1/4] Extraindo IDs dos vídeos...")
    video_ids = extract_video_ids_from_input(input_str)
    if not video_ids:
        print("Nenhum vídeo encontrado. Verifique a URL/input.")
        return
    print(f"  Encontrados: {len(video_ids)} vídeos")

    # 2. Buscar metadados
    print("\n[2/4] Buscando metadados...")
    metadata = []
    for vid in video_ids:
        m = get_video_metadata(vid)
        metadata.append(m)
        title = m.get("title", vid)[:50]
        views = m.get("view_count", "?")
        print(f"  {title} | {views} views")

    # 3. Extrair transcrições
    print("\n[3/4] Extraindo transcrições...")
    transcripts = []
    for vid in video_ids:
        t = get_transcript(vid)
        transcripts.append(t)
        status = "OK" if t["status"] == "ok" else f"ERRO: {t.get('error', '?')}"
        print(f"  {vid}: {status}")

    ok_count = sum(1 for t in transcripts if t["status"] == "ok")
    if ok_count == 0:
        print("\nNenhuma transcrição extraída. Verifique se os vídeos têm legendas.")
        return

    # 4. Análise com Claude
    print(f"\n[4/4] Analisando {ok_count} transcrições com Claude...")
    result = analyze_with_claude(transcripts, metadata)

    if "error" in result:
        print(f"Erro: {result['error']}")
        return

    # Salvar resultado
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = output_name or f"clerk_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    sop_path = OUTPUT_DIR / f"{name}_sop.md"
    sop_path.write_text(result["analysis"], encoding="utf-8")

    data_path = OUTPUT_DIR / f"{name}_data.json"
    data = {
        "generated_at": datetime.now().isoformat(),
        "input": input_str,
        "videos": [
            {**m, "video_id": vid, "transcript_status": t["status"]}
            for vid, m, t in zip(video_ids, metadata, transcripts)
        ],
        "stats": {
            "total_videos": len(video_ids),
            "transcripts_ok": ok_count,
        }
    }
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  CONCLUÍDO!")
    print(f"  SOP salvo em: {sop_path}")
    print(f"  Dados salvos em: {data_path}")
    print(f"  Vídeos analisados: {ok_count}/{len(video_ids)}")
    print(f"{'=' * 60}")

    return {"sop_path": str(sop_path), "data_path": str(data_path), "analysis": result}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python clerk.py <URL_CANAL_OU_VIDEO> [nome_output]")
        print("Exemplos:")
        print("  python clerk.py https://youtube.com/@LoadedDice")
        print("  python clerk.py https://youtube.com/watch?v=ABC123")
        print("  python clerk.py videos.txt meu_canal")
        sys.exit(1)

    input_str = sys.argv[1]
    output_name = sys.argv[2] if len(sys.argv) > 2 else None
    run_clerk(input_str, output_name)
