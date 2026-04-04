# YouTube Channel Cloner — Documentacao Completa v10.0

> Este documento descreve o funcionamento COMPLETO da aplicacao. Qualquer AI ou desenvolvedor que ler este arquivo entende 100% do sistema.

## 1. O QUE E

Plataforma web que **analisa canais de YouTube de sucesso** e gera um **SOP (Standard Operating Procedure)** com 17 secoes detalhadas. Esse SOP e usado como "DNA" para criar conteudo que **ELEVA** (nao copia) o padrao do canal original.

**URL**: `https://cloner.canaisdarks.com.br`
**Stack**: FastAPI + SQLite + Jinja2 + Docker (EasyPanel)
**AI**: LaoZhang API (proxy Claude/GPT) + API individual por aluno
**Repo**: `github.com/ofcdarks/youtube-cloner` branch `master`

---

## 2. ARQUITETURA

```
youtube-cloner/
├── dashboard.py          # App principal FastAPI + rotas admin + pipeline (1826 linhas)
├── database.py           # SQLite com 18 tabelas, bcrypt, Fernet, migrations
├── services.py           # Transcript analysis, mindmap HTML, validators
├── config.py             # Env vars e constantes
├── auth.py               # Session auth, require_admin, require_auth
├── middleware.py          # Request logging, CSRF protection
├── rate_limit.py          # Shared SlowAPI Limiter (importado por todos os modules)
├── progress_store.py      # Thread-safe store para SSE progress do pipeline
├── protocols/
│   ├── ai_client.py       # Chat com LaoZhang API + tracking de tokens
│   ├── google_export.py   # Google Drive: create_folder, create_doc, create_sheet
│   └── title_scorer.py    # Scoring de titulos (CTR, trends)
├── routes/
│   ├── api_routes.py      # Ideas, scoring, script gen, trend radar, multi-lang clone
│   ├── auth_routes.py     # Login, logout, health
│   ├── gdrive_routes.py   # Google Drive OAuth web flow (PKCE fix)
│   └── student_routes.py  # Painel aluno, channels, analytics, script judge
├── templates/             # Jinja2 HTML (8 templates)
├── static/                # CSS + JS
├── Dockerfile             # Multi-stage build, sem Playwright
├── entrypoint.sh          # Volume permissions + startup
└── test_app.py            # Smoke tests + DB tests + security audit
```

---

## 3. FLUXO PRINCIPAL

### 3.1 Pipeline Admin (analyze-channel) — 12 Steps

O admin analisa um canal do YouTube. O pipeline roda em thread separada com SSE progress real-time.

```
Step 1:  Cria projeto + pasta Google Drive
Step 2:  Gera SOP (3 fontes: Manual NLM > Transcricoes > AI fallback)
Step 3:  Gera 5 sub-nichos derivados
Step 4:  Gera 30 titulos virais
Step 5:  Gera SEO Pack (10 videos)
Step 6:  Gera Thumbnail Prompts (Midjourney/DALL-E)
Step 7:  Gera Music Prompts (Suno/Udio/MusicGPT)
Step 8:  Gera Teaser Prompts (Shorts/Reels/TikTok)
Step 9:  Gera 3 roteiros completos (com [MUSICA], [SFX], [B-ROLL])
Step 10: Gera Mind Map HTML interativo
Step 11: Exporta 14 arquivos padrao pro Google Drive
Step 12: Pipeline concluido (SSE envia "done")
```

### 3.2 SOP — O DNA do Canal

O SOP e o documento central. Pode ser gerado de 3 formas:

**Forma 1 (MELHOR): Manual via NotebookLM**
1. Admin cria um NotebookLM com a base do canal (videos, transcricoes)
2. Envia 5 prompts sequenciais no NLM:
   - PARTE 1: Autopsia do canal (identidade, formato, producao)
   - PARTE 2: Engenharia de roteiro (anatomia, hooks reais, exemplos)
   - PARTE 3: Storytelling + regras de ouro (open loops, spikes, 15 regras)
   - PARTE 4: Estrategia + inteligencia competitiva (SEO, retencao, monetizacao)
   - PARTE 5: Manual de replicacao para IA (system prompt, template, checklist)
3. Cola as 5 respostas no campo "SOP Manual" da aplicacao
4. O SOP resultante tem 17 SECOES:
   - 1. Identidade profunda
   - 2. Formato e producao
   - 3. Anatomia do roteiro (hook, atos, climax)
   - 4. Playbook de hooks (8 tipos com exemplos reais)
   - 5. Tecnicas de storytelling (open loops, pattern interrupts, cliffhangers)
   - 6. Regras de ouro (15 regras com exemplos)
   - 7. Pilares de conteudo
   - 8. Formula de titulos
   - 9. Estilo de thumbnail
   - 10. SEO
   - 11. Monetizacao
   - 12. Retencao
   - 13. Competidores
   - 14. Evolucao do canal
   - 15. System prompt para IA (300+ palavras, vocabulario, tom, exemplos)
   - 16. Template de roteiro com timestamps exatos
   - 17. Checklist de qualidade (15 perguntas SIM/NAO)

