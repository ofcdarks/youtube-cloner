"""
Migration 001: Initial schema
Created: 2026-04-03
Base schema for all tables — matches database.py init_db().
"""


def up(conn):
    """Apply migration — create all base tables."""
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

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
        CREATE INDEX IF NOT EXISTS idx_ideas_project ON ideas(project_id);
        CREATE INDEX IF NOT EXISTS idx_scripts_project ON scripts(project_id);
        CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_log(project_id);
        CREATE INDEX IF NOT EXISTS idx_assignments_student ON assignments(student_id);
        CREATE INDEX IF NOT EXISTS idx_progress_student ON progress(student_id);
        CREATE INDEX IF NOT EXISTS idx_progress_assignment ON progress(assignment_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
    """)


def down(conn):
    """Rollback — drop all tables (DESTRUCTIVE)."""
    tables = [
        "sessions", "admin_settings", "progress", "assignments",
        "seo_packs", "scripts", "niches", "ideas", "files",
        "activity_log", "users", "projects",
    ]
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
