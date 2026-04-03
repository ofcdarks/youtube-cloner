# TUTORIAL COMPLETO - YouTube Channel Cloner

## Como Modelar Qualquer Canal do YouTube

---

## PASSO 1: Escolher o Canal para Modelar

Encontre um canal faceless que esta tendo sucesso. Criterios:
- Muitas views por video (1M+)
- Poucos videos postados (sinal de que o formato e forte)
- Estilo replicavel (animacao, slides, stock footage)
- Nicho com RPM bom (financas, tech, true crime, negocios)

**Exemplo:** Canal "Loaded Dice" - 85M views com 13 videos de poker/gambling em low poly 3D.

---

## PASSO 2: Extrair o SOP do Canal (Protocol Clerk)

O Protocol Clerk analisa os videos do canal, extrai transcricoes e gera um SOP (Procedimento Operacional Padrao) que explica COMO o canal faz seus roteiros.

### Opcao A: Via Terminal (local)

```bash
cd c:/Users/DigiAi/Desktop/youtube-cloner

# Com URL do canal
python run.py clerk https://youtube.com/@NomeDoCanal --name meu_canal

# Com lista de videos especificos
python run.py clerk "https://youtube.com/watch?v=VIDEO1,https://youtube.com/watch?v=VIDEO2" --name meu_canal

# Com arquivo de URLs
python run.py clerk videos.txt --name meu_canal
```

O que acontece:
1. yt-dlp extrai os IDs dos videos
2. youtube-transcript-api baixa as transcricoes
3. A IA analisa a estrutura dos roteiros
4. Gera SOP em duas versoes: humano + IA
5. Salva em `output/meu_canal_sop.md`

### Opcao B: Via Claude Code

Diga: "Analisa o canal @NomeDoCanal e gera um SOP"

### Opcao C: Via NotebookLM (mais profundo)

```bash
notebooklm create "Analise Canal X"
notebooklm source add "URL_DO_VIDEO_1"
notebooklm source add "URL_DO_VIDEO_2"
notebooklm ask "Analise a estrutura dos roteiros deste canal..."
```

---

## PASSO 3: Gerar Nichos Derivados (Niche Bending)

O Niche Bender pega o SOP do canal e sugere 5 nichos novos que usam a MESMA estrutura mas com conteudo diferente.

### Via Terminal:

```bash
python run.py niche --sop output/meu_canal_sop.md --original "nicho do canal original" --count 5
```

### Via Claude Code:

"Gera 5 nichos derivados do SOP que criamos"

### Resultado:

Para cada nicho voce recebe:
- Nome sugerido do canal
- Conceito (1 paragrafo)
- Por que funciona
- Publico-alvo
- 5 pilares de conteudo
- 10 ideias de videos
- Estilo visual recomendado
- RPM estimado
- Nivel de competicao
- 3 paises ideais para abrir o canal (com idioma)
- Fontes de pesquisa

---

## PASSO 4: Escolher Nicho e Gerar Titulos

### No Dashboard (cloner.canaisdarks.com.br):

1. Login: rudy@ytcloner.com / 253031
2. Na secao "Nichos Gerados", clique nos nichos que quer trabalhar (max 2)
3. Veja os paises recomendados e idiomas
4. Clique "+ Gerar Titulos" → escolha o nicho → quantidade
5. A IA gera titulos unicos seguindo o SOP

### Via Terminal:

```bash
python run.py script --sop output/meu_canal_sop.md --niche "Nome do Nicho" --count 3
```

---

## PASSO 5: Pontuar Titulos

### No Dashboard:

1. Selecione a regiao no dropdown (Global + BR + US, etc)
2. Clique "Pontuar Todos"
3. Cada titulo recebe score 0-100:
   - YouTube: demanda real (views de videos similares)
   - Google Trends: interesse de busca por regiao
4. Cores: verde (80+), azul (60+), amarelo (40+), vermelho (<40)
5. Comece pelos titulos com score mais alto

---

## PASSO 6: Gerar Roteiro

### No Dashboard:

1. Clique no icone de lapis ao lado do titulo
2. Confirme
3. Espere 1-2 min (usa a API laozhang.ai)
4. Roteiro completo + narracao limpa para ElevenLabs
5. Exporta automaticamente para Google Drive
6. Marca titulo como usado

### Via Claude Code:

"Gera o roteiro do titulo 5: [nome do titulo]"

### Via Terminal:

```bash
python -c "
from protocols.ai_client import generate_script, generate_narration
from pathlib import Path
sop = Path('output/meu_canal_sop.md').read_text(encoding='utf-8')
script = generate_script('TITULO AQUI', 'HOOK AQUI', sop, 'NICHO')
narration = generate_narration(script)
Path('output/roteiro_novo.md').write_text(script, encoding='utf-8')
Path('output/narracao_nova.txt').write_text(narration, encoding='utf-8')
"
```

