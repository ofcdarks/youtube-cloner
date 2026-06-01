# YouTube Channel Cloner - Referencia Completa

> Documento para contexto entre sessoes. Qualquer AI que ler este arquivo entende 100% do sistema.

## 1. VISAO GERAL

**O que e**: Plataforma web que analisa canais do YouTube e gera SOPs (Standard Operating Procedures) com 17 secoes. O SOP serve como "DNA" para criar conteudo que **ELEVA** (nao copia) o padrao do canal original.

**URL Producao**: `https://cloner.canaisdarks.com.br`
**Stack**: FastAPI + SQLite (WAL) + Jinja2 + Docker (EasyPanel)
**AI**: LaoZhang API (proxy Claude/GPT) + API individual por aluno
**Repo**: `github.com/ofcdarks/youtube-cloner` branch `master`
**Python**: 3.11-slim | **Porta**: 8888

---

## 2. ARQUITETURA DE ARQUIVOS

> Contagens de linhas aproximadas (mai/2026). Os arquivos legados grandes (dashboard.py, database.py, *_routes.py) ainda excedem o limite de 800 linhas — refactor pendente.

```
youtube-cloner/
├── dashboard.py           # App FastAPI principal (~1190 linhas)
│                          # Registra 10 routers, pipeline-progress SSE, file serving,
│                          # rotas niches-lab + bent-ideas, paginas admin HTML
├── database.py            # SQLite: 21 tabelas, bcrypt, Fernet, _run_migrations (~1570 linhas)
├── services.py            # Transcript analysis, mindmap HTML, validate_url (SSRF allowlist) (~640 linhas)
├── config.py              # Env vars, constantes, startup validation (~159 linhas)
├── auth.py                # Session auth (memory+DB), require_admin/require_auth (~125 linhas)
├── middleware.py          # CSRF (HMAC-SHA256), safe errors, security headers, request log (~178 linhas)
├── rate_limit.py          # Shared SlowAPI Limiter instance (~8 linhas)
├── progress_store.py      # Thread-safe dict para SSE pipeline progress (~46 linhas)
├── run.py                 # CLI: full/clerk/niche/script/export
├── export_*.py / migrate_to_db.py / extract_roteiro_prompts.py  # scripts CLI one-off (nao usados pelo app)
│
├── protocols/             # 15 modulos
│   ├── ai_client.py        # chat(), generate_script(), generate_narration() — retry 3x, token/cost
│   ├── google_export.py    # create_folder/doc/sheet, export_project() — OAuth auto-refresh
│   ├── title_scorer.py     # score_title(): YouTube + Google Trends (0.6/0.4)
│   ├── viral_engine.py     # geracao de titulos virais / hooks
│   ├── idea_bender.py      # Niche/Idea Bender (dobra de nichos)
│   ├── niches_lab.py       # Niches Lab + DataForSEO (cache em memoria)
│   ├── keywords_everywhere.py / trend_research.py  # volume de busca, tendencias
│   ├── channel_mockup.py   # mockup de canal (mockup_routes)
│   ├── creative_prompts.py / seo_generator.py      # usados por export_complete.py (CLI)
│   ├── clerk.py / niche_bender.py / script_stealer.py  # usados por run.py (CLI)
│   └── imagefx_client.py   # ImageFX (thumbnails)
│
├── routes/                # 10 routers registrados no dashboard.py
│   ├── auth_routes.py      # Login POST/GET, logout, /api/health
│   ├── api_routes.py       # Ideas, scoring, script gen, idea-bender, clone-language, seeds
│   ├── student_routes.py   # Painel aluno, script gen, score/improve judge, analytics  (~2660 linhas)
│   ├── admin_routes.py     # CRUD projetos/alunos, release-titles, channel ops
│   ├── pipeline_routes.py  # Pipeline 12-step analyze-channel + regenerate-titles  (~1520 linhas)
│   ├── drive_admin_routes.py / gdrive_routes.py  # Google Drive admin ops + OAuth web flow
│   ├── mockup_routes.py     # geracao de mockups de canal
│   ├── resources_routes.py  # recursos compartilhados com alunos (upload/delete/agent)
│   └── import_routes.py     # import de projeto via JSON seed
│
├── templates/              # Jinja2 HTML (15 templates)
│   ├── base.html / login.html / change_password.html
│   ├── dashboard.html / student_dashboard.html
│   ├── admin_panel.html / admin_projects.html / admin_students.html / admin_student_detail.html
│   ├── admin_niches_lab.html / admin_bent_ideas.html / admin_radar.html / admin_sop_analysis.html
│   └── _ab_title_block.html / _card_extras.html  (partials)
│
├── static/
│   ├── css/main.css        # Design system dark: #020617 bg, #7c3aed accent, Inter/JetBrains
│   └── js/app.js           # apiFetch, showToast, showConfirm, selectNiche, toggleUsed
│
├── migrations/versions/    # Alembic-style INERTE — o sistema real e _run_migrations() em database.py
│   ├── 001_initial_schema.py
│   └── 002_add_analytics.py
│
├── Dockerfile              # python:3.11-slim, ffmpeg, yt-dlp, non-root appuser
├── entrypoint.sh           # Fix permissions (/app/output) + uvicorn as appuser
├── test_app.py             # Smoke + DB + security tests (pytest) — 40 testes
└── tests/test_e2e.py       # Playwright E2E (login, nav, security headers)
```

