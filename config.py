"""
Centralized configuration — loads from environment variables with validation.
All secrets and settings are defined here. No hardcoded defaults for sensitive values.
"""

import os
import sys
import secrets
import logging
from pathlib import Path

# Load .env file if it exists (for local dev and Docker)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

logger = logging.getLogger("ytcloner.config")

# ── Paths ─────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR / "output"
PROJECTS_DIR = OUTPUT_DIR / "projects"
DB_PATH = OUTPUT_DIR / "ytcloner.db"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
(PROJECT_DIR / "static" / "js").mkdir(parents=True, exist_ok=True)

# ── Admin Credentials ────────────────────────────────────
DASH_USER = os.environ.get("DASH_USER", "")
DASH_PASS = os.environ.get("DASH_PASS", "")
DASH_EMAIL = os.environ.get("DASH_EMAIL", "")

# ── AI Settings ──────────────────────────────────────────
LAOZHANG_API_KEY = os.environ.get("LAOZHANG_API_KEY", "")
LAOZHANG_BASE_URL = os.environ.get("LAOZHANG_BASE_URL", "https://api.laozhang.ai/v1")
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")

# ── Keywords Everywhere ─────────────────────────────────
KEYWORDS_EVERYWHERE_API_KEY = os.environ.get("KEYWORDS_EVERYWHERE_API_KEY", "")

# ── Encryption ───────────────────────────────────────────
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

# ── CSRF ─────────────────────────────────────────────────
CSRF_SECRET = os.environ.get("CSRF_SECRET", "")

# ── CORS ─────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# ── Google OAuth ─────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# ── Server ───────────────────────────────────────────────
PORT = int(os.environ.get("PORT", "8888"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")

# ── Rate Limiting ────────────────────────────────────────
RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "30/minute")
RATE_LIMIT_AI = os.environ.get("RATE_LIMIT_AI", "5/minute")
RATE_LIMIT_ANALYSIS = os.environ.get("RATE_LIMIT_ANALYSIS", "3/minute")

# ── Constants ────────────────────────────────────────────
MAX_TOKENS_LARGE = 8000
MAX_TOKENS_MEDIUM = 4000
MAX_IDEAS_PER_REQUEST = 50
SESSION_EXPIRY_DAYS = 7

# ── Language labels (single source of truth) ─────────────
LANG_LABELS = {
    "pt-BR": "Portugues Brasileiro", "en": "English", "es": "Espanol",
    "fr": "Francais", "de": "Deutsch", "it": "Italiano", "ja": "Japones", "ko": "Coreano",
}
VALID_LANGS = set(LANG_LABELS.keys())

# ── Cookie settings ──────────────────────────────────────
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = "lax"
COOKIE_MAX_AGE = SESSION_EXPIRY_DAYS * 24 * 3600


def validate_startup() -> tuple[list[str], list[str]]:
    """Validate required configuration. Returns list of warnings/errors."""
    errors: list[str] = []
    warnings: list[str] = []

    # Admin credentials
    if not DASH_PASS:
        generated = secrets.token_urlsafe(16)
        os.environ["DASH_PASS"] = generated
        warnings.append(
            f"DASH_PASS not set! Generated temporary password: {generated} "
            f"— SET THIS IN .env FOR PRODUCTION"
        )

    if not DASH_USER:
        os.environ["DASH_USER"] = "admin"
        warnings.append("DASH_USER not set, defaulting to 'admin'")

    if not DASH_EMAIL:
        user = os.environ.get("DASH_USER", "admin")
        os.environ["DASH_EMAIL"] = f"{user}@ytcloner.local"

    # Encryption key
    if not ENCRYPTION_KEY:
        from cryptography.fernet import Fernet
        generated_key = Fernet.generate_key().decode()
        os.environ["ENCRYPTION_KEY"] = generated_key
        warnings.append(
            "ENCRYPTION_KEY not set! Generated temporary key. "
            "Student API keys will be lost on restart. SET THIS IN .env"
        )

    # CSRF secret
    if not CSRF_SECRET:
        os.environ["CSRF_SECRET"] = secrets.token_hex(32)
        warnings.append("CSRF_SECRET not set, generated temporary secret")

    # AI key
    if not LAOZHANG_API_KEY:
        warnings.append("LAOZHANG_API_KEY not set — AI features will not work")

    return errors, warnings


def print_startup_banner(errors: list[str], warnings: list[str]):
    """Print startup status."""
    print("\n" + "=" * 60)
    print("  YOUTUBE CHANNEL CLONER — Startup Check")
    print("=" * 60)

    if errors:
        for e in errors:
            print(f"  [FATAL] {e}")
        print("=" * 60)
        print("  Cannot start. Fix the errors above.")
        print("=" * 60 + "\n")
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")
    else:
        print("  [OK] All configuration validated")

    print("=" * 60 + "\n")
