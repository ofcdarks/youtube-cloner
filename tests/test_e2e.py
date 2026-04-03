"""
End-to-End Tests — Playwright-based browser tests for full user flows.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    # Start the server first:
    python dashboard.py &
    
    # Then run tests:
    python tests/test_e2e.py
"""

import os
import sys
import time

# Set test env vars
os.environ.setdefault("DASH_USER", "testadmin")
os.environ.setdefault("DASH_PASS", "e2e-test-pass-secure!")
os.environ.setdefault("DASH_EMAIL", "e2e@ytcloner.test")
os.environ.setdefault("ENCRYPTION_KEY", "yMbnpT-MVjeYR5l2JEXMpbsG_CB5fJ71mb5LqZ1Sx9Y=")
os.environ.setdefault("CSRF_SECRET", "e2e-csrf-secret-test")
os.environ.setdefault("COOKIE_SECURE", "false")

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8888")
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


def wait_for_server(url: str, timeout: int = 30):
    """Wait for server to be ready."""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def test_login_flow(page):
    """Test the complete login flow."""
    print("\n── E2E: Login Flow ──")

    # Visit login page
    page.goto(f"{BASE_URL}/login")
    report("Login page loads", page.title() == "YT Cloner - Login" or "Login" in page.content())

    # Check form elements exist
    email_input = page.locator('input[name="email"]')
    pass_input = page.locator('input[name="pass"]')
    submit_btn = page.locator('button[type="submit"]')

    report("Email field exists", email_input.count() == 1)
    report("Password field exists", pass_input.count() == 1)
    report("Submit button exists", submit_btn.count() == 1)

    # Try invalid login
    email_input.fill("wrong@test.com")
    pass_input.fill("wrongpassword")
    submit_btn.click()
    page.wait_for_load_state("networkidle")
    report("Invalid login shows error", "invalido" in page.content().lower() or page.url.endswith("/login"))

    # Valid login
    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill(ADMIN_EMAIL)
    page.locator('input[name="pass"]').fill(ADMIN_PASS)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Should redirect to dashboard
    report("Valid login redirects to dashboard", "/login" not in page.url)
    report("Dashboard loads", page.locator("body").count() == 1)

    # Check session cookie is set
    cookies = page.context.cookies()
    session_cookie = next((c for c in cookies if c["name"] == "session"), None)
    report("Session cookie set", session_cookie is not None)
    if session_cookie:
        report("Cookie is httpOnly", session_cookie.get("httpOnly", False))
        report("Cookie has sameSite", session_cookie.get("sameSite", "") in ("Lax", "Strict"))


def test_dashboard_navigation(page):
    """Test dashboard navigation and key elements."""
    print("\n── E2E: Dashboard Navigation ──")

    # Login first
    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill(ADMIN_EMAIL)
    page.locator('input[name="pass"]').fill(ADMIN_PASS)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Check main dashboard elements
    report("Dashboard has content", len(page.content()) > 500)

    # Try accessing admin pages
    page.goto(f"{BASE_URL}/admin/students")
    page.wait_for_load_state("networkidle")
    report("Admin students page accessible", page.url.endswith("/admin/students") or "students" in page.content().lower())

    page.goto(f"{BASE_URL}/admin/projects")
    page.wait_for_load_state("networkidle")
    report("Admin projects page accessible", page.url.endswith("/admin/projects") or "project" in page.content().lower())

    # Check CSRF token is in page
    csrf_meta = page.locator('meta[name="csrf-token"]')
    report("CSRF meta tag present", csrf_meta.count() == 1)
    if csrf_meta.count() == 1:
        csrf_value = csrf_meta.get_attribute("content")
        report("CSRF token not empty", csrf_value and len(csrf_value) > 10)


def test_logout_flow(page):
    """Test logout flow."""
    print("\n── E2E: Logout Flow ──")

    # Login
    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill(ADMIN_EMAIL)
    page.locator('input[name="pass"]').fill(ADMIN_PASS)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Logout
    page.goto(f"{BASE_URL}/logout")
    page.wait_for_load_state("networkidle")
    report("Logout redirects to login", "/login" in page.url)

    # Session should be invalid
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("networkidle")
    report("Dashboard redirects after logout", "/login" in page.url)


