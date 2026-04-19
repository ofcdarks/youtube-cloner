"""
Database — SQLite with proper connection management, encryption, and security.

All connections use context managers to prevent leaks.
API keys are encrypted with Fernet (ENCRYPTION_KEY env var required for persistence).
Passwords use bcrypt.
"""

import sqlite3
import json
import hashlib
import base64
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager

import bcrypt
from cryptography.fernet import Fernet

from config import DB_PATH, ENCRYPTION_KEY

logger = logging.getLogger("ytcloner.db")


# ── Connection Management ────────────────────────────────

@contextmanager
def get_db():
    """Context manager for database connections. Always use with `with`."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL is persistent — set once in init_db(), not per-connection
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables and run migrations."""
    with get_db() as conn:
        # WAL mode is persistent — set once here, not per-connection
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel_original TEXT,
                niche_chosen TEXT,
                drive_folder_id TEXT,
                drive_folder_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                meta TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                category TEXT NOT NULL,
                label TEXT NOT NULL,
                filename TEXT NOT NULL,
                content TEXT,
                drive_url TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                num INTEGER,
                title TEXT NOT NULL,
                hook TEXT,
                summary TEXT,
                pillar TEXT,
                priority TEXT DEFAULT 'MEDIA',
                status TEXT DEFAULT 'idea',
                score INTEGER DEFAULT 0,
                rating TEXT DEFAULT '',
                used INTEGER DEFAULT 0,
                score_details TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS niches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                rpm_range TEXT,
                competition TEXT,
                color TEXT,
                chosen INTEGER DEFAULT 0,
                pillars TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                idea_id INTEGER,
                title TEXT NOT NULL,
                content TEXT,
                duration_estimate TEXT,
                drive_url TEXT,
                status TEXT DEFAULT 'draft',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (idea_id) REFERENCES ideas(id)
            );

            CREATE TABLE IF NOT EXISTS seo_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idea_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                titles_ab TEXT,
                description TEXT,
                tags TEXT,
                hashtags TEXT,
                thumbnail_prompt TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (idea_id) REFERENCES ideas(id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                action TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                api_provider TEXT DEFAULT '',
                api_key_encrypted TEXT DEFAULT '',
                max_titles INTEGER DEFAULT 5,
                created_by INTEGER,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login TEXT
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                niche TEXT NOT NULL,
                titles_released INTEGER DEFAULT 5,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES users(id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                idea_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                video_url TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                script_generated INTEGER DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                FOREIGN KEY (idea_id) REFERENCES ideas(id),
                FOREIGN KEY (student_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS _migrations (id TEXT PRIMARY KEY);

            CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
            CREATE INDEX IF NOT EXISTS idx_ideas_project ON ideas(project_id);
            CREATE INDEX IF NOT EXISTS idx_scripts_project ON scripts(project_id);
            CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_log(project_id);
            CREATE INDEX IF NOT EXISTS idx_assignments_student ON assignments(student_id);
            CREATE INDEX IF NOT EXISTS idx_progress_student ON progress(student_id);
            CREATE INDEX IF NOT EXISTS idx_progress_assignment ON progress(assignment_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

            -- Performance indexes (tables that exist at init time)
            CREATE INDEX IF NOT EXISTS idx_files_visible ON files(project_id, visible_to_students);
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token, expires_at);
            CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);
            CREATE INDEX IF NOT EXISTS idx_niches_project ON niches(project_id);
        """)

    # Run safe migrations for columns that may not exist
    _run_migrations()
    logger.info(f"Database initialized: {DB_PATH}")


def _run_migrations():
    """Add columns that may be missing from older schema versions."""
    migrations = [
        ("ideas_score", "ALTER TABLE ideas ADD COLUMN score INTEGER DEFAULT 0"),
        ("ideas_rating", "ALTER TABLE ideas ADD COLUMN rating TEXT DEFAULT ''"),
        ("ideas_used", "ALTER TABLE ideas ADD COLUMN used INTEGER DEFAULT 0"),
        ("ideas_score_details", "ALTER TABLE ideas ADD COLUMN score_details TEXT DEFAULT '{}'"),
        ("projects_language", "ALTER TABLE projects ADD COLUMN language TEXT DEFAULT 'pt-BR'"),
        ("files_visible", "ALTER TABLE files ADD COLUMN visible_to_students INTEGER DEFAULT 0"),
        # v8.7: Student channels
        ("create_student_channels", """CREATE TABLE IF NOT EXISTS student_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            channel_name TEXT NOT NULL,
            channel_url TEXT DEFAULT '',
            channel_id TEXT DEFAULT '',
            niche TEXT DEFAULT '',
            language TEXT DEFAULT 'pt-BR',
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES users(id)
        )"""),
        # v8.7: Student drive files (track what's in their Drive folder)
        ("create_student_drive_files", """CREATE TABLE IF NOT EXISTS student_drive_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            file_id INTEGER,
            drive_file_id TEXT DEFAULT '',
            drive_folder_id TEXT DEFAULT '',
            filename TEXT NOT NULL,
            label TEXT DEFAULT '',
            category TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES users(id),
            FOREIGN KEY (file_id) REFERENCES files(id)
        )"""),
        # v8.7: Student Drive folder ID on users table
        ("users_drive_folder", "ALTER TABLE users ADD COLUMN drive_folder_id TEXT DEFAULT ''"),
        # v8.7: Schedule info on assignments
        ("assignments_schedule", "ALTER TABLE assignments ADD COLUMN schedule TEXT DEFAULT '{}'"),
        # v8.7: Channel ID on progress (which channel this title is for)
        ("progress_channel_id", "ALTER TABLE progress ADD COLUMN channel_id INTEGER DEFAULT 0"),
        # v10.0: A/B title decision log (regra 6h)
        ("progress_ab_decision", "ALTER TABLE progress ADD COLUMN ab_decision TEXT DEFAULT ''"),
        ("progress_ab_decided_at", "ALTER TABLE progress ADD COLUMN ab_decided_at TEXT DEFAULT ''"),
        ("progress_ab_reason", "ALTER TABLE progress ADD COLUMN ab_reason TEXT DEFAULT ''"),
        # v8.9: Notifications
        ("create_notifications", """CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT DEFAULT '',
            read INTEGER DEFAULT 0,
            link TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )"""),
        # v8.9: AI usage tracking
        ("create_ai_usage", """CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT DEFAULT '',
            user_id INTEGER DEFAULT 0,
            model TEXT DEFAULT '',
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0.0,
            operation TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )"""),
        ("files_score_json", "ALTER TABLE files ADD COLUMN score_json TEXT DEFAULT ''"),
        # v9.2: Video performance tracking
        ("create_video_performance", """CREATE TABLE IF NOT EXISTS video_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            channel_id INTEGER DEFAULT 0,
            video_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            published_at TEXT DEFAULT '',
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            duration TEXT DEFAULT '',
            thumbnail_url TEXT DEFAULT '',
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES users(id)
        )"""),
        ("student_channels_project_id", "ALTER TABLE student_channels ADD COLUMN project_id TEXT DEFAULT ''"),
        ("student_channels_stats", "ALTER TABLE student_channels ADD COLUMN cached_stats TEXT DEFAULT ''"),
        # Performance indexes for migration-created tables
        ("idx_notif_user_read", "CREATE INDEX IF NOT EXISTS idx_notif_user_read ON notifications(user_id, read)"),
        ("idx_video_perf_student", "CREATE INDEX IF NOT EXISTS idx_video_perf_student ON video_performance(student_id)"),
        # Allow admin to share their API key with students
        ("users_use_admin_api", "ALTER TABLE users ADD COLUMN use_admin_api INTEGER DEFAULT 0"),
        # First-login flow: when 1, the user must change their password before continuing
        ("users_must_change_password", "ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0"),
        ("ideas_search_volume", "ALTER TABLE ideas ADD COLUMN search_volume INTEGER DEFAULT 0"),
        ("ideas_search_competition", "ALTER TABLE ideas ADD COLUMN search_competition REAL DEFAULT -1"),
        ("ideas_title_b", "ALTER TABLE ideas ADD COLUMN title_b TEXT DEFAULT ''"),
        ("ideas_trending", "ALTER TABLE ideas ADD COLUMN trending INTEGER DEFAULT 0"),
        # Keyword cache per project (avoid re-researching every time)
        ("create_keyword_cache", """CREATE TABLE IF NOT EXISTS keyword_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            keywords_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )"""),
        ("idx_keyword_cache_project", "CREATE INDEX IF NOT EXISTS idx_kw_cache_proj ON keyword_cache(project_id)"),
        # Admin resources — files shared with students for download
        ("create_admin_resources", """CREATE TABLE IF NOT EXISTS admin_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            description TEXT DEFAULT '',
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            category TEXT DEFAULT 'general',
            badge_color TEXT DEFAULT '#7c3aed',
            badge_icon TEXT DEFAULT '📦',
            target_student_id INTEGER DEFAULT 0,
            target_project_id TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            downloads INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (target_student_id) REFERENCES users(id)
        )"""),
        # v8.8: Idea Bender history (niche/idea bending tool)
        ("create_bent_ideas", """CREATE TABLE IF NOT EXISTS bent_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_mode TEXT NOT NULL DEFAULT 'internal',
            source_project_id TEXT DEFAULT '',
            source_idea_id INTEGER DEFAULT 0,
            source_title TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            source_views INTEGER DEFAULT 0,
            language TEXT DEFAULT 'en',
            dna_json TEXT DEFAULT '{}',
            variations_json TEXT DEFAULT '[]',
            num_variations INTEGER DEFAULT 5,
            created_at TEXT NOT NULL,
            created_by INTEGER DEFAULT 0
        )"""),
        ("idx_bent_ideas_project", "CREATE INDEX IF NOT EXISTS idx_bent_ideas_project ON bent_ideas(source_project_id)"),
        ("backfill_search_volume", "SELECT 1"),  # handled below as custom migration
    ]
    with get_db() as conn:
        for migration_id, sql in migrations:
            try:
                existing = conn.execute(
                    "SELECT id FROM _migrations WHERE id=?", (migration_id,)
                ).fetchone()
                if not existing:
                    conn.execute(sql)
                    conn.execute("INSERT INTO _migrations (id) VALUES (?)", (migration_id,))
            except Exception:
                pass  # Column already exists

        # Backfill search_volume from score_details JSON for already-scored ideas
        try:
            rows = conn.execute(
                "SELECT id, score_details FROM ideas WHERE score > 0 AND (search_volume IS NULL OR search_volume = 0) AND score_details != '{}'"
            ).fetchall()
            for row in rows:
                try:
                    details = json.loads(row["score_details"]) if isinstance(row["score_details"], str) else row["score_details"]
                    vol = details.get("search_volume", 0)
                    if vol and vol > 0:
                        conn.execute("UPDATE ideas SET search_volume=? WHERE id=?", (vol, row["id"]))
                except (ValueError, TypeError, KeyError):
                    pass
        except Exception:
            pass


# ── Password Hashing ─────────────────────────────────────

_LEGACY_SALT = "ytcloner_salt"


def _hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    """Verify password. Falls back to legacy SHA256 for migration."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        old_hash = hashlib.sha256((password + _LEGACY_SALT).encode()).hexdigest()
        return old_hash == hashed


