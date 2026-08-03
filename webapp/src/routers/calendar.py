from __future__ import annotations

import calendar as py_calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, grid_layout, recurrence_expand
from ..deps import get_bridge, get_db, templates
from .calendars import get_hidden_calendars

router = APIRouter(prefix="/calendar", tags=["calendar"])
# Event CRUD is a separate, unprefixed router -- these are shared item
# endpoints (fetched by uid from Month/Week/Day/Agenda views, the modal
# system, etc.), not "the calendar page" itself, same as /tasks/... and
# /contacts/... aren't nested under their own view prefixes either.
events_router = APIRouter(tags=["events"])


def _week_bounds(d: date) -> tuple[date, date]:
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _color_map(conn) -> dict[str, str]:
    return {c["uid"]: c["color"] for c in db.list_calendars(conn)}


def _annotate_colors(events: list[dict], color_map: dict[str, str]) -> list[dict]:
    for e in events:
        e["calendar_color"] = color_map.get(e.get("calendar_path"), "blue")
    return events


def _project_calendar_uids(conn, project_uid: str | None, group_uid: str | None) -> set[str] | None:
    """Return the set of calendar UIDs that satisfy the project/space filter,
    or None when no filter is active (caller should not filter at all).
    Only one filter is expected to be set at a time from the UI, but both are
    supported; project_uid takes priority when both arrive together."""
    if not project_uid and not group_uid:
        return None
    calendars = db.list_calendars(conn)
    if project_uid:
        return {c["uid"] for c in calendars if c.get("project_uid") == project_uid}
    # Space (group_uid) filter: collect project UIDs for this space first.
    group_project_uids = {
        p["uid"] for p in db.list_projects(conn, include_archived=False)
        if p.get("group_uid") == group_uid
    }
    return {c["uid"] for c in calendars if c.get("project_uid") in group_project_uids}


def _project_list_uids(conn, project_uid: str | None, group_uid: str | None) -> set[str] | None:
    """Same logic as _project_calendar_uids but for task_lists, used to filter
    tasks shown alongside events in every calendar view."""
    if not project_uid and not group_uid:
        return None
    task_lists = db.list_task_lists(conn)
    if project_uid:
        return {l["uid"] for l in task_lists if l.get("project_uid") == project_uid}
    group_project_uids = {
        p["uid"] for p in db.list_projects(conn, include_archived=False)
        if p.get("group_uid") == group_uid
    }
    return {l["uid"] for l in task_lists if l.get("project_uid") in group_project_uids}


def _month_grid(year: int, month: int, events: list[dict], tasks: list[dict]) -> list[list[dict]]:
    events_by_date: dict[str, list[dict]] = {}
    for e in events:
        if not e.get("start_at"):
            continue
        events_by_date.setdefault(e["start_at"][:10], []).append(e)
    tasks_by_date: dict[str, list[dict]] = {}
    for t in tasks:
        if not t.get("due_at"):
            continue
        tasks_by_date.setdefault(t["due_at"][:10], []).append(t)

    cal = py_calendar.Calendar(firstweekday=0)
    today = date.today()
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        week_days = []
        for day in week:
            key = day.isoformat()
            week_days.append(
                {
                    "date": day,
                    "iso": key,
                    "in_month": day.month == month,
                    "is_today": day == today,
                    "events": sorted(
                        events_by_date.get(key, []), key=lambda e: e.get("start_at") or ""
                    ),
                    "tasks": tasks_by_date.get(key, []),
                }
            )
        weeks.append(week_days)
    return weeks