---

## PASSO 7: Gerar Audio (ElevenLabs)

### Opcao A: Manual

1. Abra o arquivo de narracao no Google Drive
2. Copie o texto inteiro
3. Cole no ElevenLabs (elevenlabs.io)
4. Configuracoes recomendadas:
   - Voice: Adam ou Josh
   - Model: eleven_multilingual_v2
   - Stability: 0.35
   - Similarity: 0.75
   - Style: 0.45
5. Gere o audio

### Configuracao por secao (para ajuste fino):

| Secao | Stability | Style | Speed |
|---|---|---|---|
| Hook (0-30s) | 0.25 | 0.60 | 1.05x |
| Contexto | 0.45 | 0.30 | 0.95x |
| Desenvolvimento | 0.35 | 0.45 | 1.00x |
| Climax | 0.20 | 0.70 | 1.10x |
| Resolucao | 0.50 | 0.25 | 0.90x |

---

## PASSO 8: Gerar SEO

O sistema gera automaticamente:
- 5 variacoes de titulo para A/B testing
- Descricao otimizada com timestamps
- 30 tags relevantes
- Hashtags
- Prompt de thumbnail (Midjourney/DALL-E)

### Acessar:

No dashboard, clique em "Seo" na secao "Arquivos do Projeto"
Ou no Google Drive, abra "SEO Pack Completo"

---

## PASSO 9: Producao do Video

### Opcao A: Freelancer (recomendado)

1. Pegue o roteiro (com indicacoes [B-ROLL])
2. Envie para animador no Upwork/Fiverr
3. Custo: $80-300 por video (low poly 3D)
4. Peca estimativa antes

### Opcao B: IA

Use os prompts de teaser/thumbnail gerados:
- Video: Runway, Kling, Pika
- Thumbnail: Midjourney, DALL-E
- Musica: Suno, Udio (prompts incluidos no pack)

---

## PASSO 10: Atribuir para Alunos

### No Dashboard:

1. Clique "Alunos" no topbar
2. "Criar Aluno" → nome, email, senha, nicho, quantidade de titulos
3. O aluno recebe login proprio
4. Ve so os titulos atribuidos num kanban
5. Configura SUA api key (Anthropic/OpenAI/Google)
6. Gera roteiros com a propria API
7. Move cards: Pendente → Escrevendo → Gravando → Editando → Publicado
8. Voce monitora o progresso no admin

### Para liberar mais titulos:

Admin → Aluno → "Liberar +5 Titulos"

---

## FLUXO COMPLETO RESUMIDO

```
1. Escolher canal de referencia
   ↓
2. Protocol Clerk → SOP
   ↓
3. Niche Bending → 5 nichos + paises + idiomas
   ↓
4. Escolher 1-2 nichos
   ↓
5. Gerar 30+ titulos → Pontuar (YouTube + Trends)
   ↓
6. Gerar roteiros (top scores primeiro)
   ↓
7. Gerar narracao (ElevenLabs)
   ↓
8. Gerar SEO + thumbnails + musica
   ↓
9. Produzir video (freelancer ou IA)
   ↓
10. Publicar + monitorar
```

---

## PIPELINE COMPLETO (tudo de uma vez)

```bash
cd c:/Users/DigiAi/Desktop/youtube-cloner
python run.py full https://youtube.com/@CanalAlvo --niche "Nome" --scripts 3
```

Isso executa: Clerk → Niche Bending → Script Stealing → Export Google Drive

---

## DICAS

1. **Comece pelos titulos com score 80+** - sao os com mais demanda
2. **Faca 10 videos antes de avaliar** - o algoritmo precisa de volume
3. **Poste 2-3x por semana** - consistencia importa mais que qualidade
4. **Teste 2 nichos simultaneamente** - descubra qual performa melhor
5. **Use RPM como guia** - nichos com RPM $15+ pagam mais por view
6. **Monitore no YouTube Studio** - CTR e retencao sao as metricas chave
7. **Itere os titulos** - se um formato de titulo funcionar, faca mais dele

---

## LINKS UTEIS

- Dashboard: https://cloner.canaisdarks.com.br
- Google Drive: https://drive.google.com/drive/folders/1BVZfiN7q4NrToiPLllO0yD1aFMplxfRL
- Mind Map: https://cloner.canaisdarks.com.br/output/mindmap_system_breakers.html
- ElevenLabs: https://elevenlabs.io
- Suno (musica): https://suno.ai
- Midjourney (thumbnails): https://midjourney.com
- Upwork (freelancers): https://upwork.com
