"""
Auth routes — login, logout, health check.
"""

import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from auth import optional_auth, create_session, destroy_session, set_session_cookie, clear_session_cookie, get_session_token
from middleware import generate_csrf_token
from database import authenticate_user
from rate_limit import limiter

logger = logging.getLogger("ytcloner.routes.auth")

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(optional_auth)):
    if user:
        if user.get("role") == "admin":
            return RedirectResponse("/", status_code=302)
        return RedirectResponse("/student", status_code=302)

    from dashboard import render
    return render(request, "login.html", {"error": ""})


@router.post("/login")
@limiter.limit("5/minute")
async def login_submit(request: Request):
    form = await request.form()
    email = form.get("email", "").strip()
    password = form.get("pass", "")

    user = authenticate_user(email, password)
    if not user:
        from dashboard import render
        return render(request, "login.html", {"error": "Email ou senha invalidos"})

    token = create_session(user["id"])
    logger.info(f"Login: {email} (role={user['role']})")

    if user["role"] == "admin":
        response = RedirectResponse("/", status_code=302)
    else:
        response = RedirectResponse("/student", status_code=302)

    return set_session_cookie(response, token)


@router.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request):
    token = request.cookies.get("session", "")
    if token:
        destroy_session(token)
        logger.info(f"Logout: session ended")

    response = RedirectResponse("/login", status_code=302)
    return clear_session_cookie(response)


@router.get("/api/health")
async def health():
    return JSONResponse({"status": "ok"})
