"""Virtual & derived states (1.1, plans/open-priority.md § Virtual & derived
states): the shared, deterministic derivation of a task's Importance / Urgency
effective values and its virtual-state membership.

Everything here is pure -- no DB connection, no request -- so every surface
(Tasks Table/Board/Timeline filters, Dashboard widgets, label pages, WebDAV
export/import) computes the same answer without re-implementing the math.
Callers resolve label rules once (db.effective_label_config_ci per tag) and
pass a {label_name: cfg} mapping in; this module never touches the database.

Values are 1..3 on each axis (higher = more important / more urgent), with 0
meaning "none". A later rework (post-1.1 side work) removed the per-task
*explicit* axes entirely -- there is no manual "set this task's importance/
urgency" input anywhere in the app anymore. The effective value is now
derived purely from label-based rules and temporal state, using
max-precedence: `effective importance = label-derived`, `effective urgency =
max(label-derived, temporal)`. Nothing derived is ever stored. The one
persistent exception is the label config rules themselves
(`label_config.importance`/`urgency_threshold_days`) -- configured once per
label, not per task -- which live in the DB as real columns; see db.py's
`label_config` comment.

The virtual states this derives (`Important`, `Urgent`, and the temporal
`Today` / `Tomorrow` / `This Week` / `This Month` / `Overdue`) are query
projections, not labels -- see routers/tasks.py's DATE_FILTERS (the
temporal ones) and IMPORTANCE_FILTERS/URGENCY_FILTERS/STATUS_FILTERS
(Important/Urgent/Overdue, moved there by the Tasks page filter cleanup,
2026-08-15) for where they surface as filters.
"""

from __future__ import annotations

from datetime import date

# The two axes share a 1..3 scale, deliberately. 1 = Low, 2 = Medium,
# 3 = High on each; 0 = none/unset. Kept as named constants so callers and
# tests never scatter magic numbers.
IMPORTANCE_LOW = 1
IMPORTANCE_MEDIUM = 2
IMPORTANCE_HIGH = 3

URGENCY_LOW = 1
URGENCY_MEDIUM = 2
URGENCY_HIGH = 3

# Display labels (mirror of tasks.py's old PRIORITY_LABELS, now two axes).
IMPORTANCE_LABELS = {1: "Low", 2: "Medium", 3: "High"}
URGENCY_LABELS = {1: "Low", 2: "Medium", 3: "High"}

# The effective-value cutoff at which an entity counts as `Important` /
# `Urgent` -- the derived states the plan says every surface should expose.
IMPORTANT_THRESHOLD = IMPORTANCE_HIGH
URGENT_THRESHOLD = URGENCY_HIGH


def _task_tags(task: dict) -> list[str]:
    return [tag for tag in (task.get("tags") or []) if tag]


def label_rules_for(task: dict, label_rules: dict) -> list[dict]:
    """The resolved label-config dict for every label this task carries.
    `label_rules` maps label name -> effective config (see
    db.effective_label_config_ci); a tag with no entry contributes nothing."""
    return [label_rules.get(tag) or {} for tag in _task_tags(task)]


def _max_int(values: list) -> int:
    return max((int(v or 0) for v in values), default=0)


def effective_importance(task: dict, label_rules: dict) -> int:
    """Deterministic effective importance = label-derived only (no manual
    per-task input, see this module's docstring). Returns 0..3 (0 = no
    importance anywhere -- correct for a task carrying no importance-rule
    label, not a gap to fill)."""
    return _max_int(rule.get("importance") for rule in label_rules_for(task, label_rules))


def _due_date(task: dict) -> date | None:
    raw = task.get("due_at")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _days_until(task: dict, today: date) -> int | None:
    due = _due_date(task)
    return (due - today).days if due is not None else None


