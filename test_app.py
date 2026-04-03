"""
Comprehensive tests for the YouTube Cloner application.

Covers: auth, CSRF, database, API endpoints, access control, input validation.
Uses generic test credentials — never use real credentials in tests.
"""

import os
import sys
import secrets

# Set env vars BEFORE any imports — test-only values
os.environ["DASH_USER"] = "testadmin"
os.environ["DASH_PASS"] = "testpass123!secure"
os.environ["DASH_EMAIL"] = "testadmin@ytcloner.test"
os.environ["LAOZHANG_API_KEY"] = "sk-test-dummy-key"
os.environ["ENCRYPTION_KEY"] = "yMbnpT-MVjeYR5l2JEXMpbsG_CB5fJ71mb5LqZ1Sx9Y="
os.environ["CSRF_SECRET"] = secrets.token_hex(32)
os.environ["COOKIE_SECURE"] = "false"  # Allow non-HTTPS in tests

import warnings
warnings.filterwarnings("ignore")

from database import init_db, create_default_admin
init_db()
create_default_admin()

from fastapi.testclient import TestClient
from dashboard import app

client = TestClient(app, raise_server_exceptions=False)

# Test constants
ADMIN_EMAIL = os.environ["DASH_EMAIL"]
ADMIN_PASS = os.environ["DASH_PASS"]

PASS = 0
FAIL = 0
ERRORS: list[str] = []


def report(name: str, passed: bool, detail: str = ""):
    global PASS, FAIL
    if passed:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        ERRORS.append(name)


def get_admin_session() -> str:
    """Login as admin and return session token."""
    resp = client.post("/login", data={"email": ADMIN_EMAIL, "pass": ADMIN_PASS}, follow_redirects=False)
    cookies = resp.cookies
    return cookies.get("session", "")


# ═══════════════════════════════════════════════════════════
# 1. AUTH TESTS
# ═══════════════════════════════════════════════════════════

def test_auth():
    print("\n── Auth Tests ──")

    # Login page accessible
    resp = client.get("/login")
    report("Login page loads", resp.status_code == 200)

    # Valid login
    resp = client.post("/login", data={"email": ADMIN_EMAIL, "pass": ADMIN_PASS}, follow_redirects=False)
    report("Valid login redirects", resp.status_code in (302, 303))
    report("Login sets cookie", "session" in resp.cookies)

    # Invalid login
    resp = client.post("/login", data={"email": "wrong@test.com", "pass": "wrong"}, follow_redirects=False)
    report("Invalid login stays on page", resp.status_code == 200 or resp.status_code == 401)

    # Unauthenticated access redirects to login
    resp = client.get("/", follow_redirects=False)
    report("Unauth dashboard redirects/401", resp.status_code in (302, 401))

    # API without auth returns 401
    resp = client.get("/api/ideas")
    report("API without auth returns 401", resp.status_code == 401)

    # Logout
    session = get_admin_session()
    if session:
        resp = client.get("/logout", cookies={"session": session}, follow_redirects=False)
        report("Logout redirects", resp.status_code in (302, 303))

        # Session invalid after logout
        resp = client.get("/api/ideas", cookies={"session": session})
        report("Session invalid after logout", resp.status_code == 401)


# ═══════════════════════════════════════════════════════════
# 2. DATABASE TESTS
# ═══════════════════════════════════════════════════════════

