"""The unified object model — ported from app/lib/core/objects/object_types.dart
and ARCHITECTURE.md §4. Every entity in the system is an Object with a type
discriminator. Extension tables add type-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ObjectType(str, Enum):
    task = "task"
    project = "project"
    event = "event"
    note = "note"
    goal = "goal"
    roadmap_node = "roadmap_node"
    person = "person"
    media = "media"
    infra_node = "infra_node"
    file = "file"
    board = "board"

    @classmethod
    def from_db(cls, v: str) -> ObjectType:
        return cls(v)


class ObjectStatus:
    active = "active"
    in_progress = "in_progress"
    waiting = "waiting"
    done = "done"
    archived = "archived"

    core = {active, in_progress, waiting, done, archived}

    @staticmethod
    def is_open(s: str) -> bool:
        return s not in (ObjectStatus.done, ObjectStatus.archived)


class Priority:
    urgent = 1
    high = 2
    medium = 3
    low = 4


# Progress is derived from status, not independently editable (2026-07-19
# rework -- see plans/tasks-ux-rework.md and features/tasks.md). Values are
# fractions (0.0-1.0) to match `Object.progress`'s existing representation.
STATUS_PROGRESS: dict[str, float] = {
    ObjectStatus.active: 0.0,
    ObjectStatus.in_progress: 0.5,
    ObjectStatus.waiting: 0.9,
    ObjectStatus.done: 1.0,
    ObjectStatus.archived: 1.0,
}


def progress_for_status(status: str) -> float:
    """The fixed progress fraction implied by a status value. Any status
    outside the core vocabulary (shouldn't happen, but `Object.status` is a
    plain str, not an enum) falls back to 0.0 rather than raising."""
    return STATUS_PROGRESS.get(status, 0.0)


@dataclass
class Object:
    """A unified object — can be task, event, note, project, etc."""

    id: str
    type: ObjectType
    title: str = ""
    description: str = ""
    icon: str | None = None
    cover_path: str | None = None
    status: str = ObjectStatus.active
    priority: int | None = None
    progress: float | None = None
    start_at: str | None = None
    due_at: str | None = None
    pinned: bool = False
    parent_id: str | None = None
    sort_key: str | None = None
    created_at: str = ""
    updated_at: str = ""
    deleted_at: str | None = None

    tags: list[str] = field(default_factory=list)

    workspace_id: str = "default"

    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskDetails:
    checklist: list[dict] = field(default_factory=list)
    estimate_min: int | None = None
    time_spent_min: int = 0
    recurrence: str | None = None
    waiting_on: str | None = None


@dataclass
class EventDetails:
    end_at: str | None = None
    all_day: bool = False
    location: str | None = None
    meeting_url: str | None = None
    recurrence: str | None = None
    calendar_id: str | None = None
    reminders: list[int] = field(default_factory=list)


@dataclass
class NoteDetails:
    body: str = ""
    is_daily: bool = False
    daily_date: str | None = None
    template: bool = False


@dataclass
class ProjectDetails:
    color: str | None = None
    milestones: list[dict] = field(default_factory=list)


@dataclass
class PersonDetails:
    """Fields for ObjectType.person. Matches FieldRegistry.entities["person_details"]
    (registry.py) -- that allowlist existed already but this dataclass didn't,
    so `details` for person objects round-tripped as an untyped dict. Field
    choices mirror vCard's most common properties (ORG, TEL, EMAIL, ADR,
    PHOTO, CATEGORIES) since these are the CardDAV sync target."""

    org: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    photo_path: str | None = None
    category: str | None = None


@dataclass
class BoardDetails:
    columns: list[dict] = field(default_factory=list)
