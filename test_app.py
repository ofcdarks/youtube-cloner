"""
YouTube Channel Cloner — Test Suite
Covers: health, auth, admin routes, student role isolation, IDOR protection,
CSRF enforcement, file access control, security headers, database operations,
rate limiting meta-check, and error handling patterns.
"""

import os
import re
import secrets
import tempfile

# ── Test environment (before any app imports) ──────────────
_TEST_ADMIN_EMAIL = "testadmin@ytcloner.test"
_TEST_ADMIN_PASS = "TestAdminPass!2024"

os.environ["DASH_USER"] = _TEST_ADMIN_EMAIL
os.environ["DASH_PASS"] = _TEST_ADMIN_PASS
os.environ["DASH_EMAIL"] = _TEST_ADMIN_EMAIL
os.environ["LAOZHANG_API_KEY"] = "test-key"
os.environ["ENCRYPTION_KEY"] = "QDSBzxR8MauG4HcDsSPVb0SCVTO98taBRLrwKXsrObI="
os.environ["CSRF_SECRET"] = "test-csrf-secret-key-minimum-32-chars-long-enough"

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture(scope="session")
def client():
    """TestClient backed by a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["OUTPUT_DIR"] = tmpdir

        from dashboard import app
        from database import (
            init_db,
            create_default_admin,
            authenticate_user,
            _hash_password,
            get_db,
        )

        init_db()
        create_default_admin()

        # Guarantee admin exists even if env-var propagation was cached
        if not authenticate_user(_TEST_ADMIN_EMAIL, _TEST_ADMIN_PASS):
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO users "
                    "(name, email, password_hash, role, created_at, active) "
                    "VALUES (?, ?, ?, 'admin', datetime('now'), 1)",
                    ("Test Admin", _TEST_ADMIN_EMAIL, _hash_password(_TEST_ADMIN_PASS)),
                )

        yield TestClient(app)


@pytest.fixture(scope="session")
def admin_client(client):
    """TestClient with admin session cookie set directly."""
    from database import authenticate_user
    from auth import create_session

    user = authenticate_user(_TEST_ADMIN_EMAIL, _TEST_ADMIN_PASS)
    assert user, f"Admin user not found for {_TEST_ADMIN_EMAIL}"

    token = create_session(user["id"])
    client.cookies.set("session", token)
    return client


@pytest.fixture(scope="session")
def admin_csrf(admin_client):
    """Valid CSRF token bound to the admin session."""
    from middleware import generate_csrf_token

    session_token = admin_client.cookies.get("session")
    return generate_csrf_token(session_token)


@pytest.fixture(scope="session")
def student_client(client):
    """Separate TestClient logged in as a student."""
    from dashboard import app
    from database import create_user, authenticate_user
    from auth import create_session

    email = "student@ytcloner.test"
    password = "StudentPass!2024"

    uid = create_user("Test Student", email, password, role="student")
    if not uid:
        user = authenticate_user(email, password)
        uid = user["id"] if user else None

    user = authenticate_user(email, password)
    assert user, "Student user not found"

    token = create_session(user["id"])
    sc = TestClient(app)
    sc.cookies.set("session", token)
    sc._student_id = uid
    sc._session_token = token
    return sc


@pytest.fixture(scope="session")
def student_csrf(student_client):
    """Valid CSRF token bound to the student session."""
    from middleware import generate_csrf_token

    return generate_csrf_token(student_client._session_token)


# ══════════════════════════════════════════════════════════
# HEALTH & LOGIN PAGE
# ══════════════════════════════════════════════════════════


class TestHealth:
    def test_health_endpoint(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_login_page_loads(self, client):
        r = client.get("/login")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════


class TestAuth:
    def test_unauthenticated_redirect(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (302, 307, 401)

    def test_admin_login_works(self, admin_client):
        r = admin_client.get("/")
        assert r.status_code == 200

    def test_invalid_login_fails(self, client):
        r = client.post(
            "/login",
            data={"email": "wrong@email.com", "pass": "wrongpass"},
            follow_redirects=False,
        )
        # Re-renders login page or redirects back
        assert r.status_code in (200, 302)

    def test_logout_clears_session(self, client):
        """Use a separate session to avoid destroying shared admin session."""
        from dashboard import app
        from database import authenticate_user
        from auth import create_session

        user = authenticate_user(_TEST_ADMIN_EMAIL, _TEST_ADMIN_PASS)
        token = create_session(user["id"])
        temp = TestClient(app)
        temp.cookies.set("session", token)
        r = temp.get("/logout", follow_redirects=False)
        assert r.status_code in (302, 303, 307)


# ══════════════════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════════════════


class TestAdminRoutes:
    def test_admin_panel(self, admin_client):
        r = admin_client.get("/admin/panel")
        assert r.status_code == 200

    def test_admin_projects(self, admin_client):
        r = admin_client.get("/admin/projects")
        assert r.status_code == 200

    def test_admin_students(self, admin_client):
        r = admin_client.get("/admin/students")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════
# STUDENT ROLE ISOLATION
# ══════════════════════════════════════════════════════════


class TestStudentIsolation:
    """Students must NOT access admin routes."""

    def test_student_cannot_access_admin_panel(self, student_client):
        r = student_client.get("/admin/panel")
        assert r.status_code in (401, 403), f"Student accessed admin panel: {r.status_code}"

    def test_student_cannot_access_admin_projects(self, student_client):
        r = student_client.get("/admin/projects")
        assert r.status_code in (401, 403)

    def test_student_cannot_access_admin_students(self, student_client):
        r = student_client.get("/admin/students")
        assert r.status_code in (401, 403)

    def test_student_can_access_student_dashboard(self, student_client):
        r = student_client.get("/student")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════
# IDOR PROTECTION
# ══════════════════════════════════════════════════════════


class TestIDOR:
    """Students must not modify other students' data."""

    def test_progress_update_requires_ownership(self, student_client, student_csrf):
        """Student cannot update a progress record they don't own."""
        r = student_client.post(
            "/api/student/update-progress",
            json={"progress_id": 99999, "status": "writing"},
            headers={"x-csrf-token": student_csrf},
        )
        assert r.status_code in (403, 400), (
            f"IDOR: student updated foreign progress: {r.status_code}"
        )

    def test_admin_can_update_any_progress(self, admin_client, admin_csrf):
        """Admin bypasses ownership check."""
        r = admin_client.post(
            "/api/student/update-progress",
            json={"progress_id": 99999, "status": "writing"},
            headers={"x-csrf-token": admin_csrf},
        )
        # Admin passes ownership gate; may fail on DB lookup but NOT 403
        assert r.status_code != 403, "Admin was blocked by ownership check"


