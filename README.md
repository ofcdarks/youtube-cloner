# YouTube Channel Cloner

AI-powered platform for YouTube channel analysis and faceless content generation.

## Features

- **Channel Analysis**: Extract SOP from any YouTube channel via transcripts, NotebookLM, or AI
- **Niche Generation**: Generate 5 sub-niches with RPM estimates and competition analysis
- **Title Generation**: Create 30 viral video ideas with hooks and priorities
- **Title Scoring**: Score titles using Google Trends + YouTube competition data
- **SEO Pack**: Generate titles A/B, descriptions, tags, and hashtags
- **Script Generation**: Full 10-12 min scripts with storytelling techniques
- **Mind Map**: Interactive HTML visualization of the entire strategy
- **Google Drive Export**: Auto-export SOPs, titles, and scripts to Drive
- **Team Management**: Admin/student roles with assignment tracking
- **Multi-Provider AI**: Support for LaoZhang, OpenAI, Anthropic, Google

## Quick Start

```bash
# 1. Clone and setup
cp .env.example .env
# Edit .env with your values (DASH_PASS, LAOZHANG_API_KEY, ENCRYPTION_KEY)

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python dashboard.py
# Open http://localhost:8888
```

## Docker

```bash
docker build -t ytcloner .
docker run -p 8888:8888 --env-file .env ytcloner
```

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DASH_PASS` | Admin password (required) |
| `ENCRYPTION_KEY` | Fernet key for API key encryption |
| `CSRF_SECRET` | Secret for CSRF token generation |
| `LAOZHANG_API_KEY` | AI provider API key |

See `.env.example` for all options.

## Architecture

```
├── config.py          # Centralized settings with validation
├── auth.py            # Session management, secure cookies
├── middleware.py       # CSRF, CORS, safe error handling
├── services.py        # Business logic (analysis, mindmap, validation)
├── database.py        # SQLite with context managers
├── dashboard.py       # FastAPI app assembly and routes
├── routes/            # Route modules
├── protocols/         # AI client, Google export, scoring
├── templates/         # Jinja2 templates
└── static/            # CSS, JS
```

## Security

- CSRF protection on all state-changing endpoints
- Bcrypt password hashing with legacy migration
- Fernet encryption for stored API keys
- Secure cookie flags (httponly, samesite, secure)
- Path traversal prevention
- Rate limiting on all sensitive endpoints
- Safe error messages (no internal leak)
- Input validation and sanitization
- Database file not served via static routes

## Tests

```bash
# Unit + integration tests
python test_app.py

# E2E browser tests (requires Playwright)
pip install playwright && playwright install chromium
python dashboard.py &
python tests/test_e2e.py
```

Covers: auth, database CRUD, API endpoints, security (path traversal, XSS), access control (admin vs student), input validation, CSRF, services/mindmap, full browser flows.

## Database Migrations

```bash
# Check migration status
python migrations/migrate.py status

# Apply pending migrations
python migrations/migrate.py up

# Rollback last migration
python migrations/migrate.py down

# Create new migration
python migrations/migrate.py create "add video analytics"
```

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`) runs on every push:
- **Lint**: Ruff linting and format check
- **Test**: Unit + integration tests, credential leak check
- **Security**: Bandit scan, dependency vulnerability check, hardcoded secret grep
- **Docker**: Build image + health check test
- **E2E**: Playwright browser tests (main branch only)

## CSS Architecture

Styles are extracted to `static/css/main.css` (598 lines) for browser caching. Templates use `{% block extra_style %}` for page-specific overrides. Design system tokens in CSS custom properties enable consistent theming.

