"""
Migration 002: Add analytics tracking
Created: 2026-04-03
Adds columns for tracking video analytics and performance data.
"""


def up(conn):
    """Apply migration."""
    # Add analytics columns to ideas
    try:
        conn.execute("ALTER TABLE ideas ADD COLUMN views_estimate INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE ideas ADD COLUMN ctr_estimate REAL DEFAULT 0.0")
    except Exception:
        pass

    # Add analytics table for tracking published video performance
    conn.execute("""
        CREATE TABLE IF NOT EXISTS video_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            video_url TEXT,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0.0,
            avg_view_duration REAL DEFAULT 0.0,
            revenue_estimate REAL DEFAULT 0.0,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (idea_id) REFERENCES ideas(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_idea ON video_analytics(idea_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_project ON video_analytics(project_id)")


def down(conn):
    """Rollback migration."""
    conn.execute("DROP TABLE IF EXISTS video_analytics")
    # Note: SQLite can't drop columns easily, the ALTER TABLE additions remain