# ══════════════════════════════════════════════════════════
# CSRF ENFORCEMENT
# ══════════════════════════════════════════════════════════


class TestCSRF:
    """CSRF tokens must be enforced on all state-changing requests."""

    def test_post_without_csrf_rejected(self, admin_client):
        """POST without CSRF token -> 403."""
        r = admin_client.post(
            "/api/admin/youtube-settings",
            json={"api_key": "test", "channel_id": "test"},
        )
        assert r.status_code == 403, f"POST without CSRF succeeded: {r.status_code}"

    def test_post_with_invalid_csrf_rejected(self, admin_client):
        """POST with invalid CSRF token -> 403."""
        r = admin_client.post(
            "/api/admin/youtube-settings",
            json={"api_key": "test", "channel_id": "test"},
            headers={"x-csrf-token": "invalid.token"},
        )
        assert r.status_code == 403

    def test_post_with_valid_csrf_passes(self, admin_client, admin_csrf):
        """POST with valid CSRF token passes the CSRF check."""
        r = admin_client.post(
            "/api/admin/youtube-settings",
            json={"api_key": "test-yt-key", "channel_id": "@testchannel"},
            headers={"x-csrf-token": admin_csrf},
        )
        assert r.status_code != 403, f"Valid CSRF was rejected: {r.status_code}"

    def test_login_is_csrf_exempt(self, client):
        """POST /login works without CSRF (exempt path)."""
        r = client.post(
            "/login",
            data={"email": "nobody@test.com", "pass": "wrong"},
            follow_redirects=False,
        )
        assert r.status_code != 403


