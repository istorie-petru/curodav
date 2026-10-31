"""Defaults that save a choice per item: where a new note's tag and a class's reminder start from. Stored in app_meta.

Feature notes: curodav-notes/documentation/features/notebook.md.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import db

KEYS = {"note_tag": "default_note_tag", "class_reminder": "default_class_reminder", "event_reminder": "default_event_reminder",
        "event_length": "default_event_length", "exam_reminder": "default_exam_reminder", "class_length": "default_class_length",
        "passing_grade": "default_passing_grade", "quiet_start": "quiet_hours_start", "quiet_end": "quiet_hours_end",
        "calendar_view": "default_calendar_view", "habit_reminder": "default_habit_reminder", "tasks_view": "default_tasks_view"}
REMINDER_CHOICES = [("", "None"), ("5", "5 minutes before"), ("10", "10 minutes before"), ("15", "15 minutes before"),
                    ("30", "30 minutes before"), ("60", "1 hour before")]


def get(conn: sqlite3.Connection, name: str) -> str:
    return db.get_app_meta(conn, KEYS[name]) or ""


def put(conn: sqlite3.Connection, name: str, value: str) -> None:
    db.set_app_meta(conn, KEYS[name], value.strip())


LENGTH_CHOICES = [("", "None"), ("30", "30 minutes"), ("60", "1 hour"), ("90", "90 minutes"), ("120", "2 hours")]


def event_reminders(conn: sqlite3.Connection) -> list[int]:
    value = get(conn, "event_reminder")
    return [int(value)] if value.isdigit() else []


def event_end(conn: sqlite3.Connection, start: str | None) -> str | None:
    """The end a new timed event starts with: its start plus the default length, on the same day; None when none is set."""
    length = get(conn, "event_length")
    if not (start and length.isdigit() and "T" in start):
        return None
    moved = datetime.fromisoformat(start) + timedelta(minutes=int(length))
    return moved.strftime("%Y-%m-%dT%H:%M") if moved.date() == datetime.fromisoformat(start).date() else None


def class_reminders(conn: sqlite3.Connection) -> list[int]:
    value = get(conn, "class_reminder")
    return [int(value)] if value.isdigit() else []


HOUR_CHOICES = [("", "Off")] + [(f"{h:02d}:00", f"{h:02d}:00") for h in range(24)]
CALENDAR_VIEWS = [("fourweek", "4 weeks"), ("week", "Week")]
TASKS_VIEWS = [("list", "List"), ("board", "Board"), ("habits", "Habits")]
TASKS_VIEW_URLS = {"list": "/tasks", "board": "/tasks/board", "habits": "/habits"}


def in_quiet_hours(conn: sqlite3.Connection, now: datetime) -> bool:
    """True while `now` falls between the quiet start and end (which may wrap past midnight); never when either is unset."""
    start, end = get(conn, "quiet_start"), get(conn, "quiet_end")
    if not (start and end) or start == end:
        return False
    clock_now = now.strftime("%H:%M")
    return start <= clock_now < end if start < end else clock_now >= start or clock_now < end


def view_of(conn: sqlite3.Connection, name: str, choices: list[tuple[str, str]]) -> str:
    value = get(conn, name)
    return value if value in dict(choices) else choices[0][0]


FOLDER_TEMPLATE = "folder_template:"


def folder_template(conn: sqlite3.Connection, label: str) -> str:
    """The template a new note in this shelf folder starts from; empty for a blank note."""
    return (db.get_app_meta(conn, FOLDER_TEMPLATE + label) or "") if label else ""


def put_folder_template(conn: sqlite3.Connection, label: str, template_uid: str) -> None:
    db.set_app_meta(conn, FOLDER_TEMPLATE + label, template_uid)
