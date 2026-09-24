"""The Habits page (`/habits`) -- 2026-09-24, plans/ui-cleanup-2026-09.md
item 14, slice H2.

A habit is a habit-labeled task; this page renders them through
habit_view.habit_items, never as task rows, and replaces the Tasks table's
old Habits group outright (Peter's answer to the plan's question 3).
Layout, per the Streak-informed plan: a "To do" section (habits whose open
window isn't kept yet) above an "On track" one, each row with a one-tap
check-in, the schedule and streak, and a tap-a-day strip of the last seven
days. Every mutation posts to the existing task completion endpoints;
static/habits_page.js fetches them and re-renders `#habits-body` from
`/habits/regions`.

The standalone Habit entity this router used to own (`habits`/
`habit_entries`, CRUD + entries endpoints) was removed in slice 1; its
tables stay physically in an existing cache.sqlite. Any other old
`/habits/...` URL redirects here.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import db, habit_view
from ..deps import get_db, templates

router = APIRouter(prefix="/habits", tags=["habits"])


def _habits_context(conn, request: Request) -> dict:
    items = habit_view.habit_items(conn)
    return {
        "request": request,
        "active_tab": "habits",
        "todo": [h for h in items if h["due_today"]],
        "on_track": [h for h in items if not h["due_today"]],
        "has_habits": bool(items),
        "habit_label": db.get_task_habit_settings(conn)["habit_label"],
        "today_iso": date.today().isoformat(),
    }


@router.get("")
def habits_page(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("habits.html", _habits_context(conn, request))


@router.get("/regions")
def habits_regions(request: Request, conn=Depends(get_db)):
    """Async-CRUD region fragment: just `#habits-body`, re-rendered after a
    check-in or a habit edit (features/async-crud.md)."""
    html = templates.env.get_template("_habits_body.html").render(_habits_context(conn, request))
    return HTMLResponse(html)


@router.get("/{rest:path}")
def habit_page_redirect(rest: str):
    return RedirectResponse(url="/habits", status_code=302)
