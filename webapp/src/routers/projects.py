"""Old Project URLs. A project's page lives at `/labels/{name}` since
labels-as-modules slice b (2026-09-25, routers/label_pages.py). Its
deadline is set in the label form, and archiving is a button on that page
(`/labels/{name}/archive`), available to any label with a deadline. The
promote/dates/demote/archive POST endpoints that used to live here had no
UI posting to them any more and are gone, along with the start/end period
and its overlap rule (Peter, 2026-09-25: keep deadline + archive flow, drop
start_date).

What's left is redirects, so old links and bookmarks still land somewhere
real.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects_redirect():
    """The `/projects` listing was retired 2026-08-15; the Tasks table
    groups by project, which is the closest equivalent."""
    return RedirectResponse(url="/tasks", status_code=302)


@router.get("/{name}")
def project_detail_redirect(name: str):
    return RedirectResponse(url=f"/labels/{quote(name)}", status_code=301)


@router.get("/{name}/calendar")
def project_calendar_redirect(name: str):
    return RedirectResponse(url=f"/labels/{quote(name)}", status_code=301)
