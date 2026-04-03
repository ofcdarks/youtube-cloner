"""
Database Migrations — Lightweight migration system for SQLite.

Usage:
    python migrations/migrate.py status     # Show migration status
    python migrations/migrate.py up         # Apply all pending migrations
    python migrations/migrate.py down       # Rollback last migration
    python migrations/migrate.py create NAME  # Create new migration file

Migrations are Python files in migrations/versions/ with up() and down() functions.
Each migration receives a sqlite3 connection object.
"""

import sys
import os
import sqlite3
import importlib.util
from pathlib import Path
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH

MIGRATIONS_DIR = Path(__file__).parent / "versions"
MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Ensure migration tracking table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_applied_migrations(conn) -> set[str]:
    rows = conn.execute("SELECT id FROM _schema_migrations ORDER BY id").fetchall()
    return {r["id"] for r in rows}


def get_all_migrations() -> list[tuple[str, str, Path]]:
    """Returns sorted list of (id, name, path) tuples."""
    migrations = []
    for f in sorted(MIGRATIONS_DIR.glob("*.py")):
        if f.name.startswith("__"):
            continue
        # Expected format: 001_create_initial_schema.py
        parts = f.stem.split("_", 1)
        if len(parts) == 2:
            migration_id = parts[0]
            name = parts[1]
        else:
            migration_id = f.stem
            name = f.stem
        migrations.append((migration_id, name, f))
    return migrations


def load_migration(path: Path):
    """Load a migration module from file."""
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_status():
    """Show migration status."""
    conn = get_db()
    applied = get_applied_migrations(conn)
    all_migrations = get_all_migrations()
    conn.close()

    print(f"\nDatabase: {DB_PATH}")
    print(f"Migrations directory: {MIGRATIONS_DIR}")
    print(f"\n{'ID':<6} {'Name':<40} {'Status'}")
    print("-" * 60)

    for mid, name, path in all_migrations:
        status = "applied" if mid in applied else "PENDING"
        marker = "  " if mid in applied else ">>"
        print(f"{marker} {mid:<4} {name:<40} {status}")

    pending = len([m for m in all_migrations if m[0] not in applied])
    print(f"\n{len(all_migrations)} total, {len(applied)} applied, {pending} pending\n")


def cmd_up():
    """Apply all pending migrations."""
    conn = get_db()
    applied = get_applied_migrations(conn)
    all_migrations = get_all_migrations()

    pending = [(mid, name, path) for mid, name, path in all_migrations if mid not in applied]

    if not pending:
        print("No pending migrations.")
        conn.close()
        return

    for mid, name, path in pending:
        print(f"  Applying {mid}_{name}...", end=" ")
        try:
            mod = load_migration(path)
            mod.up(conn)
            conn.execute(
                "INSERT INTO _schema_migrations (id, name, applied_at) VALUES (?, ?, ?)",
                (mid, name, datetime.now().isoformat()),
            )
            conn.commit()
            print("OK")
        except Exception as e:
            conn.rollback()
            print(f"FAILED: {e}")
            break

    conn.close()


def cmd_down():
    """Rollback last applied migration."""
    conn = get_db()
    applied = get_applied_migrations(conn)
    all_migrations = get_all_migrations()

    # Find last applied
    applied_list = sorted([m for m in all_migrations if m[0] in applied], key=lambda x: x[0], reverse=True)

    if not applied_list:
        print("No migrations to rollback.")
        conn.close()
        return

    mid, name, path = applied_list[0]
    print(f"  Rolling back {mid}_{name}...", end=" ")
    try:
        mod = load_migration(path)
        if hasattr(mod, "down"):
            mod.down(conn)
        conn.execute("DELETE FROM _schema_migrations WHERE id=?", (mid,))
        conn.commit()
        print("OK")
    except Exception as e:
        conn.rollback()
        print(f"FAILED: {e}")

    conn.close()


def cmd_create(name: str):
    """Create a new migration file."""
    all_migrations = get_all_migrations()
    if all_migrations:
        last_id = int(all_migrations[-1][0])
        new_id = f"{last_id + 1:03d}"
    else:
        new_id = "001"

    safe_name = name.lower().replace(" ", "_").replace("-", "_")
    filename = f"{new_id}_{safe_name}.py"
    filepath = MIGRATIONS_DIR / filename

    template = f'''"""
Migration {new_id}: {name}
Created: {datetime.now().isoformat()}
"""


def up(conn):
    """Apply migration."""
    conn.execute("""
        -- Add your SQL here
        -- Example: ALTER TABLE ideas ADD COLUMN new_field TEXT DEFAULT ''
    """)


def down(conn):
    """Rollback migration (best effort for SQLite)."""
    # SQLite has limited ALTER TABLE support
    # For column drops, you'd need to recreate the table
    pass
'''

    filepath.write_text(template, encoding="utf-8")
    print(f"Created: {filepath}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python migrations/migrate.py [status|up|down|create NAME]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        cmd_status()
    elif cmd == "up":
        cmd_up()
    elif cmd == "down":
        cmd_down()
    elif cmd == "create":
        if len(sys.argv) < 3:
            print("Usage: python migrations/migrate.py create NAME")
            sys.exit(1)
        cmd_create(" ".join(sys.argv[2:]))
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
