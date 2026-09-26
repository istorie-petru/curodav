"""The Habits page (`/habits`) -- 2026-09-24, plans/ui-cleanup-2026-09.md
item 14, slice H2.

A habit is a habit-labeled task; this page renders them through
habit_view.habit_items, never as task rows, and replaces the Tasks table's
old Habits group outright (Peter's answer to the plan's question 3).
Layout, per the Streak-informed plan: a "To do" section (habits whose open
window isn't kept yet) above an "On track" one, each row with a one-tap
check-in, the schedule and streak, and a tap-a-day strip of the last seven
days. Every mutation posts to the existing task completion endpoints;
static/habit_actions.js fetches them and re-renders `#habits-body` from
`/habits/regions`.

The standalone Habit entity this router used to own (`habits`/
`habit_entries`, CRUD + entries endpoints) was removed in slice 1; its
tables stay physically in an existing cache.sqlite. Any other old
`/habits/...` URL redirects here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db, habit_view
from ..deps import get_db, respond, templates

# Habits H6: longest single pause (vacation) range accepted.
_MAX_PAUSE_DAYS = 366

router = APIRouter(prefix="/habits", tags=["habits"])


def _habits_context(conn, request: Request) -> dict:
    items = habit_view.habit_items(conn)
    # 2026-09-26: each row's expandable history (heatmap or week/month
    # grid + insights), same week start as the strip.
    week_start = db.get_app_meta(conn, habit_view.WEEK_START_KEY) or "monday"
    for h in items:
        task = db.get_task(conn, h["uid"])
        h["history"] = habit_view.history(conn, task, week_start=week_start) if task else None
    return {
        "request": request,
        "active_tab": "habits",
        "todo": [h for h in items if h["due_today"]],
        "on_track": [h for h in items if not h["due_today"] and not h["paused_today"]],
        # Habits H6: habits on a pause today get their own section.
        "paused": [h for h in items if h["paused_today"] and not h["due_today"]],
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


@router.get("/pauses")
def pauses_modal(request: Request, conn=Depends(get_db)):
    """2026-09-26 (Peter): every pause -- all-habit and single-habit -- in
    one modal behind the Habits page header's Pauses button, instead of a
    Vacation section on the page and a Pause section in each habit."""
    today = date.today().isoformat()
    habits = [
        {"uid": h["uid"], "title": h["title"]}
        for h in habit_view.habit_items(conn)
        if not h["is_avoid"]  # an avoid habit's clean streak ignores pauses (UI audit H-12)
    ]
    titles = {h["uid"]: h["title"] for h in habits}
    pauses = []
    for p in db.list_habit_pauses(conn):
        if p["end_date"] < today:
            continue
        if p["task_uid"] is None:
            title = "All habits"
        else:
            task = db.get_task(conn, p["task_uid"])
            if task is None:
                continue
            title = titles.get(p["task_uid"]) or task.get("title") or "Habit"
        pauses.append({**p, "habit_title": title})
    return templates.TemplateResponse(
        "habit_pauses.html",
        {"request": request, "active_tab": "habits", "pauses": pauses, "habits": habits, "today_iso": today},
    )


@router.post("/pauses")
def add_pause(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    task_uid: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Habits H6: pause one habit (`task_uid`) or all habits (blank) for an
    inclusive date range -- a vacation. Past ranges are allowed on
    purpose (forgot to set it before leaving); paused days are neutral for
    streaks, never "missed"."""
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid date."}, status_code=400)
    if end < start:
        return JSONResponse({"error": "The pause must end on or after its start."}, status_code=400)
    if (end - start).days + 1 > _MAX_PAUSE_DAYS:
        return JSONResponse({"error": "A pause can be at most a year long."}, status_code=400)
    task_uid = (task_uid or "").strip() or None
    if task_uid is not None and db.get_task(conn, task_uid) is None:
        return JSONResponse({"error": "Unknown habit."}, status_code=404)
    db.add_habit_pause(
        conn, str(uuid.uuid4()), task_uid, start.isoformat(), end.isoformat(), datetime.now(timezone.utc).isoformat()
    )
    return respond(x_requested_with, request.headers.get("referer") or "/habits")


@router.post("/pauses/{pause_uid}/delete")
def delete_pause(
    pause_uid: str, request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)
):
    db.delete_habit_pause(conn, pause_uid)
    return respond(x_requested_with, request.headers.get("referer") or "/habits")


@router.get("/{rest:path}")
def habit_page_redirect(rest: str):
    return RedirectResponse(url="/habits", status_code=302)
