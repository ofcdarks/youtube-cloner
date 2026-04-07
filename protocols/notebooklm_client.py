"""
NotebookLM Integration — Envia os 5 prompts ao notebook, espera resposta,
analisa e adapta o proximo. Extrai o DNA completo do canal.

Voce cria o notebook manualmente e adiciona as fontes.
O sistema conversa automaticamente usando os mesmos 5 scripts.

Auth: `notebooklm login`
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger("ytcloner.notebooklm")

STORAGE_DIR = Path.home() / ".notebooklm"


def is_available() -> bool:
    try:
        from notebooklm import NotebookLMClient
        return STORAGE_DIR.exists() and (STORAGE_DIR / "storage_state.json").exists()
    except ImportError:
        return False


def get_status() -> dict:
    try:
        from notebooklm import NotebookLMClient
    except ImportError:
        return {"installed": False, "authenticated": False, "error": "notebooklm-py nao instalado"}

    storage_file = STORAGE_DIR / "storage_state.json"
    if not storage_file.exists():
        return {"installed": True, "authenticated": False, "error": "Execute: notebooklm login"}

    return {"installed": True, "authenticated": True, "storage_path": str(storage_file)}


async def list_notebooks() -> list[dict]:
    from notebooklm import NotebookLMClient
    async with await NotebookLMClient.from_storage() as client:
        notebooks = await client.notebooks.list()
        return [{"id": nb.id, "title": nb.title} for nb in notebooks]


async def ask(notebook_id: str, question: str) -> str:
    from notebooklm import NotebookLMClient
    async with await NotebookLMClient.from_storage() as client:
        response = await client.chat.ask(notebook_id, question)
        return response.answer if hasattr(response, "answer") else str(response)


# ── Os 5 prompts (mesmos do dashboard) ───────────────────

def _build_prompts(niche_name: str) -> list[dict]:
    """Build the 5 extraction prompts. Same as the manual ones."""
    return [
        {
            "key": "parte1_dna_formato",
            "label": "Parte 1/6 — Autopsia do Canal (DNA + Formato)",
            "prompt": f"""PARTE 1 de 6 — AUTOPSIA DO CANAL

Faca uma analise EXTREMAMENTE DETALHADA deste canal para criar um SOP de replicacao no nicho "{niche_name}".

1. IDENTIDADE PROFUNDA
- Nicho EXATO e sub-nicho (seja especifico, nao generico)
- Publico-alvo: idade, genero, interesses, DORES e DESEJOS
- Proposta de valor UNICA: por que assistir ESTE canal?
- Tom de voz: CITE 5 frases que exemplificam o tom
- Persona do narrador: quem "fala"? Como se posiciona?
- CITE 10 expressoes/palavras tipicas do canal

2. FORMATO E PRODUCAO
- Tipo: faceless/talking head/animacao/misto?
- Duracao MEDIA real dos videos analisados
- Estilo visual dominante e tipo de B-roll
- Edicao: frequencia de cortes, transicoes, text overlays
- Musica e sound design: genero, quando muda, efeitos sonoros
- Narrador: voz humana/IA? Ritmo? Entonacao?

IMPORTANTE: Use exemplos REAIS dos videos. Cite trechos especificos. Nao generalize.""",
        },
        {
            "key": "parte2_roteiro_hooks",
            "label": "Parte 2/6 — Engenharia de Roteiro + Hooks",
            "prompt": f"""PARTE 2 de 6 — ENGENHARIA DE ROTEIRO

3. ANATOMIA DO ROTEIRO (analise 5+ videos)
- HOOK (0-5s): Liste a PRIMEIRA FRASE de cada video analisado
- HOOK EXPANDIDO (5-30s): Como constroem a promessa? 5 exemplos reais
- CONTEXTO (30s-2min): Como fazem o setup?
- DESENVOLVIMENTO: Quantos atos? Progressao de tensao?
- CLIMAX: Como constroem o ponto alto?
- CTA: Frase exata? Em que momento?

4. PLAYBOOK DE HOOKS — para cada tipo, 3 exemplos REAIS:
a) CHOQUE ("Ele perdeu $200M em 3h")
b) CURIOSIDADE ("O que acontece quando...")
c) PERGUNTA IMPOSSIVEL ("Como um estagiario hackeou...")
d) NUMERO IMPACTANTE ("$1.7 bilhao desapareceu")
e) CONTRASTE ("De morador de rua a bilionario")
f) URGENCIA ("Isso esta acontecendo AGORA")
g) SEGREDO ("O metodo que bancos escondem")
h) IMERSAO/POV ("Voce acorda e percebe que...")
i) Outros tipos que o canal usa

