"""Settings hub -- 2026-08-01 Phase B nav rework. Projects/Habits/Contacts
management moved off the main topbar (see base.html's nav comment: none of
the three are visited often enough to earn a permanent tab) into one
Settings section, reached via the gear icon next to the theme toggle.

Deliberately not a real page of its own with duplicated content -- Projects,
Habits, and Contacts already have full, working management UIs
(projects_manage.html, habits_list.html, contacts_list.html), each now
carrying the shared `_settings_nav.html` segmented strip. Rebuilding that as
a fourth "hub" page would just be a worse copy of the first tab. `/settings`
is a plain redirect to the first section instead, same as clicking the
first tab would do."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["settings"])


@router.get("/settings")
def settings_index() -> RedirectResponse:
    return RedirectResponse(url="/projects", status_code=307)