@router.get("")
def month_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    project_uid: str | None = None,
    group_uid: str | None = None,
    conn=Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    hidden = get_hidden_calendars(request)

    # Expand across the visible 6-week grid, not just the calendar month,
    # so recurring events show correctly on the leading/trailing days from
    # the adjacent months that the grid always displays a few of.
    grid_start = date(year, month, 1) - timedelta(days=6)
    grid_end = date(year, month, 28) + timedelta(days=13)
    events = db.list_events(
        conn, start=grid_start.isoformat(), end=grid_end.isoformat() + "T23:59:59",
        exclude_calendars=list(hidden),
    )
    events = recurrence_expand.expand_events(events, grid_start, grid_end)
    events = _annotate_colors(events, _color_map(conn))

    # Project/space filter -- applied after calendar-visibility so the two
    # systems stay independent. None means "no filter, show everything."
    cal_uids = _project_calendar_uids(conn, project_uid, group_uid)
    if cal_uids is not None:
        events = [e for e in events if e.get("calendar_path") in cal_uids]
    list_uids = _project_list_uids(conn, project_uid, group_uid)
    tasks = db.list_tasks(conn)
    if list_uids is not None:
        tasks = [t for t in tasks if t.get("list_path") in list_uids]

    weeks = _month_grid(year, month, events, tasks)

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return templates.TemplateResponse(
        "calendar_month.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "month",
            "today_iso": today.isoformat(),
            "weeks": weeks,
            "year": year,
            "month": month,
            "month_name": py_calendar.month_name[month],
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "calendars": db.list_calendars(conn),
            "hidden": hidden,
            "projects": db.list_projects(conn, include_archived=False),
            "project_groups": db.list_project_groups(conn),
            "active_project_uid": project_uid or "",
            "active_group_uid": group_uid or "",
        },
    )


@router.get("/week")
def week_view(
    request: Request,
    date_: str | None = None,
    project_uid: str | None = None,
    group_uid: str | None = None,
    conn=Depends(get_db),
):
    anchor = date.fromisoformat(date_) if date_ else date.today()
    monday, sunday = _week_bounds(anchor)
    hidden = get_hidden_calendars(request)

    # `end` must be an end-of-day timestamp, not a bare date -- db.list_events
    # compares these as plain strings, and "2026-09-02T09:00:00" sorts
    # *after* "2026-09-02" lexicographically, so a bare end-date would
    # silently exclude every timed event on the range's last calendar day.
    events = db.list_events(
        conn, start=monday.isoformat(), end=sunday.isoformat() + "T23:59:59",
        exclude_calendars=list(hidden),
    )
    events = recurrence_expand.expand_events(events, monday, sunday)
    events = _annotate_colors(events, _color_map(conn))

    cal_uids = _project_calendar_uids(conn, project_uid, group_uid)
    if cal_uids is not None:
        events = [e for e in events if e.get("calendar_path") in cal_uids]
    list_uids = _project_list_uids(conn, project_uid, group_uid)
    tasks = db.list_tasks(conn)
    if list_uids is not None:
        tasks = [t for t in tasks if t.get("list_path") in list_uids]

    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        key = d.isoformat()
        day_events = [e for e in events if e.get("start_at", "").startswith(key)]
        all_day = [e for e in day_events if e.get("all_day")]
        timed = grid_layout.layout_day(day_events)
        day_tasks = [t for t in tasks if (t.get("due_at") or "").startswith(key)]
        days.append(
            {
                "date": d,
                "iso": key,
                "is_today": d == date.today(),
                "all_day": all_day,
                "timed": timed,
                "tasks": day_tasks,
            }
        )

    return templates.TemplateResponse(
        "calendar_week.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "week",
            "today_iso": date.today().isoformat(),
            "days": days,
            "hours": list(range(grid_layout.GRID_HOURS)),
            "px_per_hour": grid_layout.PX_PER_HOUR,
            "monday": monday,
            "sunday": sunday,
            "prev_week": (monday - timedelta(days=7)).isoformat(),
            "next_week": (monday + timedelta(days=7)).isoformat(),
            "calendars": db.list_calendars(conn),
            "hidden": hidden,
            "projects": db.list_projects(conn, include_archived=False),
            "project_groups": db.list_project_groups(conn),
            "active_project_uid": project_uid or "",
            "active_group_uid": group_uid or "",
        },
    )