Cite o TEXTO EXATO de cada hook encontrado.""",
        },
        {
            "key": "parte3_storytelling_regras",
            "label": "Parte 3/6 — Storytelling + Regras de Ouro",
            "prompt": """PARTE 3 de 6 — STORYTELLING + REGRAS DE OURO

5. TECNICAS DE STORYTELLING — 5 exemplos CONCRETOS de cada:
- OPEN LOOPS: misterios plantados que resolvem depois. Cite o trecho exato e quando resolve.
- PATTERN INTERRUPTS: quebras de expectativa. A cada quantos minutos acontecem?
- CLIFFHANGERS INTERNOS: ganchos entre secoes. Cite frases exatas.
- SPECIFIC SPIKES: picos emocionais. Em que minuto? O que causa?
- ARCO EMOCIONAL: mapeie como a emocao muda (curiosidade→tensao→choque→reflexao)
- RITMO: quando acelera/desacelera? Frases curtas=tensao, longas=contexto
- TRANSICOES: liste 10 frases de transicao reais usadas entre secoes

6. REGRAS DE OURO (15 regras):
Regras de ABERTURA (primeiros 30s):
Regras de MEIO (corpo):
Regras de FECHAMENTO:
Regras de LINGUAGEM (palavras que SEMPRE usa + NUNCA usa):
ANTI-PATTERNS (o que NUNCA fazem):

Seja detalhado. Cada regra com exemplo real.""",
        },
        {
            "key": "parte4_estrategia_competitivo",
            "label": "Parte 4/6 — Estrategia + Inteligencia Competitiva",
            "prompt": f"""PARTE 4 de 6 — ESTRATEGIA + INTELIGENCIA COMPETITIVA

7. PILARES DE CONTEUDO: 5-7 categorias com nome, %, 3 exemplos reais, qual performa melhor

8. FORMULA DE TITULOS: padroes repetidos, palavras de poder, 10 melhores titulos reais, template + 5 exemplos para "{niche_name}"

9. THUMBNAIL (resumo rapido — analise profunda vem na Parte 6): paleta hex dominante, familia tipografica, padrao de composicao (hero left/center/right), uso de rosto humano, densidade de texto

10. SEO: tags, descricao template, hashtags, end screens, playlists, frequencia/timing

11. MONETIZACAO: AdSense estimado, sponsors, afiliados, funil de vendas, RPM do nicho

12. RETENCAO: momentos onde espectador SAI (valleys), tecnicas anti-dropout, curva de retencao esperada

13. COMPETIDORES: 5 canais similares, diferencial competitivo, "molho secreto", gaps de conteudo

14. EVOLUCAO: como o canal mudou ao longo do tempo? Que ajustes funcionaram? Que erros cometeram?

Use evidencias reais para cada ponto.""",
        },
        {
            "key": "parte5_sop_ia_template",
            "label": "Parte 5/6 — Manual de Replicacao para IA",
            "prompt": """PARTE 5 de 6 — MANUAL DE REPLICACAO PARA IA

15. SYSTEM PROMPT COMPLETO (300+ palavras) para IA gerar roteiros identicos:
- Persona com backstory
- Tom de voz com exemplos "faca" vs "NAO faca"
- Estrutura com tempos exatos
- 30 palavras do vocabulario frequente
- 15 palavras PROIBIDAS
- Como criar open loops, pausas, transicoes
- Exemplo de PARAGRAFO no estilo exato (100 palavras)
- Exemplo de HOOK no estilo exato (3 frases)
- Exemplo de FECHAMENTO no estilo exato

16. TEMPLATE DE ROTEIRO preenchivel:
[HOOK 0:00-0:05] Frase de impacto: ___
[HOOK EXPANDIDO 0:05-0:30] Expansao + open loop 1: ___
[CONTEXTO 0:30-2:00] Setup + dado ancora: ___
[ATO 1 2:00-5:00] Desenvolvimento + open loop 2: ___
[ATO 2 5:00-8:00] Escalada + specific spike: ___
[CLIMAX 8:00-10:00] Revelacao + resolve open loop 1: ___
[RESOLUCAO 10:00-11:00] Reflexao + resolve open loop 2: ___
[CTA 11:00-12:00] CTA natural + gancho proximo video: ___

17. CHECKLIST — 15 perguntas SIM/NAO:
O hook prende em 5s? Tem 3+ open loops? Tom consistente? Spikes a cada 2-3min? CTA natural? Vocabulario no padrao? Ritmo alterna curto/longo? Duracao na media? Poderia ser confundido com video real do canal?

