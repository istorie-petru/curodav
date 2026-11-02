"""Settings > API access: personal tokens, connected apps, the connector address and recent API activity.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

A new token's secret is shown once: the create POST keeps it in memory for a few minutes and the next full page load
takes it out (the modal's own fetch of the redirect leaves it), so it never travels in a URL or lands in the database.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import access_tokens, api_activity, api_history, clock
from ..api_write import EditError
from ..deps import get_db, templates, wants_json

router = APIRouter(tags=["settings-api-access"])

PATH = "/settings/api-access"
_REVEAL_FOR = timedelta(minutes=5)
_fresh: list[tuple[str, object]] = []


def base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _take_fresh(request: Request) -> str | None:
    if wants_json(request.headers.get("x-requested-with")):
        return None
    now = clock.now()
    secrets = [secret for secret, at in _fresh if now - at <= _REVEAL_FOR]
    _fresh.clear()
    return secrets[-1] if secrets else None


@router.get(PATH)
def api_access_page(request: Request, conn=Depends(get_db)):
    tokens = [t | {"access": access_tokens.describe(t["scopes"])} for t in access_tokens.list_tokens(conn)]
    return templates.TemplateResponse(request, "settings_api_access.html", {
        "active_tab": "settings_api_access", "crumbs": [{"url": "/settings", "name": "Settings"}], "title": "API access",
        "personal": [t for t in tokens if t["kind"] == "personal"], "apps": [t for t in tokens if t["kind"] == "oauth"],
        "fresh_secret": _take_fresh(request), "base": base_url(request),
        "visits": api_activity.recent_visits(conn),
        "changes": [c | {"when": _local(c["at"])} for c in api_history.list_changes(conn)],
        "conflict": request.query_params.get("conflict", ""),
    })


def _local(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%dT%H:%M")


@router.get(PATH + "/new")
def new_token_modal(request: Request):
    return templates.TemplateResponse(request, "settings_api_token_modal.html", {
        "token": None, "scope_rows": access_tokens.scope_rows(access_tokens.DEFAULT_SCOPES)})


@router.get(PATH + "/tokens/{uid}/edit")
def edit_token_modal(uid: str, request: Request, conn=Depends(get_db)):
    token = access_tokens.get_token(conn, uid)
    if token is None:
        return RedirectResponse(url=f"{PATH}?error=That token no longer exists", status_code=303)
    return templates.TemplateResponse(request, "settings_api_token_modal.html", {
        "token": token, "scope_rows": access_tokens.scope_rows(token["scopes"])})


@router.post(PATH + "/tokens")
def create_token(name: str = Form(""), grant: list[str] = Form(default=[]), scopes_sent: str = Form(""), conn=Depends(get_db)):
    _uid, secret = access_tokens.create_personal_token(conn, name, " ".join(grant) if scopes_sent else access_tokens.DEFAULT_SCOPES)
    _fresh.append((secret, clock.now()))
    return RedirectResponse(url=PATH, status_code=303)


@router.post(PATH + "/tokens/{uid}")
def save_token_access(uid: str, grant: list[str] = Form(default=[]), conn=Depends(get_db)):
    if not access_tokens.set_scopes(conn, uid, " ".join(grant)):
        return RedirectResponse(url=f"{PATH}?error=That token no longer exists", status_code=303)
    return RedirectResponse(url=f"{PATH}?note=Access saved", status_code=303)


@router.post(PATH + "/tokens/{uid}/revoke")
def revoke_token(uid: str, conn=Depends(get_db)):
    access_tokens.revoke_token(conn, uid)
    return RedirectResponse(url=f"{PATH}?note=Access removed", status_code=303)


@router.post(PATH + "/changes/{uid}/undo")
def undo_change(uid: str, force: str = Form(""), conn=Depends(get_db)):
    try:
        api_history.undo(conn, uid, force=force == "1")
    except EditError as exc:
        query = {"error": f"{exc}. Undo anyway replaces those later changes too." if exc.code == "conflict" else str(exc)}
        if exc.code == "conflict":
            query["conflict"] = uid
        return RedirectResponse(url=f"{PATH}?{urlencode(query)}", status_code=303)
    return RedirectResponse(url=f"{PATH}?note=Undone", status_code=303)