# ── API Key Encryption ───────────────────────────────────

def _get_fernet() -> Fernet:
    """Get Fernet cipher. Uses ENCRYPTION_KEY from env (validated at startup)."""
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key or len(key) != 44:
        raise ValueError(
            "ENCRYPTION_KEY not set or invalid. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt_api_key(key: str) -> str:
    """Encrypt API key using Fernet."""
    if not key:
        return ""
    try:
        return _get_fernet().encrypt(key.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return ""


def _decrypt_api_key(encrypted: str) -> str:
    """Decrypt API key using Fernet. Returns empty string if decryption fails."""
    if not encrypted:
        return ""
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        # SECURITY: Removed legacy base64 fallback (base64 is encoding, not encryption).
        # If decryption fails, user must re-enter their API key.
        logger.warning("API key decryption failed — user must re-enter key")
        return ""


# ── Projects ─────────────────────────────────────────────

def create_project(
    name: str,
    channel_original: str = "",
    niche_chosen: str = "",
    drive_folder_id: str = "",
    meta: dict | None = None,
    language: str = "pt-BR",
) -> str:
    now = datetime.now().isoformat()
    pid = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name.lower().replace(' ', '_')[:50]}"
    drive_url = f"https://drive.google.com/drive/folders/{drive_folder_id}" if drive_folder_id else ""

    with get_db() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, channel_original, niche_chosen, drive_folder_id, drive_folder_url, created_at, updated_at, meta, language) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, name, channel_original, niche_chosen, drive_folder_id, drive_url, now, now, json.dumps(meta or {}), language),
        )
        log_activity(pid, "project_created", f"Projeto '{name}' criado ({language})", conn)
    return pid


