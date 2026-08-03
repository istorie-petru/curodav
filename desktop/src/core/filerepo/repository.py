"""File Repository Layer (REWORK_PLAN §7, §3.2).

Read/write object.json, body.md, checklist.json, milestones.json from the file
tree at `~/CommandCenter/objects/<id>/`. HLC merge on read resolves Syncthing
conflict files.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Object, ObjectType
from ..sync.hlc import Hlc, HlcClock


_SETTINGS_PATH = Path.home() / ".command_center" / "settings.json"


def _default_command_center() -> Path:
    """Resolve the default data folder, honoring the configured folder path.

    Several call sites construct `FileRepository()` with no `base_path`
    (widgets that duplicate/delete/inline-edit objects -- see
    STRESS_TEST_2026-07-17.md). Previously this always meant
    `~/CommandCenter` regardless of Settings -> General -> Folder path,
    which was itself a no-op. Reading the same settings.json here (rather
    than requiring every call site to thread a configured FileRepository
    through) means changing the folder path actually moves *all* of the
    app's data access, not just the instance MainWindow happens to hold.
    Read directly from disk instead of importing features.settings, to
    avoid a core -> features dependency.
    """
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            configured = data.get("folder_path")
            if configured:
                return Path(configured)
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return Path.home() / "CommandCenter"


def _hlc_field(v: Any, hlc: Hlc) -> dict:
    return {"v": v, "h": str(hlc)}


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _unwrap(obj: dict, key: str, default: Any = None) -> Any:
    field = obj.get(key)
    if isinstance(field, dict) and "v" in field:
        return field["v"]
    return field if field is not None else default


class FileRepository:
    """File-tree-backed repository for objects.

    Uses `~/CommandCenter/` as the root. Each object is a directory named by
    its UUID, containing object.json and optionally body.md, checklist.json,
    milestones.json.
    """

    def __init__(
        self,
        base_path: Path | None = None,
        clock: HlcClock | None = None,
    ) -> None:
        self._base = base_path or _default_command_center()
        self._objects_dir = self._base / "objects"
        self._clock = clock or HlcClock(device_id="desktop")

    @property
    def base_path(self) -> Path:
        return self._base

    @property
    def clock(self) -> HlcClock:
        return self._clock

    def read_object(self, object_id: str) -> Object | None:
        """Read an object from the file tree. Returns None if not found.

        If Syncthing conflict files exist, merges per-field by HLC.
        """
        obj_dir = self._objects_dir / object_id
        obj_file = obj_dir / "object.json"
        if not obj_file.exists():
            return None

        try:
            data = _read_json(obj_file)
        except (json.JSONDecodeError, ValueError):
            return None
        if data is None:
            return None

        self._resolve_conflicts(obj_dir, data)

        raw_tags = _unwrap(data, "tags", [])
        tags = list(raw_tags) if isinstance(raw_tags, list) else []

        raw_details = _unwrap(data, "details", {})
        details = dict(raw_details) if isinstance(raw_details, dict) else {}

        return Object(
            id=object_id,
            type=ObjectType.from_db(_unwrap(data, "type", "task")),
            title=_unwrap(data, "title", ""),
            description=_unwrap(data, "description", ""),
            icon=_unwrap(data, "icon"),
            cover_path=_unwrap(data, "cover_path"),
            status=_unwrap(data, "status", "active"),
            priority=_unwrap(data, "priority"),
            progress=_unwrap(data, "progress"),
            start_at=_unwrap(data, "start_at"),
            due_at=_unwrap(data, "due_at"),
            pinned=_unwrap(data, "pinned", False),
            parent_id=_unwrap(data, "parent_id"),
            sort_key=_unwrap(data, "sort_key"),
            created_at=_unwrap(data, "created_at", ""),
            updated_at=_unwrap(data, "updated_at", ""),
            deleted_at=_unwrap(data, "deleted_at"),
            tags=tags,
            details=details,
        )

    def write_object(self, obj: Object) -> None:
        """Serialize an Object to the file tree as object.json with HLC stamps."""
        now = self._clock.send()
        hlc_str = str(now)

        data: dict[str, Any] = {
            "type": obj.type.value,
            "title": _hlc_field(obj.title, now),
            "status": _hlc_field(obj.status, now),
            "description": _hlc_field(obj.description, now),
            "pinned": _hlc_field(obj.pinned, now),
            "created_at": _hlc_field(obj.created_at, now),
            "updated_at": _hlc_field(hlc_str, now),
        }

        optional_fields = [
            "icon",
            "cover_path",
            "priority",
            "progress",
            "start_at",
            "due_at",
            "parent_id",
            "sort_key",
            "deleted_at",
        ]
        for f in optional_fields:
            val = getattr(obj, f, None)
            if val is not None:
                data[f] = _hlc_field(val, now)

        if obj.tags:
            data["tags"] = _hlc_field(list(obj.tags), now)

        if obj.details:
            # Type-specific extension fields (EventDetails.end_at/all_day/...,
            # NoteDetails.is_daily/daily_date, etc. -- see core/models/object.py)
            # live here as one JSON blob, same HLC-wrapped-field envelope as
            # every other field. Previously `details` wasn't serialized at
            # all: it round-tripped to `{}` on every read, silently dropping
            # anything stored in it (e.g. an event's end time, so resizing
            # an event in the week/day grid looked like it worked but the
            # new duration was never actually saved).
            data["details"] = _hlc_field(dict(obj.details), now)

        obj_dir = self._objects_dir / obj.id
        _write_json(obj_dir / "object.json", data)

    def delete_object(self, object_id: str) -> None:
        """Soft-delete by writing deleted_at."""
        obj = self.read_object(object_id)
        if obj is not None:
            now = datetime.now(timezone.utc).isoformat()
            obj.deleted_at = now
            self.write_object(obj)

    def list_object_ids(self) -> list[str]:
        """Return all object IDs in the file tree."""
        if not self._objects_dir.exists():
            return []
        return sorted(
            d.name
            for d in self._objects_dir.iterdir()
            if d.is_dir() and (d / "object.json").exists()
        )

    def iter_objects(self) -> list[Object]:
        """Iterate all objects in the file tree."""
        result: list[Object] = []
        for oid in self.list_object_ids():
            obj = self.read_object(oid)
            if obj is not None:
                result.append(obj)
        return result

    def read_body(self, object_id: str) -> str | None:
        path = self._objects_dir / object_id / "body.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_body(self, object_id: str, body: str) -> None:
        path = self._objects_dir / object_id / "body.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def read_checklist(self, object_id: str) -> list[dict] | None:
        path = self._objects_dir / object_id / "checklist.json"
        data = _read_json(path)
        return data if data is not None else None

    def write_checklist(self, object_id: str, checklist: list[dict]) -> None:
        path = self._objects_dir / object_id / "checklist.json"
        _write_json(path, checklist)

    def read_milestones(self, object_id: str) -> list[dict] | None:
        path = self._objects_dir / object_id / "milestones.json"
        data = _read_json(path)
        return data if data is not None else None

    def write_milestones(self, object_id: str, milestones: list[dict]) -> None:
        path = self._objects_dir / object_id / "milestones.json"
        _write_json(path, milestones)

    def resolve_sync_conflict(self, object_id: str) -> None:
        """Force re-read and merge of conflict files for the given object."""
        obj_dir = self._objects_dir / object_id
        obj_file = obj_dir / "object.json"
        if not obj_file.exists():
            return
        data = _read_json(obj_file)
        if data is None:
            return
        self._resolve_conflicts(obj_dir, data)
        _write_json(obj_file, data)

    # ------------------------------------------------------------------ #

    def _resolve_conflicts(self, obj_dir: Path, data: dict) -> None:
        """Merge Syncthing conflict files into the main data dict.

        For each conflict file found, load it, merge per-field by HLC,
        then delete the conflict file.
        """
        for child in obj_dir.iterdir():
            if "sync-conflict" not in child.name:
                continue
            conflict = _read_json(child)
            if conflict is None:
                continue
            self._merge_fieldwise(data, conflict)
            child.unlink()

    @staticmethod
    def _merge_fieldwise(target: dict, source: dict) -> None:
        """Merge *source* fields into *target* per-field by HLC string comparison."""
        for key, src_val in source.items():
            if not isinstance(src_val, dict) or "h" not in src_val:
                continue
            tgt_val = target.get(key)
            if isinstance(tgt_val, dict) and "h" in tgt_val:
                if src_val["h"] > tgt_val["h"]:
                    target[key] = src_val
            else:
                target[key] = src_val
