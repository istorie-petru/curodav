"""Single-user login routes (2026-08-16, src/auth.py).

Three routes:
  - `GET /login`  -- the login page. Renders a minimal standalone template
    (not base.html -- showing the full app chrome on the sign-in screen
    would be odd and would leak page nav to a signed-out browser).
    Redirects away when login isn't actually enforced (auth disabled) or
    the visitor is already authenticated.
  - `POST /login` -- verify the credentials and, on success, set the
    signed session cookie and redirect to the validated `next` target (or
    `/`). Wrong credentials re-render the form with an error -- no
    distinguishing "username wrong" vs "password wrong" messages, and the
    comparison itself is constant-time (src/auth.py::verify_credentials).
  - `POST /logout` -- clear the cookie and return to /login.

`next` is a same-origin relative path only, validated by the same
`_safe_next` guard routers/tasks.py's work-session actions use (open-
redirect safety for a client-submitted redirect target).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth, db
from ..deps import get_db, templates

router = APIRouter(tags=["auth"])


def _safe_next(next_url: str) -> str | None:
    """A same-origin relative path safe for a post-login redirect --
    rejects schemes, "//host" and so on that a client-submitted `next`
    could carry. Same rule as routers/tasks.py's `_safe_next`. The
    isinstance guard also covers direct router calls in tests that omit
    `next` (its Form default object)."""
    if isinstance(next_url, str) and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return None


@router.get("/login")
def login_page(request: Request, next: str = ""):
    settings = request.app.state.settings
    if not auth.auth_enabled(settings):
        return RedirectResponse(url="/", status_code=302)
    # Already logged in -- skip the form and go straight to where they
    # were headed.
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        with db.connect(settings.db_path) as conn:
            secret = auth.session_secret(settings, conn)
        if auth.read_session_token(secret, token):
            return RedirectResponse(url=_safe_next(next) or "/", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next_url": _safe_next(next) or "", "error": None},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
    conn=Depends(get_db),
):
    settings = request.app.state.settings
    if not auth.auth_enabled(settings):
        return RedirectResponse(url="/", status_code=302)
    if auth.verify_credentials(settings, username, password):
        secret = auth.session_secret(settings, conn)
        token = auth.make_session_token(secret, username)
        response = RedirectResponse(
            url=_safe_next(next) or "/", status_code=303
        )
        response.set_cookie(
            auth.SESSION_COOKIE,
            token,
            max_age=auth.SESSION_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next_url": _safe_next(next) or "", "error": "Incorrect username or password."},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response