def test_database():
    print("\n── Database Tests ──")

    from database import (
        create_project, get_project, get_projects, delete_project,
        save_idea, get_ideas, update_idea_score, toggle_idea_used,
        create_user, authenticate_user, get_users, delete_user,
        save_file, get_files,
        _encrypt_api_key, _decrypt_api_key,
        save_session, get_session_user_id, delete_session,
        get_stats,
    )

    # Projects
    pid = create_project("Test Project", "https://youtube.com/test", "test-niche")
    report("Create project", pid is not None)

    proj = get_project(pid)
    report("Get project", proj is not None and proj["name"] == "Test Project")

    projs = get_projects()
    report("List projects", len(projs) > 0)

    # Ideas
    iid = save_idea(pid, 1, "Test Title", "Hook test", "Summary", "Pilar", "ALTA")
    report("Save idea", iid is not None)

    ideas = get_ideas(pid)
    report("Get ideas", len(ideas) > 0)

    update_idea_score(iid, 85, "EXCELENTE", {"test": True})
    from database import get_idea
    idea = get_idea(iid)
    report("Update idea score", idea and idea["score"] == 85)

    val = toggle_idea_used(iid)
    report("Toggle idea used", val == 1)

    # Files
    save_file(pid, "analise", "SOP Test", "sop_test.md", "SOP content here")
    files = get_files(pid, "analise")
    report("Save and get files", len(files) > 0)

    # Users
    uid = create_user("Test Student", "student@test.com", "pass123!")
    report("Create user", uid is not None)

    auth = authenticate_user("student@test.com", "pass123!")
    report("Authenticate user", auth is not None)

    auth_bad = authenticate_user("student@test.com", "wrongpass")
    report("Bad password rejected", auth_bad is None)

    # Duplicate email
    uid_dup = create_user("Dup Student", "student@test.com", "pass456!")
    report("Duplicate email rejected", uid_dup is None)

    # Encryption
    encrypted = _encrypt_api_key("sk-test-key-12345")
    decrypted = _decrypt_api_key(encrypted)
    report("API key encryption roundtrip", decrypted == "sk-test-key-12345")

    empty = _encrypt_api_key("")
    report("Empty key encryption", empty == "")

    # Sessions
    token = "test-token-" + secrets.token_hex(8)
    save_session(token, 1)
    found = get_session_user_id(token)
    report("Session save/get", found == 1)

    delete_session(token)
    found_after = get_session_user_id(token)
    report("Session delete", found_after is None)

    # Stats
    stats = get_stats()
    report("Stats returns data", "projects" in stats and "ideas" in stats)

    # Cleanup
    if uid:
        delete_user(uid)
    delete_project(pid)
    report("Cleanup ok", get_project(pid) is None)


# ═══════════════════════════════════════════════════════════
# 3. API ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════

def test_api_endpoints():
    print("\n── API Endpoint Tests ──")

    session = get_admin_session()
    if not session:
        report("Get admin session", False, "Cannot login")
        return

    headers = {"Cookie": f"session={session}"}

    # Health
    resp = client.get("/api/health")
    report("Health endpoint", resp.status_code == 200)

    # Ideas
    resp = client.get("/api/ideas", headers=headers)
    report("GET /api/ideas", resp.status_code == 200)

    # Toggle used (without valid id)
    from middleware import generate_csrf_token
    csrf = generate_csrf_token(session)
    resp = client.post("/api/toggle-used", json={"id": 99999},
                       headers={**headers, "x-csrf-token": csrf})
    report("Toggle used with CSRF", resp.status_code == 200)


# ═══════════════════════════════════════════════════════════
# 4. SECURITY TESTS
# ═══════════════════════════════════════════════════════════

def test_security():
    print("\n── Security Tests ──")

    session = get_admin_session()
    headers = {"Cookie": f"session={session}"} if session else {}

    # Path traversal in /file
    resp = client.get("/file?path=../../etc/passwd", headers=headers)
    report("Path traversal blocked (..)", resp.status_code in (400, 403, 404))

    resp = client.get("/file?path=/etc/shadow", headers=headers)
    report("Absolute path blocked", resp.status_code in (400, 403, 404))

    # DB file access blocked
    resp = client.get("/output-file?name=ytcloner.db", headers=headers)
    report("DB file access blocked", resp.status_code == 403)

    resp = client.get("/output-file?name=../database.py", headers=headers)
    report("Output traversal blocked", resp.status_code in (403, 404))

    # Invalid project ID
    resp = client.get("/project?id=../../etc", headers=headers)
    report("Invalid project ID blocked", resp.status_code == 400)

    # XSS in niche name (if analyze was called)
    # Just test that angle brackets are stripped
    from services import sanitize_niche_name
    clean = sanitize_niche_name('<script>alert("xss")</script>Test')
    report("XSS sanitized in niche", "<script>" not in clean and "Test" in clean)

    # URL validation
    from services import validate_url
    report("Valid URL accepted", validate_url("https://youtube.com/test") is not None)
    report("Javascript URL blocked", validate_url("javascript:alert(1)") is None)
    report("File URL blocked", validate_url("file:///etc/passwd") is None)
    report("Localhost blocked", validate_url("http://localhost:8080") is None)
    report("Empty URL rejected", validate_url("") is None)
    report("No protocol rejected", validate_url("youtube.com") is None)