**Forma 2: Transcricoes automaticas**
- yt-dlp extrai IDs dos videos do canal
- YouTubeTranscriptApi baixa transcricoes (pt/en)
- AI analisa padroes reais e gera SOP

**Forma 3: AI pura (fallback)**
- Se nao tem NLM nem transcricoes, AI gera SOP baseado na URL/nicho

### 3.3 Fluxo do Aluno

```
1. Admin cria aluno (nome, email, senha, nicho, projeto)
2. Admin cadastra canais do aluno (ate 5)
3. Admin libera titulos pro aluno (5, 10, 15...)
4. Aluno recebe notificacao (sino com badge)
5. Aluno configura sua API key (Anthropic/OpenAI/LaoZhang/Google)
6. Aluno ve titulos no Kanban (Pendente → Escrevendo → Gravando → Editando → Publicado)
7. Aluno clica "Gerar Roteiro" — AI usa o SOP COMPLETO como referencia
8. Roteiro + narracao limpa sao salvos nos arquivos
9. Aluno clica "★ Score" — AI Script Judge avalia contra o SOP (0-100)
10. Se score < 80, aluno ajusta e re-gera
11. Aluno publica video e move card pra "Publicado"
12. Aluno clica "Atualizar Dados" — puxa analytics reais do YouTube
13. Admin clica "Evoluir SOP" — AI analisa performance e sugere melhorias
```

### 3.4 Prompt do Aluno para Gerar Roteiro

O prompt envia o SOP COMPLETO (sem truncar) e instrui a AI a:
- Usar a estrutura e tecnicas das secoes 3/5 como BASE, mas MELHORAR a execucao
- Aplicar as Regras de Ouro da secao 6 (inegociaveis)
- Usar vocabulario/tom do nicho (secao 15) mas com VOZ PROPRIA
- Seguir o Template da secao 16 como esqueleto
- Cada hook, open loop e spike deve ser ORIGINAL e mais poderoso
- Adicionar insights que o canal original NAO explorou

**Filosofia: "Voce NAO esta copiando — voce esta ELEVANDO."**

System prompt: "Seu trabalho NAO e copiar — e ELEVAR. Voce pega o que funciona e entrega uma versao MELHORADA."

---

## 4. BANCO DE DADOS (18 tabelas SQLite)

| Tabela | Descricao |
|--------|-----------|
| projects | Projetos (canal, nicho, idioma, drive_folder_id) |
| files | Arquivos gerados (SOP, roteiros, SEO, etc) com visible_to_students e score_json |
| ideas | 30 titulos por projeto (title, hook, score, priority, pillar) |
| niches | 5 sub-nichos derivados por projeto |
| scripts | Roteiros gerados (title, content, duration) |
| seo_packs | SEO packs (descricao, tags, hashtags) |
| activity_log | Log de atividades (action, details, timestamp) |
| users | Admin + alunos (bcrypt password, Fernet API key, drive_folder_id) |
| assignments | Aluno ↔ Projeto (nicho, titles_released, schedule) |
| progress | Progresso por titulo (status: pending/writing/recording/editing/published) |
| sessions | Sessoes de login (token, user_id, expires_at) |
| admin_settings | Key-value store (YouTube API key, Google OAuth token, etc) |
| _migrations | Controle de migrations executadas |
| student_channels | Canais do aluno (ate 5, gerenciados pelo admin) |
| student_drive_files | Tracking de arquivos no Drive pessoal do aluno |
| notifications | Notificacoes (type, title, message, read, link) |
| ai_usage | Tracking de tokens AI (model, tokens, cost, operation) |
| video_performance | Performance real dos videos (views, likes, comments, engagement) |

---

## 5. ROTAS API (63 total, 35 com rate limit)

