"""
Channel Strategist — The AI brain that coordinates everything.

Takes NotebookLM responses (5 parts), analyzes, cross-references,
fills gaps, and produces a complete channel launch strategy.

This is where Claude processes the raw data and makes strategic decisions.
"""

import re
import json
import logging
from datetime import date, timedelta

logger = logging.getLogger("ytcloner.strategist")


def analyze_and_build_strategy(
    dna: dict,
    niche_name: str,
    channel_url: str = "",
    ai_chat_fn=None,
) -> dict:
    """Take the 5 NLM responses and build a complete channel strategy.

    Args:
        dna: dict from extract_dna() with all 5 parts
        niche_name: chosen niche name
        channel_url: original channel URL
        ai_chat_fn: function(prompt, system) -> str for AI calls

    Returns complete strategy dict with all sections.
    """
    # ── 1. Compile raw SOP from NLM responses ──
    from protocols.notebooklm_client import compile_sop
    raw_sop = compile_sop(dna, niche_name)

    # ── 2. Extract key metrics from responses ──
    metrics = _extract_metrics(dna)

    # ── 3. If we have an AI function, enhance the strategy ──
    enhanced_sop = raw_sop
    launch_plan = None
    channel_identity = None
    first_titles = None

    if ai_chat_fn:
        # Use Claude to analyze the NLM data and fill gaps
        enhanced_sop = _enhance_sop(raw_sop, niche_name, metrics, ai_chat_fn)
        launch_plan = _generate_launch_plan(raw_sop, niche_name, metrics, ai_chat_fn)
        channel_identity = _generate_channel_identity(raw_sop, niche_name, metrics, ai_chat_fn)
        first_titles = _generate_first_titles(raw_sop, niche_name, metrics, ai_chat_fn)

    return {
        "raw_sop": raw_sop,
        "enhanced_sop": enhanced_sop,
        "metrics": metrics,
        "launch_plan": launch_plan,
        "channel_identity": channel_identity,
        "first_titles": first_titles,
        "niche_name": niche_name,
        "channel_url": channel_url,
    }


def _extract_metrics(dna: dict) -> dict:
    """Extract quantifiable metrics from all NLM responses."""
    all_text = " ".join(e.get("content", "") for e in dna.values()).lower()

    metrics = {}

    # RPM
    m = re.search(r'\$(\d+)\s*[-–]\s*\$?(\d+)', all_text)
    if m:
        metrics["rpm"] = f"${m.group(1)}-${m.group(2)}"

    # Duration
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:min|minutos)', all_text)
    if m:
        metrics["duration"] = f"{m.group(1)}-{m.group(2)} min"

    # Views
    m = re.search(r'(\d+[\d,.]*\s*[mkb]?\s*(?:views|visualiza))', all_text)
    if m:
        metrics["views"] = m.group(1).strip()

    # Frequency
    m = re.search(r'(\d+[-–]\d+\s*(?:videos?|v[ií]deos?)\s*/?\s*(?:semana|week))', all_text)
    if m:
        metrics["frequency"] = m.group(1)

    # Word counts per section
    metrics["total_words"] = sum(e.get("words", 0) for e in dna.values())
    metrics["parts_ok"] = sum(1 for e in dna.values() if not e.get("content", "").startswith("Erro:"))

    return metrics


def _enhance_sop(raw_sop: str, niche_name: str, metrics: dict, chat_fn) -> str:
    """Use Claude to analyze the raw SOP and fill gaps."""
    prompt = f"""Voce e um estrategista de YouTube que acabou de receber uma analise bruta de um canal de sucesso.

ANALISE BRUTA (do NotebookLM):
{raw_sop[:12000]}

NICHO ALVO: {niche_name}
METRICAS EXTRAIDAS: {json.dumps(metrics, ensure_ascii=False)}

Sua tarefa: REESCREVA este SOP de forma ESTRUTURADA e ACIONAVEL.

Organize em secoes claras:
1. VISAO GERAL (nicho, publico, proposta de valor)
2. FORMULA DE TITULOS (padrao + 5 templates)
3. ESTRUTURA DO ROTEIRO (timing exato de cada secao)
4. PLAYBOOK DE HOOKS (top 5 tipos com template)
5. REGRAS DE OURO (10 regras numeradas)
6. ESTILO DE PRODUCAO (visual, audio, edicao)
7. MONETIZACAO (RPM, fontes de receita)
8. INSTRUCOES PARA IA (system prompt para gerar roteiros)

IMPORTANTE:
- Mantenha TODOS os dados reais e exemplos do original
- Preencha gaps onde a analise ficou vaga
- Adicione metricas concretas onde faltam
- O resultado deve ser COMPLETO o suficiente para alguem criar o canal do ZERO"""

    system = "Voce e um estrategista senior de YouTube. Reescreva SOPs de forma clara, estruturada e acionavel."
    return chat_fn(prompt, system)


