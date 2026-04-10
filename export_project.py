"""
Export a local project to import_*.json for production deployment.

Usage:
    python export_project.py <project_id>
    python export_project.py --list              # List all local projects
    python export_project.py --all               # Export all projects

The JSON is saved to seed_output/ and will be auto-imported on next deploy.
"""

import json
import sys
import os
from pathlib import Path

# Ensure we can import from project root
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("LAOZHANG_API_KEY", "skip")

from database import init_db, get_db

SEED_DIR = Path(__file__).parent / "seed_output"


def list_projects():
    """List all local projects."""
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, niche_chosen, language, created_at FROM projects ORDER BY created_at DESC"
        ).fetchall()
    if not rows:
        print("No projects found.")
        return
    print(f"\n{'ID':<50} {'Name':<35} {'Language':<5} {'Created'}")
    print("-" * 120)
    for r in rows:
        print(f"{r['id']:<50} {r['name']:<35} {r['language'] or 'pt':<5} {r['created_at']}")
    print(f"\nTotal: {len(rows)} projects")


def export_project(project_id: str) -> Path | None:
    """Export a single project to seed_output/import_<slug>.json."""
    init_db()
    with get_db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not proj:
            print(f"Project not found: {project_id}")
            return None

        niches = conn.execute(
            "SELECT name, description, rpm_range, competition, color, chosen, pillars FROM niches WHERE project_id=?",
            (project_id,)
        ).fetchall()

        ideas = conn.execute(
            "SELECT num, title, hook, summary, pillar, priority, score, rating, search_volume FROM ideas WHERE project_id=? ORDER BY num",
            (project_id,)
        ).fetchall()

        files = conn.execute(
            "SELECT category, label, filename, content FROM files WHERE project_id=? AND content IS NOT NULL",
            (project_id,)
        ).fetchall()

    # Find SOP content
    sop_content = ""
    for f in files:
        if f["category"] == "analise" and "SOP" in (f["label"] or ""):
            sop_content = f["content"]
            break

    # Build import JSON
    export_data = {
        "project": {
            "name": proj["name"],
            "channel_original": proj["channel_original"] or "",
            "niche_chosen": proj["niche_chosen"] or "",
            "language": proj["language"] or "en",
            "meta": proj["meta"] or "{}",
        },
        "sop": sop_content,
        "niches": [
            {
                "name": n["name"],
                "description": n["description"] or "",
                "rpm_range": n["rpm_range"] or "",
                "competition": n["competition"] or "",
                "color": n["color"] or "#7c3aed",
                "chosen": bool(n["chosen"]),
                "pillars": json.loads(n["pillars"]) if isinstance(n["pillars"], str) and n["pillars"] else [],
            }
            for n in niches
        ],
        "ideas": [
            {
                "num": i["num"],
                "title": i["title"],
                "hook": i["hook"] or "",
                "summary": i["summary"] or "",
                "pillar": i["pillar"] or "",
                "priority": i["priority"] or "MEDIA",
                "score": i["score"] or 0,
                "rating": i["rating"] or "",
                "search_volume": i["search_volume"] or 0,
            }
            for i in ideas
        ],
        "files": [
            {
                "category": f["category"],
                "label": f["label"],
                "filename": f["filename"],
                "content": f["content"],
            }
            for f in files
            if f["category"] != "analise" or "SOP" not in (f["label"] or "")  # SOP already in top-level
        ],
    }

    # Save
    SEED_DIR.mkdir(exist_ok=True)
    slug = proj["name"].lower().replace(" ", "_").replace("'", "")[:40]
    out_path = SEED_DIR / f"import_{slug}.json"
    out_path.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")

    n_niches = len(export_data["niches"])
    n_ideas = len(export_data["ideas"])
    n_files = len(export_data["files"])
    sop_len = len(sop_content)

    print(f"Exported: {proj['name']}")
    print(f"  -> {out_path}")
    print(f"  {n_niches} niches, {n_ideas} ideas, {n_files} files, SOP {sop_len} chars")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python export_project.py --list")
        print("  python export_project.py --all")
        print("  python export_project.py <project_id>")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--list":
        list_projects()
    elif arg == "--all":
        init_db()
        with get_db() as conn:
            rows = conn.execute("SELECT id, name FROM projects").fetchall()
        exported = 0
        for r in rows:
            path = export_project(r["id"])
            if path:
                exported += 1
        print(f"\nExported {exported}/{len(rows)} projects to {SEED_DIR}/")
    else:
        export_project(arg)
