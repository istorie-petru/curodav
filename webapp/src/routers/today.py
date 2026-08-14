"""Today -- execution (1.7, plans/open-priority.md § Information
architecture & view surfaces' "Today -- execution" bullet): "What am I
dealing with now?" An operational view of the current day combining today's
calendar events, today's scheduled task work (work allocations), due/
overdue tasks, and other important/urgent items -- generated entirely from
existing data (db.list_events/list_tasks, db.work_allocation_task_uid,
derived_state.virtual_states), per the spec's own "no separate Today data
model" line. This is the first slice of 1.7; Week (planning) and Spaces
(context) are separate, later slices -- see plans/STATE.md.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Request

from .. import db, derived_state
from ..deps import get_db, templates

router = APIRouter(tags=["today"])


def _hours_between(start_at: str | None, end_at: str | None) -> float:
    """Local copy of db._hours_between's trivial duration math -- a work
    allocation event's own start/end, not worth exposing db's private
    helper across module boundaries for one two-line calculation."""
    if not start_at or not end_at:
        return 0.0
    try:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
    except ValueError:
        return 0.0
    return max((end - start).total_seconds() / 3600.0, 0.0)


@router.get("/today")
def today_view(request: Request, conn=Depends(get_db)):
    today = date.today()
    today_iso = today.isoformat()
    start = f"{today_iso}T00:00:00"
    end = f"{today_iso}T23:59:59"

    events = db.list_events(conn, start=start, end=end)
    events = [e for e in events if e.get("start_at") and e["start_at"][:10] == today_iso]

    # Split today's events into ordinary calendar commitments and scheduled
    # task work (work allocations) -- the same is_work_allocation
    # distinction routers/projects.py::project_calendar draws per event,
    # via the same db.work_allocation_task_uid lookup.
    calendar_events: list[dict] = []
    scheduled_work: list[dict] = []
    scheduled_hours_today = 0.0
    for e in events:
        task_uid = db.work_allocation_task_uid(conn, e["uid"])
        if task_uid:
            task = db.get_task(conn, task_uid)
            hours = _hours_between(e.get("start_at"), e.get("end_at"))
            scheduled_work.append({"event": e, "task": task, "hours": hours})
            scheduled_hours_today += hours
        else:
            calendar_events.append(e)
    calendar_events.sort(key=lambda e: e.get("start_at") or "")
    scheduled_work.sort(key=lambda w: w["event"].get("start_at") or "")

    open_tasks = [t for t in db.list_tasks(conn) if t.get("status") not in ("done", "archived")]
    overdue_tasks = sorted(
        (t for t in open_tasks if t.get("due_at") and t["due_at"][:10] < today_iso),
        key=lambda t: t["due_at"],
    )
    due_today_tasks = sorted(
        (t for t in open_tasks if t.get("due_at") and t["due_at"][:10] == today_iso),
        key=lambda t: t["due_at"],
    )

    # Important/urgent items not already surfaced above -- the shared
    # aggregation service (1.1, src/derived_state.py), same "important"/
    # "urgent" virtual states the Dashboard's At a Glance widget counts, so
    # this list can never disagree with what /tasks?date_filter=important
    # shows. Excludes anything already shown in the due/overdue lists above
    # so nothing appears twice on the page.
    shown_uids = {t["uid"] for t in overdue_tasks} | {t["uid"] for t in due_today_tasks}
    label_rules = db.list_label_rules(conn)
    important_upcoming = []
    for t in open_tasks:
        if t["uid"] in shown_uids:
            continue
        states = derived_state.virtual_states(t, label_rules, today)
        if "important" in states or "urgent" in states:
            important_upcoming.append((t, states))
    important_upcoming.sort(
        key=lambda pair: (
            -derived_state.effective_importance(pair[0], label_rules),
            -derived_state.effective_urgency(pair[0], label_rules, today),
            pair[0].get("due_at") or "9999-99-99",
        )
    )
    important_upcoming = important_upcoming[:8]

    workload = {
        "scheduled_hours_today": round(scheduled_hours_today, 1),
        "overdue_count": len(overdue_tasks),
        "due_today_count": len(due_today_tasks),
        "events_count": len(calendar_events),
    }

    return templates.TemplateResponse(
        "today.html",
        {
            "request": request,
            "active_tab": "today",
            "today": today_iso,
            "today_label": today.strftime("%A, %B %d"),
            "calendar_events": calendar_events,
            "scheduled_work": scheduled_work,
            "overdue_tasks": overdue_tasks,
            "due_today_tasks": due_today_tasks,
            "important_upcoming": important_upcoming,
            "workload": workload,
        },
    )