INSTRUCAO: Minimo 1500 palavras nesta parte. Cada exemplo deve ser ESCRITO por voce no estilo exato do canal.""",
        },
        {
            "key": "parte6_thumbs_alto_ctr",
            "label": "Parte 6/6 — Biblioteca de Thumbs de Alto CTR",
            "prompt": f"""PARTE 6 de 6 — BIBLIOTECA DE THUMBS DE ALTO CTR

Analise visual EXTREMAMENTE DETALHADA das thumbnails do canal + concorrentes do nicho "{niche_name}". Objetivo: recriar thumbs que gerem CTR >= 8% desde o primeiro video.

1. TOP 10 THUMBS DO CANAL ORIGINAL (da mais clicavel pra menos). Para CADA uma:
- Titulo exato do video
- Views aproximadas (se souber)
- COMPOSICAO: posicao do hero subject (left/center/right), tamanho relativo em % do frame, POV (close/medio/wide), angulo
- BACKGROUND: cenario, profundidade, luz (god rays, golden hour, neon, fogo, neblina)
- PERSONAGEM (se houver): expressao facial, direcao do olhar, roupa/armadura/uniforme, etnia/genero, era historica
- TEXTO OVERLAY: palavras exatas, numero de palavras, fonte (serif/sans/marker/handwritten), peso, cor principal + outline, tamanho relativo, posicao
- PALETA DOMINANTE: 3 cores em HEX + mood (quente/frio/neutro)
- ELEMENTOS GRAFICOS: setas, circulos, highlights, particulas, lens flare, grain
- PSYCHOLOGY HOOK: o que faz essa thumb ser clicavel em 1 frase (curiosity gap, face reaction, contraste brutal, misterio, stakes altos...)

2. PADROES REPETIDOS (o que se repete em 80%+ das thumbs do canal):
- Arquetipo visual dominante (ex: "heroi em 3/4 view + background epico + texto serif dourado")
- Paleta mestre: 3-5 cores hex que aparecem em quase todas
- Familia tipografica identificada (nome especifico se possivel: Trajan, Cinzel, Impact, Permanent Marker...)
- Regra de composicao (tercos, centralizado, assimetrico)
- % que usam rosto humano close-up vs cena ampla
- % que usam texto vs so imagem
- Numero medio de palavras no texto (se houver)

3. TOP 5 THUMBS DE CONCORRENTES DIRETOS do nicho (canais similares, mesmo publico, CTR comprovado). Para cada: mesma analise do item 1, MAIS o que elas fazem DIFERENTE do canal original e se esse diferencial e vantagem ou risco.

4. PALETA MESTRE CONSOLIDADA — 5 cores em HEX com funcao:
- Primary (dominante em fundos/grandes areas)
- Secondary (contraste/sombra)
- Accent (texto/highlight principal)
- Warning (alertas, perigo, stakes — geralmente vermelho/laranja)
- Neutral (branco/creme/preto pra respiro)

5. TIPOGRAFIA MESTRE — 2 fontes (primaria pro titulo grande, secundaria pro subtitulo/tag). Nome da fonte, peso, estilo. Se nao conseguir identificar a exata, cite a familia (ex: "serif condensada tipo Trajan Pro").

6. 5 TEMPLATES REPRODUZIVEIS — descreva 5 layouts que o canal repete e que eu posso recriar pra qualquer novo titulo:
- Template nome (ex: "Hero + Serif Gold")
- Descricao visual em 3 frases
- Para que tipo de titulo funciona (ex: "titulos com nome de personagem historico")
- Elementos fixos (posicao do texto, paleta, arquetipo)
- Elementos variaveis (o que muda de video pra video)

7. ANTI-PADROES — liste 5 coisas que o canal NUNCA faz nas thumbs (ex: "nunca usa emoji", "nunca usa fundo branco", "nunca centraliza o rosto").

8. PROMPT BASE EM INGLES pra gerar novas thumbs (ImageFX/Midjourney/DALL-E) que replique o estilo exato do canal. Deve incluir: "cinematic movie poster YouTube thumbnail 1280x720", estilo, paleta, arquetipo, iluminacao, mood, "NO LOGO NO WATERMARK". ~80 palavras.

