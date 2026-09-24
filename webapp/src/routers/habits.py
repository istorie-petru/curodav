"""`/habits` URLs -- redirect-only since 2026-09-24.

The standalone Habit entity (`habits`/`habit_entries`, create/edit/
archive/delete/entries/toggle endpoints, its detail page and form) was
removed outright that day (plans/ui-cleanup-2026-09.md item 14, slice 1:
Peter had no real entities in use). A habit is a habit-labeled task now,
rendered through habit_view.py; its tables stay physically in an existing
cache.sqlite, never force-dropped, same convention as every other table
removal in db.py. Every old `/habits...` bookmark lands on the Tasks
page's Habits group -- the dedicated Habits page is the next slice.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/habits", tags=["habits"])


@router.get("")
def list_habits_redirect():
    return RedirectResponse(url="/tasks", status_code=302)


@router.get("/{rest:path}")
def habit_page_redirect(rest: str):
    return RedirectResponse(url="/tasks", status_code=302)
