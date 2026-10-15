"""Tasks, habits, completions and work sessions.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from .. import habit_heatmap

from .core import ENTITY_SYNC_FIELDS, _hours_between, _row_columns, _row_to_dict, get_app_meta, set_app_meta, set_field_hlc
from .labels import _attach_tags, _attach_tags_bulk, _reject_multiple_project_labels, list_object_ids_for_label, set_object_labels
from .pages import banner_for_object
from .events import _EVENT_JSON_FIELDS, delete_event, get_event, upsert_event


def set_task_habit_look(conn: sqlite3.Connection, uid: str, icon: str | None, color: str | None) -> None:
    """A habit's icon and colour -- see the tasks.habit_icon
        column comment. Callers validate the names; blank = default.
    """
    conn.execute(
        "UPDATE tasks SET habit_icon = ?, habit_color = ? WHERE uid = ?", (icon or None, color or None, uid)
    )
    conn.commit()


# --------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------- #

_TASK_JSON_FIELDS: tuple[str, ...] = ()


_TASK_DONE_STATUSES = ("done", "archived")


def upsert_task(
    conn: sqlite3.Connection, row: dict[str, Any], *, record_server_write: bool = True
) -> None:
    from .sync import record_server_sync_write
    data = dict(row)
    if record_server_write:
        previous = _row_columns(conn, "tasks", str(data.get("uid")), _TASK_SYNC_COLUMNS)
    tags = data.pop("tags", None)
    # Validated before anything is written (not just before set_object_labels
    # further down) so a rejected label set never leaves a partial write --
    # the task row's other columns and its labels are kept consistent by
    # never touching either on a rejected call.
    if tags is not None:
        _reject_multiple_project_labels(conn, tags)
    existing_status = conn.execute("SELECT status FROM tasks WHERE uid = ?", (data.get("uid"),)).fetchone()
    was_done = bool(existing_status and existing_status["status"] in _TASK_DONE_STATUSES)
    now_done = data.get("status") in _TASK_DONE_STATUSES
    if now_done and not was_done:
        data["completed_at"] = datetime.now(timezone.utc).isoformat()
    elif not now_done:
        data["completed_at"] = None
    else:
        # Still done, was already done (e.g. editing title while status
        # stays "done") -- leave the existing completed_at exactly alone
        # rather than re-stamping "now" on every unrelated edit.
        prev = conn.execute("SELECT completed_at FROM tasks WHERE uid = ?", (data.get("uid"),)).fetchone()
        data["completed_at"] = prev["completed_at"] if prev else None
    # timeline_lane is deliberately NOT in this column list -- same
    # "upsert never touches it, only a dedicated setter does" pattern as
    # schedule_classes.project_uid (see set_task_timeline_lane below).
    # Every existing caller of upsert_task builds its row from
    # `dict(existing)` first (routers/tasks.py's update_task/update_field/
    # complete_task), so omitting it here just means those callers' own
    # unrelated edits can never accidentally clobber a manual timeline
    # placement to NULL -- there'd be no way to *un*-clobber it via the
    # round-trip pattern if it were in this list and a caller ever forgot
    # to carry it through.
    # NOT NULL DEFAULT 0 columns -- same coercion upsert_event already does
    # for its own holiday-policy columns, see that function's comment.
    data["exclude_saturday"] = 1 if data.get("exclude_saturday") else 0
    data["exclude_sunday"] = 1 if data.get("exclude_sunday") else 0
    cols = [
        "uid", "title", "description",
        "start_at", "due_at", "status", "progress",
        "recurrence", "completed_at", "created_at", "updated_at",
        "target_per_day", "habits_per_period", "habit_unit", "habit_kind",
        "holiday_calendar", "exclude_saturday", "exclude_sunday",
    ]
    values = [(data.get(c) if c != "target_per_day" else (data.get(c) or 1)) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "task", data["uid"], tags)
    # 1.4 (Work allocations, § Task & calendar semantics): "editing the task
    # updates the representation of its associated work allocations where
    # appropriate" -- keep every linked work-allocation event's title equal
    # to the task's current title. Cheap no-op when the task has none (the
    # UPDATE's subquery matches zero rows) and idempotent when the title
    # didn't actually change, so this runs unconditionally rather than
    # diffing old vs. new title first.
    if data.get("title") is not None:
        sync_work_allocation_titles(conn, data["uid"], data["title"])
    if record_server_write:
        record_server_sync_write(
            conn,
            "task",
            data["uid"],
            previous,
            _row_columns(conn, "tasks", data["uid"], _TASK_SYNC_COLUMNS),
        )
    conn.commit()
    if now_done and not was_done:
        from .. import clock, finance
        finance.post_for_task(conn, data["uid"], clock.today().isoformat())


def delete_task(
    conn: sqlite3.Connection, uid: str, *, record_server_write: bool = True
) -> None:
    from .sync import record_server_delete
    if record_server_write:
        record_server_delete(conn, "task", uid)
    from .. import finance
    finance.unlink_task(conn, uid)
    conn.execute("DELETE FROM tasks WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'task' AND object_id = ?", (uid,))
    # Mirror of delete_event's relation cleanup -- the linked event survives,
    # only this task's rows go.
    conn.execute("DELETE FROM event_task_relations WHERE task_uid = ?", (uid,))
    # Habits H6: a habit's own pauses go with it (all-habit pauses stay).
    conn.execute("DELETE FROM habit_pauses WHERE task_uid = ?", (uid,))
    conn.commit()


def delete_completed_tasks(conn: sqlite3.Connection) -> int:
    """Settings' "Purge completed" -- every task with
        status done/archived, deleted the same way a single delete_task
        would (object_labels cascade included), just looped. Doesn't touch
        task_checklist_items/task_completions for those tasks -- same gap
        delete_task already has for a single task, not something this purge
        action should silently start cleaning up on its own. Returns the
        count deleted, so the caller can report what actually happened.
    """
    rows = conn.execute("SELECT uid FROM tasks WHERE status IN ('done', 'archived')").fetchall()
    for row in rows:
        delete_task(conn, row["uid"])
    return len(rows)


def delete_old_completed_tasks(conn: sqlite3.Connection, days: int) -> int:
    """"Auto-archive completed tasks" --
        the automatic, age-based sibling of delete_completed_tasks above:
        deletes every done/archived task whose `completed_at` is older than
        `days`, instead of every completed task regardless of age. Same
        per-task delete_task() cascade (object_labels included, task_checklist
        _items/task_completions not -- identical gap, see
        delete_completed_tasks' own docstring).

        A task can be done/archived with `completed_at` NULL -- e.g. one
        whose status was set directly in the database, or synced in from
        somewhere that predates this column -- deliberately excluded here
        rather than treated as "infinitely old" and swept up immediately;
        an unknown completion date is a reason to leave a task alone, not
        delete it. `days <= 0` is a no-op (routers/tasks.py's lazy caller
        only invokes this when the Settings > Advanced preference is a
        positive number -- "Never" stores 0/empty and never reaches this at
        all -- but this function stays a safe no-op either way, not relying
        on the caller alone to enforce that).
    """
    if days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT uid FROM tasks WHERE status IN ('done', 'archived') AND completed_at IS NOT NULL AND completed_at < ?",
        (cutoff,),
    ).fetchall()
    for row in rows:
        delete_task(conn, row["uid"])
    return len(rows)


def get_task(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE uid = ?", (uid,)).fetchone()
    return _attach_tags(conn, "task", _row_to_dict(row, _TASK_JSON_FIELDS)) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    status: str | None = None,
    q: str | None = None,
    include_habit_tasks: bool = False,
) -> list[dict[str, Any]]:
    """`include_habit_tasks` defaults False -- a task carrying the configured habit label
        (task_habit_settings.habit_label) is meant to live *only* on Tasks >
        Habits, not the normal Table/Timeline/Board/Calendar/dashboard-widget
        views this function backs almost everywhere in the app. Every one of
        those call sites gets the exclusion for free without needing its own
        change; the two callers that genuinely need every task regardless
        (routers/tasks.py's own habits_view, and export.py's full backup) pass
        True explicitly.
    """
    query = "SELECT * FROM tasks"
    params: list[str] = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("title LIKE ?")
        params.append(f"%{q}%")
    if not include_habit_tasks:
        habit_label = get_task_habit_settings(conn)["habit_label"]
        excluded_uids = list_object_ids_for_label(conn, "task", habit_label)
        if excluded_uids:
            placeholders = ", ".join("?" for _ in excluded_uids)
            clauses.append(f"uid NOT IN ({placeholders})")
            params.extend(excluded_uids)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    # Importance/Urgency used to sort here before that whole feature was
    # removed outright -- see src/derived_state.py's module docstring.
    query += " ORDER BY (due_at IS NULL), due_at ASC"
    rows = conn.execute(query, params).fetchall()
    return _attach_tags_bulk(conn, "task", [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows])


def list_habit_tasks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The mirror image of list_tasks' default exclusion -- every task
    carrying the configured habit label, for Tasks > Habits itself."""
    habit_label = get_task_habit_settings(conn)["habit_label"]
    uids = list_object_ids_for_label(conn, "task", habit_label)
    if not uids:
        return []
    placeholders = ", ".join("?" for _ in uids)
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE uid IN ({placeholders}) ORDER BY title COLLATE NOCASE", uids
    ).fetchall()
    return _attach_tags_bulk(conn, "task", [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows])