@router.get("/day/{day}")
def day_view(
    day: str,
    request: Request,
    project_uid: str | None = None,
    group_uid: str | None = None,
    conn=Depends(get_db),
):
    d = date.fromisoformat(day)
    hidden = get_hidden_calendars(request)
    events = db.list_events(conn, start=day, end=day + "T23:59:59", exclude_calendars=list(hidden))
    events = recurrence_expand.expand_events(events, d, d)
    events = [e for e in events if e.get("start_at", "").startswith(day)]
    events = _annotate_colors(events, _color_map(conn))

    cal_uids = _project_calendar_uids(conn, project_uid, group_uid)
    if cal_uids is not None:
        events = [e for e in events if e.get("calendar_path") in cal_uids]
    list_uids = _project_list_uids(conn, project_uid, group_uid)
    all_tasks = db.list_tasks(conn)
    if list_uids is not None:
        all_tasks = [t for t in all_tasks if t.get("list_path") in list_uids]
    tasks = [t for t in all_tasks if (t.get("due_at") or "").startswith(day)]

    all_day = [e for e in events if e.get("all_day")]
    timed = grid_layout.layout_day(events)

    return templates.TemplateResponse(
        "calendar_day.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "day",
            "today_iso": date.today().isoformat(),
            "day": day,
            "prev_day": (d - timedelta(days=1)).isoformat(),
            "next_day": (d + timedelta(days=1)).isoformat(),
            "all_day": all_day,
            "timed": timed,
            "tasks": tasks,
            "hours": list(range(grid_layout.GRID_HOURS)),
            "px_per_hour": grid_layout.PX_PER_HOUR,
            "calendars": db.list_calendars(conn),
            "hidden": hidden,
            "projects": db.list_projects(conn, include_archived=False),
            "project_groups": db.list_project_groups(conn),
            "active_project_uid": project_uid or "",
            "active_group_uid": group_uid or "",
        },
    )


@router.get("/agenda")
def agenda_view(
    request: Request,
    project_uid: str | None = None,
    group_uid: str | None = None,
    conn=Depends(get_db),
):
    today = date.today()
    window_end = today + timedelta(days=30)
    hidden = get_hidden_calendars(request)

    events = db.list_events(
        conn, start=today.isoformat(), end=window_end.isoformat() + "T23:59:59",
        exclude_calendars=list(hidden),
    )
    events = recurrence_expand.expand_events(events, today, window_end)
    events = _annotate_colors(events, _color_map(conn))

    cal_uids = _project_calendar_uids(conn, project_uid, group_uid)
    if cal_uids is not None:
        events = [e for e in events if e.get("calendar_path") in cal_uids]
    list_uids = _project_list_uids(conn, project_uid, group_uid)
    all_tasks = db.list_tasks(conn)
    if list_uids is not None:
        all_tasks = [t for t in all_tasks if t.get("list_path") in list_uids]
    tasks = [
        t
        for t in all_tasks
        if t.get("due_at") and today.isoformat() <= t["due_at"][:10] <= window_end.isoformat()
    ]

    by_day: dict[str, dict[str, list]] = {}
    for e in events:
        key = (e.get("start_at") or "")[:10]
        if not key:
            continue
        by_day.setdefault(key, {"events": [], "tasks": []})["events"].append(e)
    for t in tasks:
        key = t["due_at"][:10]
        by_day.setdefault(key, {"events": [], "tasks": []})["tasks"].append(t)

    days = []
    for key in sorted(by_day.keys()):
        days.append(
            {
                "date": date.fromisoformat(key),
                "iso": key,
                "is_today": key == today.isoformat(),
                "events": sorted(by_day[key]["events"], key=lambda e: e.get("start_at") or ""),
                "tasks": by_day[key]["tasks"],
            }
        )

    return templates.TemplateResponse(
        "calendar_agenda.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "agenda",
            "today_iso": today.isoformat(),
            "days": days,
            "window_end": window_end,
            "calendars": db.list_calendars(conn),
            "hidden": hidden,
            "projects": db.list_projects(conn, include_archived=False),
            "project_groups": db.list_project_groups(conn),
            "active_project_uid": project_uid or "",
            "active_group_uid": group_uid or "",
        },
    )


