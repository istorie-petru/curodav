"""1.8 slice 1 -- "Field-HLC shadow store + sync API skeleton"
(plans/open-priority.md § Offline-first editing & synchronization, §11
slice 1). Pure conflict-detection/apply logic, deliberately independent
of FastAPI/HTTP (routers/sync_api.py is the thin HTTP wrapper around this
module) -- same "pure module + router" split as recurrence_expand.py/
grid_layout.py elsewhere in this app.

Scope, per the slice breakdown: §6's per-field last-write-wins conflict
detection and §8's push/pull protocol shape, tested entirely server-side.
Deliberately NOT in this slice (see §11 slice 2): the `sync_conflicts`
table, and §7(b)/(c)'s two conflict-*surfacing* exceptions (event
start_at/end_at concurrent-edit detection, single-project-per-task
re-validation after a batch) -- those get wired into this module's apply
path by slice 2, not built here. What this slice already gets right,
because it falls out of the same per-field HLC mechanism rather than
needing special-casing: structural ops (label_add/label_remove) are
commutative by construction (§7a) and a delete is just a `deleted_at`
field write, so an edit with a newer HLC than the tombstone un-deletes
the row for free (§4) -- both handled below with no extra state.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import db

HLC = tuple[int, int, str]

# Entity types this slice's sync API covers -- the base pool only (§1: a
# task/event/contact already carries the stable `uid` sync needs). Labels
# are handled separately below (`object_label`, natural-key identified,
# no HLC arbitration needed at all -- §7a).
_ENTITY_TABLES: dict[str, str] = {
    "task": "tasks",
    "event": "events",
    "contact": "contacts",
}

# Whitelist of columns a `field_set`/`create` op may target -- op payloads
# are client-supplied JSON, so field names must never be interpolated into
# SQL unchecked. `deleted_at` is included deliberately: §4 models a delete
# as an ordinary field write, not a separate code path.
_ENTITY_FIELDS: dict[str, set[str]] = {
    "task": {
        "title", "description", "start_at", "due_at", "importance", "urgency",
        "status", "progress", "recurrence", "exdates_json", "completed_at",
        "target_per_day", "created_at", "updated_at", "deleted_at",
    },
    "event": {
        "title", "description", "start_at", "end_at", "all_day", "location",
        "meeting_url", "status", "recurrence", "exdates_json", "reminders_json",
        "holiday_calendar", "exclude_saturday", "exclude_sunday",
        "created_at", "updated_at", "deleted_at",
    },
    "contact": {
        "full_name", "org", "phone", "email", "address", "notes",
        "photo_b64", "photo_type", "created_at", "updated_at", "deleted_at",
    },
}


class UnknownEntityTypeError(ValueError):
    pass


def hlc_from_payload(payload: dict[str, Any]) -> HLC:
    return (int(payload["physical"]), int(payload["logical"]), str(payload["device_id"]))


def hlc_to_payload(hlc: HLC) -> dict[str, Any]:
    return {"physical": hlc[0], "logical": hlc[1], "device_id": hlc[2]}


def _hlc_to_iso(hlc: HLC) -> str:
    """A best-effort human-readable timestamp for `deleted_at`, derived
    from the tombstoning op's own HLC physical time -- not read by any
    conflict-detection logic (field_versions' own stored HLC is what that
    compares against), purely so the column holds something inspectable
    rather than an opaque marker."""
    return datetime.fromtimestamp(hlc[0] / 1000, tz=timezone.utc).isoformat()


def _ensure_row_exists(conn: sqlite3.Connection, table: str, uid: str) -> None:
    conn.execute(f"INSERT OR IGNORE INTO {table} (uid) VALUES (?)", (uid,))


def _apply_field_write(
    conn: sqlite3.Connection,
    entity_type: str,
    table: str,
    uid: str,
    field_name: str,
    value: Any,
    hlc: HLC,
    field_results: dict[str, str],
) -> None:
    """One field's §6 comparison + apply, shared by field_set/create ops
    and the synthetic `deleted_at` write a delete op performs."""
    existing_hlc = db.get_field_hlc(conn, entity_type, uid, field_name)
    if existing_hlc is not None and existing_hlc >= hlc:
        # Older (or a literal replay of the same write) is a silent no-op
        # for *this field only* (§6) -- correct, not lossy, since the
        # write's intent for every other field it touched is unaffected.
        field_results[field_name] = "stale"
        return
    conn.execute(f"UPDATE {table} SET {field_name} = ? WHERE uid = ?", (value, uid))
    db.set_field_hlc(conn, entity_type, uid, field_name, hlc)
    field_results[field_name] = "applied"
    if field_name != "deleted_at":
        # §4: "an edit newer than the tombstone un-deletes the row" --
        # falls out of the same per-field LWW rule rather than needing a
        # separate undelete op type: any field write whose HLC beats the
        # stored tombstone's HLC clears the tombstone too.
        deleted_hlc = db.get_field_hlc(conn, entity_type, uid, "deleted_at")
        if deleted_hlc is not None and hlc > deleted_hlc:
            conn.execute(f"UPDATE {table} SET deleted_at = NULL WHERE uid = ?", (uid,))
            db.set_field_hlc(conn, entity_type, uid, "deleted_at", hlc)
            field_results["deleted_at"] = "cleared_by_newer_edit"


def _apply_field_set(conn: sqlite3.Connection, op: dict[str, Any]) -> dict[str, Any]:
    entity_type = op["entity_type"]
    if entity_type not in _ENTITY_TABLES:
        raise UnknownEntityTypeError(entity_type)
    table = _ENTITY_TABLES[entity_type]
    allowed = _ENTITY_FIELDS[entity_type]
    uid = op["entity_uid"]
    _ensure_row_exists(conn, table, uid)
    field_results: dict[str, str] = {}
    for field_name, spec in op.get("fields", {}).items():
        if field_name not in allowed:
            field_results[field_name] = "rejected_unknown_field"
            continue
        hlc = hlc_from_payload(spec["hlc"])
        _apply_field_write(conn, entity_type, table, uid, field_name, spec["value"], hlc, field_results)
    conn.commit()
    return {"status": _summarize(field_results), "fields": field_results}


def _apply_delete(conn: sqlite3.Connection, op: dict[str, Any]) -> dict[str, Any]:
    entity_type = op["entity_type"]
    if entity_type not in _ENTITY_TABLES:
        raise UnknownEntityTypeError(entity_type)
    table = _ENTITY_TABLES[entity_type]
    uid = op["entity_uid"]
    hlc = hlc_from_payload(op["hlc"])
    _ensure_row_exists(conn, table, uid)
    field_results: dict[str, str] = {}
    _apply_field_write(conn, entity_type, table, uid, "deleted_at", _hlc_to_iso(hlc), hlc, field_results)
    conn.commit()
    return {"status": _summarize(field_results), "fields": field_results}


def _apply_label_op(conn: sqlite3.Connection, op: dict[str, Any]) -> dict[str, Any]:
    """§7a: object_labels add/remove is commutative by construction --
    applying "add" twice or "remove" twice converges to the same state
    regardless of arrival order, so this needs no HLC arbitration at all,
    unlike every other op type above."""
    target = op["target"]
    object_type, object_id, label_name = target["object_type"], target["object_id"], target["label_name"]
    if op["op_type"] == "label_add":
        conn.execute(
            "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
            (object_type, object_id, label_name),
        )
    else:
        conn.execute(
            "DELETE FROM object_labels WHERE object_type = ? AND object_id = ? AND label_name = ?",
            (object_type, object_id, label_name),
        )
    conn.commit()
    return {"status": "applied", "fields": {}}


def _summarize(field_results: dict[str, str]) -> str:
    values = set(field_results.values())
    if not values or values <= {"applied", "cleared_by_newer_edit"}:
        return "applied" if values else "noop"
    if "applied" in values or "cleared_by_newer_edit" in values:
        return "applied_partial"
    return "stale"


def apply_op(conn: sqlite3.Connection, op: dict[str, Any]) -> dict[str, Any]:
    """Applies one op (§2's shape) with §5 idempotency: a duplicate
    `op_id` (a retried push after a connection drop) replays the cached
    result instead of re-applying. Every op type below is individually
    safe to re-run, but the ledger is still the source of truth per §5 --
    re-deriving "was this already applied" from field_versions state alone
    would be more fragile than just remembering the op_id."""
    op_id = op["op_id"]
    entity_type = op["entity_type"]
    entity_uid = op.get("entity_uid") or ""
    cached = db.get_sync_applied_op(conn, op_id)
    if cached is not None:
        return {"op_id": op_id, **cached}

    op_type = op["op_type"]
    if op_type in ("create", "field_set"):
        result = _apply_field_set(conn, op)
    elif op_type == "delete":
        result = _apply_delete(conn, op)
    elif op_type in ("label_add", "label_remove"):
        result = _apply_label_op(conn, op)
    else:
        raise ValueError(f"unknown op_type: {op_type!r}")

    db.record_sync_applied_op(conn, op_id, entity_type, entity_uid, result)
    return {"op_id": op_id, **result}


def apply_batch(conn: sqlite3.Connection, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """§5: ops sync in per-entity chronological (their own HLC) order so
    intra-entity causality (a `create` always applies before a later
    `field_set` against the same uid) is preserved even though cross-
    entity order never matters. Sorting is stable, so ops for different
    entities interleaved in the input keep their relative order too."""
    def _op_hlc(op: dict[str, Any]) -> HLC:
        if op["op_type"] in ("create", "field_set"):
            fields = op.get("fields") or {}
            if not fields:
                return (0, 0, "")
            return max(hlc_from_payload(spec["hlc"]) for spec in fields.values())
        return hlc_from_payload(op["hlc"])

    ordered = sorted(ops, key=_op_hlc)
    return [apply_op(conn, op) for op in ordered]


def _current_field_value(conn: sqlite3.Connection, entity_type: str, uid: str, field_name: str) -> Any:
    table = _ENTITY_TABLES.get(entity_type)
    if table is None:
        return None
    row = conn.execute(f"SELECT {field_name} FROM {table} WHERE uid = ?", (uid,)).fetchone()
    return row[0] if row is not None else None


# Tombstone GC retention horizon (§4) -- a device whose cursor predates
# this can't safely apply an incremental pull (a tombstone it never saw
# may already be gone) and instead gets told to do a full resync (§8).
# Physical purge itself is slice 7's job; this slice only needs the
# comparison, since nothing here ever deletes a field_versions row yet.
RETENTION_DAYS = 90


def pull(
    conn: sqlite3.Connection,
    cursor: HLC | None,
    *,
    retention_days: int = RETENTION_DAYS,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """§8's pull phase. `cursor=None` is a brand-new device's first-ever
    pull -- `db.list_field_versions_since(None)` already returns "every
    field write that exists," so that's a plain (large) incremental delta,
    not a "cursor too old" case; there's no prior cursor to have gone
    stale. A *non-None* cursor older than the retention horizon forces a
    full resync instead (§4/§8) -- a real prior sync that fell far enough
    behind that an incremental pull could miss a purged tombstone."""
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    horizon_ms = retention_days * 24 * 60 * 60 * 1000
    is_stale = cursor is not None and (now_ms - cursor[0]) > horizon_ms
    if is_stale:
        new_cursor = db.max_field_hlc(conn) or (now_ms, 0, "")
        return {"full_resync": True, "changes": [], "cursor": new_cursor}

    versions = db.list_field_versions_since(conn, cursor)
    changes = [
        {
            "entity_type": v["entity_type"],
            "entity_uid": v["entity_uid"],
            "field_name": v["field_name"],
            "value": _current_field_value(conn, v["entity_type"], v["entity_uid"], v["field_name"]),
            "hlc": v["hlc"],
        }
        for v in versions
    ]
    new_cursor = changes[-1]["hlc"] if changes else cursor
    return {"full_resync": False, "changes": changes, "cursor": new_cursor}
