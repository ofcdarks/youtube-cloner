"""
AI Client - Usa laozhang.ai (OpenAI-compatible) para gerar conteudo.

Features:
- Timeout configuravel (default 120s)
- Retry automatico com backoff exponencial (3 tentativas)
- Structured logging
"""

import os
import json
import time
import logging
import requests
from pathlib import Path

logger = logging.getLogger("ytcloner.ai_client")

try:
    from config import LAOZHANG_API_KEY as API_KEY, LAOZHANG_BASE_URL as BASE_URL, AI_MODEL as MODEL
except ImportError:
    API_KEY = os.environ.get("LAOZHANG_API_KEY", "")
    BASE_URL = os.environ.get("LAOZHANG_BASE_URL", "https://api.laozhang.ai/v1")
    MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds — exponential: 2, 4, 8
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def chat(prompt: str, system: str = "", model: str = None, max_tokens: int = 8000, temperature: float = 0.7, timeout: int = 120) -> str:
    """Envia prompt para a API e retorna resposta.

    Args:
        prompt: User prompt text
        system: Optional system prompt
        model: Model override (default from AI_MODEL env)
        max_tokens: Max response tokens
        temperature: Sampling temperature
        timeout: Request timeout in seconds (default 180)

    Returns:
        AI response text

    Raises:
        ValueError: If API key is not configured
        Exception: On API errors after all retries exhausted
    """
    if not API_KEY:
        raise ValueError("LAOZHANG_API_KEY nao configurada. Adicione no EasyPanel ou como variavel de ambiente.")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    used_model = model or MODEL
    last_error = None
    _fallback_attempted = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"[AI] Request attempt {attempt}/{MAX_RETRIES}: model={used_model}, max_tokens={max_tokens}, prompt_len={len(prompt)}")

            response = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": used_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=timeout,
            )

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # Track token usage
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

                # Estimate cost (approximate — varies by model)
                cost = 0.0
                if "claude" in used_model.lower():
                    cost = (prompt_tokens * 3 + completion_tokens * 15) / 1_000_000  # Claude Sonnet pricing
                elif "gpt-4" in used_model.lower():
                    cost = (prompt_tokens * 2.5 + completion_tokens * 10) / 1_000_000
                elif "gpt-3" in used_model.lower() or "mini" in used_model.lower():
                    cost = (prompt_tokens * 0.15 + completion_tokens * 0.6) / 1_000_000

                try:
                    from database import log_ai_usage
                    log_ai_usage(model=used_model, prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens, estimated_cost=cost,
                                operation="chat")
                except Exception:
                    pass

                logger.info(f"[AI] Success on attempt {attempt}: response_len={len(content)}, tokens={total_tokens}, cost=${cost:.4f}")
                return content

            # Check if retryable
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"[AI] Retryable error {response.status_code} on attempt {attempt}. Waiting {wait_time}s...")
                time.sleep(wait_time)
                last_error = f"API error {response.status_code}: {response.text[:300]}"
                continue

            # Model not found / Bedrock error → auto-fallback to gpt-4o
            if response.status_code == 400 and not _fallback_attempted:
                resp_text = response.text[:500]
                if "model identifier is invalid" in resp_text or "InvokeModel" in resp_text or "bedrock" in resp_text.lower():
                    _fallback_attempted = True
                    logger.warning(f"[AI] Model '{used_model}' rejected by provider. Falling back to gpt-4o")
                    used_model = "gpt-4o"
                    continue

            # Non-retryable error
            raise Exception(f"API error {response.status_code}: {response.text[:500]}")

        except requests.exceptions.Timeout:
            last_error = f"Request timeout after {timeout}s"
            if attempt < MAX_RETRIES:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"[AI] Timeout on attempt {attempt}. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise Exception(f"API timeout after {MAX_RETRIES} attempts ({timeout}s each)")

        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {str(e)[:200]}"
            if attempt < MAX_RETRIES:
                wait_time = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"[AI] Connection error on attempt {attempt}. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise Exception(f"API connection failed after {MAX_RETRIES} attempts: {last_error}")

    # Should not reach here, but just in case
    raise Exception(f"API failed after {MAX_RETRIES} attempts. Last error: {last_error}")