# ═══════════════════════════════════════════════════════════
# 5. ACCESS CONTROL TESTS
# ═══════════════════════════════════════════════════════════

def test_access_control():
    print("\n── Access Control Tests ──")

    # Create a student user
    from database import create_user, delete_user
    from auth import create_session as auth_create_session

    uid = create_user("Student Test", "acl_student@test.com", "studpass123!")
    if not uid:
        report("Create test student", False)
        return

    student_token = auth_create_session(uid)
    student_headers = {"Cookie": f"session={student_token}"}

    # Student cannot access admin routes
    resp = client.get("/admin/students", headers=student_headers, follow_redirects=False)
    report("Student blocked from admin/students", resp.status_code in (403, 401))

    resp = client.get("/admin/projects", headers=student_headers, follow_redirects=False)
    report("Student blocked from admin/projects", resp.status_code in (403, 401))

    # Student cannot access SOP files
    resp = client.get("/file?path=sop_test.md", headers=student_headers)
    report("Student blocked from SOP files", resp.status_code == 403)

    # Student can access student dashboard
    resp = client.get("/student", headers=student_headers)
    report("Student can access /student", resp.status_code == 200)

    # Cleanup
    delete_user(uid)


# ═══════════════════════════════════════════════════════════
# 6. INPUT VALIDATION TESTS
# ═══════════════════════════════════════════════════════════

def test_input_validation():
    print("\n── Input Validation Tests ──")

    session = get_admin_session()
    from middleware import generate_csrf_token
    csrf = generate_csrf_token(session)
    headers = {"Cookie": f"session={session}", "x-csrf-token": csrf}

    # Create student with invalid data
    resp = client.post("/api/admin/create-student", json={
        "name": "", "email": "bad", "password": "x"
    }, headers=headers)
    report("Create student rejects short name", resp.status_code == 400)

    resp = client.post("/api/admin/create-student", json={
        "name": "OK Name", "email": "notanemail", "password": "goodpass123"
    }, headers=headers)
    report("Create student rejects bad email", resp.status_code == 400)

    resp = client.post("/api/admin/create-student", json={
        "name": "OK Name", "email": "ok@test.com", "password": "12"
    }, headers=headers)
    report("Create student rejects short password", resp.status_code == 400)

    # Generate ideas with bad count
    resp = client.post("/api/generate-ideas", json={
        "count": 1000, "niche": "test"
    }, headers=headers)
    report("Generate ideas rejects large count", resp.status_code == 400)

    resp = client.post("/api/generate-ideas", json={
        "count": -1, "niche": "test"
    }, headers=headers)
    report("Generate ideas rejects negative count", resp.status_code == 400)


# ═══════════════════════════════════════════════════════════
# 7. SERVICES TESTS (mindmap, helpers)
# ═══════════════════════════════════════════════════════════