def all_task_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM tasks").fetchall()}


def set_task_timeline_lane(conn: sqlite3.Connection, uid: str, lane: int | None) -> None:
    """Explicit setter for a task's manual Timeline row placement -- see
    the `tasks.timeline_lane` column comment in init_schema. Pass None to
    clear it (falls back to auto-packing, timeline_layout.py's
    assign_swimlanes). Not folded into upsert_task's own column list, same
    "a dedicated setter, not a field an ordinary save can clobber"
    convention as every other setter in this file (see upsert_task's own
    comment on why timeline_lane is deliberately excluded there)."""
    conn.execute("UPDATE tasks SET timeline_lane = ? WHERE uid = ?", (lane, uid))
    conn.commit()


def normalize_reminder_time(value: str | None) -> str | None:
    """"H:MM"/"HH:MM" (24h) -> "HH:MM"; blank or unparseable -> None."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def set_task_reminder_time(conn: sqlite3.Connection, uid: str, value: str | None) -> None:
    """A habit's own reminder time -- see the tasks.reminder_time
        column comment. Dedicated setter, same reason as set_task_timeline_lane:
        an ordinary save (or a CalDAV sync) must not be able to clear it.
    """
    conn.execute("UPDATE tasks SET reminder_time = ? WHERE uid = ?", (normalize_reminder_time(value), uid))
    conn.commit()


def add_event_task_relation(
    conn: sqlite3.Connection, event_uid: str, task_uid: str, is_work_allocation: int = 0
) -> None:
    """Idempotent link insert (composite PK means a duplicate is a no-op) --
    the caller is responsible for the "must share a label" rule (the UI's
    picker enforces it, the routers re-check it defensively); the DB itself
    doesn't -- same "constraint lives in the app layer" convention as every
    other table in this file. `is_work_allocation` defaults to 0 (an
    ordinary Relations-card link, this function's original purpose) --
    routers/export.py's restore path is the one caller that passes a
    backed-up row's real value through, so a work allocation round-trips
    through a JSON backup as one instead of silently downgrading to a plain
    relation."""
    conn.execute(
        "INSERT OR IGNORE INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
        "VALUES (?, ?, ?, ?)",
        (event_uid, task_uid, datetime.now(timezone.utc).isoformat(), int(is_work_allocation)),
    )
    conn.commit()


def remove_event_task_relation(conn: sqlite3.Connection, event_uid: str, task_uid: str) -> None:
    conn.execute(
        "DELETE FROM event_task_relations WHERE event_uid = ? AND task_uid = ?",
        (event_uid, task_uid),
    )
    conn.commit()


def list_event_task_relations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM event_task_relations ORDER BY created_at").fetchall()]


def restore_work_session_fields(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Re-apply a backed-up relation row's work session fields (hours, difficulty, own title)."""
    if not row.get("is_work_allocation"):
        return
    conn.execute(
        "UPDATE event_task_relations SET hours_estimate = ?, difficulty = ?, own_title = ? "
        "WHERE event_uid = ? AND task_uid = ?",
        (row.get("hours_estimate"), row.get("difficulty"), int(row.get("own_title") or 0), row["event_uid"], row["task_uid"]),
    )
    conn.commit()


def related_tasks_for_event(conn: sqlite3.Connection, event_uid: str) -> list[dict[str, Any]]:
    """Every task currently linked to `event_uid`, ordered the same way
    list_tasks orders (undated last, then due date -- importance/urgency
    are computed, not SQL-orderable columns, see list_tasks' own comment)
    so a Relations card's list reads like every other task list in the
    app."""
    rows = conn.execute(
        "SELECT tasks.* FROM tasks JOIN event_task_relations r ON r.task_uid = tasks.uid "
        "WHERE r.event_uid = ? ORDER BY (tasks.due_at IS NULL), tasks.due_at ASC",
        (event_uid,),
    ).fetchall()
    return _attach_tags_bulk(conn, "task", [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows])


def related_events_for_task(conn: sqlite3.Connection, task_uid: str) -> list[dict[str, Any]]:
    """Every event currently linked to `task_uid`, ordered by start time."""
    rows = conn.execute(
        "SELECT events.* FROM events JOIN event_task_relations r ON r.event_uid = events.uid "
        "WHERE r.task_uid = ? ORDER BY events.start_at ASC",
        (task_uid,),
    ).fetchall()
    return _attach_tags_bulk(conn, "event", [_row_to_dict(r, _EVENT_JSON_FIELDS) for r in rows])


def create_work_allocation(
    conn: sqlite3.Connection, task_uid: str, start_at: str | None = None, end_at: str | None = None
) -> str:
    """Schedule a block of work on `task_uid`: a plain event titled after
    the task (kept in sync by upsert_task, see below) and inheriting the
    task's labels, linked back with `is_work_allocation=1`. Returns the new
    event's uid. Placing a task into "as many [calendar periods] as
    necessary keeps every allocation associated with the same task" -- so
    this is called once per block; calling it again for the same task just
    creates another independent event/relation pair, exactly as the spec
    describes for a task split across multiple sessions.

    Either both of `start_at`/`end_at` or neither may be given. A
    start/end pair schedules the block (renders on calendars, counts toward
    `db.task_work_hours`'s `scheduled`). Omitting both creates an
    UNSCHEDULED session placeholder -- no date yet, so the task still
    appears on the planning grids' "Unscheduled work" panel and the session
    is placed onto a real slot by dragging it there (see
    `set_work_allocation_times`/`first_undated_work_allocation_for_task`);
    this is what the task modal's Work sessions "+" button creates."""
    import uuid

    task = get_task(conn, task_uid)
    if task is None:
        raise ValueError(f"no such task: {task_uid}")
    now = datetime.now(timezone.utc).isoformat()
    event_uid = str(uuid.uuid4())
    upsert_event(
        conn,
        {
            "uid": event_uid,
            "title": task["title"],
            "description": "",
            "start_at": start_at,
            "end_at": end_at,
            "all_day": False,
            "status": "active",
            "tags": task.get("tags") or [],
            "created_at": now,
            "updated_at": now,
        },
    )
    conn.execute(
        "INSERT OR IGNORE INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
        "VALUES (?, ?, ?, 1)",
        (event_uid, task_uid, now),
    )
    record_work_allocation_flag(conn, event_uid)
    conn.commit()
    return event_uid


def list_work_allocations_for_task(conn: sqlite3.Connection, task_uid: str) -> list[dict[str, Any]]:
    """Every scheduled work block for `task_uid` -- the work-allocation-only
    counterpart to related_events_for_task above (which returns ordinary
    Relations-card links too). Ordered by creation time (not start time), so
    the Work sessions card's "Session 1/2/3" numbering stays the stable
    order sessions were added in and an undated session (start_at NULL, a
    "+"-added placeholder) keeps its position once it's placed later."""
    rows = conn.execute(
        "SELECT events.*, r.hours_estimate AS hours_estimate, r.difficulty AS difficulty, r.own_title AS own_title "
        "FROM events JOIN event_task_relations r ON r.event_uid = events.uid "
        "WHERE r.task_uid = ? AND r.is_work_allocation = 1 ORDER BY events.created_at ASC, events.uid ASC",
        (task_uid,),
    ).fetchall()
    return _attach_tags_bulk(conn, "event", [_row_to_dict(r, _EVENT_JSON_FIELDS) for r in rows])


def update_work_session(
    conn: sqlite3.Connection, task_uid: str, event_uid: str, *, title: str, hours_estimate, difficulty: str | None
) -> bool:
    """Save a session's own title, hours estimate and difficulty.

    A blank title hands the title back to the task (it follows task renames
    again); any other title is the session's own and survives them. Returns
    False when `event_uid` is not one of this task's work sessions."""
    from .. import work_sessions

    if work_allocation_task_uid(conn, event_uid) != task_uid:
        return False
    task = get_task(conn, task_uid)
    event = get_event(conn, event_uid)
    if task is None or event is None:
        return False
    title = (title or "").strip()
    own = int(bool(title) and title != task["title"])
    event = dict(event)
    event["title"] = title if own else task["title"]
    event["updated_at"] = datetime.now(timezone.utc).isoformat()
    upsert_event(conn, event)
    conn.execute(
        "UPDATE event_task_relations SET hours_estimate = ?, difficulty = ?, own_title = ? "
        "WHERE event_uid = ? AND task_uid = ?",
        (work_sessions.parse_hours(hours_estimate), work_sessions.normalize_difficulty(difficulty), own, event_uid, task_uid),
    )
    conn.commit()
    return True


def sync_work_sessions(conn: sqlite3.Connection, task_uid: str, rows: list[dict[str, Any]]) -> None:
    """Make the task's work sessions match the edit form's rows.

    Each row is {uid, title, hours, difficulty, start, end}. A blank uid is a
    new session; a stored session missing from `rows` is deleted. A blank
    start and end leaves the session undated; a half-filled or inverted pair
    leaves its current times alone."""
    kept = {r["uid"] for r in rows if r.get("uid")}
    stored = {wa["uid"]: wa for wa in list_work_allocations_for_task(conn, task_uid)}
    for uid in stored:
        if uid not in kept:
            delete_work_allocation(conn, uid)
    for row in rows:
        uid = row.get("uid") or ""
        if uid not in stored:
            uid = create_work_allocation(conn, task_uid)
            stored[uid] = {"start_at": None}
        update_work_session(
            conn, task_uid, uid, title=row.get("title", ""), hours_estimate=row.get("hours", ""), difficulty=row.get("difficulty")
        )
        start, end = row.get("start") or "", row.get("end") or ""
        if start and end:
            set_work_allocation_times(conn, uid, start, end)
        elif not start and not end and stored[uid].get("start_at"):
            unschedule_work_allocation(conn, uid)


def work_allocation_task_uid(conn: sqlite3.Connection, event_uid: str) -> str | None:
    """If `event_uid` is a work-allocation event, its task's uid; otherwise
    None. Used to redirect a title edit on the event back onto the task --
    see routers/calendar.py's update_event."""
    row = conn.execute(
        "SELECT task_uid FROM event_task_relations WHERE event_uid = ? AND is_work_allocation = 1",
        (event_uid,),
    ).fetchone()
    return row["task_uid"] if row else None


def work_allocation_event_uids(conn: sqlite3.Connection) -> set[str]:
    """Every event uid that is a work-allocation block, in one query -- the
    bulk counterpart to work_allocation_task_uid, for a page (e.g. Month)
    that needs to exclude every work-allocation event from a list it
    already fetched via db.list_events, without an N+1 per-event lookup."""
    rows = conn.execute("SELECT event_uid FROM event_task_relations WHERE is_work_allocation = 1").fetchall()
    return {row["event_uid"] for row in rows}


def delete_work_allocation(conn: sqlite3.Connection, event_uid: str) -> None:
    """"Deleting a work allocation removes only that scheduled block -- not
    the task. The user is removing planned working time, not the underlying
    work." delete_event already only ever cascades the event's own rows
    (object_labels, event_task_relations WHERE event_uid=...), never
    touches `tasks` -- so this is delete_event under a name that states the
    1.4 semantics explicitly at the call site."""
    delete_event(conn, event_uid)


def first_undated_work_allocation_for_task(conn: sqlite3.Connection, task_uid: str) -> dict[str, Any] | None:
    """The task's oldest work-allocation session that has no start/end yet
    (a "+"-added session placeholder awaiting placement on a planning grid),
    or None. `list_work_allocations_for_task` is creation-ordered, so the
    first undated one is the session a grid drop should place next."""
    for wa in list_work_allocations_for_task(conn, task_uid):
        if not wa.get("start_at"):
            return wa
    return None


def set_work_allocation_times(conn: sqlite3.Connection, event_uid: str, start_at: str, end_at: str) -> bool:
    """Give an existing work-allocation session its scheduled start/end --
    the "place this session" half of a session created undated from the task
    modal's Work sessions card (create_work_allocation with no dates). Only
    a real work allocation may be moved (work_allocation_task_uid guard, the
    same idiom the routers' move_allocation endpoints use); returns False if
    it isn't one or the range is invalid, otherwise updates the event and
    returns True."""
    if not start_at or not end_at or end_at <= start_at:
        return False
    if not work_allocation_task_uid(conn, event_uid):
        return False
    existing = get_event(conn, event_uid)
    if existing is None:
        return False
    row = dict(existing)
    row["start_at"] = start_at
    row["end_at"] = end_at
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    upsert_event(conn, row)
    return True


def unschedule_work_allocation(conn: sqlite3.Connection, event_uid: str) -> bool:
    """The inverse of `set_work_allocation_times`: clear an existing work-
        allocation session's start/end back to undated instead of deleting the
        session outright. This is what "unschedule" means for the planning
        grids' block interactions (drag a block back onto the "Unscheduled
        work" panel, or its own delete button) -- the block comes off the
        calendar, but the session itself is still there, now back on the panel
        as an unplaced session, exactly like a "+"-added placeholder. Only a real work allocation may be unscheduled (`work_allocation_
        task_uid` guard, same idiom `set_work_allocation_times` uses); returns
        False if it isn't one or the event doesn't exist.
    """
    if not work_allocation_task_uid(conn, event_uid):
        return False
    existing = get_event(conn, event_uid)
    if existing is None:
        return False
    row = dict(existing)
    row["start_at"] = None
    row["end_at"] = None
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    upsert_event(conn, row)
    return True


def work_allocation_panel_info(conn: sqlite3.Connection, task_uid: str) -> dict[str, Any]:
    """Summary the planning grids' "Unscheduled work" panel needs for one
        task (week_view/timetable_view/project_calendar build the same item
        shape): session count plus the scheduled/total hours shown next to the
        title. `scheduled_hours` is the sum of dated session durations (the
        same number db.task_work_hours reports as `scheduled`); `total_hours`
        adds one default hour per undated session -- an undated session has no
        duration yet, so its planned contribution counts as the default 1-hour
        block it becomes when placed on a grid (project_calendar.js's
        DEFAULT_BLOCK_MINUTES), which makes the x/y read "hours on the calendar
        out of hours planned". `undated_count` is the number of sessions still
        awaiting placement -- the panel's "still unscheduled" rule needs it, and it's what separates the panel summary from
        task_work_hours.
    """
    allocations = list_work_allocations_for_task(conn, task_uid)
    scheduled = sum(_hours_between(a.get("start_at"), a.get("end_at")) for a in allocations)
    undated = sum(1 for a in allocations if not a.get("start_at"))
    return {
        "count": len(allocations),
        "scheduled_hours": scheduled,
        "total_hours": scheduled + undated,
        "undated_count": undated,
    }


def habit_work_sessions_status(
    conn: sqlite3.Connection, task_uid: str, recurrence: str | None, period_start: str, period_end: str
) -> dict[str, Any]:
    """Unscheduled-work visibility for a habit-tracked recurring task,
        scoped to `period_start`/`period_end` (ISO dates, inclusive) --
        routers/calendar.py's week_view picks the period per the habit's own
        cadence (the displayed week for daily/weekly, that week's calendar
        month for monthly/anything else) and passes it in here rather than
        this function guessing at "which week" from the task alone.
    """
    allocations = list_work_allocations_for_task(conn, task_uid)
    dated_in_period = sum(
        1 for a in allocations if a.get("start_at") and period_start <= a["start_at"][:10] <= period_end
    )
    undated = sum(1 for a in allocations if not a.get("start_at"))
    required = 7 if habit_heatmap.recurrence_frequency(recurrence) == "daily" else 1
    return {
        "dated_in_period": dated_in_period,
        "undated_count": undated,
        "required": required,
        "needed": max(0, required - dated_in_period - undated),
    }


def remove_latest_work_allocation(conn: sqlite3.Connection, task_uid: str) -> str | None:
    """Remove the task's most recently added UNDATED work session -- the
    last still-undated one in `list_work_allocations_for_task`'s creation
    order, the "Unscheduled work" panel "−" button's undo of its own "+".
    Deliberately ignores dated (already-scheduled) sessions even if one of
    those is more recently created -- the panel's count is now "sessions
    still needing placement" (`work_allocation_panel_info`'s
    `undated_count`), so "−" must only ever touch that same pool; it must
    never silently delete an already-scheduled calendar block just because
    it happened to be the most recent thing created. Returns the removed
    event's uid, or None if the task has no undated sessions to remove
    (also None for a task that doesn't exist -- get_task guard, same as
    create_work_allocation). The task itself, and every dated session, are
    never touched."""
    if get_task(conn, task_uid) is None:
        return None
    undated = [wa for wa in list_work_allocations_for_task(conn, task_uid) if not wa.get("start_at")]
    if not undated:
        return None
    uid = undated[-1]["uid"]
    delete_event(conn, uid)
    return uid


def task_work_hours(conn: sqlite3.Connection, task_uid: str) -> dict[str, float]:
    """"The estimated work of a task is calculated from its actual calendar
    allocations... Total planned work is therefore the sum of the task's
    work blocks" -- `scheduled` is that sum; `completed` is the portion
    already in the past ("the application retains enough information to
    distinguish scheduled work from completed work"). A work-allocation
    event has no independent "done" flag -- whether the work happened is
    read off the clock, same as any other calendar event."""
    now = datetime.now(timezone.utc).isoformat()
    allocations = list_work_allocations_for_task(conn, task_uid)
    scheduled = sum(_hours_between(a.get("start_at"), a.get("end_at")) for a in allocations)
    completed = sum(
        _hours_between(a.get("start_at"), a.get("end_at"))
        for a in allocations
        if a.get("end_at") and a["end_at"] <= now
    )
    return {"scheduled": scheduled, "completed": completed, "remaining": max(scheduled - completed, 0.0)}


def task_work_hours_bulk(conn: sqlite3.Connection, task_uids: list[str]) -> dict[str, dict[str, float]]:
    """Batch counterpart to `task_work_hours` above -- one query for every
        task in `task_uids` instead of one `list_work_allocations_for_task`
        query per task. Added for the 1.5 "deadline vs. work allocation"
        surfacing slice: the global
        Tasks table and the project detail Tasks view both render every visible
        row's scheduled/completed hours, and calling the per-task function in a
        template loop would be a straightforward N+1 (one row -> one query) on
        any list beyond a handful of tasks. There was no existing "aggregate X
        across many tasks in one query" precedent in this module to follow
        (`_project_card`'s `progress` counts an already-fetched Python list, not
        a SQL aggregate) -- this is the first one, and `task_work_hours` itself
        is left untouched (same return shape, same semantics) so single-task
        call sites (task detail/edit modals) are unaffected.

        Returns a dict keyed by task_uid, every value the same
        `{"scheduled", "completed", "remaining"}` shape `task_work_hours`
        returns -- including a zero-filled entry for a task with no allocations
        at all, so callers never need an `if task_uid in result` branch.
    """
    result = {uid: {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0} for uid in task_uids}
    if not task_uids:
        return result
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in task_uids)
    rows = conn.execute(
        f"SELECT r.task_uid AS task_uid, events.start_at AS start_at, events.end_at AS end_at "
        f"FROM events JOIN event_task_relations r ON r.event_uid = events.uid "
        f"WHERE r.is_work_allocation = 1 AND r.task_uid IN ({placeholders})",
        tuple(task_uids),
    ).fetchall()
    for row in rows:
        uid = row["task_uid"]
        hours = _hours_between(row["start_at"], row["end_at"])
        result[uid]["scheduled"] += hours
        if row["end_at"] and row["end_at"] <= now:
            result[uid]["completed"] += hours
    for uid, hours in result.items():
        hours["remaining"] = max(hours["scheduled"] - hours["completed"], 0.0)
    return result


