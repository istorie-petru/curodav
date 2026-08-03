"""Apply inbound CalDAV/CardDAV field updates onto an existing local Object.

This is the inbound half of the sync bridge described in `ical.py`'s
docstring: `vtodo_to_fields`/`vevent_to_fields`/`vcard_to_fields` parse a
resource into a dict of only the standard fields that resource actually
carries. `merge_standard_fields_into` applies that dict onto the object
already sitting in the local file tree -- so an external edit (e.g. a task
completed from a phone's native Reminders app, which knows nothing about
CommandCenter's `X-COMMANDCENTER-*` properties) only ever touches the
fields it could see. Links, tags outside CATEGORIES the edit didn't
resend, and any `details` key the source format has no slot for, are left
exactly as they were.

Deliberately does not touch `id`, `type`, `created_at`, or `deleted_at` --
those are identity/lifecycle fields, not sync-able content, and a
CalDAV/CardDAV resource update should never be able to change an object's
type or resurrect/soft-delete it as a side effect of a field sync.
"""

from __future__ import annotations

from typing import Any

from ..models import Object

_TOP_LEVEL_FIELDS = {
    "title",
    "description",
    "icon",
    "cover_path",
    "status",
    "priority",
    "progress",
    "start_at",
    "due_at",
    "pinned",
    "parent_id",
    "sort_key",
    "tags",
    "workspace_id",
}


def merge_standard_fields_into(obj: Object, updates: dict[str, Any]) -> Object:
    """Mutate `obj` in place with whatever `updates` contains, and return it
    for convenience. Caller is still responsible for persisting the result
    (e.g. `FileRepository.write_object(obj)`)."""
    for key, value in updates.items():
        if key == "details":
            if not isinstance(value, dict):
                continue
            merged_details = dict(obj.details or {})
            merged_details.update(value)
            obj.details = merged_details
        elif key in _TOP_LEVEL_FIELDS:
            setattr(obj, key, value)
    return obj