### Admin
| Metodo | Rota | Descricao | Rate |
|--------|------|-----------|------|
| POST | /api/admin/analyze-channel | Pipeline completo (12 steps) | 3/min |
| POST | /api/admin/create-student | Criar aluno | 5/min |
| POST | /api/admin/delete-project | Excluir projeto | 10/min |
| POST | /api/admin/delete-student | Excluir aluno | 10/min |
| POST | /api/admin/connect-drive | Criar pasta Drive pra projeto | 5/min |
| POST | /api/admin/sync-drive | Re-sincronizar 14 arquivos (com dedup) | 5/min |
| POST | /api/admin/release-titles | Liberar titulos pro aluno (+ notificacao) | 20/min |
| POST | /api/admin/assign-niche | Atribuir nicho ao aluno | 20/min |
| POST | /api/admin/toggle-file-visibility | Toggle visibilidade (+ notificacao) | 20/min |
| POST | /api/admin/bulk-file-visibility | Toggle todos arquivos de categoria | 20/min |
| POST | /api/admin/add-student-channel | Cadastrar canal do aluno | 20/min |
| POST | /api/admin/remove-student-channel | Remover canal do aluno | 20/min |
| POST | /api/admin/toggle-student | Ativar/desativar aluno | 20/min |
| POST | /api/admin/remove-title | Remover titulo do aluno | 20/min |
| POST | /api/admin/youtube-settings | Salvar YouTube API key | 5/min |
| POST | /api/admin/evolve-sop | SOP Vivo — analisa performance real | 3/min |
| POST | /api/admin/trend-radar | Radar de tendencias (YouTube + Trends) | 3/min |
| POST | /api/admin/clone-language | Clonar projeto pra outro idioma | 3/min |
| POST | /api/regenerate-mindmap | Re-gerar Mind Map HTML | 5/min |
| GET | /api/admin/pipeline-progress | SSE progress real-time do pipeline | — |
| GET | /api/admin/youtube-stats | Stats do canal no YouTube | — |

### Aluno
| Metodo | Rota | Descricao | Rate |
|--------|------|-----------|------|
| POST | /api/student/generate-script | Gerar roteiro (SOP completo, "elevar") | 10/min |
| POST | /api/student/score-script | AI Script Judge (0-100, 10 criterios) | 10/min |
| POST | /api/student/update-progress | Mover card no Kanban | 30/min |
| POST | /api/student/update-api-key | Salvar API key do aluno | 10/min |
| POST | /api/student/delete-file | Excluir roteiro/narracao | 20/min |
| POST | /api/student/fetch-channel-stats | Puxar analytics do YouTube | 5/min |
| POST | /api/student/mark-notification-read | Marcar notificacao como lida | 30/min |
| POST | /api/student/sync-to-drive | Enviar arquivo pro Drive pessoal | 5/min |
| GET | /api/student/notifications | Listar notificacoes | — |
| GET | /api/student/performance-summary | Resumo de performance | — |
| GET | /api/student/channels | Listar canais | — |

### Google Drive OAuth
| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | /api/admin/gdrive/auth | Inicia fluxo OAuth → Google |
| GET | /api/admin/gdrive/callback | Callback do Google → salva token |
| GET | /api/admin/gdrive/status | Status da conexao (com debug info) |
| POST | /api/admin/gdrive/disconnect | Desconectar Drive |

---

## 6. FEATURES ESPECIAIS

### 6.1 AI Script Judge
Avalia roteiro contra o SOP em 10 criterios (0-10 cada):
1. Hook, 2. Open Loops, 3. Storytelling, 4. Tom de Voz, 5. Estrutura,
6. Regras de Ouro, 7. Duracao, 8. Engagement, 9. Originalidade, 10. Fechamento

Retorna: score total (0-100), grade (A/B/C/D/F), aprovado/reprovado (threshold 80), sugestoes de melhoria.

### 6.2 SOP Vivo
Admin clica "Evoluir SOP" → AI compara Top 5 vs Bottom 5 videos dos alunos → identifica padroes vencedores → sugere atualizacoes nas secoes 2/4/6/8 do SOP. O SOP fica mais inteligente com o tempo.

### 6.3 Radar de Tendencias
Escaneia YouTube Search API (videos populares ultimas 2 semanas) + Google Trends (pytrends). AI gera: analise de tendencias, 10 titulos urgentes com janela de oportunidade, alertas de gaps de conteudo.

### 6.4 Multi-Language Cloning
Pega SOP de um projeto e ADAPTA (nao traduz) para outro idioma. Adaptacao cultural profunda: hooks, expressoes, SEO keywords, referencias culturais. Cria projeto novo com SOP adaptado + 30 titulos adaptados. Suporta 8 idiomas: pt-BR, en, es, fr, de, it, ja, ko.

### 6.5 SSE Progress
Pipeline roda em thread separada. Cada step atualiza `progress_store.py` (thread-safe). Frontend abre `EventSource` e recebe updates em tempo real: `[3/12] Gerando 5 nichos derivados`.