> **Removido em mai/2026** (dead code): `gdrive_routes.py` na raiz, `protocols/narration_export.py`, e todo o subsistema NotebookLM de auto-captura (`nlm_routes.py`, `nlm_api_routes.py`, `channel_strategist.py`, `notebooklm_client.py`, `notebooklm_auth.py`, templates `admin_nlm_*`). O fluxo manual de colar o SOP do NotebookLM no pipeline (`nlm_sop`) **continua ativo**.

---

## 3. BANCO DE DADOS (21 tabelas SQLite)

### Tabelas Principais

| Tabela | PK | Colunas Chave | Relacoes |
|--------|-----|---------------|----------|
| **projects** | id (TEXT) | name, channel_original, niche_chosen, drive_folder_id, language, meta (JSON), status | → files, ideas, niches, scripts, activity_log |
| **files** | id (INT) | project_id, category, label, filename, content (TEXT), drive_url, visible_to_students, score_json | → projects |
| **ideas** | id (INT) | project_id, num, title, hook, summary, pillar, priority, status, score, rating, used | → projects, seo_packs, progress |
| **niches** | id (INT) | project_id, name, description, rpm_range, competition, color, chosen, pillars (JSON) | → projects |
| **scripts** | id (INT) | project_id, idea_id, title, content, duration_estimate, drive_url, status | → projects, ideas |
| **seo_packs** | id (INT) | idea_id, titles_ab (JSON), description, tags (JSON), hashtags (JSON), thumbnail_prompt | → ideas |

### Tabelas de Usuarios

| Tabela | PK | Colunas Chave | Relacoes |
|--------|-----|---------------|----------|
| **users** | id (INT) | name, email, password_hash (bcrypt), role (admin/student), api_key_encrypted (Fernet), max_titles, active, last_login | → sessions, assignments, notifications |
| **sessions** | token (TEXT) | user_id, created_at, expires_at (7 dias) | → users |
| **assignments** | id (INT) | student_id, project_id, niche, titles_released, status, schedule (JSON) | → users, projects, progress |
| **progress** | id (INT) | assignment_id, idea_id, student_id, status (pending/writing/recording/editing/published), video_url, notes | → assignments, ideas |

### Tabelas de Suporte