@events_router.get("/events/new")
def new_event_form(
    request: Request,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    end_date: str | None = None,
    conn=Depends(get_db),
):
    # `end_date` (no start_time/end_time) is the month-view click-and-hold
    # drag-to-create path (static/calendar_month.js) -- a day-granularity
    # range with no time-of-day at all, prefilled as an all-day event
    # spanning midnight-to-midnight. The existing `start_time`/`end_time`
    # path (Week/Day view's drag-to-create, static/calendar.js) still
    # takes priority when present, since that one's a same-day, specific
    # time range.
    prefill_all_day = False
    if date and end_date and not start_time and not end_time:
        prefill_start = f"{date}T00:00"
        prefill_end = f"{end_date}T23:59"
        prefill_all_day = True
    else:
        prefill_start = f"{date}T{start_time}" if date and start_time else (f"{date}T09:00" if date else None)
        prefill_end = f"{date}T{end_time}" if date and end_time else None
    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "active_tab": "calendar",
            "event": None,
            "prefill_start": prefill_start,
            "prefill_end": prefill_end,
            "prefill_all_day": prefill_all_day,
            "calendars": db.list_calendars(conn),
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@events_router.post("/events")
def create_event(
    title: str = Form(...),
    description: str = Form(""),
    start_at: str = Form(...),
    end_at: str = Form(""),
    all_day: str = Form(""),
    location: str = Form(""),
    meeting_url: str = Form(""),
    tags: str = Form(""),
    recurrence: str = Form(""),
    reminders: str = Form(""),
    calendar_uid: str = Form(db.DEFAULT_CALENDAR_UID),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at or None,
        "all_day": bool(all_day),
        "location": location or None,
        "meeting_url": meeting_url or None,
        "status": "active",
        "tags": _tags_list(tags),
        "recurrence": recurrence or None,
        "reminders": [int(m) for m in reminders.split(",") if m.strip().isdigit()],
        "calendar_path": calendar_uid,
        "created_at": now,
        "updated_at": now,
    }
    saved = bridge.save_event_row(row)
    db.upsert_event(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return RedirectResponse(url="/calendar", status_code=303)


@events_router.get("/events/{uid}/edit")
def edit_event_form(uid: str, request: Request, conn=Depends(get_db)):
    event = db.get_event(conn, uid)
    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "active_tab": "calendar",
            "event": event,
            "calendars": db.list_calendars(conn),
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@events_router.post("/events/{uid}")
def update_event(
    uid: str,
    title: str = Form(...),
    description: str = Form(""),
    start_at: str = Form(...),
    end_at: str = Form(""),
    all_day: str = Form(""),
    location: str = Form(""),
    meeting_url: str = Form(""),
    tags: str = Form(""),
    recurrence: str = Form(""),
    reminders: str = Form(""),
    calendar_uid: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    existing = db.get_event(conn, uid) or {}
    old_calendar_path = existing.get("calendar_path", db.DEFAULT_CALENDAR_UID)
    new_calendar_path = calendar_uid or old_calendar_path
    row = dict(existing)
    row.update(
        {
            "uid": uid,
            "title": title,
            "description": description,
            "start_at": start_at,
            "end_at": end_at or None,
            "all_day": bool(all_day),
            "location": location or None,
            "meeting_url": meeting_url or None,
            "tags": _tags_list(tags),
            "recurrence": recurrence or None,
            "reminders": [int(m) for m in reminders.split(",") if m.strip().isdigit()],
            "calendar_path": new_calendar_path,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if new_calendar_path != old_calendar_path:
        # Moving between calendars = different CalDAV collection = delete
        # from the old one, create fresh in the new one (same uid, so the
        # cache row and any external references by uid still make sense).
        bridge.delete_event(uid, old_calendar_path)
    saved = bridge.save_event_row(row)
    db.upsert_event(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return RedirectResponse(url="/calendar", status_code=303)


@events_router.post("/events/{uid}/delete")
def delete_event(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    existing = db.get_event(conn, uid)
    calendar_path = existing.get("calendar_path", db.DEFAULT_CALENDAR_UID) if existing else db.DEFAULT_CALENDAR_UID
    bridge.delete_event(uid, calendar_path)
    db.delete_event(conn, uid)
    return RedirectResponse(url="/calendar", status_code=303)


@events_router.post("/events/{uid}/reschedule")
async def reschedule_event(
    uid: str, request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)
):
    """JSON endpoint for the Week/Day grid's drag-to-move / drag-to-resize
    (see static/calendar.js) -- only touches start_at/end_at, leaves every
    other field alone. A plain form POST to /events/{uid} would also work
    but means round-tripping every field through JS for no reason; this is
    the minimal surface the drag interaction actually needs."""
    payload = await request.json()
    existing = db.get_event(conn, uid)
    if existing is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = dict(existing)
    row["start_at"] = payload["start_at"]
    row["end_at"] = payload.get("end_at")
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    saved = bridge.save_event_row(row)
    db.upsert_event(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return JSONResponse({"ok": True, "start_at": saved.get("start_at"), "end_at": saved.get("end_at")})
