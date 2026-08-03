"""Field registry (ARCHITECTURE.md §7.3).

Ported from app/lib/core/objects/field_registry.dart. Single source of truth
for which entity/field pairs exist in the sync vocabulary. Doubles as the
SQL-injection allowlist for dynamic updates.
"""

from __future__ import annotations


class FieldRegistry:
    entities: dict[str, set[str]] = {
        "objects": {
            "workspace_id",
            "type",
            "title",
            "description",
            "icon",
            "cover_path",
            "image_ref",
            "status",
            "priority",
            "progress",
            "start_at",
            "due_at",
            "pinned",
            "parent_id",
            "sort_key",
            "created_at",
            "updated_at",
            "deleted_at",
        },
        "task_details": {
            "checklist",
            "estimate_min",
            "time_spent_min",
            "recurrence",
            "waiting_on",
            "weights",
        },
        "event_details": {
            "end_at",
            "all_day",
            "location",
            "meeting_url",
            "recurrence",
            "calendar_id",
            "reminders",
        },
        "note_details": {"body", "is_daily", "daily_date", "template"},
        "project_details": {"color", "milestones"},
        "person_details": {
            "org",
            "phone",
            "email",
            "address",
            "photo_path",
            "category",
        },
        "board_details": {"columns"},
        "links": {"from_id", "to_id", "link_type", "created_at", "deleted_at"},
        "tags": {"name", "color", "created_at", "deleted_at"},
        "object_tags": {"object_id", "tag_id"},
        "calendars": {"name", "color", "created_at", "deleted_at"},
        "attachments": {
            "object_id",
            "sha256",
            "filename",
            "mime",
            "size_bytes",
            "created_at",
            "deleted_at",
        },
        "activities": {"object_id", "kind", "detail", "at", "device_id"},
    }

    pks: dict[str, str] = {
        "objects": "id",
        "task_details": "object_id",
        "event_details": "object_id",
        "note_details": "object_id",
        "project_details": "object_id",
        "person_details": "object_id",
        "board_details": "object_id",
        "links": "id",
        "tags": "id",
        "object_tags": "composite",
        "attachments": "id",
        "activities": "id",
        "calendars": "id",
    }

    detail_table_for: dict[str, str] = {
        "task": "task_details",
        "event": "event_details",
        "note": "note_details",
        "project": "project_details",
        "person": "person_details",
        "board": "board_details",
    }

    @classmethod
    def check(cls, entity: str, fields: list[str]) -> None:
        allowed = cls.entities.get(entity)
        if allowed is None:
            raise ValueError(f"Unknown entity: {entity}")
        for f in fields:
            if f not in allowed:
                raise ValueError(f"Unknown field {entity}.{f}")
