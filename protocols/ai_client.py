"""
AI Client - Usa laozhang.ai (OpenAI-compatible) para gerar conteudo.

Features:
- Timeout configuravel (default 180s)
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
    MODEL = os.environ.get("AI_MODEL", "gpt-4o")

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds — exponential: 2, 4, 8
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def chat(prompt: str, system: str = "", model: str = None, max_tokens: int = 8000, temperature: float = 0.7, timeout: int = 180) -> str:
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


def generate_script(title: str, hook: str, sop: str, niche: str = "System Breakers", language: str = "pt-BR") -> str:
    """Gera um roteiro completo para um titulo."""

    from config import LANG_LABELS
    lang_label = LANG_LABELS.get(language, language)

    system = f"""Voce e um roteirista profissional de YouTube especializado em canais faceless de storytelling.
Voce escreve roteiros cinematicos, dramaticos, com narrativa envolvente que prende o espectador do inicio ao fim.
Seus roteiros sao otimizados para narracao em voz (TTS) - sem marcacoes tecnicas no texto da narracao.
Escreva SEMPRE em {lang_label}."""

    prompt = f"""Escreva um roteiro COMPLETO de 10-12 minutos para o canal "{niche}".

TITULO: {title}
HOOK: {hook}

O roteiro deve ter estas secoes:
1. **HOOK** (0:00-0:30) - Primeiros 30 segundos, capturar atencao imediata
2. **CONTEXTO** (0:30-2:30) - Setup da historia, epoca, personagens
3. **ATO 1 - A DESCOBERTA** (2:30-4:30) - Como tudo comecou
4. **ATO 2 - A EXECUCAO** (4:30-6:30) - O que aconteceu, como funcionou
5. **ATO 3 - O CAOS** (6:30-8:00) - Consequencias, reacoes, perseguicao
6. **CLIMAX** (8:00-9:30) - Momento mais impactante, revelacao final
7. **RESOLUCAO** (9:30-10:30) - O que aconteceu depois, licoes
8. **CTA** (10:30-11:00) - Call to action natural

REGRAS OBRIGATORIAS (do SOP):
- Use OPEN LOOPS (misterios que so se resolvem depois)
- Use PATTERN INTERRUPTS (quebras de expectativa)
- Use SPECIFIC SPIKES (momentos de pico de tensao)
- Inclua [B-ROLL: descricao visual] para o animador
- Inclua [PAUSA DRAMATICA] nos momentos certos
- Numeros grandes devem causar impacto
- Cada secao deve terminar com um gancho para a proxima
- O roteiro deve ter aproximadamente 1500-1800 palavras de narracao

SOP DO CANAL:
{sop[:6000]}

Escreva o roteiro completo agora."""

    return chat(prompt, system, max_tokens=8000)


def generate_narration(script: str) -> str:
    """Converte roteiro em narracao limpa para ElevenLabs."""

    system = "Voce converte roteiros de YouTube em texto limpo para narracao TTS."

    prompt = f"""Converta este roteiro em texto de NARRACAO PURA para colar no ElevenLabs.

REGRAS:
- Remova TODAS as marcacoes: [B-ROLL], [TRANSICAO], [PAUSA DRAMATICA], **bold**, # headers
- Remova timestamps e indicacoes tecnicas
- Mantenha apenas o texto que sera FALADO pelo narrador
- Use "..." para pausas dramaticas curtas
- Escreva numeros por extenso (duzentos milhoes, nao $200M)
- O resultado deve ter entre 1500-1800 palavras
- NAO adicione nada que nao esteja no roteiro original

ROTEIRO:
{script}

Retorne APENAS o texto da narracao, nada mais."""

    return chat(prompt, system, max_tokens=6000, temperature=0.3)


if __name__ == "__main__":
    if not API_KEY:
        print("Configure LAOZHANG_API_KEY para testar")
        print("  export LAOZHANG_API_KEY=sk-...")
    else:
        response = chat("Diga 'API funcionando!' em uma frase curta.")
        print(f"Teste: {response}")