| Tabela | PK | Colunas Chave |
|--------|-----|---------------|
| **activity_log** | id | project_id, action, details, created_at |
| **admin_settings** | key (TEXT) | value (key-value store) |
| **notifications** | id | user_id, type, title, message, read, link |
| **student_channels** | id | student_id, channel_name, channel_url, niche, language, project_id, cached_stats (JSON), active |
| **student_drive_files** | id | student_id, file_id, drive_file_id, drive_folder_id, filename, category |
| **ai_usage** | id | project_id, user_id, model, prompt_tokens, completion_tokens, estimated_cost, operation |
| **video_performance** | id | student_id, channel_id, video_id, title, views, likes, comments, published_at |
| **keyword_cache** | id | keyword, country, language, volume, cpc, competition, cached_at (TTL 7 dias) |
| **admin_resources** | id | filename, category, content, visible_to_students, uploaded_by |
| **bent_ideas** | id | project_id, source, variations_json, starred (historico do Niche/Idea Bender) |
| **_migrations** | id | Controle de migrations executadas (via _run_migrations em database.py) |

### Padroes DB
- **Context manager**: `with get_db() as conn` (auto-commit/rollback)
- **WAL mode**: Concurrent reads during writes
- **Foreign keys**: PRAGMA foreign_keys=ON
- **Cascade delete**: project → (assignments → progress), files, ideas, niches, scripts, seo_packs, activity_log
- **Soft delete**: student_channels (active=0)
- **JSON columns**: niches.pillars, seo_packs.titles_ab/tags/hashtags, projects.meta, student_channels.cached_stats
- **Status flow**: pending → writing → recording → editing → published

---

## 4. PIPELINE PRINCIPAL (12 Steps)

O admin analisa um canal via `POST /api/admin/analyze-channel`. Roda em `asyncio.to_thread()` com SSE progress real-time.

```
Step 1:  Cria projeto + pasta Google Drive
Step 2:  Gera SOP (prioridade: Manual NLM > Transcricoes yt-dlp > AI fallback)
Step 3:  Gera 5 sub-nichos derivados (Niche Bending)
Step 4:  Gera 30 titulos virais (max 100 chars cada, YouTube limit)
Step 5:  Gera SEO Pack (10 videos: titles A/B, desc 150-200 words, tags max 500 chars, 10 hashtags)
Step 6:  Gera Thumbnail Prompts (Midjourney + DALL-E)
Step 7:  Gera Music Prompts (Suno/Udio/MusicGPT)
Step 8:  Gera Teaser Prompts (Shorts/Reels/TikTok)
Step 9:  Gera 3 roteiros completos (~2500-3500 words, markers: [MUSICA], [SFX], [B-ROLL])
Step 10: Gera Mind Map HTML interativo (dark theme, System Breakers design)
Step 11: Exporta 14 arquivos padrao pro Google Drive (Docs + Sheets)
Step 12: Pipeline concluido (SSE envia "done")
```

### SSE Progress
- `progress_store.py`: Thread-safe dict `{project_id: {step, total, label, detail, pct, ts}}`
- Endpoint: `GET /api/admin/pipeline-progress?niche=<name>`
- Poll 1s, timeout 10min, stale detection 5min

### SOP (17 Secoes)
1. Identidade profunda | 2. Formato e producao | 3. Anatomia do roteiro | 4. Playbook de hooks (8 tipos)
5. Tecnicas storytelling | 6. Regras de ouro (15 regras) | 7. Pilares de conteudo | 8. Formula titulos
9. Estilo thumbnail | 10. SEO | 11. Monetizacao | 12. Retencao | 13. Competidores | 14. Evolucao
15. System prompt para IA (300+ palavras) | 16. Template roteiro com timestamps | 17. Checklist qualidade (15 perguntas)

### 14 Arquivos Drive
1-3. SOP, SEO Pack, 30 Ideias (Docs) | 4-6. Roteiros 1/2/3 (Docs) | 7-9. Thumbnail/Music/Teaser Prompts (Docs)
10. Mind Map (Doc) | 11-13. Titulos, Nichos, SEO (Sheets) | 14. Narracoes Completas (Doc)

---

## 5. ROTAS API (~110 endpoints em 10 routers)

