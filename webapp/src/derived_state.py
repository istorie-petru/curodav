"""Virtual & derived states (1.1, plans/open-priority.md § Virtual & derived
states): the shared, deterministic derivation of a task's temporal
virtual-state membership (Today / Tomorrow / This Week / This Month /
Overdue).

Everything here is pure -- no DB connection, no request -- so every surface
(Tasks Table filters, Dashboard widgets, label pages, WebDAV export/import)
computes the same answer without re-implementing the date math.

The Importance/Urgency axes this module used to derive (label-rule-based,
1.1) were removed outright (no longer a feature the app offers -- was: two
independent 1..3 axes, `effective importance = label-derived`, `effective
urgency = max(label-derived, temporal)`, surfaced as the `important`/`urgent`
virtual states, the Dashboard's "Important & Urgent" widget and At a Glance
stat blocks, the Organize Today widget's "Urgent, unscheduled" section, the
task detail read-only meta row, and the iCal/CSV export PRIORITY/Importance/
Urgency columns). `label_config.importance`/`urgency_threshold_days` stay
physically on disk, unused, same "never force-drop old data" convention as
every other removed column in db.py.

The virtual states this derives (`Today` / `Tomorrow` / `This Week` /
`This Month` / `Overdue`) are query projections, not labels -- see
routers/tasks.py's DATE_FILTERS for where they surface as filters.
"""

from __future__ import annotations

from datetime import date


def _due_date(task: dict) -> date | None:
    raw = task.get("due_at")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------- #
# Aggregation -- the one place per-state membership / counts are computed.
# Every surface (Dashboard widgets, label pages) reads these rather than
# re-implementing the date math; tasks.py's `_apply_date_filter` is built
# on the same `virtual_states` predicate so a count on the Dashboard and a
# filter on the Tasks page can never disagree.
# --------------------------------------------------------------------- #


def virtual_states(task: dict, today: date | None = None) -> set[str]:
    """The set of virtual-state names a task currently belongs to, computed
    purely from its due date -- never stored, never labels. State names
    match the filter values in routers/tasks.py's DATE_FILTERS."""
    if today is None:
        today = date.today()
    states = set()
    due = _due_date(task)
    if due is not None:
        delta = (due - today).days
        if delta < 0:
            states.add("overdue")
        if delta == 0:
            states.add("today")
        if delta == 1:
            states.add("tomorrow")
        if 0 <= delta <= 6:
            states.add("this_week")
        if due.year == today.year and due.month == today.month:
            states.add("this_month")
    return states


def count_by_state(tasks: list[dict], today: date | None = None) -> dict[str, int]:
    """One pass over a task list producing the per-state counts every
    surface needs (overdue / today / tomorrow / this_week / this_month).
    State names match routers/tasks.py's DATE_FILTERS, so
    `count_by_state(...)["overdue"]` is the same set of tasks the Tasks
    page's date filter shows. A task counts toward every state it belongs
    to (overdue *and* this_week etc.), matching how the filters
    independently project rather than partition."""
    if today is None:
        today = date.today()
    counts = {name: 0 for name in ("overdue", "today", "tomorrow", "this_week", "this_month")}
    for task in tasks:
        for name in virtual_states(task, today):
            counts[name] += 1
    return counts
