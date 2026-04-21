"""
Fix: Alinha prompt de roteiro do aluno com formato do admin (generate_script).
Remove referência à Seção 16 (causa cenas numeradas) e aplica roteiro CORRIDO.
Também ajusta limites de títulos no viral_engine e api_routes.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ═══════════════════════════════════════════════════════════
# FIX 1: student_routes.py — Prompt de roteiro do aluno
# ═══════════════════════════════════════════════════════════
student_file = ROOT / "routes" / "student_routes.py"
content = student_file.read_text(encoding="utf-8")

OLD_PROMPT = '''        prompt = f"""TITULO DO VIDEO: {title}
HOOK SUGERIDO: {hook}

===== SOP DO CANAL MODELO (REFERENCIA DE SUCESSO) =====
{sop}
===== FIM DO SOP =====

INSTRUCAO CRITICA: Leia o SOP acima com ATENCAO TOTAL. O SOP define:
- O NICHO do canal (Secao 1 \u2014 identidade profunda)
- O TOM e VOCABULARIO (Secao 15 \u2014 system prompt)
- A ESTRUTURA exata do roteiro (Secao 16 \u2014 template)
- As REGRAS inegociaveis (Secao 6 \u2014 regras de ouro)

Seu roteiro DEVE estar 100% alinhado com o nicho e estilo do SOP. Se o SOP e sobre poker, o roteiro e sobre poker. Se e sobre crime, e sobre crime. Se e sobre ciencia, e sobre ciencia. NAO invente outro nicho.

FILOSOFIA: Voce NAO esta copiando \u2014 voce esta ELEVANDO. Pega o que funciona no SOP e executa MELHOR.

FORMATO DO ROTEIRO (OBRIGATORIO):
Escreva APENAS a narracao \u2014 o texto que sera lido em voz alta (voice-over).
NAO inclua:
- Analise tecnica, scores, ou meta-comentarios
- Listas de tags, keywords, SEO
- Secoes de "Analise de Elevacao", "Frameworks", "Retencao Esperada"
- Headers como "## HOOK DEVASTADOR" (use transicoes naturais)
- Descricoes de estilo visual ou formato

INCLUA:
- Marcacoes inline entre colchetes: [MUSICA: tipo], [SFX: descricao], [B-ROLL: descricao], [PAUSA DRAMATICA]
- Disclaimer de IA no final (lido pelo narrador)
- Transicoes naturais entre atos (sem headers markdown)

REGRAS DO SOP:
1. SIGA a estrutura da Secao 16 (template com timestamps)
2. APLIQUE as Regras de Ouro da Secao 6 \u2014 todas sem excecao
3. USE o vocabulario da Secao 15 \u2014 tom, ritmo, formalidade
4. APLIQUE hooks da Secao 4 \u2014 escolha um dos frameworks
5. USE open loops da Secao 5 \u2014 setup explicito + resolucao tardia
6. TAMANHO: 1500-2100 palavras de voice-over (10-14 minutos)

LIMITES DO YOUTUBE:
- Titulo: MAXIMO 100 caracteres
- Tags: MAXIMO 500 caracteres no total

O objetivo: alguem que conhece o canal original assiste e pensa "esse video e ainda MELHOR que os outros".