def _generate_launch_plan(raw_sop: str, niche_name: str, metrics: dict, chat_fn) -> str:
    """Generate a launch plan for the first 30 days."""
    duration = metrics.get("duration", "10-12 min")
    frequency = metrics.get("frequency", "2-3 videos/semana")

    today = date.today()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(30)]

    prompt = f"""Baseado neste SOP de canal YouTube, crie um PLANO DE LANCAMENTO para os primeiros 30 dias.

SOP (resumo):
{raw_sop[:6000]}

NICHO: {niche_name}
DURACAO DOS VIDEOS: {duration}
FREQUENCIA: {frequency}
DATA DE INICIO: {today.isoformat()}

Crie:

## SEMANA 1 (Pre-lancamento)
- Dia 1-3: O que preparar antes do primeiro video
- Dia 4-5: Setup do canal (nome, banner, descricao, playlists)
- Dia 6-7: Primeiro video (qual tema? por que esse primeiro?)

## SEMANA 2-4 (Lancamento)
Para cada video planejado:
- DATA DE POSTAGEM
- TITULO (seguindo a formula do SOP)
- HOOK (primeiros 30 segundos)
- DURACAO ALVO
- HORARIO DE POSTAGEM
- PILAR DE CONTEUDO

## METAS DO PRIMEIRO MES
- Videos publicados: X
- Views esperadas: X
- Inscritos esperados: X
- Watch time medio esperado: X

## ESTRATEGIA DE CRESCIMENTO
- Como ganhar tracao nos primeiros 10 videos
- Shorts/Reels como complemento?
- Colaboracoes/comunidade
- SEO dos primeiros videos

Seja ESPECIFICO com datas, titulos e horarios reais."""

    system = "Voce cria planos de lancamento detalhados para canais YouTube. Seja especifico com datas e metricas."
    return chat_fn(prompt, system)


def _generate_channel_identity(raw_sop: str, niche_name: str, metrics: dict, chat_fn) -> str:
    """Generate complete channel identity."""
    prompt = f"""Baseado neste SOP, crie a IDENTIDADE COMPLETA do canal "{niche_name}".

SOP (resumo):
{raw_sop[:4000]}

Entregue:

## 1. NOME DO CANAL
- 5 opcoes de nome (criativos, memoraveis, com SEO)
- Para cada: nome + por que funciona

## 2. DESCRICAO DO CANAL (About)
- Versao curta (1 linha — para pesquisa)
- Versao completa (para a pagina About)

## 3. BANNER E AVATAR
- Prompt para gerar banner no Midjourney/DALL-E
- Prompt para gerar avatar/logo
- Cores dominantes (hex codes)
- Tipografia recomendada

## 4. PLAYLISTS INICIAIS
- 5 playlists com nome e descricao
- Baseadas nos pilares de conteudo do SOP

## 5. TAGS DO CANAL
- 20 tags otimizadas para SEO

## 6. LINKS E REDES
- Descricao para cada rede social
- Bio para Instagram/TikTok/X

## 7. BRANDING
- Tom de voz em 3 palavras
- Frase de efeito / tagline
- Cores primaria e secundaria (hex)
- Estilo visual em uma frase"""

    system = "Voce cria identidades visuais e estrategicas para canais YouTube. Seja criativo mas comercialmente viavel."
    return chat_fn(prompt, system)


def _generate_first_titles(raw_sop: str, niche_name: str, metrics: dict, chat_fn) -> str:
    """Generate the first 10 video titles with hooks, ordered strategically."""
    prompt = f"""Baseado neste SOP, gere os PRIMEIROS 10 VIDEOS do canal "{niche_name}".

SOP (resumo):
{raw_sop[:6000]}

REGRAS:
- Os titulos DEVEM seguir EXATAMENTE a formula de titulos do SOP
- O VIDEO 1 deve ser o mais VIRAL possivel (porta de entrada)
- Os videos 2-5 devem cobrir pilares diferentes
- Videos 6-10 devem aprofundar o pilar que mais performa
- Ordem ESTRATEGICA: comece com temas de alto volume de busca

Para CADA video:
1. **NUMERO**: #1, #2, etc
2. **TITULO**: seguindo a formula exata
3. **HOOK (30s)**: texto completo dos primeiros 30 segundos
4. **POR QUE ESSE VIDEO NESSA POSICAO**: justificativa estrategica
5. **PILAR**: qual pilar de conteudo
6. **DURACAO ALVO**: baseado no SOP
7. **PRIORIDADE**: ALTA/MEDIA
8. **POTENCIAL DE BUSCA**: estimativa de demanda

Organize do video 1 ao 10 na ordem que devem ser publicados."""

    system = "Voce e um estrategista de conteudo YouTube. Gere titulos que seguem exatamente o padrao do SOP."
    return chat_fn(prompt, system)
