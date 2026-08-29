"""Habit tracking (Phase 6 of the projects/tags rework, but a standalone
feature otherwise -- see db.py's `habits`/`habit_entries` CREATE TABLE
comments for the storage rationale). Entirely local, same category as
projects/tags -- no CalDAV/CardDAV equivalent.

2026-08-28 "major rework" session (item 2, "Merge Habits into the Tasks
table"): the standalone manage/list page (`GET /habits`) is retired to a
redirect -- every Habit entity now renders as a row in the Tasks table's
own Habits group instead (routers/tasks.py's _habit_group_items/
_build_task_groups). Presentation-only: nothing below this docstring
changed except `list_habits`/`habits_regions`'s `region=list` branch (both
only ever backed that one retired page) -- create/edit/archive/unarchive/
delete/entries/toggle are exactly as before, and the Dashboard's own habit
check-in widget (`_render_habit_checkin`) still calls them unchanged.

Two things this router still owns:
  1. Detail page (`/habits/{uid}`) -- full heatmap, current/longest streak,
     a backfill form for entering exact past data. Reached from the Tasks
     table's Habits group row now, not a list page.
  2. The heatmap itself (`_heatmap_weeks`) -- a GitHub-style calendar grid
     built server-side as plain HTML (each day cell is a tiny <form>
     posting a toggle), not a canvas/JS widget, so it works with no JS and
     the "easy editing" requirement (click a day) is a single request with
     no client-side state to keep in sync.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db
from ..deps import get_db, respond, templates, wants_json
from .. import habit_heatmap
from . import dashboard as dashboard_router
from .labels import COLORS, ICON_GROUPS, LABEL_ICONS

router = APIRouter(prefix="/habits", tags=["habits"])

# 2026-08-08: imported directly from routers/labels.py rather than a
# second hand-copied literal -- this used to be its own identical 8-entry
# list with a comment pointing out it was "identical to routers/labels
# .py's own COLORS," which is exactly the kind of duplication that drifts
# the moment one of the two copies gets edited and the other doesn't (see
# this same file's ICON_GROUPS/LABEL_ICONS import just below, already
# solving the equivalent problem for icons). One list, two importers.
#
# Same curated icon-sprite set routers/labels.py already offers for a
# label/project's icon (modal-input-design Phase C, swatch-grid revival) --
# a habit's icon used to be a free-typed emoji glyph; reusing this list
# (grouped, same as labels -- 2026-08-08) rather than inventing a
# habit-specific one keeps "which icons exist, and how they're grouped" a
# single source of truth.
ICONS = LABEL_ICONS

# How many weeks the full detail-page heatmap shows -- moved to
# habit_heatmap.py (2026-08-29) so routers/tasks.py's habit-task detail
# modal can share the exact same "full year" window instead of its own
# much-narrower default (see that constant's own docstring for why: a
# narrower window left visible empty space in the modal). Re-exported under
# the old name here so every existing reference in this file/its tests is
# unchanged. PREVIEW_WEEKS (the list page's shorter compact preview) is gone
# with the list page itself (2026-08-28 "major rework" session, item 2).
DETAIL_WEEKS = habit_heatmap.DETAIL_WEEKS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _heatmap_weeks(entries_by_date: dict[str, float], target: float, weeks: int, today: date | None = None) -> list[list[dict]]:
    """Thin wrapper -- the actual logic moved to ../habit_heatmap.py
    (2026-08-08) so routers/tasks.py's own habits_view (Tasks > Habits)
    can share it without a circular import (routers/labels.py imports
    from routers/tasks.py, which would otherwise need to import this
    module, which imports from routers/labels.py for LABEL_ICONS). Kept
    under its old name/signature here so every existing call site in this
    file is unchanged."""
    return habit_heatmap.heatmap_weeks(entries_by_date, target, weeks, today)


def _streaks(
    entries_by_date: dict[str, float], today: date | None = None, excluded_dates: set[str] | None = None
) -> tuple[int, int]:
    """Thin wrapper -- see _heatmap_weeks above."""
    return habit_heatmap.streaks(entries_by_date, today, excluded_dates)


def _excluded_dates_for_habit(
    conn, habit: dict, entries_by_date: dict[str, float], today: date
) -> set[str]:
    """2026-08-29 (STATE.md backlog item 3): a habit's own holiday_calendar/
    exclude_saturday/exclude_sunday policy (see db.py's `habits` CREATE
    TABLE comment), resolved into the concrete set of ISO dates
    habit_heatmap.streaks should treat as non-working. Scanned from the
    earliest logged entry (or today, for a brand-new habit with none yet)
    through today -- bounded to two years back so a habit with policy set
    but no entries for a long time doesn't force an unbounded day-by-day
    scan. Cheap no-op (empty set, no DB read) when the habit has no policy
    at all, same short-circuit `excluded_dates_in_range` itself has."""
    if not (habit.get("holiday_calendar") or habit.get("exclude_saturday") or habit.get("exclude_sunday")):
        return set()
    logged = [date.fromisoformat(d) for d in entries_by_date if d]
    start = min(logged) if logged else today
    start = max(start, today - timedelta(days=730))
    holiday_calendars = db.list_holidays_by_calendar(conn)
    return habit_heatmap.excluded_dates_in_range(habit, holiday_calendars, start, today)


@router.get("")
def list_habits_redirect():
    """The standalone Habits list page is retired (2026-08-28 "major
    rework" session, item 2: "Merge Habits into the Tasks table") -- every
    standalone Habit entity now renders as a row in the Table view's own
    Habits group instead (routers/tasks.py's _habit_group_items/
    _build_task_groups), alongside habit-labeled tasks. Redirect rather
    than a bare 404, same "any bookmark still lands somewhere real"
    precedent `/projects`'s own retirement established. `_habits_cards`/
    habits_list.html/_habits_body.html are gone with it; every mutation
    endpoint below (create/edit/archive/unarchive/delete/entries/toggle)
    is untouched -- this was presentation-only, per the session brief's own
    "not a deletion of habit semantics" instruction."""
    return RedirectResponse(url="/tasks", status_code=302)


def _habit_detail_context(conn, request: Request, uid: str) -> dict:
    habit = db.get_habit(conn, uid)
    ctx = {"request": request, "active_tab": "habits", "habit": habit, "today": date.today().isoformat()}
    if habit:
        entries = db.habit_entries_by_date(conn, uid)
        excluded = _excluded_dates_for_habit(conn, habit, entries, date.today())
        current, longest = _streaks(entries, excluded_dates=excluded)
        total_logged = len([v for v in entries.values() if v > 0])
        ctx.update(
            {
                "weeks": _heatmap_weeks(entries, habit["target_per_day"], DETAIL_WEEKS),
                "current_streak": current,
                "longest_streak": longest,
                "total_logged": total_logged,
                "project": db.effective_label_config(conn, habit["project_uid"]) if habit.get("project_uid") else None,
            }
        )
    return ctx


@router.get("/regions")
def habits_regions(
    request: Request,
    region: str = "detail",
    uid: str = "",
    conn=Depends(get_db),
):
    """Async-CRUD region fragment (features/async-crud.md) -- `region=detail`
    (with uid) renders the #habit-detail-body div shared with
    habit_detail.html, so refreshRegion() can swap it in place after a
    mutation instead of a full reload. `region=list` is gone (2026-08-28
    "major rework" session, item 2) along with habits_list.html/
    _habits_body.html -- the list page it backed is retired."""
    if region == "detail":
        ctx = _habit_detail_context(conn, request, uid)
        html = templates.env.get_template("_habit_detail_body.html").render(ctx)
        return HTMLResponse(html)
    return JSONResponse({"error": f"unknown region '{region}'"}, status_code=400)


@router.get("/new")
def new_habit_form(request: Request, conn=Depends(get_db)):
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "habit_form.html",
        {
            "request": request,
            "active_tab": "habits",
            "habit": None,
            "colors": COLORS,
            "icons": ICONS,
            "icon_groups": ICON_GROUPS,
            "projects": [l for l in db.list_labels(conn) if not l.get("generate_space")],
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            # 2026-08-29 (STATE.md backlog item 3) -- feeds the same
            # holiday-calendar dropdown _event_form_fields.html uses.
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
        },
    )


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


@router.post("")
def create_habit(
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form("blue"),
    icon: str = Form(""),
    target_per_day: str = Form("1"),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    project_uid: str = Form(""),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    name = name.strip()
    if not name:
        return respond(x_requested_with, "/tasks")
    # Defensively coerced -- same reasoning as routers/tasks.py's
    # create_task's own start_at comment: every pre-existing direct caller
    # of this function (this suite's tests) predates these three fields
    # entirely, so their FastAPI Form(...) defaults would otherwise be the
    # literal marker object here, not a real string.
    if not isinstance(holiday_calendar, str):
        holiday_calendar = ""
    if not isinstance(exclude_saturday, str):
        exclude_saturday = ""
    if not isinstance(exclude_sunday, str):
        exclude_sunday = ""
    now = _now()
    tag_list = _tags_list(dashboard_router._combine_tags(tags, tags_labels))
    uid = str(uuid.uuid4())
    db.upsert_habit(
        conn,
        {
            "uid": uid,
            "name": name,
            "description": description,
            "color": color,
            "icon": icon.strip() or None,
            "target_per_day": float(target_per_day) if target_per_day else 1.0,
            "tags": tag_list,
            "project_uid": project_uid or None,
            # 2026-08-29 (STATE.md backlog item 3) -- see the `habits`
            # CREATE TABLE comment.
            "holiday_calendar": holiday_calendar or None,
            "exclude_saturday": exclude_saturday in ("1", "true", "on"),
            "exclude_sunday": exclude_sunday in ("1", "true", "on"),
            "created_at": now,
            "updated_at": now,
        },
    )
    return respond(x_requested_with, "/tasks", status_code=201, uid=uid)


@router.get("/{uid}/edit")
def edit_habit_form(uid: str, request: Request, conn=Depends(get_db)):
    habit = db.get_habit(conn, uid)
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "habit_form.html",
        {
            "request": request,
            "active_tab": "habits",
            "habit": habit,
            "colors": COLORS,
            "icons": ICONS,
            "icon_groups": ICON_GROUPS,
            "projects": [l for l in db.list_labels(conn) if not l.get("generate_space")],
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
        },
    )


@router.post("/{uid}/edit")
def edit_habit(
    uid: str,
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form("blue"),
    icon: str = Form(""),
    target_per_day: str = Form("1"),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    project_uid: str = Form(""),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    existing = db.get_habit(conn, uid)
    if existing is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "habit not found"}, status_code=404)
        return RedirectResponse(url="/habits", status_code=303)
    # Defensively coerced -- see create_habit's own comment.
    if not isinstance(holiday_calendar, str):
        holiday_calendar = ""
    if not isinstance(exclude_saturday, str):
        exclude_saturday = ""
    if not isinstance(exclude_sunday, str):
        exclude_sunday = ""
    tag_list = _tags_list(dashboard_router._combine_tags(tags, tags_labels))
    row = dict(existing)
    row.update(
        {
            "name": name.strip() or existing["name"],
            "description": description,
            "color": color,
            "icon": icon.strip() or None,
            "target_per_day": float(target_per_day) if target_per_day else 1.0,
            "tags": tag_list,
            "project_uid": project_uid or None,
            # 2026-08-29 (STATE.md backlog item 3) -- see create_habit.
            "holiday_calendar": holiday_calendar or None,
            "exclude_saturday": exclude_saturday in ("1", "true", "on"),
            "exclude_sunday": exclude_sunday in ("1", "true", "on"),
            "updated_at": _now(),
        }
    )
    db.upsert_habit(conn, row)
    return respond(x_requested_with, f"/habits/{uid}")


@router.post("/{uid}/archive")
def archive_habit(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.archive_habit(conn, uid, _now())
    return respond(x_requested_with, "/tasks")


@router.post("/{uid}/unarchive")
def unarchive_habit(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.unarchive_habit(conn, uid)
    return respond(x_requested_with, "/tasks")


@router.post("/{uid}/delete")
def delete_habit(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.delete_habit(conn, uid)
    return respond(x_requested_with, "/tasks")


@router.get("/{uid}")
def habit_detail(uid: str, request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("habit_detail.html", _habit_detail_context(conn, request, uid))


@router.post("/{uid}/entries/{entry_date}/toggle")
def toggle_entry(
    uid: str,
    entry_date: str,
    request: Request,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.toggle_habit_entry(conn, uid, entry_date, _now())
    if wants_json(x_requested_with):
        return JSONResponse({"ok": True})
    # Heatmap cells are plain forms (no JS) -- redirect straight back to
    # wherever the click came from (list preview or detail page) so a
    # click from the list page's mini heatmap doesn't bounce you to the
    # full detail page just to register one day.
    referer = request.headers.get("referer")
    return RedirectResponse(url=referer or f"/habits/{uid}", status_code=303)


@router.post("/{uid}/entries")
def add_entry(
    uid: str,
    request: Request,
    entry_date: str = Form(...),
    value: str = Form("1"),
    note: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """The explicit backfill form on the detail page -- lets you enter an
    exact value for any date (not just toggle 0/1), the "ability to add
    past data" the feature request called out specifically. Also reused
    (2026-08-01) by the Dashboard's habit check-in widget for a quantity
    habit's "+1" button, submitting today's date and the pre-computed
    next value -- referer-aware redirect (same as toggle_entry above) is
    what makes that work without bouncing a dashboard click over to the
    habit's own detail page just to register it."""
    try:
        parsed_value = float(value) if value else 1.0
    except ValueError:
        parsed_value = 1.0
    # 2026-08-28 follow-up ("direct number input" for the Habits group's
    # check-in cell, routers/tasks.py's set_task_completion carries the
    # same clamp/comment) -- server-side mirror of the input's own
    # `max="999999"`, which is advisory only.
    if parsed_value > 999999:
        parsed_value = 999999
    if parsed_value <= 0:
        db.delete_habit_entry(conn, uid, entry_date)
    else:
        db.upsert_habit_entry(conn, uid, entry_date, parsed_value, note or None, _now())
    if wants_json(x_requested_with):
        return JSONResponse({"ok": True})
    referer = request.headers.get("referer")
    return RedirectResponse(url=referer or f"/habits/{uid}", status_code=303)


@router.post("/{uid}/entries/{entry_date}/delete")
def delete_entry(uid: str, entry_date: str, conn=Depends(get_db)):
    db.delete_habit_entry(conn, uid, entry_date)
    return RedirectResponse(url=f"/habits/{uid}", status_code=303)