### 6.6 Notificacoes
Sino com badge no painel do aluno. Notifica quando: admin libera titulos, admin cria conta, admin torna arquivo visivel. Dropdown com lista de notificacoes, marcar como lido individual ou todas.

### 6.7 YouTube Analytics
Aluno clica "Atualizar Dados" → puxa stats reais via YouTube Data API: inscritos, views total, media por video, engagement rate, 15 videos recentes com metricas. Dados salvos no DB para analise de tendencia.

### 6.8 AI Cost Tracking
Cada chamada AI via `protocols/ai_client.py` registra: model, prompt_tokens, completion_tokens, estimated_cost. Admin ve no painel: tokens totais, custo estimado, breakdown por operacao.

### 6.9 Google Drive — 14 Arquivos Padrao
Cada projeto exporta exatamente 14 arquivos:
1. SOP (Doc)
2. SEO Pack (Doc)
3. Roteiro 1 (Doc)
4. Roteiro 2 (Doc)
5. Roteiro 3 (Doc)
6. Thumbnail Prompts (Doc)
7. Music Prompts (Doc)
8. Teaser Prompts (Doc)
9. MIND MAP (Doc)
10. 30 Ideias de Videos (Doc)
11. Titulos (Sheet)
12. 5 Nichos Derivados (Sheet)
13. SEO Sheet (Sheet)
14. Narracoes Completas (Doc)

Sync com deduplicacao: lista arquivos existentes antes de criar novos.

---

## 7. SEGURANCA

- **Autenticacao**: Session-based com token no cookie, bcrypt para senhas
- **API keys dos alunos**: Encriptadas com Fernet (AES-128-CBC)
- **CSRF**: Token validation em todas as rotas POST
- **Rate limiting**: 35 rotas protegidas via SlowAPI (shared `rate_limit.py`)
- **Path traversal**: Validacao de URLs e project IDs
- **Role-based access**: `require_admin` vs `require_auth`
- **Visibilidade de arquivos**: Toggle por arquivo, alunos so veem o que admin libera
- **Drive isolado**: Aluno nao ve pasta Drive do projeto, tem pasta propria

---

## 8. VARIAVEIS DE AMBIENTE

```env
# Admin
DASH_USER=rudy@ytcloner.com
DASH_PASS=senha
DASH_EMAIL=rudy@ytcloner.com

# AI
LAOZHANG_API_KEY=sk-...
LAOZHANG_BASE_URL=https://api.laozhang.ai/v1
AI_MODEL=claude-3-7-sonnet-latest

# Google Drive OAuth
GOOGLE_CLIENT_ID=728121...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=https://cloner.canaisdarks.com.br/api/admin/gdrive/callback

# Security
ENCRYPTION_KEY=base64...
CSRF_SECRET=hex...

# Server
PORT=8888
LOG_LEVEL=info
COOKIE_SECURE=true
ALLOWED_ORIGINS=https://studio.canaisdarks.com.br
```

---

## 9. DEPLOY

```bash
# Build e deploy via EasyPanel (Docker)
git add -A & git commit -m "mensagem" & git push origin master

# Se historico divergiu:
git push origin master --force
```

**Docker**: Multi-stage build, Python 3.11-slim, ffmpeg + yt-dlp, sem Playwright.
**Volume**: `ytcloner-data` montado em `/app/output` (DB + mindmaps).
**Healthcheck**: `GET /api/health` a cada 30s.

---

## 10. COMO CONTINUAR DESENVOLVENDO

### Para adicionar uma nova feature:
1. Adicionar migration no `database.py` (array `migrations`)
2. Adicionar funcoes DB no final de `database.py`
3. Adicionar rota em `routes/` (com `@limiter.limit`)
4. Adicionar UI no template HTML correspondente
5. Adicionar JS no final do template
6. Rodar `python -c "import ast; ast.parse(open('arquivo.py').read())"` pra checar sintaxe
7. Commitar e push

### Arquivos principais pra editar:
- **Novo endpoint admin**: `dashboard.py` ou `routes/api_routes.py`
- **Novo endpoint aluno**: `routes/student_routes.py`
- **Nova tabela/coluna**: `database.py` (migrations + funcoes)
- **UI admin**: `templates/dashboard.html` ou `templates/admin_*.html`
- **UI aluno**: `templates/student_dashboard.html`
- **Pipeline AI**: `dashboard.py` (funcao `_run_pipeline`)
- **Google Drive**: `routes/gdrive_routes.py` + `protocols/google_export.py`

### Convencoes:
- Rate limit em TODA rota POST
- `try/except` com logging em toda operacao externa
- Notificacao pro aluno quando admin faz acao relevante
- Arquivos salvos com `save_file()` e categoria correta
- Activity log com `log_activity()` pra auditoria
