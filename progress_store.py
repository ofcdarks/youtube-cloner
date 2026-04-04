"""
Pipeline progress tracking for SSE (Server-Sent Events).
Thread-safe store for pipeline step updates.
"""

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_progress: dict[str, dict] = {}


def update_progress(project_id: str, step: int, total: int, label: str, detail: str = ""):
    """Update pipeline progress for a project."""
    with _lock:
        _progress[project_id] = {
            "step": step,
            "total": total,
            "label": label,
            "detail": detail,
            "pct": round(step / total * 100) if total else 0,
            "ts": time.time(),
        }


def get_progress(project_id: str) -> dict | None:
    """Get current progress for a project."""
    with _lock:
        return _progress.get(project_id, {}).copy() if project_id in _progress else None


def clear_progress(project_id: str):
    """Remove progress entry when pipeline completes."""
    with _lock:
        _progress.pop(project_id, None)


def is_running(project_id: str) -> bool:
    """Check if a pipeline is currently running."""
    with _lock:
        p = _progress.get(project_id)
        if not p:
            return False
        # Consider stale if no update for 5 minutes
        return (time.time() - p.get("ts", 0)) < 300