def test_services():
    print("\n── Services Tests ──")

    from services import (
        sanitize_niche_name, validate_url, validate_file_path,
        validate_project_id, generate_mindmap_html,
    )

    # sanitize_niche_name
    report("Sanitize removes HTML", "<" not in sanitize_niche_name("<b>test</b>"))
    report("Sanitize removes parens", "(" not in sanitize_niche_name("test(evil)"))
    report("Sanitize keeps clean text", sanitize_niche_name("System Breakers") == "System Breakers")
    report("Sanitize truncates long", len(sanitize_niche_name("x" * 200)) <= 100)

    # validate_url
    report("URL accepts https", validate_url("https://youtube.com/test") is not None)
    report("URL rejects empty", validate_url("") is None)
    report("URL rejects no protocol", validate_url("youtube.com") is None)
    report("URL rejects javascript:", validate_url("javascript:alert(1)") is None)
    report("URL rejects file://", validate_url("file:///etc/passwd") is None)
    report("URL rejects localhost", validate_url("http://localhost:8080") is None)
    report("URL rejects 127.0.0.1", validate_url("http://127.0.0.1") is None)
    report("URL rejects very long", validate_url("https://x.com/" + "a" * 500) is None)

    # validate_project_id
    report("Project ID accepts normal", validate_project_id("20260101_test_project"))
    report("Project ID rejects traversal", not validate_project_id("../../etc"))
    report("Project ID rejects empty", not validate_project_id(""))
    report("Project ID rejects slashes", not validate_project_id("test/evil"))

    # generate_mindmap_html
    html = generate_mindmap_html(
        niche_name="Test Niche",
        channel_url="https://youtube.com/test",
        sop="This is a test SOP with hooks and storytelling techniques.",
        niches=[
            {"name": "Test Niche", "description": "Primary niche", "rpm_range": "$5-15",
             "competition": "Media", "pillars": ["Pilar 1", "Pilar 2"]},
            {"name": "Alt Niche", "description": "Alternative", "rpm_range": "$3-10",
             "competition": "Baixa"},
        ],
        top_ideas=[
            {"title": "Amazing Title 1", "hook": "Hook 1", "summary": "Summary", "priority": "ALTA"},
            {"title": "Good Title 2", "hook": "Hook 2", "summary": "Summary", "priority": "MEDIA"},
        ],
        scripts_count=3,
    )
    report("Mindmap generates HTML", "<!DOCTYPE html>" in html)
    report("Mindmap contains niche name", "TEST NICHE" in html)
    report("Mindmap contains ideas", "Amazing Title 1" in html)
    report("Mindmap contains stats", "3" in html)  # scripts_count
    report("Mindmap has proper CSS", ".branch" in html)
    report("Mindmap escapes HTML", "<script>" not in generate_mindmap_html(
        '<script>alert("xss")</script>', "", "", [], [], 0
    ))


# ═══════════════════════════════════════════════════════════
# 8. CSRF TESTS
# ═══════════════════════════════════════════════════════════

def test_csrf():
    print("\n── CSRF Tests ──")

    from middleware import generate_csrf_token, verify_csrf_token

    session = "test-session-123"
    token = generate_csrf_token(session)
    report("CSRF token generated", token and "." in token)
    report("CSRF token valid", verify_csrf_token(token, session))
    report("CSRF wrong session rejected", not verify_csrf_token(token, "wrong-session"))
    report("CSRF empty rejected", not verify_csrf_token("", session))
    report("CSRF malformed rejected", not verify_csrf_token("not.valid.token", session))

    # POST without CSRF should be rejected (except login)
    admin_session = get_admin_session()
    if admin_session:
        resp = client.post("/api/toggle-used", json={"id": 1},
                           headers={"Cookie": f"session={admin_session}"})
        report("POST without CSRF rejected", resp.status_code == 403)

        # POST with valid CSRF should work
        csrf = generate_csrf_token(admin_session)
        resp = client.post("/api/toggle-used", json={"id": 99999},
                           headers={"Cookie": f"session={admin_session}", "x-csrf-token": csrf})
        report("POST with CSRF accepted", resp.status_code == 200)


# ═══════════════════════════════════════════════════════════
# RUN ALL
# ═══════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  YOUTUBE CLONER — Test Suite")
    print("=" * 60)

    test_auth()
    test_database()
    test_api_endpoints()
    test_security()
    test_access_control()
    test_input_validation()
    test_services()
    test_csrf()

    print("\n" + "=" * 60)
    total = PASS + FAIL
    pct = round(PASS / total * 100) if total else 0
    print(f"  Results: {PASS}/{total} passed ({pct}%)")
    if ERRORS:
        print(f"  Failed: {', '.join(ERRORS)}")
    status = "PASS" if FAIL == 0 else "FAIL"
    print(f"  Status: {status}")
    print("=" * 60 + "\n")

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
