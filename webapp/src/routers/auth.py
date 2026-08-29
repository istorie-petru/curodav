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
    Rate-limited per client IP (src/auth.py::login_rate_limited) -- too
    many failures in the window gets a 429 instead of even checking the
    submitted credentials.
  - `POST /logout` -- clear the cookie and return to /login.

`next` is a same-origin relative path only, validated by the same
`_safe_next` guard routers/tasks.py's work-session actions use (open-
redirect safety for a client-submitted redirect target).

2026-08-29: two more routes, the forced first-run setup flow (src/
auth.py's module docstring, `setup_required`):
  - `GET /setup` -- the account-creation form. Only rendered when
    setup_required() is true (a production deploy with no account yet);
    otherwise redirects away, same as /login's disabled-install redirect.
    Also offers an optional "connect to Radicale" section (URL/username/
    password) when the environment didn't already configure one (see
    config.py's radicale_env_configured) -- skippable, and editable again
    later from Settings (routers/settings.py) since this page only ever
    renders once per install.
  - `POST /setup` -- validates and persists the chosen username/password
    (hashed) via `auth.set_persisted_credentials`, logs the browser in
    immediately (no separate trip through /login), and redirects home.
    Re-checks setup_required() itself too -- the middleware already blocks
    a configured install from reaching here without a valid session, but
    the route refuses to ever re-run setup regardless of how it's called.
    Radicale fields are optional and, if all blank, silently skipped;
    persisted via config.RADICALE_*_KEY (config.py's own module docstring
    covers why the password is stored retrievable, not hashed) when any
    are filled in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth, config, db
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
def login_page(request: Request, next: str = "", conn=Depends(get_db)):
    settings = request.app.state.settings
    if not auth.auth_enabled(settings, conn):
        return RedirectResponse(url="/", status_code=302)
    # Already logged in -- skip the form and go straight to where they
    # were headed.
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
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
    if not auth.auth_enabled(settings, conn):
        return RedirectResponse(url="/", status_code=302)
    client_key = auth.client_ip(request)
    if auth.login_rate_limited(client_key):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "next_url": _safe_next(next) or "",
                "error": "Too many attempts. Try again in a few minutes.",
            },
            status_code=429,
        )
    if auth.verify_credentials(settings, username, password, conn):
        auth.clear_login_attempts(client_key)
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
            secure=auth.is_secure_request(request),
            path="/",
        )
        return response
    auth.record_failed_login(client_key)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next_url": _safe_next(next) or "", "error": "Incorrect username or password."},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        auth.SESSION_COOKIE, path="/", samesite="lax", secure=auth.is_secure_request(request)
    )
    return response


@router.get("/setup")
def setup_page(request: Request, conn=Depends(get_db)):
    settings = request.app.state.settings
    if not auth.setup_required(settings, conn):
        return RedirectResponse(
            url="/login" if auth.auth_enabled(settings, conn) else "/", status_code=302
        )
    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "error": None,
            "radicale_env_configured": settings.radicale_env_configured,
        },
    )


def _save_radicale_fields(conn, url: str, username: str, password: str) -> None:
    """Persists a Radicale connection entered through /setup (or, later,
    Settings) into app_meta -- see config.py's RADICALE_*_KEY docstring
    for why the password is stored retrievable. Only writes anything when
    all three fields are non-blank; a partially-filled form is treated as
    "not filled in" rather than saving a broken connection."""
    url, username, password = url.strip(), username.strip(), password.strip()
    if url and username and password:
        db.set_app_meta(conn, config.RADICALE_URL_KEY, url)
        db.set_app_meta(conn, config.RADICALE_USERNAME_KEY, username)
        db.set_app_meta(conn, config.RADICALE_PASSWORD_KEY, password)


@router.post("/setup")
def setup_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    radicale_url: str = Form(""),
    radicale_username: str = Form(""),
    radicale_password: str = Form(""),
    conn=Depends(get_db),
):
    settings = request.app.state.settings
    if not auth.setup_required(settings, conn):
        return RedirectResponse(
            url="/login" if auth.auth_enabled(settings, conn) else "/", status_code=302
        )
    username = username.strip()
    error = None
    if not username:
        error = "Choose a username."
    elif not password:
        error = "Choose a password."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != password_confirm:
        error = "Passwords do not match."
    if error:
        return templates.TemplateResponse(
            "setup.html",
            {
                "request": request,
                "error": error,
                "radicale_env_configured": settings.radicale_env_configured,
            },
            status_code=400,
        )
    auth.set_persisted_credentials(conn, username, password)
    if not settings.radicale_env_configured:
        _save_radicale_fields(conn, radicale_url, radicale_username, radicale_password)
    # The middleware caches "is this install configured" on app.state once
    # true (see AuthMiddleware._configured) -- set it here too so the very
    # next request (the redirect this response issues) doesn't race a
    # fresh DB read that a concurrent request could still see as
    # unconfigured.
    state = getattr(request.app, "state", None)
    if state is not None:
        state._cc_auth_configured = True
    secret = auth.session_secret(settings, conn)
    token = auth.make_session_token(secret, username)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=auth.is_secure_request(request),
        path="/",
    )
    return response