def sync_work_allocation_titles(conn: sqlite3.Connection, task_uid: str, title: str) -> None:
    """"Editing the task updates the representation of its associated work
    allocations where appropriate" -- called from upsert_task whenever a
    task's title changes, so every linked work-allocation event's title
    stays the task's title rather than drifting into an independent name.
    Ordinary Relations-linked events (is_work_allocation=0) are untouched --
    only a work allocation's title is owned by its task."""
    conn.execute(
        "UPDATE events SET title = ?, updated_at = ? WHERE uid IN ("
        "SELECT event_uid FROM event_task_relations WHERE task_uid = ? AND is_work_allocation = 1 AND own_title = 0)",
        (title, datetime.now(timezone.utc).isoformat(), task_uid),
    )


def list_tasks_sharing_labels(conn: sqlite3.Connection, label_names: list[str]) -> list[dict[str, Any]]:
    """Every non-habit task carrying at least one of `label_names` -- the
    "link an existing task" pool for an event's Relations card. Mirrors
    list_tasks' default habit-task exclusion (a habit task is hidden from
    every non-Habits view, so it shouldn't surface as a link candidate
    here either) and the same label-membership test every label filter in
    this app uses (object_labels membership, case-sensitive on the stored
    name)."""
    labels = [n for n in (label_names or []) if n]
    if not labels:
        return []
    habit_label = get_task_habit_settings(conn)["habit_label"]
    placeholders = ", ".join("?" for _ in labels)
    rows = conn.execute(
        f"SELECT tasks.* FROM tasks "
        f"WHERE tasks.uid IN (SELECT DISTINCT object_id FROM object_labels "
        f"  WHERE object_type = 'task' AND label_name IN ({placeholders}) "
        f"  AND object_id NOT IN (SELECT object_id FROM object_labels "
        f"    WHERE object_type = 'task' AND label_name = ?)) "
        f"ORDER BY tasks.title COLLATE NOCASE",
        (*labels, habit_label),
    ).fetchall()
    return _attach_tags_bulk(conn, "task", [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows])