def get_projects(status: str = "active") -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row) if row else None


def update_project(project_id: str, **kwargs):
    """Update project fields. Only allowed fields are updated."""
    allowed = {"name", "channel_original", "niche_chosen", "drive_folder_id", "drive_folder_url", "status", "meta", "language"}
    updates, values = [], []
    for k, v in kwargs.items():
        if k in allowed:
            updates.append(f"{k}=?")
            values.append(v)
    if not updates:
        return
    updates.append("updated_at=?")
    values.append(datetime.now().isoformat())
    values.append(project_id)
    with get_db() as conn:
        conn.execute(f"UPDATE projects SET {','.join(updates)} WHERE id=?", values)


def delete_project(project_id: str):
    """Delete a project and all related data (cascade through assignments)."""
    with get_db() as conn:
        # First delete progress via assignments (progress has no project_id column)
        assignment_ids = [r[0] for r in conn.execute(
            "SELECT id FROM assignments WHERE project_id=?", (project_id,)
        ).fetchall()]
        if assignment_ids:
            placeholders = ",".join("?" * len(assignment_ids))
            conn.execute(f"DELETE FROM progress WHERE assignment_id IN ({placeholders})", assignment_ids)

        # Delete other tables that have project_id
        for table in ["assignments", "seo_packs", "scripts", "niches", "ideas", "files", "activity_log"]:
            try:
                conn.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            except Exception:
                pass
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


# ── Files ────────────────────────────────────────────────

def save_file(project_id: str, category: str, label: str, filename: str, content: str = "", drive_url: str = "", visible_to_students: bool = False):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO files (project_id, category, label, filename, content, drive_url, created_at, visible_to_students) VALUES (?,?,?,?,?,?,?,?)",
            (project_id, category, label, filename, content, drive_url, now, 1 if visible_to_students else 0),
        )


