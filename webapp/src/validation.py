"""Server-side checks for task and event input, so a direct post cannot store what the forms would refuse.

Each check returns None when the input is fine, or {"field", "message"}, the
structured shape the modal turns into a toast.
"""

from __future__ import annotations

from datetime import date, datetime

TITLE_MAX = 300


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _moment(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if "T" in value else datetime.combine(date.fromisoformat(value), datetime.min.time())
    except ValueError:
        return None


def _title_error(title) -> dict | None:
    text = _text(title)
    if not text:
        return {"field": "title", "message": "Title is required"}
    if len(text) > TITLE_MAX:
        return {"field": "title", "message": f"Title is too long (at most {TITLE_MAX} characters)"}
    return None


def _date_error(field: str, label: str, value) -> dict | None:
    text = _text(value)
    if text and _moment(text) is None:
        return {"field": field, "message": f"{label} is not a valid date"}
    return None


def _order_error(field: str, label: str, first, second) -> dict | None:
    a, b = _moment(_text(first)), _moment(_text(second))
    if a and b and b < a:
        return {"field": field, "message": label}
    return None


def task_error(title, start_at, due_at, status, statuses) -> dict | None:
    """The first problem with a task's title, dates or status."""
    if status is not None and isinstance(status, str) and status and status not in statuses:
        return {"field": "status", "message": "Status is not one of the available choices"}
    return (
        _title_error(title)
        or _date_error("start_at", "Start date", start_at)
        or _date_error("due_at", "Due date", due_at)
        or _order_error("due_at", "Due date cannot be before the start date", start_at, due_at)
    )


def event_error(title, start_at, end_at) -> dict | None:
    """The first problem with an event's title or times."""
    return (
        _title_error(title)
        or _date_error("start_at", "Start", start_at)
        or _date_error("end_at", "End", end_at)
        or _order_error("end_at", "End cannot be before the start", start_at, end_at)
    )