> As tabelas abaixo cobrem as rotas principais documentadas; o numero real cresceu (idea-bender, niches-lab, mockups, resources, drive-admin). Para a lista autoritativa, ver os `@router`/`@app` em `routes/*.py` e `dashboard.py`.

### Admin (principais)
| Metodo | Rota | Rate | Funcao |
|--------|------|------|--------|
| POST | /api/admin/analyze-channel | 3/min | Pipeline completo 12 steps |
| POST | /api/admin/create-student | 5/min | Criar aluno com niche |
| POST | /api/admin/delete-project | 10/min | Delete cascata |
| POST | /api/admin/delete-student | 10/min | Delete cascata |
| POST | /api/admin/connect-drive | 5/min | Criar pasta Drive |
| POST | /api/admin/sync-drive | 5/min | Re-sync 14 arquivos (dedup) |
| POST | /api/admin/release-titles | 20/min | Liberar titulos + notificacao |
| POST | /api/admin/assign-niche | 20/min | Atribuir nicho |
| POST | /api/admin/toggle-file-visibility | 20/min | Toggle visibilidade |
| POST | /api/admin/bulk-file-visibility | 20/min | Bulk toggle categoria |
| POST | /api/admin/add-student-channel | 20/min | Cadastrar canal (max 5) |
| POST | /api/admin/remove-student-channel | 20/min | Remover canal |
| POST | /api/admin/toggle-student | 20/min | Ativar/desativar |
| POST | /api/admin/remove-title | 20/min | Remover titulo |
| POST | /api/admin/youtube-settings | 5/min | Salvar YouTube API key |
| POST | /api/admin/evolve-sop | 3/min | SOP Vivo (canal ou alunos) |
| POST | /api/admin/trend-radar | 3/min | YouTube + Trends scan |
| POST | /api/admin/clone-language | 3/min | Adaptar projeto p/ idioma |
| POST | /api/regenerate-mindmap | 5/min | Re-gerar Mind Map HTML |
| GET | /api/admin/pipeline-progress | -- | SSE real-time |
| GET | /api/admin/youtube-stats | -- | Stats do canal |

### Aluno (16 rotas)
| Metodo | Rota | Rate | Funcao |
|--------|------|------|--------|
| POST | /api/student/generate-script | 10/min | Gerar roteiro (SOP completo como ref) |
| POST | /api/student/score-script | 10/min | AI Judge (0-100, 10 criterios) |
| POST | /api/student/update-progress | 30/min | Mover card Kanban |
| POST | /api/student/update-api-key | 10/min | Salvar API key encriptada |
| POST | /api/student/delete-file | 20/min | Excluir roteiro/narracao |
| POST | /api/student/fetch-channel-stats | 5/min | YouTube analytics |
| POST | /api/student/mark-notification-read | 30/min | Marcar lida |
| POST | /api/student/sync-to-drive | 5/min | Upload p/ Drive pessoal |
| POST | /api/student/generate-companion | 10/min | Gerar SEO/thumbnail/music/teaser |
| POST | /api/student/save-youtube-key | 5/min | Salvar YouTube Data API key |
| POST | /api/student/update-calendar | 3/min | AI sugere schedule posting |
| GET | /api/student/notifications | -- | Listar notificacoes |
| GET | /api/student/performance-summary | -- | Resumo performance |
| GET | /api/student/channels | -- | Listar canais |
| GET | /student | -- | Dashboard Kanban |

### Google Drive OAuth (4 rotas)
| Metodo | Rota | Funcao |
|--------|------|--------|
| GET | /api/admin/gdrive/auth | Inicia OAuth → Google (com PKCE) |
| GET | /api/admin/gdrive/callback | Callback Google → salva token |
| GET | /api/admin/gdrive/status | Status conexao + debug info |
| POST | /api/admin/gdrive/disconnect | Desconectar Drive |

