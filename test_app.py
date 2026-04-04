"""
YouTube Channel Cloner — Smoke Tests
Tests critical routes and DB operations.
"""
import os
import sys
import json
import tempfile

# Set test environment
os.environ["LAOZHANG_API_KEY"] = "test-key"
os.environ["ENCRYPTION_KEY"] = "QDSBzxR8MauG4HcDsSPVb0SCVTO98taBRLrwKXsrObI="
os.environ["CSRF_SECRET"] = "test-csrf-secret-key-minimum-32-chars-long"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Create test client with temp DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["OUTPUT_DIR"] = tmpdir
        # Import after setting env vars
        from dashboard import app
        from database import init_db, create_default_admin
        init_db()
        create_default_admin()
        yield TestClient(app)


@pytest.fixture(scope="module")
def admin_session(client):
    """Login as admin and return session token."""
    resp = client.post("/login", data={
        "email": os.environ.get("DASH_USER", "rudy@ytcloner.com"),
        "password": os.environ.get("DASH_PASS", "253031"),
    }, follow_redirects=False)
    cookies = resp.cookies
    return cookies


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_login_page(self, client):
        r = client.get("/login")
        assert r.status_code == 200


class TestAuth:
    def test_unauthenticated_redirect(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (302, 307, 401)

    def test_admin_login(self, client, admin_session):
        r = client.get("/", cookies=admin_session)
        assert r.status_code == 200


class TestAdminRoutes:
    def test_admin_panel(self, client, admin_session):
        r = client.get("/admin/panel", cookies=admin_session)
        assert r.status_code == 200
        assert "PAINEL ADMINISTRATIVO" in r.text

    def test_admin_projects(self, client, admin_session):
        r = client.get("/admin/projects", cookies=admin_session)
        assert r.status_code == 200

    def test_admin_students(self, client, admin_session):
        r = client.get("/admin/students", cookies=admin_session)
        assert r.status_code == 200


class TestDatabase:
    def test_create_project(self):
        from database import create_project, get_project
        pid = create_project("Test Project", "https://youtube.com/@test", "Test Niche")
        assert pid
        proj = get_project(pid)
        assert proj["name"] == "Test Project"

    def test_create_user(self):
        from database import create_user, get_user_by_email
        uid = create_user("Test Student", "test@test.com", "password123", role="student")
        assert uid
        user = get_user_by_email("test@test.com")
        assert user["name"] == "Test Student"
        assert user["role"] == "student"

    def test_notifications(self):
        from database import create_notification, get_notifications, count_unread_notifications, mark_all_notifications_read
        # Need a user first
        from database import create_user
        uid = create_user("Notif Test", "notif@test.com", "pass123", role="student")
        create_notification(uid, "test", "Test Title", "Test message")
        create_notification(uid, "test", "Test Title 2", "Another message")
        assert count_unread_notifications(uid) == 2
        notifs = get_notifications(uid)
        assert len(notifs) >= 2
        mark_all_notifications_read(uid)
        assert count_unread_notifications(uid) == 0

    def test_ai_usage(self):
        from database import log_ai_usage, get_ai_usage_summary
        log_ai_usage(project_id="test", model="test-model", prompt_tokens=100,
                     completion_tokens=200, estimated_cost=0.01, operation="test_op")
        summary = get_ai_usage_summary()
        assert summary["total_tokens"] >= 300
        assert summary["total_cost"] >= 0.01

    def test_student_channels(self):
        from database import create_user, create_student_channel, get_student_channels, delete_student_channel
        uid = create_user("Channel Test", "channel@test.com", "pass123", role="student")
        cid = create_student_channel(uid, "Test Channel", "https://youtube.com/@test", "Dark POV")
        channels = get_student_channels(uid)
        assert len(channels) == 1
        assert channels[0]["channel_name"] == "Test Channel"
        delete_student_channel(cid, uid)
        assert len(get_student_channels(uid)) == 0


class TestSecurity:
    def test_rate_limit_exists(self):
        """Verify all POST routes have rate limiting."""
        import ast
        for filepath in ["dashboard.py", "routes/api_routes.py", "routes/student_routes.py", "routes/gdrive_routes.py"]:
            try:
                source = open(filepath).readlines()
                for i, line in enumerate(source):
                    s = line.strip()
                    if s.startswith("@app.post(") or s.startswith("@router.post("):
                        has_limit = i + 1 < len(source) and "@limiter" in source[i + 1]
                        assert has_limit, f"NO RATE LIMIT: {filepath}:{i+1} {s}"
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