# ── Per-project script overrides ─────────────────────────────────────
# Maps project name (uppercase) to script generation parameters.
_SCRIPT_OVERRIDES = {
    "RELATOS FAMILIARES": {
        "duration_minutes": 50,
        "min_words": 7000,
        "max_words": 10000,
        "max_tokens": 16000,
        "temperature": 0.75,
        "timeout": 300,
        "forbidden_words": [
            "berrei", "espancei", "surtei", "perdoei", "reconciliação",
            "pena", "abraçamos", "voltamos", "esqueci", "perdi a cabeça",
            "descontrole", "bati", "agressão", "choraminguei",
        ],
        "mandatory_vocab": [
            "advogado", "silêncio", "pasta de documentos", "escritura",
            "cartório", "extrato", "testamento", "herança", "patrimônio",
            "provas irrefutáveis",
        ],
    },
}


def generate_script(title: str, hook: str, sop: str, niche: str = "System Breakers",
                    language: str = "pt-BR", project_name: str = "") -> str:
    """Gera um roteiro completo para um titulo.

    Supports per-project overrides for duration, word count, and style rules
    via the _SCRIPT_OVERRIDES dict.
    """

    from config import LANG_LABELS
    lang_label = LANG_LABELS.get(language, language)

    # Lookup per-project override
    override = _SCRIPT_OVERRIDES.get(project_name.upper().strip(), {})
    duration_min = override.get("duration_minutes", 12)
    min_words = override.get("min_words", 1500)
    max_words = override.get("max_words", 1800)
    max_tok = override.get("max_tokens", 8000)
    temp = override.get("temperature", 0.7)
    tout = override.get("timeout", 120)
    forbidden = override.get("forbidden_words", [])
    mandatory = override.get("mandatory_vocab", [])

    system = f"""Voce e um roteirista profissional de YouTube especializado em canais faceless de storytelling.
Voce escreve roteiros cinematicos, dramaticos, com narrativa envolvente que prende o espectador do inicio ao fim.
Seus roteiros sao otimizados para narracao em voz (TTS) - sem marcacoes tecnicas no texto da narracao.
Escreva SEMPRE em {lang_label}."""

    # Build structure block — long-form vs standard
    if duration_min >= 30:
        structure_block = f"""O roteiro deve seguir este fluxo CORRIDO (NAO divida em cenas numeradas).
Duracao alvo: {duration_min} MINUTOS ({min_words}-{max_words} palavras de narracao).

1. **HOOK** (0:00-0:30) - Frase de choque maximo. Sem introducoes.
2. **HOOK EXPANDIDO** (0:30-2:00) - Aprofunde a dor. Open loop 1.
3. **CONTEXTO** (2:00-5:00) - Nome, idade, rotina de sacrificio. Humanize o protagonista.
4. **ATO 1 - A INOCENCIA TRAIDA** (5:00-12:00) - MINIMO 5 micro-humilhacoes detalhadas.
   Cada humilhacao deve ser uma CENA completa com dialogo, ambiente e reacao interna.
5. **ATO 2 - O SILENCIO ESTRATEGICO** (12:00-22:00) - Protagonista finge nao saber.
   Contrata advogados em segredo. Reune provas. Open loops 2 e 3.
   INCLUA: reunioes com advogado, visitas ao cartorio, obtencao de documentos.
6. **ATO 3 - A ARMADILHA ARMADA** (22:00-32:00) - O antagonista tenta o golpe final.
   Protagonista deixa acontecer. Tensao cresce a cada paragrafo.
   Pattern Interrupt obrigatorio neste ponto.
7. **CLIMAX - O CONFRONTO DOCUMENTADO** (32:00-42:00) - Humilhacao PUBLICA do antagonista.
   OBRIGATORIO: acontece em ambiente PUBLICO (jantar, assembleia, cartorio, casamento).
   Protagonista coloca pasta de documentos na mesa. Voz baixa. Frieza absoluta.
   Antagonista empalidece. Silencio ensurdecedor.
8. **RESOLUCAO** (42:00-47:00) - Destruicao financeira completa do antagonista.
   Consequencias legais. O que perderam. Quem ficou sem nada.
9. **REFLEXAO + CTA** (47:00-{duration_min}:00) - Licao moral fria.
   "Se voce chegou ate aqui..." CTA organico. Filosofia do silencio."""
    else:
        structure_block = f"""O roteiro deve seguir este fluxo CORRIDO (NAO divida em cenas numeradas).
Duracao alvo: {duration_min} MINUTOS ({min_words}-{max_words} palavras).

1. **HOOK** (0:00-0:30) - Primeiros 30 segundos, capturar atencao imediata
2. **CONTEXTO** (0:30-2:30) - Setup da historia, epoca, personagens
3. **ATO 1 - A DESCOBERTA** (2:30-4:30) - Como tudo comecou
4. **ATO 2 - A EXECUCAO** (4:30-6:30) - O que aconteceu, como funcionou
5. **ATO 3 - O CAOS** (6:30-8:00) - Consequencias, reacoes, perseguicao
6. **CLIMAX** (8:00-9:30) - Momento mais impactante, revelacao final
7. **RESOLUCAO** (9:30-10:30) - O que aconteceu depois, licoes
8. **CTA** (10:30-11:00) - Call to action natural"""

    # Build forbidden/mandatory blocks
    rules_extra = ""
    if forbidden:
        rules_extra += "\n\nPALAVRAS PROIBIDAS (NUNCA use — se aparecerem o roteiro sera REJEITADO):\n"
        rules_extra += ", ".join(f'"{w}"' for w in forbidden)
    if mandatory:
        rules_extra += "\n\nVOCABULARIO OBRIGATORIO (use PELO MENOS 60% destas palavras no roteiro):\n"
        rules_extra += ", ".join(mandatory)

    prompt = f"""Escreva um roteiro COMPLETO de {duration_min} minutos para o canal "{niche}".

TITULO: {title}
HOOK: {hook}

{structure_block}

REGRAS OBRIGATORIAS (do SOP):
- Use OPEN LOOPS (misterios que so se resolvem depois) — MINIMO 4
- Use PATTERN INTERRUPTS (quebras de expectativa) — MINIMO 2
- Use SPECIFIC SPIKES (momentos de pico de tensao) a cada 3-5 minutos
- Inclua [B-ROLL: descricao visual] para o animador
- Inclua [PAUSA DRAMATICA] nos momentos certos
- Numeros grandes devem causar impacto
- Cada secao deve terminar com um gancho para a proxima
- O roteiro deve ter aproximadamente {min_words}-{max_words} palavras de narracao
- Escreva o roteiro como texto CORRIDO — NUNCA como lista de cenas{rules_extra}

SOP DO CANAL:
{sop[:8000]}

Escreva o roteiro completo agora. LEMBRE-SE: {min_words} palavras MINIMO."""

    result = chat(prompt, system, max_tokens=max_tok, temperature=temp, timeout=tout)

    # Post-generation validation for forbidden words
    if forbidden:
        result_lower = result.lower()
        violations = [w for w in forbidden if w.lower() in result_lower]
        if violations:
            logger.warning(f"[SCRIPT] Forbidden words detected: {violations}. Auto-cleaning...")
            for word in violations:
                # Replace forbidden words with SOP-approved alternatives
                import re
                result = re.sub(re.escape(word), "...", result, flags=re.IGNORECASE)

    return result


