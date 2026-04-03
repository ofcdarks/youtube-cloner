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
from datetime import datetime
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
    conn.execute("PRAGMA journal_mode=WAL")
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
    """Decrypt API key. Supports Fernet and legacy base64."""
    if not encrypted:
        return ""
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        # Legacy base64 fallback
        try:
            return base64.b64decode(encrypted.encode()).decode()
        except Exception:
            return ""


# ── Projects ─────────────────────────────────────────────

def create_project(
    name: str,
    channel_original: str = "",
    niche_chosen: str = "",
    drive_folder_id: str = "",
    meta: dict | None = None,
) -> str:
    now = datetime.now().isoformat()
    pid = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name.lower().replace(' ', '_')[:50]}"
    drive_url = f"https://drive.google.com/drive/folders/{drive_folder_id}" if drive_folder_id else ""

    with get_db() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, channel_original, niche_chosen, drive_folder_id, drive_folder_url, created_at, updated_at, meta) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, name, channel_original, niche_chosen, drive_folder_id, drive_url, now, now, json.dumps(meta or {})),
        )
        log_activity(pid, "project_created", f"Projeto '{name}' criado", conn)
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
    allowed = {"name", "channel_original", "niche_chosen", "drive_folder_id", "drive_folder_url", "status", "meta"}
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

def save_file(project_id: str, category: str, label: str, filename: str, content: str = "", drive_url: str = ""):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO files (project_id, category, label, filename, content, drive_url, created_at) VALUES (?,?,?,?,?,?,?)",
            (project_id, category, label, filename, content, drive_url, now),
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

def save_idea(
    project_id: str,
    num: int,
    title: str,
    hook: str = "",
    summary: str = "",
    pillar: str = "",
    priority: str = "MEDIA",
) -> int:
    now = datetime.now().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO ideas (project_id, num, title, hook, summary, pillar, priority, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (project_id, num, title, hook, summary, pillar, priority, now),
        )
        return cur.lastrowid


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
        conn.execute(
            "UPDATE ideas SET score=?, rating=?, score_details=? WHERE id=?",
            (score, rating, json.dumps(details or {}), idea_id),
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


def get_activity(project_id: str | None = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
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
    with get_db() as conn:
        return {
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "ideas": conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0],
            "scripts": conn.execute("SELECT COUNT(*) FROM scripts").fetchone()[0],
            "niches": conn.execute("SELECT COUNT(*) FROM niches").fetchone()[0],
            "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "seo_packs": conn.execute("SELECT COUNT(*) FROM seo_packs").fetchone()[0],
        }


# ── Users ────────────────────────────────────────────────

def create_user(
    name: str, email: str, password: str, role: str = "student", created_by: int | None = None
) -> int | None:
    now = datetime.now().isoformat()
    password_hash = _hash_password(password)
    with get_db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, role, created_by, created_at) VALUES (?,?,?,?,?,?)",
                (name, email, password_hash, role, created_by, now),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


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
    allowed = {"name", "email", "role", "api_provider", "api_key_encrypted", "max_titles", "active"}
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
    """Delete user and all assignments/progress."""
    with get_db() as conn:
        conn.execute("DELETE FROM progress WHERE student_id=?", (user_id,))
        conn.execute("DELETE FROM assignments WHERE student_id=?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
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
            """SELECT p.*, i.title, i.hook, i.summary, i.pillar, i.priority, i.score, i.rating, i.num
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
    with get_db() as conn:
        students = conn.execute(
            "SELECT * FROM users WHERE role='student' AND active=1 ORDER BY created_at DESC"
        ).fetchall()

        overview = []
        for s in students:
            sid = s["id"]
            assignments = conn.execute("SELECT * FROM assignments WHERE student_id=?", (sid,)).fetchall()
            total_assigned, total_completed, total_in_progress = 0, 0, 0
            niches = []
            for a in assignments:
                niches.append(a["niche"])
                counts = conn.execute(
                    """SELECT COUNT(*) as total,
                              SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) as completed,
                              SUM(CASE WHEN status IN ('writing','recording','editing') THEN 1 ELSE 0 END) as in_progress
                       FROM progress WHERE assignment_id=?""",
                    (a["id"],),
                ).fetchone()
                total_assigned += counts["total"] or 0
                total_completed += counts["completed"] or 0
                total_in_progress += counts["in_progress"] or 0

            overview.append({
                "id": s["id"],
                "name": s["name"],
                "email": s["email"],
                "niches": ", ".join(niches) if niches else "Nenhum",
                "total_assigned": total_assigned,
                "total_completed": total_completed,
                "total_in_progress": total_in_progress,
                "has_api_key": bool(s["api_key_encrypted"]),
                "last_login": s["last_login"] or "Nunca",
                "created_at": s["created_at"],
            })
    return overview


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