IMPORTANTE: cite numeros, cores HEX reais, fontes especificas. Nada generico. Se nao tiver certeza da fonte, diga "familia serif condensada" em vez de inventar. Minimo 1500 palavras nesta parte.""",
        },
    ]


def _build_followup(part_key: str, response_text: str, niche_name: str) -> str | None:
    """Analyze a response and generate a follow-up if data is thin."""
    word_count = len(response_text.split())

    # If response is too short, ask for more detail
    if word_count < 300:
        return (
            f"Sua resposta sobre {part_key} ficou curta ({word_count} palavras). "
            f"Preciso de MUITO mais detalhes. Reanalise as fontes e expanda com: "
            f"- Mais exemplos REAIS e especificos "
            f"- Citacoes diretas dos videos "
            f"- Dados numericos (views, duracao, frequencia) "
            f"Minimo 800 palavras."
        )

    # Check for missing RPM in part 4
    if part_key == "parte4_estrategia_competitivo":
        if not re.search(r'\$\d+', response_text):
            return (
                "Voce nao incluiu o RPM estimado em dolares. "
                "Qual o RPM estimado deste nicho? Responda no formato $X-$Y "
                "e explique como chegou nesse valor."
            )

    return None


async def extract_dna(notebook_id: str, niche_name: str = "Canal") -> dict:
    """Send all 5 prompts sequentially, wait for each response, adapt if needed.

    Returns dict with all responses keyed by prompt key.
    """
    prompts = _build_prompts(niche_name)
    results = {}

    for i, p in enumerate(prompts):
        key = p["key"]
        label = p["label"]
        prompt_text = p["prompt"]

        logger.info(f"[NLM DNA {i+1}/5] Enviando: {label}")

        try:
            # Send prompt and get response
            response = await ask(notebook_id, prompt_text)
            results[key] = {
                "label": label,
                "content": response,
                "words": len(response.split()),
            }
            logger.info(f"[NLM DNA {i+1}/5] Resposta: {len(response.split())} palavras")

            # Check if we need a follow-up
            followup = _build_followup(key, response, niche_name)
            if followup:
                logger.info(f"[NLM DNA {i+1}/5] Follow-up necessario, enviando...")
                followup_response = await ask(notebook_id, followup)
                # Append follow-up to the original response
                results[key]["content"] += f"\n\n---\n\n### DETALHES ADICIONAIS:\n\n{followup_response}"
                results[key]["words"] = len(results[key]["content"].split())
                results[key]["had_followup"] = True

        except Exception as e:
            logger.error(f"[NLM DNA {i+1}/5] Erro: {e}")
            results[key] = {
                "label": label,
                "content": f"Erro: {str(e)[:200]}",
                "words": 0,
            }

    return results


def compile_sop(dna: dict, niche_name: str = "") -> str:
    """Compile all 6 responses into a single SOP document."""
    sections = []
    sections.append(f"# SOP COMPLETO — {niche_name or 'Canal Analisado'}")
    sections.append("Gerado via NotebookLM Deep Analysis (6 prompts sequenciais)\n")

    order = [
        "parte1_dna_formato",
        "parte2_roteiro_hooks",
        "parte3_storytelling_regras",
        "parte4_estrategia_competitivo",
        "parte5_sop_ia_template",
        "parte6_thumbs_alto_ctr",
    ]

    total_words = 0
    for key in order:
        if key in dna:
            entry = dna[key]
            label = entry.get("label", key)
            content = entry.get("content", "")
            words = entry.get("words", 0)
            total_words += words
            if content and not content.startswith("Erro:"):
                sections.append(f"\n---\n\n## {label}\n\n{content}")

    sections.append(f"\n---\n\n*Total: {total_words} palavras | {len([k for k in order if k in dna and not dna[k].get('content','').startswith('Erro:')])} de 6 partes extraidas*")

    return "\n".join(sections)


def extract_rpm(dna: dict) -> str:
    """Extract RPM value from the strategy/monetization response."""
    for key in ("parte4_estrategia_competitivo", "parte1_dna_formato"):
        content = dna.get(key, {}).get("content", "")
        if content:
            m = re.search(r'\$(\d+)\s*[-–]\s*\$?(\d+)', content)
            if m:
                return f"${m.group(1)}-${m.group(2)}"
    return ""


def extract_schedule(dna: dict) -> dict:
    """Extract schedule info from DNA responses."""
    schedule = {
        "frequency": "", "best_days": "",
        "best_times": "", "video_duration": "",
    }

    content = dna.get("parte1_dna_formato", {}).get("content", "").lower()

    m = re.search(r'(\d+[-–]\d+\s*(?:videos?|v[ií]deos?)\s*/?\s*(?:semana|week))', content)
    if m:
        schedule["frequency"] = m.group(1)

    m = re.search(r'dura[cç][aã]o\s*(?:m[eé]dia)?[:\s]*(\d+[-–]\d+\s*(?:min|minutos?))', content)
    if m:
        schedule["video_duration"] = m.group(1)

    return schedule
