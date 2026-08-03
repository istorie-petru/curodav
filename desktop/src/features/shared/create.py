"""Shared object creation helpers (PHASE 1).

Provides `create_task_from_quickadd()` so both Dashboard's and Tasks' quick-add
bars use identical parsing and persistence logic.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectType
from ...core.utils.date_utils import parse_date_token

_SETTINGS_PATH = Path.home() / ".command_center" / "settings.json"


def _default_new_item_fields() -> tuple[str, int | None]:
    """(status, priority) new quick-add tasks start with, per Settings ->
    Inspector -> "Default status/priority for new items". Read straight
    from settings.json rather than importing features.settings, same
    pattern as `core/filerepo/repository.py`'s `_default_command_center`
    (avoids a core/shared -> features dependency)."""
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            return data.get("default_new_status", "active"), data.get("default_new_priority")
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return "active", None


def _resolve_project(token: str, file_repo: FileRepository) -> str | None:
    """Find an existing project by title or create a new one."""
    project_key = token[1:]
    objects = list(file_repo.iter_objects())
    for o in objects:
        if o.type == ObjectType.project and o.title == project_key:
            return o.id
    now_iso = datetime.now(timezone.utc).isoformat()
    proj = Object(
        id=str(uuid.uuid4()),
        type=ObjectType.project,
        title=project_key,
        status="active",
        created_at=now_iso,
        updated_at=now_iso,
    )
    file_repo.write_object(proj)
    return proj.id


def create_task_from_quickadd(text: str, file_repo: FileRepository) -> Object:
    """Parse *text* as a quick-add command, persist via *file_repo*, return new Object.

    Token syntax (same as TaskQuickAdd.parse_tokens):
        !1-!4   → priority (P1–P4)
        @today  → due date (also @tomorrow, @next-week, or YYYY-MM-DD)
        #project → parent_id (project name/id tag, creates project if new)
        >tag    → freeform tag (not yet persisted — tag model TBD)

    If *text* has no tokens the entire string becomes the title.
    """
    tokens = text.strip().split()
    title_parts: list[str] = []
    priority: int | None = None
    due_at: str | None = None
    parent_id: str | None = None
    tags: list[str] = []

    for token in tokens:
        if token.startswith("!") and len(token) == 2:
            try:
                p = int(token[1])
                if 1 <= p <= 4:
                    priority = p
                    continue
            except ValueError:
                pass
        elif token.startswith("@"):
            parsed = parse_date_token(token)
            if parsed:
                due_at = parsed
                continue
        elif token.startswith("#"):
            parent_id = _resolve_project(token, file_repo)
            continue
        elif token.startswith(">"):
            tags.append(token[1:])
            continue
        title_parts.append(token)

    object_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    default_status, default_priority = _default_new_item_fields()

    obj = Object(
        id=object_id,
        type=ObjectType.task,
        title=" ".join(title_parts) if title_parts else text,
        priority=priority if priority is not None else default_priority,
        due_at=due_at,
        parent_id=parent_id,
        tags=tags,
        status=default_status,
        created_at=now_iso,
        updated_at=now_iso,
    )

    file_repo.write_object(obj)
    return obj