Escreva em {lang_label}. Seja EXTREMAMENTE detalhado.\\"\\"\\"

        system_msg = "Voce e um roteirista de elite para YouTube. Voce recebeu um SOP extraido de um canal real de sucesso como REFERENCIA. Seu trabalho NAO e copiar \u2014 e ELEVAR. Voce domina as mesmas tecnicas do canal original mas executa com maestria SUPERIOR. Cada hook mais afiado, cada open loop mais intrigante, cada spike mais intenso. Voce pega o que funciona e entrega uma versao MELHORADA. O resultado e um roteiro que honra o estilo do nicho mas surpreende ate quem conhece o canal original."'''

NEW_PROMPT = '''        prompt = f"""Escreva um roteiro COMPLETO de 10-14 minutos para o canal.

TITULO: {title}
HOOK: {hook}

===== SOP DO CANAL (REFERENCIA DE ESTILO E TOM) =====
{sop[:6000]}
===== FIM DO SOP =====

INSTRUCAO CRITICA: O SOP acima define o NICHO, TOM, VOCABULARIO e REGRAS do canal.
Seu roteiro DEVE estar 100% alinhado com o nicho e estilo do SOP.
Se o SOP e sobre poker, o roteiro e sobre poker. Se e sobre crime, e sobre crime.
NAO invente outro nicho. ELEVE o que funciona no SOP.

ESTRUTURA DO ROTEIRO (fluxo CORRIDO \u2014 NAO divida em cenas numeradas):
O roteiro deve seguir este fluxo CONTINUO com transicoes naturais:
1. HOOK (0:00-0:30) - Primeiros 30 segundos, capturar atencao imediata
2. CONTEXTO (0:30-2:30) - Setup da historia, epoca, personagens
3. ATO 1 - A DESCOBERTA (2:30-4:30) - Como tudo comecou
4. ATO 2 - A EXECUCAO (4:30-6:30) - O que aconteceu, como funcionou
5. ATO 3 - O CAOS (6:30-8:00) - Consequencias, reacoes, perseguicao
6. CLIMAX (8:00-9:30) - Momento mais impactante, revelacao final
7. RESOLUCAO (9:30-10:30) - O que aconteceu depois, licoes
8. CTA (10:30-11:00) - Call to action natural

FORMATO OBRIGATORIO \u2014 ROTEIRO CORRIDO:
- Escreva como um TEXTO CONTINUO de narracao (voice-over)
- Use transicoes NATURAIS entre as partes (sem quebras abruptas)
- NAO use headers markdown (##, ###), NAO numere cenas, NAO use "Escena 1", "Escena 2"
- NAO inclua analise tecnica, scores, meta-comentarios, tags, SEO
- Cada secao deve fluir naturalmente para a proxima

MARCACOES INLINE (dentro do texto corrido):
- [B-ROLL: descricao visual] para indicar visual ao animador
- [PAUSA DRAMATICA] nos momentos certos
- [MUSICA: tipo] e [SFX: descricao] quando necessario

REGRAS OBRIGATORIAS:
- Use OPEN LOOPS (misterios que so se resolvem depois)
- Use PATTERN INTERRUPTS (quebras de expectativa)
- Use SPECIFIC SPIKES (momentos de pico de tensao)
- Aplique as Regras de Ouro do SOP \u2014 todas sem excecao
- Use o vocabulario e tom definidos no SOP
- Numeros grandes devem causar impacto
- Cada parte deve terminar com um gancho para a proxima
- TAMANHO: 1500-1800 palavras de narracao

Escreva em {lang_label}. Seja EXTREMAMENTE detalhado.\\"\\"\\"

        system_msg = f"Voce e um roteirista profissional de YouTube especializado em canais faceless de storytelling. Voce escreve roteiros cinematicos, dramaticos, com narrativa envolvente que prende o espectador do inicio ao fim. Seus roteiros sao otimizados para narracao em voz (TTS) - sem marcacoes tecnicas no texto da narracao. Voce recebeu um SOP de um canal de sucesso como REFERENCIA. Seu trabalho e ELEVAR: mesmas tecnicas, execucao SUPERIOR. Escreva SEMPRE em {lang_label}."'''

# Normalize line endings for matching
content_lf = content.replace('\r\n', '\n')
old_lf = OLD_PROMPT.replace('\r\n', '\n')
new_lf = NEW_PROMPT.replace('\r\n', '\n')

if old_lf in content_lf:
    content_lf = content_lf.replace(old_lf, new_lf)
    # Restore original line endings
    if '\r\n' in content:
        content_lf = content_lf.replace('\n', '\r\n')
    student_file.write_text(content_lf, encoding="utf-8")
    print("[OK] student_routes.py — Prompt de roteiro do aluno CORRIGIDO")
    print("     - Removida referencia a Secao 16 (causava cenas numeradas)")
    print("     - Estrutura agora IDENTICA ao generate_script do admin")
    print("     - Formato: roteiro CORRIDO com transicoes naturais")
else:
    print("[WARN] student_routes.py — Nao encontrou o prompt antigo. Tentando match parcial...")
    # Try matching just the key conflicting part
    key_old = "SIGA a estrutura da Secao 16 (template com timestamps)"
    if key_old in content_lf:
        print("  > Encontrou referencia a Secao 16. Fixando...")
        # Replace the specific conflicting instructions
        content_lf = content_lf.replace(
            "1. SIGA a estrutura da Secao 16 (template com timestamps)",
            "1. Escreva como TEXTO CORRIDO (NAO divida em cenas numeradas)"
        )
        content_lf = content_lf.replace(
            "- A ESTRUTURA exata do roteiro (Secao 16 \u2014 template)",
            "- A ESTRUTURA e REGRAS do roteiro"
        )
        # Also fix the format section
        content_lf = content_lf.replace(
            "FORMATO DO ROTEIRO (OBRIGATORIO):\nEscreva APENAS a narracao \u2014 o texto que sera lido em voz alta (voice-over).",
            "FORMATO DO ROTEIRO (OBRIGATORIO) \u2014 ROTEIRO CORRIDO:\nEscreva como TEXTO CONTINUO de narracao (voice-over). NAO divida em cenas (Escena 1, Escena 2)."
        )
        # Fix word count
        content_lf = content_lf.replace(
            "6. TAMANHO: 1500-2100 palavras de voice-over (10-14 minutos)",
            "6. TAMANHO: 1500-1800 palavras de narracao"
        )
        if '\r\n' in content:
            content_lf = content_lf.replace('\n', '\r\n')
        student_file.write_text(content_lf, encoding="utf-8")
        print("[OK] student_routes.py — Correcoes parciais aplicadas")
    else:
        print("[SKIP] student_routes.py — Prompt ja foi modificado anteriormente")

print()

# ═══════════════════════════════════════════════════════════
# FIX 2: viral_engine.py — Limites de titulo (70-100 → 50-80)
# ═══════════════════════════════════════════════════════════
viral_file = ROOT / "protocols" / "viral_engine.py"
viral_content = viral_file.read_text(encoding="utf-8")
viral_lf = viral_content.replace('\r\n', '\n')

changes_viral = 0

# Fix system prompt title limits
old_sys = "MINIMO 70 caracteres, MAXIMO 100 caracteres por titulo. Titulos curtos NAO performam."
new_sys = "MINIMO 50 caracteres, MAXIMO 80 caracteres por titulo."
if old_sys in viral_lf:
    viral_lf = viral_lf.replace(old_sys, new_sys)
    changes_viral += 1

# Fix user prompt title limits
old_usr = "9. MINIMO 70 caracteres, MAXIMO 100 caracteres por titulo"
new_usr = "9. MINIMO 50 caracteres, MAXIMO 80 caracteres por titulo"
if old_usr in viral_lf:
    viral_lf = viral_lf.replace(old_usr, new_usr)
    changes_viral += 1

if changes_viral > 0:
    if '\r\n' in viral_content:
        viral_lf = viral_lf.replace('\n', '\r\n')
    viral_file.write_text(viral_lf, encoding="utf-8")
    print(f"[OK] viral_engine.py — Limites de titulo ajustados ({changes_viral} locais)")
    print("     - Antes: MIN 70, MAX 100 caracteres")
    print("     - Agora: MIN 50, MAX 80 caracteres")
else:
    print("[SKIP] viral_engine.py — Limites de titulo ja estao corretos")

print()

# ═══════════════════════════════════════════════════════════
# FIX 3: api_routes.py — Limites de titulo no generate-ideas
# ═══════════════════════════════════════════════════════════
api_file = ROOT / "routes" / "api_routes.py"
api_content = api_file.read_text(encoding="utf-8")
api_lf = api_content.replace('\r\n', '\n')

changes_api = 0

# Fix generate-ideas title limits
old_api1 = "MINIMO 70 caracteres, MAXIMO 100 caracteres"
new_api1 = "MINIMO 50 caracteres, MAXIMO 80 caracteres"
if old_api1 in api_lf:
    api_lf = api_lf.replace(old_api1, new_api1)
    changes_api += 1

# Fix title truncation (>100 → >80)
old_trunc = 'if len(idea.get("title", "")) > 100:'
new_trunc = 'if len(idea.get("title", "")) > 80:'
if old_trunc in api_lf:
    api_lf = api_lf.replace(old_trunc, new_trunc)
    changes_api += 1

old_trunc2 = 'idea["title"] = idea["title"][:97] + "..."'
new_trunc2 = 'idea["title"] = idea["title"][:77] + "..."'
if old_trunc2 in api_lf:
    api_lf = api_lf.replace(old_trunc2, new_trunc2)
    changes_api += 1

# Fix short title threshold (< 70 → < 50)
old_short = "if len(idea.get(\"title\", \"\")) < 70"
new_short = "if len(idea.get(\"title\", \"\")) < 50"
if old_short in api_lf:
    api_lf = api_lf.replace(old_short, new_short)
    changes_api += 1

# Fix expansion prompt thresholds
old_expand = "menos de 70 caracteres"
new_expand = "menos de 50 caracteres"
if old_expand in api_lf:
    api_lf = api_lf.replace(old_expand, new_expand)
    changes_api += 1

old_expand2 = 'if len(e.get("expanded", "")) >= 70'
new_expand2 = 'if len(e.get("expanded", "")) >= 50'
if old_expand2 in api_lf:
    api_lf = api_lf.replace(old_expand2, new_expand2)
    changes_api += 1

old_expand3 = "if len(expanded) <= 100:"
new_expand3 = "if len(expanded) <= 80:"
if old_expand3 in api_lf:
    api_lf = api_lf.replace(old_expand3, new_expand3)
    changes_api += 1

if changes_api > 0:
    if '\r\n' in api_content:
        api_lf = api_lf.replace('\n', '\r\n')
    api_file.write_text(api_lf, encoding="utf-8")
    print(f"[OK] api_routes.py — Limites de titulo ajustados ({changes_api} locais)")
    print("     - Antes: MIN 70, MAX 100 caracteres")
    print("     - Agora: MIN 50, MAX 80 caracteres")
else:
    print("[SKIP] api_routes.py — Limites de titulo ja estao corretos")

print()

# ═══════════════════════════════════════════════════════════
# FIX 4: ai_client.py — generate_script (admin) - Consistência
# ═══════════════════════════════════════════════════════════
ai_file = ROOT / "protocols" / "ai_client.py"
ai_content = ai_file.read_text(encoding="utf-8")
ai_lf = ai_content.replace('\r\n', '\n')

changes_ai = 0

# Ensure admin generate_script also says "roteiro corrido"
old_ai = "O roteiro deve ter estas secoes:"
new_ai = "O roteiro deve seguir este fluxo CORRIDO (NAO divida em cenas numeradas):"
if old_ai in ai_lf:
    ai_lf = ai_lf.replace(old_ai, new_ai)
    changes_ai += 1

if changes_ai > 0:
    if '\r\n' in ai_content:
        ai_lf = ai_lf.replace('\n', '\r\n')
    ai_file.write_text(ai_lf, encoding="utf-8")
    print(f"[OK] ai_client.py — generate_script consistencia ajustada ({changes_ai} locais)")
else:
    print("[SKIP] ai_client.py — Ja esta consistente")

print()
print("=" * 60)
print("  CORRECOES APLICADAS COM SUCESSO")
print("=" * 60)
print("Resumo:")
print("  1. Roteiro do aluno: texto CORRIDO (sem cenas numeradas)")
print("  2. Titulos: MAX reduzido de 100 para 80 caracteres")
print("  3. Admin generate_script: alinhado com novo padrao")
print()
print("Teste: gere um roteiro pelo dashboard do aluno e verifique")
print("se vem CORRIDO sem 'Escena 1', 'Escena 2', etc.")