def _search_tasks(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    task_status: str | None,
    task_due_on: str | None,
    excluded: set[str],
    include_habit_tasks: bool,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM tasks"
    params: list[str] = []
    clauses: list[str] = []

    if q:
        like = f"%{q}%"
        # Labels match through object_labels membership so "find a task with
        # a label called X" and "find a task whose title is X" are one box.
        clauses.append(
            "(title LIKE ? OR description LIKE ? OR uid IN (SELECT object_id FROM object_labels "
            "WHERE object_type = 'task' AND label_name LIKE ?))"
        )
        params.extend([like, like, like])
    if task_status:
        clauses.append("status = ?")
        params.append(task_status)
    if task_due_on:
        clauses.append("due_at = ?")
        params.append(task_due_on)
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'task' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)
    if not include_habit_tasks:
        habit_label = get_task_habit_settings(conn)["habit_label"]
        excluded_uids = list_object_ids_for_label(conn, "task", habit_label)
        if excluded_uids:
            placeholders = ", ".join("?" for _ in excluded_uids)
            clauses.append(f"uid NOT IN ({placeholders})")
            params.extend(excluded_uids)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    # Importance/Urgency used to sort here before that whole feature was
    # removed outright -- see src/derived_state.py's module docstring.
    query += " ORDER BY (due_at IS NULL), due_at ASC"
    rows = conn.execute(query, params).fetchall()
    dicts = _attach_tags_bulk(conn, "task", [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows])
    out: list[dict[str, Any]] = []
    for d in dicts:
        out.append(
            {
                "type": "task",
                "uid": d["uid"],
                "title": d["title"],
                "subtitle": f"Due {d['due_at'][:10]}" if d.get("due_at") else "No due date",
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


def delete_checklist_items_for_task(conn: sqlite3.Connection, task_uid: str) -> None:
    """Called when a task is deleted -- see routers/tasks.py's delete_task.
    Without this, a re-created task that happened to reuse the same uid
    (never actually possible, uids are uuid4) is the only scenario that'd
    resurrect stale rows, but it's cheap correctness hygiene regardless --
    an orphaned checklist row pointing at a task_uid that no longer exists
    in `tasks` serves no purpose."""
    conn.execute("DELETE FROM task_checklist_items WHERE task_uid = ?", (task_uid,))
    conn.commit()


def get_task_habit_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM task_habit_settings WHERE id = 1").fetchone()
    if row is None:
        return {"habit_label": "Habit"}
    return dict(row)


def save_task_habit_settings(conn: sqlite3.Connection, habit_label: str) -> None:
    conn.execute(
        "INSERT INTO task_habit_settings (id, habit_label) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET habit_label=excluded.habit_label",
        (habit_label.strip() or "Habit",),
    )
    conn.commit()


def upsert_task_completion(
    conn: sqlite3.Connection,
    task_uid: str,
    due_date: str,
    completed_at: str,
    value: float = 1,
    note: str | None = None,
) -> None:
    """Records (or updates) that a recurring task was completed on `due_date`
        -- the row that feeds its heatmap/streak. `completed_at` is when the
        check-off actually happened (usually today), `due_date` the pattern's
        day being checked off. `value` is only meaningful for a
        habit-labeled task with target_per_day > 1 -- every other caller
        (the plain recurring-task complete_task path) leaves it at the
        default 1, same as before this column existed.

        `note`: None leaves an existing note alone (a
        check-in or +1 never wipes what you wrote); "" clears it.
    """
    conn.execute(
        "INSERT INTO task_completions (task_uid, due_date, completed_at, value, note) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(task_uid, due_date) DO UPDATE SET completed_at=excluded.completed_at, value=excluded.value, "
        "note=COALESCE(excluded.note, task_completions.note)",
        (task_uid, due_date, completed_at, value, note),
    )
    conn.commit()


def add_habit_pause(
    conn: sqlite3.Connection, uid: str, task_uid: str | None, start_date: str, end_date: str, created_at: str
) -> None:
    """Habits H6: pause one habit (`task_uid`) or all (None), inclusive."""
    conn.execute(
        "INSERT INTO habit_pauses (uid, task_uid, start_date, end_date, created_at) VALUES (?, ?, ?, ?, ?)",
        (uid, task_uid, start_date, end_date, created_at),
    )
    conn.commit()


def list_habit_pauses(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM habit_pauses ORDER BY start_date, end_date").fetchall()
    return [dict(r) for r in rows]


def delete_habit_pause(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM habit_pauses WHERE uid = ?", (uid,))
    conn.commit()


def delete_task_completion(conn: sqlite3.Connection, task_uid: str, due_date: str) -> None:
    conn.execute("DELETE FROM task_completions WHERE task_uid = ? AND due_date = ?", (task_uid, due_date))
    conn.commit()


def get_task_completion(conn: sqlite3.Connection, task_uid: str, due_date: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM task_completions WHERE task_uid = ? AND due_date = ?", (task_uid, due_date)
    ).fetchone()
    return dict(row) if row else None


def list_task_completions(conn: sqlite3.Connection, task_uid: str | None = None) -> list[dict[str, Any]]:
    """All completion rows, optionally scoped to one task. The backup
    (export.data.json) round-trips the whole table; the tasks page scopes
    to a single recurring task's history."""
    if task_uid is None:
        rows = conn.execute("SELECT * FROM task_completions ORDER BY task_uid, due_date ASC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM task_completions WHERE task_uid = ? ORDER BY due_date ASC", (task_uid,)
        ).fetchall()
    return [dict(r) for r in rows]


def banner_for_task(conn: sqlite3.Connection, task: dict[str, Any]) -> dict[str, Any] | None:
    """Thin, name-preserving wrapper over `banner_for_object` for task's
        two pre-existing consumers (task_detail.html's cover, project_detail.
    """
    return banner_for_object(conn, "task", task)


def record_work_allocation_flag(
    conn: sqlite3.Connection, event_uid: str, *, hlc: tuple[int, int, str] | None = None
) -> None:
    """Records a work-allocation event's `is_work_allocation` sync flag into
    field_versions, so a device's pull can deliver it. The flag is not an
    `events` column -- it lives in `event_task_relations.is_work_allocation`
    (see create_work_allocation) -- so record_server_sync_write's plain
    column diff can never see it; it gets its own field_versions entry
    here. The value itself is never stored: offline_sync.pull() reads it
    back from the relation table (offline_sync._current_field_value's
    special case), exactly as the deleted-at-tombstone value is synthesized
    rather than stored. Only ever recorded for work allocations -- a
    regular event has no flag entry, and a pull simply never mentions it,
    which the mirror reads as "not a work allocation." `hlc` lets a caller
    seed with a known clock value instead of minting one."""
    from .sync import bump_sync_data_version, mint_server_hlc
    if hlc is None:
        hlc = mint_server_hlc(conn)
    set_field_hlc(conn, "event", event_uid, "is_work_allocation", hlc)
    bump_sync_data_version(conn)


# The sync-whitelist columns for each entity, as a fixed ORDERED list --
# the diff/read substrate for the server-as-author recording above (a
# stable ordering keeps the generated SELECTs deterministic).
_TASK_SYNC_COLUMNS = sorted(ENTITY_SYNC_FIELDS["task"])


_WORK_ALLOCATION_FLAGS_BACKFILLED_KEY = "sync_work_allocation_flags_backfilled"


def backfill_work_allocation_flags(conn: sqlite3.Connection) -> None:
    """One-time: records an `is_work_allocation` field_versions entry for
    every pre-existing work-allocation event (an event_task_relations row
    with is_work_allocation=1), so a device's pull -- which only ever
    learns the flag through field_versions -- sees pre-existing scheduled
    work sessions as work allocations in its local mirror. `INSERT OR
    IGNORE` (field_versions' primary key is entity_type+entity_uid+
    field_name) means a field a device has already synced keeps its own
    HLC untouched, same contract as backfill_server_sync_writes. Only the
    =1 rows get an entry: a relation with is_work_allocation=0 is an
    ordinary task/event link, and a regular event having *no* flag entry
    is exactly what a pull expects to mean "not a work allocation."
    Idempotent via its own app_meta marker, and only bumps the data
    version when something was actually inserted (so a device's round-skip
    pre-check notices the new flags)."""
    from .sync import bump_sync_data_version, mint_server_hlc
    if get_app_meta(conn, _WORK_ALLOCATION_FLAGS_BACKFILLED_KEY):
        return
    hlc = mint_server_hlc(conn)
    inserted = 0
    rows = conn.execute(
        "SELECT event_uid FROM event_task_relations WHERE is_work_allocation = 1"
    ).fetchall()
    for (event_uid,) in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO field_versions "
            "(entity_type, entity_uid, field_name, hlc_physical, hlc_logical, hlc_device_id) "
            "VALUES ('event', ?, 'is_work_allocation', ?, ?, ?)",
            (event_uid, hlc[0], hlc[1], hlc[2]),
        )
        inserted += cur.rowcount
    set_app_meta(conn, _WORK_ALLOCATION_FLAGS_BACKFILLED_KEY, "1")
    if inserted:
        bump_sync_data_version(conn)


def set_task_completed_at(conn: sqlite3.Connection, uid: str, completed_at: str | None) -> None:
    """Writes a task's completion time as is, for a backup restore (upsert_task derives it from the status change)."""
    conn.execute("UPDATE tasks SET completed_at = ? WHERE uid = ?", (completed_at, uid))
    conn.commit()
