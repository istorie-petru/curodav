"""Settings > API access: personal tokens, connected apps, the connector address and recent API activity.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

A new token's secret is shown once: the create POST keeps it in memory for a few minutes and the next full page load
takes it out (the modal's own fetch of the redirect leaves it), so it never travels in a URL or lands in the database.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import access_tokens, clock
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
    tokens = access_tokens.list_tokens(conn)
    return templates.TemplateResponse(request, "settings_api_access.html", {
        "active_tab": "settings_api_access", "crumbs": [{"url": "/settings", "name": "Settings"}], "title": "API access",
        "personal": [t for t in tokens if t["kind"] == "personal"], "apps": [t for t in tokens if t["kind"] == "oauth"],
        "fresh_secret": _take_fresh(request), "base": base_url(request),
        "activity": access_tokens.recent_activity(conn, 30),
    })


@router.get(PATH + "/new")
def new_token_modal(request: Request):
    return templates.TemplateResponse(request, "settings_api_token_modal.html", {})


@router.post(PATH + "/tokens")
def create_token(name: str = Form(""), can_edit: str = Form(""), conn=Depends(get_db)):
    _uid, secret = access_tokens.create_personal_token(conn, name, "read write" if can_edit == "1" else "read")
    _fresh.append((secret, clock.now()))
    return RedirectResponse(url=PATH, status_code=303)


@router.post(PATH + "/tokens/{uid}/revoke")
def revoke_token(uid: str, conn=Depends(get_db)):
    access_tokens.revoke_token(conn, uid)
    return RedirectResponse(url=f"{PATH}?note=Access removed", status_code=303)