def generate_narration(script: str, max_words: int = 0) -> str:
    """Converte roteiro em narracao limpa para ElevenLabs."""

    system = "Voce converte roteiros de YouTube em texto limpo para narracao TTS."

    # Estimate word target from the script itself if not given
    script_words = len(script.split())
    target = max_words if max_words > 0 else max(1500, int(script_words * 0.85))

    prompt = f"""Converta este roteiro em texto de NARRACAO PURA para colar no ElevenLabs.

REGRAS:
- Remova TODAS as marcacoes: [B-ROLL], [TRANSICAO], [PAUSA DRAMATICA], **bold**, # headers
- Remova timestamps e indicacoes tecnicas
- Mantenha apenas o texto que sera FALADO pelo narrador
- Use "..." para pausas dramaticas curtas
- Escreva numeros por extenso (duzentos milhoes, nao $200M)
- O resultado deve ter aproximadamente {target} palavras
- NAO adicione nada que nao esteja no roteiro original
- NAO corte ou resuma o texto — mantenha o roteiro COMPLETO

ROTEIRO:
{script}

Retorne APENAS o texto da narracao, nada mais."""

    # Longer scripts need more tokens for narration
    narr_tokens = min(32000, max(6000, int(script_words * 2)))
    return chat(prompt, system, max_tokens=narr_tokens, temperature=0.3)


if __name__ == "__main__":
    if not API_KEY:
        print("Configure LAOZHANG_API_KEY para testar")
        print("  export LAOZHANG_API_KEY=sk-...")
    else:
        response = chat("Diga 'API funcionando!' em uma frase curta.")
        print(f"Teste: {response}")