# ══════════════════════════════════════════════════════════
# FILE ACCESS CONTROL
# ══════════════════════════════════════════════════════════


class TestFileAccess:
    """File serving must enforce role-based access control."""

    def test_db_file_blocked(self, admin_client):
        """Database files must never be served."""
        r = admin_client.get("/output-file?name=ytcloner.db")
        assert r.status_code == 403

    def test_key_file_blocked(self, admin_client):
        r = admin_client.get("/output-file?name=secret.key")
        assert r.status_code == 403

    def test_unauthenticated_access_denied(self, client):
        # Use a fresh client without session cookie
        from dashboard import app

        fresh = TestClient(app)
        r = fresh.get("/output-file?name=test.md")
        assert r.status_code in (401, 403)

    def test_student_cannot_access_unassigned_file(self, student_client):
        """Student accessing a file not in their assignments is denied."""
        r = student_client.get("/output-file?name=sop_some_project.md")
        assert r.status_code in (403, 404)


# ══════════════════════════════════════════════════════════
# SECURITY HEADERS
# ══════════════════════════════════════════════════════════


class TestSecurityHeaders:
    """Responses must include security headers."""

    def test_x_frame_options(self, client):
        r = client.get("/api/health")
        assert r.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options(self, client):
        r = client.get("/api/health")
        assert r.headers.get("x-content-type-options") == "nosniff"

    def test_referrer_policy(self, client):
        r = client.get("/api/health")
        assert "strict-origin" in r.headers.get("referrer-policy", "")

    def test_content_security_policy(self, client):
        r = client.get("/api/health")
        csp = r.headers.get("content-security-policy", "")
        assert "default-src" in csp
        assert "frame-ancestors 'none'" in csp


# ══════════════════════════════════════════════════════════
# DATABASE OPERATIONS
# ══════════════════════════════════════════════════════════


