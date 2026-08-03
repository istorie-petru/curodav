"""Test fixtures for Command Center test suite."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.core.db.database import Database
from src.core.filerepo.repository import FileRepository
from src.core.models import Object, ObjectStatus, ObjectType


def _write_object_json(obj_dir: Path, obj: Object) -> None:
    obj_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "type": obj.type.value,
        "title": {"v": obj.title, "h": "2026-01-01T00:00:00Z-desktop"},
        "status": {"v": obj.status, "h": "2026-01-01T00:00:00Z-desktop"},
        "created_at": {"v": obj.created_at, "h": "2026-01-01T00:00:00Z-desktop"},
        "updated_at": {"v": obj.updated_at or obj.created_at, "h": "2026-01-01T00:00:00Z-desktop"},
    }
    if obj.description:
        data["description"] = {"v": obj.description, "h": "2026-01-01T00:00:00Z-desktop"}
    if obj.priority is not None:
        data["priority"] = {"v": obj.priority, "h": "2026-01-01T00:00:00Z-desktop"}
    if obj.due_at:
        data["due_at"] = {"v": obj.due_at, "h": "2026-01-01T00:00:00Z-desktop"}
    if obj.parent_id:
        data["parent_id"] = {"v": obj.parent_id, "h": "2026-01-01T00:00:00Z-desktop"}
    if obj.tags:
        data["tags"] = {"v": list(obj.tags), "h": "2026-01-01T00:00:00Z-desktop"}
    if obj.progress is not None:
        data["progress"] = {"v": obj.progress, "h": "2026-01-01T00:00:00Z-desktop"}
    (obj_dir / "object.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create a temp CommandCenter tree with 5 seed objects."""
    base = tmp_path / "CommandCenter"
    objs_dir = base / "objects"
    objs_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    seed_objects = [
        Object(
            id="test-1",
            type=ObjectType.task,
            title="Review submission",
            status=ObjectStatus.active,
            priority=1,
            due_at=today,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        ),
        Object(
            id="test-2",
            type=ObjectType.task,
            title="Prepare slides",
            status=ObjectStatus.in_progress,
            priority=2,
            due_at=today,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
            tags=["work", "presentation"],
        ),
        Object(
            id="test-3",
            type=ObjectType.task,
            title="Order supplies",
            status=ObjectStatus.waiting,
            priority=3,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        ),
        Object(
            id="test-4",
            type=ObjectType.note,
            title="Architecture notes",
            status=ObjectStatus.active,
            description="Some architecture decisions",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        ),
        Object(
            id="test-5",
            type=ObjectType.event,
            title="Team standup",
            status=ObjectStatus.active,
            due_at=today,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        ),
        Object(
            id="test-6",
            type=ObjectType.project,
            title="Test Project",
            status=ObjectStatus.active,
            description="A test project",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        ),
    ]

    for obj in seed_objects:
        _write_object_json(objs_dir / obj.id, obj)

    return base


@pytest.fixture
def file_repo(temp_data_dir: Path) -> FileRepository:
    return FileRepository(base_path=temp_data_dir)


@pytest.fixture
def db(temp_data_dir: Path) -> Database:
    db = Database(db_path=temp_data_dir / "cache.sqlite")
    db.open()
    db.rebuild_from_path(temp_data_dir)
    return db