def get_files(project_id: str, category: str | None = None) -> list[dict]:
    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM files WHERE project_id=? AND category=? ORDER BY created_at",
                (project_id, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM files WHERE project_id=? ORDER BY category, created_at",
                (project_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_file(file_id: int) -> dict | None:
    """Delete a file by id. Returns the file record before deletion or None."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM files WHERE id=?", (file_id,))
            return dict(row)
    return None


# ── Ideas ────────────────────────────────────────────────

YOUTUBE_TITLE_MAX_CHARS = 100


def enforce_title_limit(title: str, max_chars: int = YOUTUBE_TITLE_MAX_CHARS) -> str:
    """Enforce YouTube 100-char title limit.

    Strategy:
    1. Strip whitespace
    2. If within limit, return as-is
    3. Try truncating at last word boundary <= max_chars
    4. If no word boundary works, hard-truncate at max_chars

    Never adds ellipsis (would waste 3 chars) — YouTube counts total chars.
    """
    if not title:
        return title
    t = title.strip()
    if len(t) <= max_chars:
        return t
    # Try to find last word boundary before max_chars
    cut = t[:max_chars].rstrip()
    # Walk back to last space to avoid breaking a word
    if " " in cut:
        last_space = cut.rfind(" ")
        # Only use word boundary if it's not too aggressive (lose < 25% of limit)
        if last_space >= max_chars * 0.75:
            cut = cut[:last_space].rstrip()
    # Strip trailing punctuation that looks weird at cut point
    while cut and cut[-1] in ",;:.-|":
        cut = cut[:-1].rstrip()
    return cut[:max_chars]


def save_idea(
    project_id: str,
    num: int,
    title: str,
    hook: str = "",
    summary: str = "",
    pillar: str = "",
    priority: str = "MEDIA",
    search_volume: int = 0,
    search_competition: float = -1,
    title_b: str = "",
    trending: int = 0,
) -> int:
    # Enforce YouTube 100-char limit on both title and title_b
    title = enforce_title_limit(title)
    if title_b:
        title_b = enforce_title_limit(title_b)
    now = datetime.now().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO ideas (project_id, num, title, hook, summary, pillar, priority, search_volume, search_competition, title_b, trending, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, num, title, hook, summary, pillar, priority, search_volume, search_competition, title_b, trending, now),
        )
        return cur.lastrowid


def update_idea_title(idea_id: int, title: str, title_b: str = None) -> bool:
    """Update an idea's title, enforcing the 100-char limit."""
    title = enforce_title_limit(title)
    with get_db() as conn:
        if title_b is not None:
            title_b = enforce_title_limit(title_b)
            conn.execute("UPDATE ideas SET title=?, title_b=? WHERE id=?", (title, title_b, idea_id))
        else:
            conn.execute("UPDATE ideas SET title=? WHERE id=?", (title, idea_id))
    return True


def find_long_titles(max_chars: int = YOUTUBE_TITLE_MAX_CHARS) -> list[dict]:
    """Find all ideas with titles exceeding the limit."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, project_id, num, title, title_b FROM ideas WHERE length(title) > ? OR length(title_b) > ?",
            (max_chars, max_chars),
        ).fetchall()
    return [dict(r) for r in rows]


def get_ideas(project_id: str, pillar: str | None = None, priority: str | None = None) -> list[dict]:
    with get_db() as conn:
        query = "SELECT * FROM ideas WHERE project_id=?"
        params: list = [project_id]
        if pillar:
            query += " AND pillar=?"
            params.append(pillar)
        if priority:
            query += " AND priority=?"
            params.append(priority)
        query += " ORDER BY num"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_idea(idea_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    return dict(row) if row else None


def update_idea_status(idea_id: int, status: str):
    with get_db() as conn:
        conn.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))


def toggle_idea_used(idea_id: int) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT used FROM ideas WHERE id=?", (idea_id,)).fetchone()
        new_val = 0 if (row and row["used"]) else 1
        conn.execute("UPDATE ideas SET used=? WHERE id=?", (new_val, idea_id))
    return new_val


def update_idea_score(idea_id: int, score: int, rating: str = "", details: dict | None = None):
    with get_db() as conn:
        search_vol = (details or {}).get("search_volume", 0) if details else 0
        conn.execute(
            "UPDATE ideas SET score=?, rating=?, score_details=?, search_volume=? WHERE id=?",
            (score, rating, json.dumps(details or {}), search_vol, idea_id),
        )


def get_keyword_cache(project_id: str) -> list[dict] | None:
    """Get cached keywords for a project if still valid (< 7 days old)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT keywords_json, expires_at FROM keyword_cache WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    if not row:
        return None
    if row["expires_at"] < datetime.now().isoformat():
        return None  # Expired
    try:
        return json.loads(row["keywords_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def save_keyword_cache(project_id: str, keywords: list[dict]):
    """Cache keywords for a project (valid for 7 days)."""
    now = datetime.now()
    expires = (now + timedelta(days=7)).isoformat()
    with get_db() as conn:
        # Remove old cache for this project
        conn.execute("DELETE FROM keyword_cache WHERE project_id=?", (project_id,))
        conn.execute(
            "INSERT INTO keyword_cache (project_id, keywords_json, created_at, expires_at) VALUES (?,?,?,?)",
            (project_id, json.dumps(keywords), now.isoformat(), expires),
        )


def delete_idea(idea_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM seo_packs WHERE idea_id=?", (idea_id,))
        conn.execute("DELETE FROM progress WHERE idea_id=?", (idea_id,))
        conn.execute("DELETE FROM scripts WHERE idea_id=?", (idea_id,))
        conn.execute("DELETE FROM ideas WHERE id=?", (idea_id,))


# ── Niches ───────────────────────────────────────────────

def save_niche(
    project_id: str,
    name: str,
    description: str = "",
    rpm_range: str = "",
    competition: str = "",
    color: str = "#888",
    chosen: bool = False,
    pillars: list | None = None,
):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO niches (project_id, name, description, rpm_range, competition, color, chosen, pillars, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, name, description, rpm_range, competition, color, int(chosen), json.dumps(pillars or []), now),
        )


def update_niche_chosen(niche_id: int, chosen: bool):
    """Toggle the chosen flag on a niche."""
    with get_db() as conn:
        conn.execute("UPDATE niches SET chosen=? WHERE id=?", (int(chosen), niche_id))


def clear_niches_chosen(project_id: str):
    """Reset all niches chosen flag for a project."""
    with get_db() as conn:
        conn.execute("UPDATE niches SET chosen=0 WHERE project_id=?", (project_id,))


def get_niches(project_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM niches WHERE project_id=? ORDER BY chosen DESC, name", (project_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Scripts ──────────────────────────────────────────────

def save_script(
    project_id: str,
    title: str,
    content: str = "",
    idea_id: int | None = None,
    duration_estimate: str = "",
    drive_url: str = "",
):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO scripts (project_id, idea_id, title, content, duration_estimate, drive_url, created_at) VALUES (?,?,?,?,?,?,?)",
            (project_id, idea_id, title, content, duration_estimate, drive_url, now),
        )


def get_scripts(project_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM scripts WHERE project_id=? ORDER BY created_at", (project_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── SEO ──────────────────────────────────────────────────

def save_seo(
    project_id: str,
    idea_id: int,
    titles_ab: list,
    description: str = "",
    tags: str = "",
    hashtags: str = "",
    thumbnail_prompt: str = "",
):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO seo_packs (idea_id, project_id, titles_ab, description, tags, hashtags, thumbnail_prompt, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (idea_id, project_id, json.dumps(titles_ab), description, json.dumps(tags), json.dumps(hashtags), thumbnail_prompt, now),
        )


def get_seo(idea_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM seo_packs WHERE idea_id=?", (idea_id,)).fetchone()
    return dict(row) if row else None


# ── Activity Log ─────────────────────────────────────────

def log_activity(project_id: str | None, action: str, details: str = "", conn=None):
    """Log an activity. Accepts optional existing connection for transaction use."""
    now = datetime.now().isoformat()
    if conn is not None:
        conn.execute(
            "INSERT INTO activity_log (project_id, action, details, created_at) VALUES (?,?,?,?)",
            (project_id, action, details, now),
        )
    else:
        with get_db() as c:
            c.execute(
                "INSERT INTO activity_log (project_id, action, details, created_at) VALUES (?,?,?,?)",
                (project_id, action, details, now),
            )


def get_activity(project_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Get activity log with pagination support."""
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE project_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
    return [dict(r) for r in rows]


# ── Search ───────────────────────────────────────────────

def search(query: str, project_id: str | None = None) -> dict:
    """Search ideas, scripts, and files."""
    q = f"%{query}%"
    with get_db() as conn:
        if project_id:
            ideas = [dict(r) for r in conn.execute(
                "SELECT * FROM ideas WHERE project_id=? AND (title LIKE ? OR hook LIKE ? OR summary LIKE ?)",
                (project_id, q, q, q),
            ).fetchall()]
            scripts = [dict(r) for r in conn.execute(
                "SELECT * FROM scripts WHERE project_id=? AND (title LIKE ? OR content LIKE ?)",
                (project_id, q, q),
            ).fetchall()]
            files = [dict(r) for r in conn.execute(
                "SELECT * FROM files WHERE project_id=? AND (label LIKE ? OR content LIKE ?)",
                (project_id, q, q),
            ).fetchall()]
        else:
            ideas = [dict(r) for r in conn.execute(
                "SELECT * FROM ideas WHERE title LIKE ? OR hook LIKE ?", (q, q)
            ).fetchall()]
            scripts = [dict(r) for r in conn.execute(
                "SELECT * FROM scripts WHERE title LIKE ? OR content LIKE ?", (q, q)
            ).fetchall()]
            files = [dict(r) for r in conn.execute(
                "SELECT * FROM files WHERE label LIKE ?", (q,)
            ).fetchall()]

    return {"ideas": ideas, "scripts": scripts, "files": files}


# ── Stats ────────────────────────────────────────────────

def get_stats() -> dict:
    """Get all table counts in a single query instead of 6 round-trips."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM projects) as projects,
                (SELECT COUNT(*) FROM ideas) as ideas,
                (SELECT COUNT(*) FROM scripts) as scripts,
                (SELECT COUNT(*) FROM niches) as niches,
                (SELECT COUNT(*) FROM files) as files,
                (SELECT COUNT(*) FROM seo_packs) as seo_packs
        """).fetchone()
        return {
            "projects": row["projects"],
            "ideas": row["ideas"],
            "scripts": row["scripts"],
            "niches": row["niches"],
            "files": row["files"],
            "seo_packs": row["seo_packs"],
        }


# ── Users ────────────────────────────────────────────────

def create_user(
    name: str,
    email: str,
    password: str,
    role: str = "student",
    created_by: int | None = None,
    must_change_password: bool = False,
) -> int | None:
    now = datetime.now().isoformat()
    password_hash = _hash_password(password)
    with get_db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, role, created_by, created_at, must_change_password) VALUES (?,?,?,?,?,?,?)",
                (name, email, password_hash, role, created_by, now, 1 if must_change_password else 0),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def change_user_password(user_id: int, new_password: str) -> bool:
    """Hash and persist a new password, clearing the must_change_password flag."""
    if not new_password or len(new_password) < 6:
        return False
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
            (_hash_password(new_password), user_id),
        )
    return True


def authenticate_user(email: str, password: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
        if row and _verify_password(password, row["password_hash"]):
            conn.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.now().isoformat(), row["id"]))
            # Rehash with bcrypt if still using legacy SHA256
            if not row["password_hash"].startswith("$2"):
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_password(password), row["id"]))
            return dict(row)
    return None


def get_users(role: str | None = None) -> list[dict]:
    with get_db() as conn:
        if role:
            rows = conn.execute("SELECT * FROM users WHERE role=? ORDER BY created_at DESC", (role,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_user(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_user(user_id: int, **kwargs):
    allowed = {"name", "email", "role", "api_provider", "api_key_encrypted", "max_titles", "active", "use_admin_api"}
    updates, values = [], []
    for k, v in kwargs.items():
        if k in allowed:
            updates.append(f"{k}=?")
            values.append(v)
    if updates:
        values.append(user_id)
        with get_db() as conn:
            conn.execute(f"UPDATE users SET {','.join(updates)} WHERE id=?", values)


def delete_user(user_id: int):
    """Delete user and all related data across all tables."""
    with get_db() as conn:
        conn.execute("DELETE FROM progress WHERE student_id=?", (user_id,))
        conn.execute("DELETE FROM assignments WHERE student_id=?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        try:
            conn.execute("DELETE FROM notifications WHERE user_id=?", (user_id,))
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM student_channels WHERE student_id=?", (user_id,))
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM student_drive_files WHERE student_id=?", (user_id,))
        except Exception:
            pass
        try:
            conn.execute("DELETE FROM video_performance WHERE student_id=?", (user_id,))
        except Exception:
            pass
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


# ── Assignments ──────────────────────────────────────────

def create_assignment(student_id: int, project_id: str, niche: str, titles_released: int = 5) -> int:
    now = datetime.now().isoformat()
    with get_db() as conn:
        if not project_id:
            first = conn.execute(
                "SELECT id FROM projects WHERE status='active' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if first:
                project_id = first["id"]

        cur = conn.execute(
            "INSERT INTO assignments (student_id, project_id, niche, titles_released, created_at) VALUES (?,?,?,?,?)",
            (student_id, project_id, niche, titles_released, now),
        )
        assignment_id = cur.lastrowid

        ideas = conn.execute(
            "SELECT * FROM ideas WHERE project_id=? ORDER BY score DESC, num ASC LIMIT ?",
            (project_id, titles_released),
        ).fetchall()

        for idea in ideas:
            conn.execute(
                "INSERT INTO progress (assignment_id, idea_id, student_id, status, created_at) VALUES (?,?,?,?,?)",
                (assignment_id, idea["id"], student_id, "pending", now),
            )
    return assignment_id


def delete_assignment(assignment_id: int) -> dict:
    """Remove um assignment e todo o progress relacionado (cascade manual)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT student_id, project_id, niche FROM assignments WHERE id=?",
            (assignment_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "assignment nao encontrado"}
        info = dict(row)
        conn.execute("DELETE FROM progress WHERE assignment_id=?", (assignment_id,))
        conn.execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
    return {"ok": True, "info": info}


def get_assignments(student_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        query = """
            SELECT a.*, u.name as student_name, u.email as student_email,
                   (SELECT COUNT(*) FROM progress WHERE assignment_id=a.id) as total_titles,
                   (SELECT COUNT(*) FROM progress WHERE assignment_id=a.id AND status='published') as completed_titles
            FROM assignments a
            JOIN users u ON a.student_id = u.id
        """
        if student_id:
            query += " WHERE a.student_id=?"
            rows = conn.execute(query + " ORDER BY a.created_at DESC", (student_id,)).fetchall()
        else:
            rows = conn.execute(query + " ORDER BY a.created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_student_ideas(assignment_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.*, p.completed_at, p.ab_decision, p.ab_decided_at, p.video_url,
                      i.title, i.title_b, i.hook, i.summary, i.pillar, i.priority, i.score, i.rating, i.num
               FROM progress p
               JOIN ideas i ON p.idea_id = i.id
               WHERE p.assignment_id=?
               ORDER BY i.score DESC, i.num ASC""",
            (assignment_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_progress(progress_id: int, status: str, video_url: str = "", notes: str = ""):
    now = datetime.now().isoformat()
    with get_db() as conn:
        updates = ["status=?"]
        values: list = [status]
        if video_url:
            updates.append("video_url=?")
            values.append(video_url)
        if notes:
            updates.append("notes=?")
            values.append(notes)
        if status in ("writing", "recording", "editing"):
            updates.append("started_at=COALESCE(started_at, ?)")
            values.append(now)
        if status == "published":
            updates.append("completed_at=?")
            values.append(now)
        values.append(progress_id)
        conn.execute(f"UPDATE progress SET {','.join(updates)} WHERE id=?", values)


def release_more_titles(assignment_id: int, count: int) -> int:
    with get_db() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,)).fetchone()
        if not assignment:
            return 0

        new_total = assignment["titles_released"] + count
        conn.execute("UPDATE assignments SET titles_released=? WHERE id=?", (new_total, assignment_id))

        existing = conn.execute("SELECT idea_id FROM progress WHERE assignment_id=?", (assignment_id,)).fetchall()
        existing_ids = {r["idea_id"] for r in existing}

        all_ideas = conn.execute(
            "SELECT * FROM ideas WHERE project_id=? ORDER BY score DESC, num ASC",
            (assignment["project_id"],),
        ).fetchall()

        now = datetime.now().isoformat()
        added = 0
        for idea in all_ideas:
            if idea["id"] not in existing_ids and added < count:
                conn.execute(
                    "INSERT INTO progress (assignment_id, idea_id, student_id, status, created_at) VALUES (?,?,?,?,?)",
                    (assignment_id, idea["id"], assignment["student_id"], "pending", now),
                )
                added += 1
    return added


def mark_progress_script_generated(progress_id: int):
    with get_db() as conn:
        conn.execute("UPDATE progress SET script_generated=1 WHERE id=?", (progress_id,))


def get_admin_overview() -> list[dict]:
    """Get student overview with assignment stats — single query, no N+1."""
    with get_db() as conn:
        # Check if use_admin_api column exists (migration may not have run yet)
        has_admin_api_col = False
        try:
            conn.execute("SELECT use_admin_api FROM users LIMIT 0")
            has_admin_api_col = True
        except Exception:
            pass

        admin_api_select = ", u.use_admin_api" if has_admin_api_col else ", 0 as use_admin_api"
        rows = conn.execute(f"""
            SELECT u.id, u.name, u.email, u.api_key_encrypted, u.last_login, u.created_at,
                   u.drive_folder_id, u.active{admin_api_select},
                   GROUP_CONCAT(DISTINCT a.niche) as niches,
                   COALESCE(SUM(p_counts.total), 0) as total_assigned,
                   COALESCE(SUM(p_counts.completed), 0) as total_completed,
                   COALESCE(SUM(p_counts.in_progress), 0) as total_in_progress
            FROM users u
            LEFT JOIN assignments a ON a.student_id = u.id
            LEFT JOIN (
                SELECT assignment_id,
                       COUNT(*) as total,
                       SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN status IN ('writing','recording','editing') THEN 1 ELSE 0 END) as in_progress
                FROM progress GROUP BY assignment_id
            ) p_counts ON p_counts.assignment_id = a.id
            WHERE u.role='student' AND u.active=1
            GROUP BY u.id
            ORDER BY u.created_at DESC
        """).fetchall()

        return [{
            "id": r["id"],
            "name": r["name"],
            "email": r["email"],
            "niches": r["niches"] or "Nenhum",
            "total_assigned": r["total_assigned"],
            "total_completed": r["total_completed"],
            "total_in_progress": r["total_in_progress"],
            "has_api_key": bool(r["api_key_encrypted"]),
            "has_drive": bool(r["drive_folder_id"]),
            "drive_folder_id": r["drive_folder_id"] or "",
            "active": r["active"],
            "use_admin_api": bool(r["use_admin_api"]),
            "last_login": r["last_login"] or "Nunca",
            "created_at": r["created_at"],
        } for r in rows]


# ── Default Admin ────────────────────────────────────────

def create_default_admin():
    """Create admin user from env vars. Password is validated at startup."""
    admin_user = os.environ.get("DASH_USER", "admin")
    admin_pass = os.environ.get("DASH_PASS", "")
    if not admin_pass:
        logger.warning("DASH_PASS not set — admin account not created")
        return

    admin_email = os.environ.get("DASH_EMAIL", "")
    if "@" in admin_user:
        admin_email = admin_user
    elif not admin_email:
        admin_email = f"{admin_user}@ytcloner.local"

    with get_db() as conn:
        existing = conn.execute("SELECT * FROM users WHERE role='admin' LIMIT 1").fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET password_hash=?, email=?, name=? WHERE id=?",
                (_hash_password(admin_pass), admin_email, admin_user, existing["id"]),
            )
        else:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                (admin_user, admin_email, _hash_password(admin_pass), "admin", now),
            )


# ── Sessions ─────────────────────────────────────────────

def save_session(token: str, user_id: int):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (token, user_id, expires_at) VALUES (?, ?, datetime('now', '+7 days'))",
            (token, user_id),
        )


def get_session_user_id(token: str) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token=? AND (expires_at IS NULL OR expires_at > datetime('now'))",
            (token,),
        ).fetchone()
    return row["user_id"] if row else None


def delete_session(token: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def cleanup_expired_sessions():
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")


# ── Admin Settings ───────────────────────────────────────

def get_setting(key: str) -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM admin_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else ""


def set_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO admin_settings (key, value) VALUES (?, ?)", (key, value))


# ── Student Channels ────────────────────────────────────

def create_student_channel(student_id: int, channel_name: str, channel_url: str = "",
                           niche: str = "", language: str = "pt-BR", project_id: str = "") -> int:
    now = datetime.now().isoformat()
    with get_db() as conn:
        # Max 5 channels per student
        count = conn.execute("SELECT COUNT(*) FROM student_channels WHERE student_id=? AND active=1",
                            (student_id,)).fetchone()[0]
        if count >= 5:
            raise ValueError("Limite de 5 canais por aluno")
        cur = conn.execute(
            "INSERT INTO student_channels (student_id, channel_name, channel_url, niche, language, project_id, created_at) VALUES (?,?,?,?,?,?,?)",
            (student_id, channel_name, channel_url, niche, language, project_id, now),
        )
        return cur.lastrowid


def get_student_channels(student_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM student_channels WHERE student_id=? AND active=1 ORDER BY created_at",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_student_channel(channel_id: int, student_id: int):
    with get_db() as conn:
        conn.execute("UPDATE student_channels SET active=0 WHERE id=? AND student_id=?",
                    (channel_id, student_id))


# ── Student Drive Files ─────────────────────────────────

def save_student_drive_file(student_id: int, file_id: int | None, drive_file_id: str,
                            drive_folder_id: str, filename: str, label: str = "",
                            category: str = "") -> int:
    now = datetime.now().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO student_drive_files (student_id, file_id, drive_file_id, drive_folder_id, filename, label, category, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (student_id, file_id, drive_file_id, drive_folder_id, filename, label, category, now),
        )
        return cur.lastrowid


def get_student_drive_files(student_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM student_drive_files WHERE student_id=? ORDER BY created_at DESC",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_student_drive_file(drive_file_id: str, student_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM student_drive_files WHERE drive_file_id=? AND student_id=?",
                    (drive_file_id, student_id))


def get_student_drive_folder(student_id: int) -> str:
    """Get or return empty string for student's Drive folder ID."""
    with get_db() as conn:
        row = conn.execute("SELECT drive_folder_id FROM users WHERE id=?", (student_id,)).fetchone()
    return (row["drive_folder_id"] or "") if row else ""


def set_student_drive_folder(student_id: int, folder_id: str):
    with get_db() as conn:
        conn.execute("UPDATE users SET drive_folder_id=? WHERE id=?", (folder_id, student_id))


# ── Notifications ───────────────────────────────────────

def create_notification(user_id: int, ntype: str, title: str, message: str = "", link: str = ""):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, message, link, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, ntype, title, message, link, now),
        )


def get_notifications(user_id: int, unread_only: bool = False, limit: int = 20, offset: int = 0) -> list[dict]:
    """Get notifications with pagination support."""
    with get_db() as conn:
        if unread_only:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE user_id=? AND read=0 ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
    return [dict(r) for r in rows]


def mark_notification_read(notification_id: int, user_id: int):
    with get_db() as conn:
        conn.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (notification_id, user_id))


def mark_all_notifications_read(user_id: int):
    with get_db() as conn:
        conn.execute("UPDATE notifications SET read=1 WHERE user_id=? AND read=0", (user_id,))


def count_unread_notifications(user_id: int) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user_id,)).fetchone()
    return row[0] if row else 0


# ── AI Usage Tracking ───────────────────────────────────

def log_ai_usage(project_id: str = "", user_id: int = 0, model: str = "",
                 prompt_tokens: int = 0, completion_tokens: int = 0,
                 estimated_cost: float = 0.0, operation: str = ""):
    now = datetime.now().isoformat()
    total = prompt_tokens + completion_tokens
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ai_usage (project_id, user_id, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost, operation, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, user_id, model, prompt_tokens, completion_tokens, total, estimated_cost, operation, now),
        )


def get_ai_usage_summary() -> dict:
    with get_db() as conn:
        total = conn.execute("SELECT COALESCE(SUM(total_tokens),0) as tokens, COALESCE(SUM(estimated_cost),0) as cost, COUNT(*) as calls FROM ai_usage").fetchone()
        by_project = conn.execute(
            "SELECT project_id, SUM(total_tokens) as tokens, SUM(estimated_cost) as cost, COUNT(*) as calls FROM ai_usage WHERE project_id!='' GROUP BY project_id ORDER BY cost DESC LIMIT 10"
        ).fetchall()
        by_operation = conn.execute(
            "SELECT operation, SUM(total_tokens) as tokens, SUM(estimated_cost) as cost, COUNT(*) as calls FROM ai_usage GROUP BY operation ORDER BY cost DESC"
        ).fetchall()
    return {
        "total_tokens": total["tokens"],
        "total_cost": round(total["cost"], 4),
        "total_calls": total["calls"],
        "by_project": [dict(r) for r in by_project],
        "by_operation": [dict(r) for r in by_operation],
    }


# ── Video Performance ───────────────────────────────────

def upsert_video_performance(student_id: int, video_id: str, channel_id: int = 0,
                              title: str = "", published_at: str = "",
                              views: int = 0, likes: int = 0, comments: int = 0,
                              duration: str = "", thumbnail_url: str = ""):
    now = datetime.now().isoformat()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM video_performance WHERE student_id=? AND video_id=?",
                               (student_id, video_id)).fetchone()
        if existing:
            conn.execute("""UPDATE video_performance SET views=?, likes=?, comments=?, fetched_at=?
                           WHERE student_id=? AND video_id=?""",
                        (views, likes, comments, now, student_id, video_id))
        else:
            conn.execute("""INSERT INTO video_performance
                           (student_id, channel_id, video_id, title, published_at, views, likes, comments, duration, thumbnail_url, fetched_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (student_id, channel_id, video_id, title, published_at, views, likes, comments, duration, thumbnail_url, now))


def get_video_performance(student_id: int, limit: int = 30) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM video_performance WHERE student_id=? ORDER BY published_at DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_performance_summary(student_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("""SELECT COUNT(*) as total_videos,
            COALESCE(SUM(views),0) as total_views,
            COALESCE(SUM(likes),0) as total_likes,
            COALESCE(SUM(comments),0) as total_comments,
            COALESCE(AVG(views),0) as avg_views,
            COALESCE(MAX(views),0) as best_views
            FROM video_performance WHERE student_id=?""", (student_id,)).fetchone()
        top = conn.execute("""SELECT title, views FROM video_performance
            WHERE student_id=? ORDER BY views DESC LIMIT 3""", (student_id,)).fetchall()
    return {
        "total_videos": row["total_videos"],
        "total_views": row["total_views"],
        "total_likes": row["total_likes"],
        "avg_views": round(row["avg_views"]),
        "best_views": row["best_views"],
        "top_videos": [dict(r) for r in top],
    }



# ── Bent Ideas (Idea Bender feature) ──────────────────────────────
def save_bent_idea(
    source_mode: str,
    source_title: str,
    language: str,
    dna: dict,
    variations: list,
    source_project_id: str = "",
    source_idea_id: int = 0,
    source_url: str = "",
    source_views: int = 0,
    created_by: int = 0,
) -> int:
    now = datetime.now().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO bent_ideas
               (source_mode, source_project_id, source_idea_id, source_title,
                source_url, source_views, language, dna_json, variations_json,
                num_variations, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_mode,
                source_project_id,
                source_idea_id,
                source_title,
                source_url,
                source_views,
                language,
                json.dumps(dna, ensure_ascii=False),
                json.dumps(variations, ensure_ascii=False),
                len(variations),
                now,
                created_by,
            ),
        )
        return cur.lastrowid


def get_bent_ideas(limit: int = 50, project_id: str = "") -> list[dict]:
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM bent_ideas WHERE source_project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bent_ideas ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["dna"] = json.loads(d.get("dna_json") or "{}")
            d["variations"] = json.loads(d.get("variations_json") or "[]")
        except (ValueError, TypeError):
            d["dna"] = {}
            d["variations"] = []
        result.append(d)
    return result


def get_bent_idea_by_id(bent_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bent_ideas WHERE id=?", (bent_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["dna"] = json.loads(d.get("dna_json") or "{}")
        d["variations"] = json.loads(d.get("variations_json") or "[]")
    except (ValueError, TypeError):
        d["dna"] = {}
        d["variations"] = []
    return d
