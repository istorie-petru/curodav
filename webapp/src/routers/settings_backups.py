"""Settings > Backups: the automatic backups of the last week on a timeline, and restoring all of one or one thing from it.

Feature document: curodav-notes/documentation/features/api-and-mcp.md (Backups)
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auto_backups
from ..api_write import EditError
from ..deps import get_db, templates

router = APIRouter(tags=["settings-backups"])

PATH = "/settings/backups"


def _dir(request: Request):
    return request.app.state.settings.backup_dir


def _back(message: str, error: bool = False) -> RedirectResponse:
    return RedirectResponse(url=f"{PATH}?{'error' if error else 'note'}={quote(message)}", status_code=303)


@router.get(PATH)
def backups_page(request: Request):
    return templates.TemplateResponse(request, "settings_backups.html", {
        "active_tab": "settings_backups", "crumbs": [{"url": "/settings", "name": "Settings"}], "title": "Backups",
        "days": auto_backups.timeline(_dir(request)), "kinds": auto_backups.KINDS})


@router.get(PATH + "/{name}")
def backup_window(name: str, request: Request, conn=Depends(get_db)):
    try:
        diff = auto_backups.compare(conn, _dir(request), name)
    except FileNotFoundError:
        return _back("That backup is no longer kept", error=True)
    entry = next((e for e in auto_backups.list_backups(_dir(request)) if e["name"] == name), None)
    return templates.TemplateResponse(request, "settings_backup_modal.html", {"backup": entry, "diff": diff})


@router.post(PATH + "/{name}/restore")
def restore_everything(name: str, request: Request):
    settings = request.app.state.settings
    try:
        auto_backups.restore_all(settings.db_path, settings.backup_dir, name)
    except FileNotFoundError:
        return _back("That backup is no longer kept", error=True)
    return _back("Restored. The state before is kept as a backup too")


@router.post(PATH + "/{name}/note")
def restore_note(name: str, request: Request, uid: str = Form(...), conn=Depends(get_db)):
    return _restore_one(request, conn, name, "note", uid)


@router.post(PATH + "/{name}/discipline")
def restore_discipline(name: str, request: Request, semester_uid: str = Form(...), discipline: str = Form(...), conn=Depends(get_db)):
    return _restore_one(request, conn, name, "discipline", [semester_uid, discipline])


def _restore_one(request: Request, conn, name: str, kind: str, key):
    try:
        auto_backups.restore_one(conn, _dir(request), name, kind, key)
    except FileNotFoundError:
        return _back("That backup is no longer kept", error=True)
    except EditError as exc:
        return _back(str(exc), error=True)
    return _back("Restored. Undo it under Settings, API access, Changes")