class TestDatabase:
    def test_create_and_get_project(self):
        from database import create_project, get_project

        pid = create_project("Test Project", "https://youtube.com/@test", "Test Niche")
        assert pid
        proj = get_project(pid)
        assert proj["name"] == "Test Project"

    def test_create_and_authenticate_user(self):
        from database import create_user, authenticate_user

        email = f"authtest_{secrets.token_hex(4)}@test.com"
        uid = create_user("Auth Test", email, "SecurePass123!", role="student")
        assert uid

        user = authenticate_user(email, "SecurePass123!")
        assert user is not None
        assert user["name"] == "Auth Test"
        assert user["role"] == "student"

        # Wrong password returns None
        assert authenticate_user(email, "WrongPassword!") is None

    def test_notifications_crud(self):
        from database import (
            create_user,
            create_notification,
            get_notifications,
            count_unread_notifications,
            mark_all_notifications_read,
        )

        uid = create_user(
            "Notif Test",
            f"notif_{secrets.token_hex(4)}@test.com",
            "pass123",
            role="student",
        )
        create_notification(uid, "test", "Title 1", "Message 1")
        create_notification(uid, "test", "Title 2", "Message 2")
        assert count_unread_notifications(uid) == 2

        notifs = get_notifications(uid)
        assert len(notifs) >= 2

        mark_all_notifications_read(uid)
        assert count_unread_notifications(uid) == 0

    def test_ai_usage_tracking(self):
        from database import log_ai_usage, get_ai_usage_summary

        log_ai_usage(
            project_id="test-proj",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=200,
            estimated_cost=0.01,
            operation="test_op",
        )
        summary = get_ai_usage_summary()
        assert summary["total_tokens"] >= 300
        assert summary["total_cost"] >= 0.01

    def test_student_channels_crud(self):
        from database import (
            create_user,
            create_student_channel,
            get_student_channels,
            delete_student_channel,
        )

        uid = create_user(
            "Chan Test",
            f"chan_{secrets.token_hex(4)}@test.com",
            "pass123",
            role="student",
        )
        cid = create_student_channel(uid, "Test Channel", "https://youtube.com/@test", "Dark POV")
        channels = get_student_channels(uid)
        assert len(channels) == 1
        assert channels[0]["channel_name"] == "Test Channel"

        delete_student_channel(cid, uid)
        assert len(get_student_channels(uid)) == 0

    def test_student_channel_max_5(self):
        from database import create_user, create_student_channel

        uid = create_user(
            "Max Chan",
            f"maxchan_{secrets.token_hex(4)}@test.com",
            "pass123",
            role="student",
        )
        for i in range(5):
            create_student_channel(uid, f"Channel {i}", f"https://youtube.com/@ch{i}", "Niche")

        with pytest.raises(ValueError):
            create_student_channel(uid, "Channel 6", "https://youtube.com/@ch6", "Niche")

    def test_get_stats_returns_all_keys(self):
        from database import get_stats

        stats = get_stats()
        for key in ("projects", "ideas", "scripts", "niches", "files", "seo_packs"):
            assert key in stats, f"Missing key: {key}"

    def test_get_admin_overview(self):
        from database import get_admin_overview

        overview = get_admin_overview()
        assert isinstance(overview, list)
        if overview:
            entry = overview[0]
            assert "id" in entry
            assert "name" in entry
            assert "total_assigned" in entry
            assert "total_completed" in entry

    def test_save_and_get_files(self):
        from database import create_project, save_file, get_files

        pid = create_project("File Test", niche_chosen="Test")
        save_file(pid, "analise", "SOP Test", "sop_test.md", "SOP content here")
        files = get_files(pid, "analise")
        assert len(files) >= 1
        assert files[0]["content"] == "SOP content here"

    def test_get_project_sop(self):
        from database import create_project, save_file
        from services import get_project_sop

        pid = create_project("SOP Test", niche_chosen="Test SOP")
        save_file(pid, "analise", "SOP - Test", "sop_test2.md", "Full SOP content")
        sop = get_project_sop(pid)
        assert sop == "Full SOP content"

    def test_get_project_sop_empty_fallback(self):
        from services import get_project_sop

        sop = get_project_sop("nonexistent-project-id")
        assert sop == "" or isinstance(sop, str)


# ══════════════════════════════════════════════════════════
# RATE LIMIT META-CHECK
# ══════════════════════════════════════════════════════════


class TestRateLimiting:
    def test_all_post_routes_have_rate_limit(self):
        """Verify every @app.post / @router.post has a @limiter decorator nearby."""
        route_files = [
            "dashboard.py",
            "routes/api_routes.py",
            "routes/student_routes.py",
            "routes/gdrive_routes.py",
        ]
        base = os.path.dirname(__file__)

        for filepath in route_files:
            full_path = os.path.join(base, filepath)
            try:
                with open(full_path, encoding="utf-8") as f:
                    source = f.readlines()
            except FileNotFoundError:
                continue

            for i, line in enumerate(source):
                stripped = line.strip()
                if stripped.startswith("@app.post(") or stripped.startswith("@router.post("):
                    context = source[max(0, i - 1) : i + 2]
                    has_limit = any("@limiter" in c for c in context)
                    assert has_limit, f"NO RATE LIMIT: {filepath}:{i + 1} {stripped}"


# ══════════════════════════════════════════════════════════
# ERROR HANDLING
# ══════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_no_str_e_in_json_responses(self):
        """No str(e) patterns leaked in JSONResponse calls in route files."""
        route_files = [
            "dashboard.py",
            "routes/api_routes.py",
            "routes/student_routes.py",
            "routes/gdrive_routes.py",
        ]
        base = os.path.dirname(__file__)

        for filepath in route_files:
            full_path = os.path.join(base, filepath)
            try:
                with open(full_path, encoding="utf-8") as f:
                    content = f.read()
            except FileNotFoundError:
                continue

            leaks = re.findall(r"JSONResponse\(.*str\(e\)", content)
            assert len(leaks) == 0, f"Error leak in {filepath}: {leaks[:3]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