def _label_urgency(rules: list[dict], task: dict, today: date) -> int:
    """A label implies urgency (URGENCY_HIGH) once its carrying entity's date
    is within the label's `urgency_threshold_days` window -- e.g. the
    `Conference` label implies urgency when the event is within one week or
    one month, per the plan. Only labels that configure a positive threshold
    contribute; an entity with no due date can never be label-urgent."""
    days = _days_until(task, today)
    if days is None:
        return 0
    best = 0
    for rule in rules:
        try:
            threshold = int(rule.get("urgency_threshold_days"))
        except (TypeError, ValueError):
            threshold = None
        if threshold is not None and days <= threshold:
            best = max(best, URGENCY_HIGH)
    return best


def _temporal_urgency(task: dict, today: date) -> int:
    """The time-remaining component: overdue or due today is URGENCY_HIGH
    (it must happen now), due tomorrow is URGENCY_MEDIUM, everything else
    contributes nothing on this axis. Conservative by design -- the label
    threshold rule above is the primary "time remaining" mechanism (it is
    configurable per label), and this plain rule keeps the `Urgent` state
    from silently collapsing into "every task with a due date is urgent"."""
    days = _days_until(task, today)
    if days is None:
        return 0
    if days <= 0:
        return URGENCY_HIGH
    if days == 1:
        return URGENCY_MEDIUM
    return 0


def effective_urgency(task: dict, label_rules: dict, today: date | None = None) -> int:
    """Deterministic effective urgency = max(label-derived, temporal) (no
    manual per-task input, see this module's docstring). Returns 0..3.
    `today` defaults to the current date; callers that need a fixed
    reference date (tests, dashboard "as of" views) pass their own."""
    if today is None:
        today = date.today()
    rules = label_rules_for(task, label_rules)
    return max(_label_urgency(rules, task, today), _temporal_urgency(task, today))


def is_important(task: dict, label_rules: dict) -> bool:
    return effective_importance(task, label_rules) >= IMPORTANT_THRESHOLD


def is_urgent(task: dict, label_rules: dict, today: date | None = None) -> bool:
    return effective_urgency(task, label_rules, today) >= URGENT_THRESHOLD


# --------------------------------------------------------------------- #
# Aggregation -- the one place per-state membership / counts are computed.
# Every surface (Dashboard widgets, Today, Week, label pages) reads these
# rather than re-implementing the date/derived math; tasks.py's
# `_apply_date_filter` is built on the same `virtual_states` predicate so a
# count on the Dashboard and a filter on the Tasks page can never disagree.
# --------------------------------------------------------------------- #


def virtual_states(task: dict, label_rules: dict, today: date | None = None) -> set[str]:
    """The set of virtual-state names a task currently belongs to, computed
    purely from current data (dates + derived importance/urgency) -- never
    stored, never labels. State names match the filter values in
    routers/tasks.py -- the temporal ones in DATE_FILTERS, `important` in
    IMPORTANCE_FILTERS, `urgent` in URGENCY_FILTERS, `overdue` in
    STATUS_FILTERS (Tasks page filter cleanup, 2026-08-15) -- so a count
    here links 1:1 to a filter there."""
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
    if is_important(task, label_rules):
        states.add("important")
    if is_urgent(task, label_rules, today):
        states.add("urgent")
    return states


def count_by_state(tasks: list[dict], label_rules: dict, today: date | None = None) -> dict[str, int]:
    """One pass over a task list producing the per-state counts every
    surface needs (overdue / today / tomorrow / this_week / this_month /
    important / urgent). State names match routers/tasks.py's filter
    values (see virtual_states' docstring for exactly which dropdown each
    lives in since the 2026-08-15 Tasks page filter cleanup), so
    `count_by_state(...)["overdue"]` is the same set of tasks the Tasks
    page's `status_filter=overdue` shows. A task counts toward every state
    it belongs to (overdue *and* important etc.), matching how the filters
    AND -- each is an independent projection, not a partition."""
    if today is None:
        today = date.today()
    counts = {name: 0 for name in ("overdue", "today", "tomorrow", "this_week", "this_month", "important", "urgent")}
    for task in tasks:
        for name in virtual_states(task, label_rules, today):
            counts[name] += 1
    return counts