### Gerais (6 rotas)
| Rota | Funcao |
|------|--------|
| GET / | Dashboard admin ou redirect /student |
| GET /login | Pagina login |
| POST /login | Autenticar |
| GET/POST /logout | Encerrar sessao |
| GET /api/health | Health check |
| GET /output-file?name= | Servir arquivo com access control |

---

## 6. FEATURES ESPECIAIS

### AI Script Judge
10 criterios (0-10 cada): Hook, Open Loops, Storytelling, Tom de Voz, Estrutura, Regras de Ouro, Duracao, Engagement, Originalidade, Fechamento
- Score total 0-100, grade A/B/C/D/F, threshold 80 p/ aprovacao
- Prompt: "Voce e um juiz IMPLACAVEL de qualidade"

### SOP Vivo
Modo 'canal': analisa videos do canal original
Modo 'alunos': compara Top 5 vs Bottom 5 dos alunos → sugere evolucoes nas secoes 2/4/6/8

### Radar de Tendencias
YouTube Search API (videos ultimas 2 semanas) + Google Trends (pytrends) → 10 titulos urgentes com janela de oportunidade

### Multi-Language Cloning
Adapta SOP + 30 titulos para outro idioma (nao traduz — adapta culturalmente)
Idiomas: pt-BR, en, es, fr, de, it, ja, ko

### Title Scoring
Formula: `final = (youtube_score * 0.6) + (avg_trends * 0.4)`
- YouTube: yt-dlp busca videos similares, calcula demand + competition
- Trends: pytrends por regiao (BR, US, global...), detecta subindo/descendo/estavel
- Rating: EXCELENTE (80+), BOM (60-79), MEDIO (40-59), BAIXO (0-39)

---

## 7. SEGURANCA

| Camada | Implementacao |
|--------|---------------|
| **Senhas** | bcrypt + salt (legacy SHA256 auto-rehash) |
| **API keys** | Fernet AES-128-CBC (ENCRYPTION_KEY env) |
| **Sessoes** | 64-char hex token, 7 dias, cookie httpOnly + secure + sameSite=lax |
| **CSRF** | HMAC-SHA256 (timestamp.signature), 24h validade, X-CSRF-Token header |
| **Rate limit** | SlowAPI por IP, 35 rotas protegidas |
| **Path traversal** | Block "..", "\", javascript:, data:, file://, localhost |
| **SSRF** | `validate_url` (services.py): allowlist youtube.com/youtu.be, rejeita IPs literais + metadata/loopback/privados |
| **IDOR** | Rotas de aluno (ideas, idea-details, improve-script, score-script) checam assignment do projeto |
| **Roles** | require_admin vs require_auth decorators (TODAS as rotas mutaveis exigem auth) |
| **Erros** | SafeErrorMiddleware: generic messages + error_id, stack trace so server-side; sem `str(e)` em respostas |
| **Drive** | Isolamento: aluno tem pasta propria, nao ve pasta do projeto |

> **Hardening mai/2026** (commit c369ca7): fechadas 5 rotas GET mutaveis sem auth, IDOR em rotas de aluno, SSRF via allowlist, rate-limit em 6 POST admin, fim de vazamento de `str(e)`. **Pendente (manual no EasyPanel):** rotacionar `DASH_PASS` (era 6 digitos), `LAOZHANG_API_KEY`, `CSRF_SECRET`; CSP ainda usa `unsafe-inline` (templates com JS inline).

---

## 8. AUTENTICACAO

### Fluxo
1. POST /login (email + password) → `authenticate_user()` (bcrypt verify)
2. `create_session()` → token 64-char hex → DB + memory cache
3. Cookie "session" set (httpOnly, secure, sameSite=lax, 7 dias)
4. Frontend: `window.SESSION_TOKEN` + `window.CSRF_TOKEN` injetados no base.html

### Token Extraction (prioridade)
1. Cookie "session"
2. Header "Authorization: Bearer ..."
3. Header "X-Session: ..."
4. Query param "_token" (para SSE)

