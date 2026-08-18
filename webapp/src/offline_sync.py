"""1.8 slices 1-2 and 7 -- "Field-HLC shadow store + sync API skeleton",
"Sync conflicts surface", and "Tombstone GC" (plans/open-priority.md §
Offline-first editing & synchronization, §11). Pure conflict-detection/
apply/GC logic, deliberately independent of FastAPI/HTTP
(routers/sync_api.py is the thin HTTP wrapper around this module) -- same
"pure module + router" split as recurrence_expand.py/grid_layout.py
elsewhere in this app.

Slice 1 scope: §6's per-field last-write-wins conflict detection and §8's
push/pull protocol shape. What falls out of that same mechanism with no
extra state needed: structural ops (label_add/label_remove) are
commutative by construction (§7a), and a delete is just a `deleted_at`
field write, so an edit with a newer HLC than the tombstone un-deletes the
row for free (§4).

Slice 2 adds §7's two deliberate exceptions to plain per-field LWW, both
still picking a winner automatically (no device is ever blocked) but
recording the losing side as an inspectable `sync_conflicts` row instead
of silently discarding it:

- **§7b** -- a genuine *concurrent* edit to the same event's
  `start_at`/`end_at` (a committed scheduling decision, not "the same fact
  measured twice"). Concurrency detection here is a deliberate
  simplification, not a full causal/version-vector history (§10 rules
  CRDTs out): per §3, both client and server merge (`max` + increment)
  their HLC clock on every op they observe from elsewhere, so a device
  that HAD already observed another device's write would have a clock
  advanced past it, and any of its own subsequent writes would carry a
  strictly higher HLC (never lose to that write). It follows that two
  writes to the same field from two *different* device_ids where one
  loses to the other can only happen if neither had observed the other's
  write yet -- i.e. genuinely concurrent. A losing write from the *same*
  device_id as the current winner is just an ordinary reordered/replayed
  op from that device's own causal history, not a conflict, and is left
  as a plain §6 stale no-op.
- **§7c** -- `apply_batch` re-validates single-project-per-task (1.5's
  `MultipleProjectLabelsError`) across an entire batch's `label_add` ops
  after they've all applied, not per-op (each individual add is a valid,
  commutative §7a op; only the *combination* can violate the invariant).

Slice 7 adds `purge_expired` -- the physical-deletion half of §4's
retention horizon. Slice 1's `pull()` already had the *safety* half (a
stale cursor forces a full resync instead of a possibly-incomplete
incremental delta); this is what actually removes a tombstoned entity
(and its `field_versions` rows) and stale `sync_applied_ops` ledger
entries once they're safely past that same horizon, so this app's own
sync bookkeeping doesn't grow forever.
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
_ENTITY_TABLES: dict[str, str] = db.ENTITY_TABLES

# Whitelist of columns a `field_set`/`create` op may target -- op payloads
# are client-supplied JSON, so field names must never be interpolated into
# SQL unchecked. `deleted_at` is included deliberately: §4 models a delete
# as an ordinary field write, not a separate code path. Single source of
# truth lives in db.py (ENTITY_SYNC_FIELDS) -- db.py's own server-write
# recording (the server is a participant in the same scheme, 2026-08-18)
# must diff against the identical whitelist, and one copy beats two.
_ENTITY_FIELDS: dict[str, set[str]] = db.ENTITY_SYNC_FIELDS


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


# §7b: fields representing a committed scheduling decision, not a plain
# fact -- see this module's own docstring for the concurrency-detection
# reasoning (different device_id on both sides of a losing write == never
# observed each other, by the HLC merge rule's own guarantee).
_CONFLICT_SURFACED_FIELDS: dict[str, set[str]] = {"event": {"start_at", "end_at"}}


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
    surfaced = field_name in _CONFLICT_SURFACED_FIELDS.get(entity_type, set())
    if existing_hlc is not None and existing_hlc >= hlc:
        # Older (or a literal replay of the same write) is a silent no-op
        # for *this field only* (§6) -- correct, not lossy, since the
        # write's intent for every other field it touched is unaffected.
        # Exception (§7b): a surfaced field losing to a *different*
        # device's write is a genuine concurrent edit, not an ordinary
        # stale/replayed op -- record it instead of discarding silently.
        if surfaced and existing_hlc[2] != hlc[2]:
            db.create_sync_conflict(conn, entity_type, uid, field_name, value, hlc, existing_hlc)
            field_results[field_name] = "conflict"
        else:
            field_results[field_name] = "stale"
        return
    # §7b, the mirror case: this write is about to win and overwrite an
    # existing value that itself came from a genuinely different device --
    # still concurrent (arrival order at the server never determines
    # causal concurrency), so the value being overwritten is recorded too,
    # not just silently replaced.
    if surfaced and existing_hlc is not None and existing_hlc[2] != hlc[2]:
        previous_value = _current_field_value(conn, entity_type, uid, field_name)
        db.create_sync_conflict(conn, entity_type, uid, field_name, previous_value, existing_hlc, hlc)
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
    if not values:
        return "noop"
    if values <= {"applied", "cleared_by_newer_edit"}:
        return "applied"
    if values <= {"stale"}:
        return "stale"
    if values <= {"conflict"}:
        # §7b: every field this op touched lost to a genuinely concurrent
        # write and was recorded as a sync_conflicts row rather than a
        # plain silent stale no-op -- distinct from ordinary "stale" so a
        # caller (or a test) can tell the two apart.
        return "conflict"
    if "applied" in values or "cleared_by_newer_edit" in values:
        return "applied_partial"
    return "stale"


def _op_hlc(op: dict[str, Any]) -> HLC:
    """The single newest HLC an op carries -- the max over a create/
    field_set's per-field HLCs, or the op's own HLC for delete/label ops.
    What `apply_batch` sorts a batch by, and what the server's own clock
    merges past when it applies the op (db.merge_server_hlc -- the server
    is itself a participant in §3's HLC scheme, 2026-08-18)."""
    if op.get("op_type") in ("create", "field_set"):
        fields = op.get("fields") or {}
        if not fields:
            return (0, 0, "")
        return max(hlc_from_payload(spec["hlc"]) for spec in fields.values())
    # Label ops are §7a commutative -- some callers (older tests, and the
    # §7c batch helpers) stamp a top-level `hlc`, but it plays no part in
    # the merge; an op without one simply doesn't advance the server clock.
    if "hlc" in op:
        return hlc_from_payload(op["hlc"])
    return (0, 0, "")


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

    # §3's receive-side merge: the server has now *observed* this op, so
    # its own clock must advance past the op's HLC -- otherwise the next
    # server-side UI write could mint an HLC that fails to outrank a
    # device write it was causally after (see db.mint_server_hlc). Only on
    # a genuinely new op, not a cached replay.
    db.merge_server_hlc(conn, _op_hlc(op))
    db.record_sync_applied_op(conn, op_id, entity_type, entity_uid, result)
    return {"op_id": op_id, **result}


_PRE_EXISTING_HLC: HLC = (0, 0, "pre-existing")  # see _reconcile_project_labels


def apply_batch(conn: sqlite3.Connection, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """§5: ops sync in per-entity chronological (their own HLC) order so
    intra-entity causality (a `create` always applies before a later
    `field_set` against the same uid) is preserved even though cross-
    entity order never matters. Sorting is stable, so ops for different
    entities interleaved in the input keep their relative order too.

    §7c: after every op has applied, re-validate single-project-per-task
    across the whole batch -- each individual `label_add` is a valid,
    commutative §7a op on its own; only the *combination* (two different
    project labels landing on the same task) can violate the invariant,
    so it can only be caught after the fact, not per-op."""
    ordered = sorted(ops, key=_op_hlc)
    project_names = {cfg["name"] for cfg in db.list_project_labels(conn)}
    pre_existing = _snapshot_pre_existing_project_labels(conn, ordered, project_names)
    # The data version (db.get_sync_data_version) must move exactly when a
    # *new* write actually changes server state -- the "did anything
    # change" signal a device compares against before running a sync round
    # (offline_sync_client.js's round-skip pre-check). A replayed op_id
    # (a retried push of an already-applied batch) returns its cached
    # "applied" result but must not bump the version: nothing changed.
    # `result["status"]` is computed pre-reconcile here -- a label_add that
    # §7c then reverts to "rejected_invariant" may bump spuriously, an
    # accepted edge case (one extra no-op pull on other devices, harmless).
    results = []
    changed = False
    for op in ordered:
        op_id = op["op_id"]
        cached = db.get_sync_applied_op(conn, op_id) is not None
        result = apply_op(conn, op)
        if not cached and result["status"] in ("applied", "applied_partial"):
            changed = True
        results.append(result)
    _reconcile_project_labels(conn, ordered, project_names, pre_existing, results)
    if changed:
        db.bump_sync_data_version(conn)
    return results


def _snapshot_pre_existing_project_labels(
    conn: sqlite3.Connection, ordered: list[dict[str, Any]], project_names: set[str]
) -> dict[str, set[str]]:
    """Project labels a task already had *before* this batch, for every
    task a `label_add` op in this batch targets with a project label --
    taken before any op in the batch applies. A pre-existing project label
    has no in-batch HLC to arbitrate with, so it always outranks anything
    newly added by this batch (see _reconcile_project_labels)."""
    pre_existing: dict[str, set[str]] = {}
    for op in ordered:
        if op.get("op_type") != "label_add" or op.get("entity_type") != "object_label":
            continue
        target = op.get("target") or {}
        if target.get("object_type") != "task" or target.get("label_name") not in project_names:
            continue
        task_uid = target["object_id"]
        if task_uid not in pre_existing:
            task = db.get_task(conn, task_uid)
            pre_existing[task_uid] = {t for t in ((task or {}).get("tags") or []) if t in project_names}
    return pre_existing


def _reconcile_project_labels(
    conn: sqlite3.Connection,
    ordered: list[dict[str, Any]],
    project_names: set[str],
    pre_existing: dict[str, set[str]],
    results: list[dict[str, Any]],
) -> None:
    results_by_op_id = {r["op_id"]: r for r in results}
    adds_by_task: dict[str, dict[str, dict[str, Any]]] = {}
    for op in ordered:
        if op.get("op_type") != "label_add" or op.get("entity_type") != "object_label":
            continue
        target = op.get("target") or {}
        label_name = target.get("label_name")
        if target.get("object_type") != "task" or label_name not in project_names:
            continue
        task_uid = target["object_id"]
        hlc = hlc_from_payload(op["hlc"])
        by_label = adds_by_task.setdefault(task_uid, {})
        # Multiple ops re-adding the *same* label are commutative (§7a) --
        # only the highest HLC of each distinct label name is kept as that
        # label's own representative for the cross-label arbitration below.
        existing = by_label.get(label_name)
        if existing is None or hlc > existing["hlc"]:
            by_label[label_name] = {"label_name": label_name, "hlc": hlc, "op_id": op["op_id"]}

    for task_uid, by_label in adds_by_task.items():
        pre = pre_existing.get(task_uid, set())
        distinct_labels = set(by_label) | pre
        if len(distinct_labels) <= 1:
            continue
        if pre:
            # A label that was already on the task before this batch wins
            # outright -- it has no in-batch HLC to lose against. Every
            # label this batch tried to add is a loser regardless of its
            # own HLC.
            winning_hlc = _PRE_EXISTING_HLC
            losers = list(by_label.values())
        else:
            best = max(by_label.values(), key=lambda v: v["hlc"])
            winner_label = best["label_name"]
            winning_hlc = best["hlc"]
            losers = [v for v in by_label.values() if v["label_name"] != winner_label]
        for loser in losers:
            conn.execute(
                "DELETE FROM object_labels WHERE object_type = 'task' AND object_id = ? AND label_name = ?",
                (task_uid, loser["label_name"]),
            )
            db.create_sync_conflict(
                conn, "task", task_uid, "project_label",
                loser["label_name"], loser["hlc"], winning_hlc,
            )
            result = results_by_op_id.get(loser["op_id"])
            if result is not None:
                result["status"] = "rejected_invariant"
        conn.commit()


def _current_field_value(conn: sqlite3.Connection, entity_type: str, uid: str, field_name: str) -> Any:
    table = _ENTITY_TABLES.get(entity_type)
    if table is None:
        return None
    row = conn.execute(f"SELECT {field_name} FROM {table} WHERE uid = ?", (uid,)).fetchone()
    if row is not None:
        return row[0]
    # A *server-side* hard delete (db.delete_task/event/contact, 2026-08-18)
    # records a `deleted_at` field_versions entry but physically removes the
    # row -- unlike a sync soft-delete, there is no column value to read
    # back. Without a special case the pull would emit `deleted_at: null`
    # and a device's mirror would never hide the entity. Emit the tombstone
    # HLC's own timestamp instead -- a truthy value whose only job is to
    # let the mirror's "not soft-deleted" filter exclude the row.
    if field_name == "deleted_at":
        hlc = db.get_field_hlc(conn, entity_type, uid, "deleted_at")
        return _hlc_to_iso(hlc) if hlc else None
    return None


# Tombstone GC retention horizon (§4) -- a device whose cursor predates
# this can't safely apply an incremental pull (a tombstone it never saw
# may already be gone) and instead gets told to do a full resync (§8).
# Slice 1 only needed this for that comparison; slice 7's `purge_expired`
# below (further down this file) is what actually deletes anything once
# it's safely past the same horizon.
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


# --------------------------------------------------------------------- #
# 1.8 slice 7 -- "Tombstone GC" (open-priority.md §11 slice 7). `pull()`
# above (slice 1) already has the *safety* half of §4's retention horizon:
# a cursor older than RETENTION_DAYS gets a forced full_resync instead of
# a possibly-incomplete incremental delta. What was still missing is the
# other half -- actually deleting anything once it's safely past that
# horizon, so field_versions/sync_applied_ops/the entity tables don't grow
# forever. `purge_expired` below is that job; it's deliberately a plain
# function with no scheduling opinion of its own (no cron in this app --
# routers/sync_api.py's own lazy "check on every pull" trigger, and
# Settings > Data health's manual one, both just call this the same way
# routers/tasks.py's own auto-archive check calls db.delete_old_completed_
# tasks).
# --------------------------------------------------------------------- #


def _purge_expired_tombstones(conn: sqlite3.Connection, cutoff_ms: int) -> dict[str, int]:
    """Physically removes any entity whose tombstone (`deleted_at`, per §4)
    is older than `cutoff_ms` -- by the time GC runs at all, the retention
    horizon has already elapsed, so every device that could still need an
    incremental delta mentioning this deletion has either already applied
    it or has a cursor stale enough to trigger `pull()`'s own full_resync
    branch instead (which never depends on an already-purged tombstone
    still being present -- a device rebuilding from scratch has nothing
    locally to "resurrect" for a uid the fresh pull simply never mentions).

    Reads eligibility off `field_versions`' own stored HLC for the
    `deleted_at` field, not the entity row's plain `deleted_at` column --
    an edit newer than a tombstone un-deletes the row (§4) by advancing
    that same field_versions HLC forward, so a row that was un-deleted
    naturally stops being eligible with no separate check needed. Reuses
    `db.delete_task`/`delete_event`/`delete_contact` (not a raw `DELETE
    FROM`) so the same related-row cleanup (`object_labels`,
    `event_task_relations`, ...) every other hard-delete path in this app
    already gets applies here too."""
    counts = {entity_type: 0 for entity_type in _ENTITY_TABLES}
    rows = conn.execute(
        "SELECT entity_type, entity_uid FROM field_versions WHERE field_name = 'deleted_at' AND hlc_physical < ?",
        (cutoff_ms,),
    ).fetchall()
    for entity_type, uid in rows:
        table = _ENTITY_TABLES.get(entity_type)
        if table is None:
            continue
        current = conn.execute(f"SELECT deleted_at FROM {table} WHERE uid = ?", (uid,)).fetchone()
        if current is None or current[0] is None:
            # Already gone (a prior GC run, or some other cleanup path),
            # or un-deleted since -- see the docstring above. Either way,
            # nothing to purge for this uid.
            continue
        if entity_type == "task":
            db.delete_task(conn, uid, record_server_write=False)
        elif entity_type == "event":
            db.delete_event(conn, uid, record_server_write=False)
        elif entity_type == "contact":
            db.delete_contact(conn, uid, record_server_write=False)
        conn.execute(
            "DELETE FROM field_versions WHERE entity_type = ? AND entity_uid = ?", (entity_type, uid)
        )
        counts[entity_type] += 1
    conn.commit()
    return counts


def _purge_expired_applied_ops(conn: sqlite3.Connection, cutoff_ms: int) -> int:
    """§5's idempotency ledger is only ever consulted to replay a *retried*
    push after a dropped connection -- nothing plausibly retries a push
    from `cutoff_ms` ago, so these rows are pure accumulated cruft past
    that point. `applied_at` is stored as an ISO 8601 UTC string
    (`record_sync_applied_op`), which sorts correctly as plain text, so no
    parsing is needed to compare it against the same cutoff."""
    cutoff_iso = _hlc_to_iso((cutoff_ms, 0, ""))
    cur = conn.execute(
        "DELETE FROM sync_applied_ops WHERE applied_at IS NOT NULL AND applied_at < ?", (cutoff_iso,)
    )
    conn.commit()
    return cur.rowcount


def purge_expired(
    conn: sqlite3.Connection, *, retention_days: int = RETENTION_DAYS, now_ms: int | None = None
) -> dict[str, Any]:
    """The one entry point every caller (the lazy pull-time trigger, the
    Settings "Run cleanup now" button, and the CLI) goes through -- see
    this section's own header comment for why none of them duplicate the
    cutoff math or the two purge steps themselves."""
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = now_ms - retention_days * 24 * 60 * 60 * 1000
    purged_entities = _purge_expired_tombstones(conn, cutoff_ms)
    purged_applied_ops = _purge_expired_applied_ops(conn, cutoff_ms)
    if any(purged_entities.values()) or purged_applied_ops:
        # GC physically removed data -- a stale device would now get a
        # different pull answer than before, so the data version must
        # move or that device's round-skip pre-check could let it quietly
        # skip past a resync it actually needs (its cursor is by
        # definition older than the retention horizon at this point).
        db.bump_sync_data_version(conn)
    return {
        "retention_days": retention_days,
        "cutoff_ms": cutoff_ms,
        "purged_entities": purged_entities,
        "purged_applied_ops": purged_applied_ops,
    }