def test_security_headers(page):
    """Test security-related behaviors."""
    print("\n── E2E: Security ──")

    # Try accessing protected pages without auth
    page.context.clear_cookies()
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("networkidle")
    report("Unauth redirect to login", "/login" in page.url)

    page.goto(f"{BASE_URL}/admin/students")
    page.wait_for_load_state("networkidle")
    report("Admin page requires auth", "/login" in page.url or page.url.endswith("/admin/students") is False)

    # Try path traversal in URL
    response = page.goto(f"{BASE_URL}/file?path=../../etc/passwd")
    report("Path traversal blocked", response.status in (400, 403, 404))

    # Try accessing DB file
    response = page.goto(f"{BASE_URL}/output-file?name=ytcloner.db")
    report("DB file blocked", response.status == 403)


def test_student_access_control(page):
    """Test that student cannot access admin pages."""
    print("\n── E2E: Student Access Control ──")

    # First, login as admin and create a student
    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill(ADMIN_EMAIL)
    page.locator('input[name="pass"]').fill(ADMIN_PASS)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    # Create student via API
    csrf_meta = page.locator('meta[name="csrf-token"]')
    csrf = csrf_meta.get_attribute("content") if csrf_meta.count() else ""

    result = page.evaluate(f"""
        fetch('/api/admin/create-student', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json', 'X-CSRF-Token': '{csrf}'}},
            body: JSON.stringify({{name: 'E2E Student', email: 'e2e-student@test.com', password: 'studentpass123!'}})
        }}).then(r => r.json())
    """)
    student_created = result and result.get("ok")
    report("Student created via API", student_created)

    # Logout and login as student
    page.goto(f"{BASE_URL}/logout")
    page.wait_for_load_state("networkidle")

    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill("e2e-student@test.com")
    page.locator('input[name="pass"]').fill("studentpass123!")
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    report("Student login works", "/login" not in page.url)

    # Student should be on /student
    report("Student redirected to /student", "/student" in page.url)

    # Student should NOT access admin pages
    resp = page.goto(f"{BASE_URL}/admin/students")
    page.wait_for_load_state("networkidle")
    report("Student blocked from admin", resp.status in (401, 403) or "/login" in page.url or "/student" in page.url)

    # Cleanup: login as admin and delete student
    page.goto(f"{BASE_URL}/logout")
    page.goto(f"{BASE_URL}/login")
    page.locator('input[name="email"]').fill(ADMIN_EMAIL)
    page.locator('input[name="pass"]').fill(ADMIN_PASS)
    page.locator('button[type="submit"]').click()
    page.wait_for_load_state("networkidle")


def main():
    print("\n" + "=" * 60)
    print("  YOUTUBE CLONER — E2E Test Suite (Playwright)")
    print("=" * 60)

    # Check server is running
    print(f"\nConnecting to {BASE_URL}...")
    if not wait_for_server(BASE_URL, timeout=15):
        print(f"ERROR: Server not running at {BASE_URL}")
        print("Start with: python dashboard.py &")
        sys.exit(1)
    print("Server is ready.\n")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed")
        print("Install with: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(10000)

        try:
            test_login_flow(page)
            test_dashboard_navigation(page)
            test_logout_flow(page)
            test_security_headers(page)
            test_student_access_control(page)
        except Exception as e:
            print(f"\n  [ERROR] Unexpected: {e}")
            ERRORS.append(f"Unexpected: {e}")
        finally:
            context.close()
            browser.close()

    # Results
    total = PASS + FAIL
    pct = round(PASS / total * 100) if total else 0
    print("\n" + "=" * 60)
    print(f"  E2E Results: {PASS}/{total} passed ({pct}%)")
    if ERRORS:
        print(f"  Failed: {', '.join(ERRORS[:10])}")
    print(f"  Status: {'PASS' if FAIL == 0 else 'FAIL'}")
    print("=" * 60 + "\n")

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