### Middleware Stack (ordem execucao)
1. SafeErrorMiddleware (exceptions)
2. RequestLogMiddleware (timing)
3. CSRFMiddleware (POST/PUT/DELETE validation)
4. CORSMiddleware (headers)

---

## 9. AI CLIENT (protocols/ai_client.py)

- **API**: OpenAI-compatible (LaoZhang proxy)
- **Model default**: claude-sonnet-4-6
- **Retry**: 3x exponential backoff (2s, 4s, 8s) em 429/500/502/503/504
- **Timeout**: 180s default, 240s para script generation
- **Token tracking**: log_ai_usage() com cost estimation por modelo
- **Cost models**: Claude Sonnet ($3/$15 per 1M), GPT-4 ($2.5/$10), GPT-3.5 ($0.15/$0.6)

### Funcoes
- `chat(prompt, system, model, max_tokens, temperature, timeout)` → str
- `generate_script(title, hook, sop, niche, language)` → str (2000-3000 words)
- `generate_narration(script)` → str (clean TTS text, temp=0.3)

---

## 10. FRONTEND

### Design System (main.css)
- **Theme**: Dark (#020617 bg, #131a2e surfaces, #7c3aed accent purple)
- **Fonts**: Inter (UI), JetBrains Mono (data/numbers)
- **Grid**: Responsive auto-fit (2/3/5 columns)
- **Components**: Stats cards, niche cards, progress bars, modals, toasts

### JavaScript (app.js)
- `apiFetch(url, opts)` — Wrapper com CSRF + session headers, auto-redirect 401
- `apiPost(url, data)` — POST JSON shorthand
- `showToast(msg, type, duration)` — Notification (success/error/warning/loading, 3s)
- `showConfirm(title, msg, cb)` — Confirmation dialog
- `selectNiche(el, name)` — Toggle max 2 niches
- `toggleUsed(id)` — Strikethrough titulo usado
- `showIdeaDetails(id)` — Modal score breakdown por regiao

### Templates (15)
- **base.html**: Layout + CSRF/session injection + global JS
- **login.html / change_password.html**: Auth
- **dashboard.html**: Admin hub (pipeline, niches, ideas, YouTube stats)
- **student_dashboard.html**: Kanban + channels + analytics + API config
- **admin_panel.html**: System stats + API keys + AI analytics + users
- **admin_students.html / admin_student_detail.html**: CRUD alunos + detalhe (assignments, channels)
- **admin_projects.html**: Projetos + Drive sync + clone language
- **admin_niches_lab.html**: Niches Lab (Top Niches + Deep Dive DataForSEO)
- **admin_bent_ideas.html**: Historico do Niche/Idea Bender
- **admin_radar.html / admin_sop_analysis.html**: Radar de tendencias + analise SOP Vivo
- **_ab_title_block.html / _card_extras.html**: partials

---

## 11. VARIAVEIS DE AMBIENTE

```env
# Admin (obrigatorio)
DASH_USER=admin              # Username admin
DASH_PASS=                   # Senha (auto-gerada se vazio)
DASH_EMAIL=                  # Email (fallback: {user}@ytcloner.local)

# AI (obrigatorio para features AI)
LAOZHANG_API_KEY=sk-...      # API key LaoZhang
LAOZHANG_BASE_URL=https://api.laozhang.ai/v1
AI_MODEL=claude-sonnet-4-6

# Google Drive OAuth (opcional)
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=https://cloner.canaisdarks.com.br/api/admin/gdrive/callback

# Security (auto-gerado se vazio, mas PERSISTIR em .env)
ENCRYPTION_KEY=base64...     # Fernet key para API keys dos alunos
CSRF_SECRET=hex...           # HMAC secret para CSRF tokens

# Server
PORT=8888
LOG_LEVEL=info
COOKIE_SECURE=true
ALLOWED_ORIGINS=https://studio.canaisdarks.com.br

# Rate Limits
RATE_LIMIT_DEFAULT=30/minute
RATE_LIMIT_AI=5/minute
RATE_LIMIT_ANALYSIS=3/minute
```

---

## 12. DEPLOY

```bash
# Docker via EasyPanel
git add -A && git commit -m "msg" && git push origin master

# Se historico divergiu:
git push origin master --force
```

- **Image**: python:3.11-slim + ffmpeg + yt-dlp
- **Volume**: `ytcloner-data` → `/app/output` (DB + mindmaps)
- **Health**: `GET /api/health` cada 30s (timeout 10s, 3 retries)
- **User**: Non-root `appuser` via entrypoint.sh
- **Proxy**: `--proxy-headers --forwarded-allow-ips '*'`

---

## 13. DEPENDENCIAS (requirements.txt)

| Categoria | Pacotes |
|-----------|---------|
| **Web** | fastapi>=0.115, uvicorn[standard]>=0.30, jinja2>=3.1, python-multipart>=0.0.9 |
| **HTTP** | requests>=2.31, httpx>=0.27 |
| **Google** | google-api-python-client>=2.0, google-auth>=2.0, google-auth-oauthlib>=1.0, gspread>=6.0 |
| **YouTube** | youtube-transcript-api>=1.0, pytrends>=4.9 |
| **Security** | bcrypt>=4.0, cryptography>=41.0 |
| **Rate Limit** | slowapi>=0.1.9 |
| **Env** | python-dotenv>=1.0 |
| **Dev** | playwright>=1.40, ruff>=0.3, mypy>=1.8, bandit>=1.7, safety>=3.0 |

---

## 14. COMO DESENVOLVER

### Adicionar feature:
1. Migration em `database.py` (array `migrations`) + funcoes DB
2. Rota em `routes/` com `@limiter.limit()`
3. UI no template HTML + JS inline ou em app.js
4. Checar sintaxe: `python -c "import ast; ast.parse(open('arquivo.py').read())"`
5. Testar: `pytest test_app.py`

### Arquivos por tipo de mudanca:
| Mudanca | Arquivo |
|---------|---------|
| Novo endpoint admin | dashboard.py ou routes/api_routes.py |
| Novo endpoint aluno | routes/student_routes.py |
| Nova tabela/coluna | database.py (migrations + funcoes) |
| UI admin | templates/dashboard.html ou admin_*.html |
| UI aluno | templates/student_dashboard.html |
| Pipeline AI | dashboard.py (_run_pipeline) |
| Google Drive | routes/gdrive_routes.py + protocols/google_export.py |
| AI prompts | protocols/ai_client.py |
| Scoring titulos | protocols/title_scorer.py |

### Convencoes:
- Rate limit em TODA rota POST
- `try/except` com logging em toda operacao externa
- Notificacao pro aluno quando admin faz acao relevante
- Arquivos salvos com `save_file()` e categoria correta
- Activity log com `log_activity()` pra auditoria
- Imutabilidade: criar novos objetos, nao modificar existentes
- Funcoes < 50 linhas, arquivos < 800 linhas (exceto dashboard.py/database.py legados)
- Validar inputs na fronteira: sanitize_niche_name(), validate_url()

### CLI (run.py):
```bash
python run.py full <url> --niche "NICHE" --scripts 3
python run.py clerk <url> --name "Project Name"
python run.py niche --sop path/to/sop.md --original "Niche" --count 5
python run.py script --sop path/to/sop.md --niche "Niche" --count 10
python run.py export --name "Project" --sop sop.md --ideas ideas.md
```

---

## 15. FILOSOFIA DO PRODUTO

> "Voce NAO esta copiando — voce esta ELEVANDO."

O SOP mostra o que funciona. O aluno executa cada tecnica MELHOR:
- Hooks mais impactantes
- Open loops mais intrigantes
- Storytelling mais envolvente
- Spikes mais intensos
- Insights que o canal original NAO explorou

System prompt: "Seu trabalho NAO e copiar — e ELEVAR. Voce pega o que funciona e entrega uma versao MELHORADA."
