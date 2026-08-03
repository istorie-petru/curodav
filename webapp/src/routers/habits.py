"""Habit tracking (Phase 6 of the projects/tags rework, but a standalone
feature otherwise -- see db.py's `habits`/`habit_entries` CREATE TABLE
comments for the storage rationale). Entirely local, same category as
projects/tags -- no CalDAV/CardDAV equivalent.

Three things this router owns:
  1. Manage/list page (`/habits`) -- create/archive/delete, mini heatmap
     preview per habit.
  2. Detail page (`/habits/{uid}`) -- full heatmap, current/longest streak,
     a backfill form for entering exact past data.
  3. The heatmap itself (`_heatmap_weeks`) -- a GitHub-style calendar grid
     built server-side as plain HTML (each day cell is a tiny <form>
     posting a toggle), not a canvas/JS widget, so it works with no JS and
     the "easy editing" requirement (click a day) is a single request with
     no client-side state to keep in sync.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db, templates

router = APIRouter(prefix="/habits", tags=["habits"])

COLORS = ["blue", "green", "orange", "red", "purple", "pink", "gray", "yellow"]

# How many weeks the full detail-page heatmap shows vs. the compact
# preview on the list page -- 53 weeks is "a bit over a year" (the extra
# partial week is whatever's needed to complete the grid from a Monday),
# matching the GitHub contribution graph's convention. The list page's
# preview is deliberately much shorter (12 weeks, ~3 months) since it's
# one of possibly several habits shown at once.
DETAIL_WEEKS = 53
PREVIEW_WEEKS = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _heatmap_weeks(entries_by_date: dict[str, float], target: float, weeks: int, today: date | None = None) -> list[list[dict]]:
    """Builds a Monday-aligned grid of `weeks` columns x 7 day-rows ending
    on `today` (real date.today() by default; a fixed value is accepted
    purely so tests are deterministic instead of depending on the clock).
    Each cell carries enough to both paint and act as a toggle target:
    `date` (ISO string, used as both the form action and a stable dict
    key), `level` (0-4 color-intensity bucket, or -1 for a future day that
    should render blank/non-interactive since there's nothing to log yet),
    and `month_label` (only set on the first Monday of a month, so the
    header row can print month names without repeating them every
    column)."""
    today = today or date.today()
    start = today - timedelta(days=weeks * 7 - 1)
    start -= timedelta(days=start.weekday())  # snap back to the preceding Monday

    days = []
    d = start
    while d <= today:
        days.append(d)
        d += timedelta(days=1)
    while len(days) % 7 != 0:
        days.append(days[-1] + timedelta(days=1))

    result: list[list[dict]] = []
    for week_start in range(0, len(days), 7):
        col = []
        for day in days[week_start : week_start + 7]:
            iso = day.isoformat()
            is_future = day > today
            value = entries_by_date.get(iso, 0)
            if is_future:
                level = -1
            elif value <= 0:
                level = 0
            elif target and target > 0:
                ratio = value / target
                level = 4 if ratio >= 1 else 3 if ratio >= 0.66 else 2 if ratio >= 0.33 else 1
            else:
                level = 4  # no meaningful target (e.g. 0) -- any logged value is "full"
            col.append(
                {
                    "date": iso,
                    "value": value,
                    "level": level,
                    "is_future": is_future,
                    "weekday": day.weekday(),
                    "month_label": day.strftime("%b") if day.day <= 7 and day.weekday() == 0 else None,
                }
            )
        result.append(col)
    return result


def _streaks(entries_by_date: dict[str, float], today: date | None = None) -> tuple[int, int]:
    """(current_streak, longest_streak) in days, counting any day with a
    logged value > 0 as "done" -- target_per_day only affects heatmap
    color, not whether a day counts at all (a habit tracker that required
    hitting the exact target to keep a streak alive would punish e.g.
    "read 8/10 pages" as a broken streak, which isn't the intent). Current
    streak tolerates today itself not being logged yet (you haven't lost
    your streak just because it's 9am and you haven't meditated yet) but
    breaks the moment a full calendar day is skipped."""
    today = today or date.today()
    done_dates = sorted(d for d, v in entries_by_date.items() if v and v > 0)
    if not done_dates:
        return 0, 0
    done_set = set(done_dates)

    longest = current_run = 0
    prev: date | None = None
    for d_str in done_dates:
        d = date.fromisoformat(d_str)
        current_run = current_run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, current_run)
        prev = d

    cursor = today
    if cursor.isoformat() not in done_set:
        cursor -= timedelta(days=1)
    current = 0
    while cursor.isoformat() in done_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


@router.get("")
def list_habits(request: Request, conn=Depends(get_db)):
    habits = db.list_habits(conn)
    cards = []
    for h in habits:
        entries = db.habit_entries_by_date(conn, h["uid"])
        current, longest = _streaks(entries)
        cards.append(
            {
                "habit": h,
                "weeks": _heatmap_weeks(entries, h["target_per_day"], PREVIEW_WEEKS),
                "current_streak": current,
                "longest_streak": longest,
            }
        )
    return templates.TemplateResponse(
        "habits_list.html",
        {"request": request, "active_tab": "habits", "settings_tab": "habits", "cards": cards},
    )


@router.get("/new")
def new_habit_form(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "habit_form.html",
        {
            "request": request,
            "active_tab": "habits",
            "habit": None,
            "colors": COLORS,
            "projects": db.list_projects(conn),
            "tag_names": db.list_tag_names_in_use(conn),
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
    project_uid: str = Form(""),
    conn=Depends(get_db),
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/habits", status_code=303)
    now = _now()
    tag_list = _tags_list(tags)
    db.upsert_habit(
        conn,
        {
            "uid": str(uuid.uuid4()),
            "name": name,
            "description": description,
            "color": color,
            "icon": icon.strip() or None,
            "target_per_day": float(target_per_day) if target_per_day else 1.0,
            "tags": tag_list,
            "project_uid": project_uid or None,
            "created_at": now,
            "updated_at": now,
        },
    )
    db.ensure_tags_registered(conn, tag_list)
    return RedirectResponse(url="/habits", status_code=303)


@router.get("/{uid}/edit")
def edit_habit_form(uid: str, request: Request, conn=Depends(get_db)):
    habit = db.get_habit(conn, uid)
    return templates.TemplateResponse(
        "habit_form.html",
        {
            "request": request,
            "active_tab": "habits",
            "habit": habit,
            "colors": COLORS,
            "projects": db.list_projects(conn),
            "tag_names": db.list_tag_names_in_use(conn),
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
    project_uid: str = Form(""),
    conn=Depends(get_db),
):
    existing = db.get_habit(conn, uid)
    if existing is None:
        return RedirectResponse(url="/habits", status_code=303)
    tag_list = _tags_list(tags)
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
            "updated_at": _now(),
        }
    )
    db.upsert_habit(conn, row)
    db.ensure_tags_registered(conn, tag_list)
    return RedirectResponse(url=f"/habits/{uid}", status_code=303)


@router.post("/{uid}/archive")
def archive_habit(uid: str, conn=Depends(get_db)):
    db.archive_habit(conn, uid, _now())
    return RedirectResponse(url="/habits", status_code=303)


@router.post("/{uid}/unarchive")
def unarchive_habit(uid: str, conn=Depends(get_db)):
    db.unarchive_habit(conn, uid)
    return RedirectResponse(url="/habits", status_code=303)


@router.post("/{uid}/delete")
def delete_habit(uid: str, conn=Depends(get_db)):
    db.delete_habit(conn, uid)
    return RedirectResponse(url="/habits", status_code=303)


@router.get("/{uid}")
def habit_detail(uid: str, request: Request, conn=Depends(get_db)):
    habit = db.get_habit(conn, uid)
    ctx = {"request": request, "active_tab": "habits", "habit": habit, "today": date.today().isoformat()}
    if habit:
        entries = db.habit_entries_by_date(conn, uid)
        current, longest = _streaks(entries)
        total_logged = len([v for v in entries.values() if v > 0])
        ctx.update(
            {
                "weeks": _heatmap_weeks(entries, habit["target_per_day"], DETAIL_WEEKS),
                "current_streak": current,
                "longest_streak": longest,
                "total_logged": total_logged,
                "project": db.get_project(conn, habit["project_uid"]) if habit.get("project_uid") else None,
            }
        )
    return templates.TemplateResponse("habit_detail.html", ctx)


@router.post("/{uid}/entries/{entry_date}/toggle")
def toggle_entry(uid: str, entry_date: str, request: Request, conn=Depends(get_db)):
    db.toggle_habit_entry(conn, uid, entry_date, _now())
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
    if parsed_value <= 0:
        db.delete_habit_entry(conn, uid, entry_date)
    else:
        db.upsert_habit_entry(conn, uid, entry_date, parsed_value, note or None, _now())
    referer = request.headers.get("referer")
    return RedirectResponse(url=referer or f"/habits/{uid}", status_code=303)


@router.post("/{uid}/entries/{entry_date}/delete")
def delete_entry(uid: str, entry_date: str, conn=Depends(get_db)):
    db.delete_habit_entry(conn, uid, entry_date)
    return RedirectResponse(url=f"/habits/{uid}", status_code=303)
