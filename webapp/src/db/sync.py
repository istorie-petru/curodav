"""Published lists, push, sync bookkeeping and search.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .core import ENTITY_SYNC_FIELDS, ENTITY_TABLES, SERVER_DEVICE_ID, _SERVER_HLC_KEY, _SERVER_WRITES_BACKFILLED_KEY, _hlc_to_str, get_app_meta, set_app_meta, set_field_hlc
from .events import _search_events
from .contacts import _search_contacts
from .tasks import _search_tasks


def search_entities(
    conn: sqlite3.Connection,
    q: str | None = None,
    types: list[str] | None = None,
    labels: list[str] | None = None,
    task_status: str | None = None,
    task_due_on: str | None = None,
    event_start: str | None = None,
    event_end: str | None = None,
    exclude_uids: dict[str, set[str]] | None = None,
    include_habit_tasks: bool = False,
    exclude_past_events: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Search across tasks, events, and contacts.

        Explicit filters (AND together):
          - `q`        -- free-text, case-insensitive substring across the
                          meaningful metadata: task title/description/labels;
                          event title/description/labels; contact name/org/
                          phone/email/labels. (Fuzzy = SQL LIKE, the same
                          mechanism list_tasks/list_contacts already use -- no
                          index, appropriate at personal-scale volumes.)
          - `types`    -- subset of ("task", "event", "contact"); None/empty
                          means all three.
          - `labels`   -- multi-select label filter, any-match (a result needs
                          just one of the chosen labels), case-sensitive on the
                          stored object_labels name like every other label
                          query here.
          - `task_status`  -- tasks only: exact status match.
          - `task_due_on`  -- tasks only: due on this exact ISO date (the
                          picker's "due date" filter).
          - `event_start`/`event_end` -- events only: start_at within this
                          ISO-date range.

        Implicit (applied by the caller, see the spec's "implicit" list):
          - `exclude_uids`     -- {type: {uid, ...}} of already-linked items to
                          drop ("not-already-linked" for the relation picker).
          - `include_habit_tasks` -- False hides habit-labeled tasks, the same
                          default list_tasks applies everywhere.
          - `exclude_past_events` -- events only: drop anything that already
                          started before today. Command palette browsing -- the default empty-query view on open
                          shouldn't be cluttered with events that have already
                          happened; a real typed query still surfaces them
                          (routers/search.py only sets this when `q` is empty).

        Returns a flat list of result dicts, one per hit, ordered by type
        (tasks, events, contacts) and then by that type's natural order; each
        carries a `type` tag plus a compact title/subtitle/tags surface for the
        picker plus the full row under `entity`:
          {"type": ..., "uid": ..., "title": ..., "subtitle": ..., "tags": [...], "entity": {...}}
    """
    wanted = set(types or ())
    # Implicit type restriction (the spec's "type" implicit filter): a
    # type-specific filter like task_status/due only ever applies to that
    # type, so supplying one narrows the search to it even when `types`
    # wasn't passed -- the same way the relation picker pre-sets its type.
    if task_status or task_due_on:
        wanted = {"task"} if not wanted else wanted & {"task"}
    if event_start or event_end:
        wanted = {"event"} if not wanted else wanted & {"event"}
    result: list[dict[str, Any]] = []
    exclude = exclude_uids or {}

    if not wanted or "task" in wanted:
        result.extend(_search_tasks(conn, q, labels, task_status, task_due_on, exclude.get("task", set()), include_habit_tasks))
    if not wanted or "event" in wanted:
        result.extend(_search_events(conn, q, labels, event_start, event_end, exclude.get("event", set()), exclude_past_events))
    if not wanted or "contact" in wanted:
        result.extend(_search_contacts(conn, q, labels, exclude.get("contact", set())))

    if limit is not None:
        result = result[:limit]
    return result


def upsert_push_subscription(
    conn: sqlite3.Connection, endpoint: str, p256dh: str, auth: str, user_agent: str | None, now: str
) -> None:
    """Web Push P1: store (or refresh the keys of) one device's subscription."""
    conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth, user_agent=excluded.user_agent",
        (endpoint, p256dh, auth, user_agent, now),
    )
    conn.commit()


def list_push_subscriptions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM push_subscriptions ORDER BY created_at").fetchall()]


def delete_push_subscription(conn: sqlite3.Connection, endpoint: str) -> None:
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()


def mark_push_subscription_ok(conn: sqlite3.Connection, endpoint: str, now: str) -> None:
    conn.execute("UPDATE push_subscriptions SET last_ok_at = ? WHERE endpoint = ?", (now, endpoint))
    conn.commit()


def push_was_sent(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM push_sent WHERE key = ?", (key,)).fetchone() is not None


def record_push_sent(conn: sqlite3.Connection, key: str, when: str) -> None:
    conn.execute("INSERT OR IGNORE INTO push_sent (key, sent_at) VALUES (?, ?)", (key, when))
    conn.commit()


def prune_push_sent(conn: sqlite3.Connection, before: str) -> None:
    conn.execute("DELETE FROM push_sent WHERE sent_at < ?", (before,))
    conn.commit()


# --------------------------------------------------------------------- #
# Published Lists (Phase 6, label-space rework) -- CRUD only. The boolean
# filter evaluator and the materializer that actually pushes rows to
# Radicale live in src/published_lists.py (pure logic + bridge I/O, kept
# out of this module the same way ical_rows.py/vcard_rows.py stayed
# separate from db.py's own CRUD).
# --------------------------------------------------------------------- #


def upsert_published_list(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    if "label_filter" in data:
        data["label_filter_json"] = json.dumps(data.pop("label_filter"))
    cols = [
        "id", "name", "entity_type", "label_filter_json",
        "radicale_collection_path", "sync_direction",
        "last_materialized_at", "created_at",
        "visibility", "public_token", "contact_name_field",
    ]
    data.setdefault("contact_name_field", "full_name")
    data.setdefault("sync_direction", "read_only")
    data.setdefault("visibility", "private")
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO published_lists ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _published_list_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["label_filter"] = json.loads(d.pop("label_filter_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["label_filter"] = {"all": [], "any": [], "none": []}
    return d


def get_published_list(conn: sqlite3.Connection, list_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM published_lists WHERE id = ?", (list_id,)).fetchone()
    return _published_list_row_to_dict(row) if row else None


def list_published_lists(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM published_lists ORDER BY name COLLATE NOCASE").fetchall()
    return [_published_list_row_to_dict(r) for r in rows]


def set_published_list_materialized_at(conn: sqlite3.Connection, list_id: str, when: str) -> None:
    conn.execute(
        "UPDATE published_lists SET last_materialized_at = ? WHERE id = ?", (when, list_id)
    )
    conn.commit()


def get_published_list_by_token(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    """The row a public feed request (routers/public_lists.py) looks up
    by its `public_token`. Does NOT filter on `visibility` here -- the
    caller must check `row["visibility"] == "public"` itself and 404
    otherwise, so a list that was switched back to private/archived after
    being shared correctly stops serving even though the token row still
    exists (the token is never cleared, only gated by visibility -- see
    the migration's comment)."""
    if not token:
        return None
    row = conn.execute(
        "SELECT * FROM published_lists WHERE public_token = ?", (token,)
    ).fetchone()
    return _published_list_row_to_dict(row) if row else None


def set_published_list_visibility(
    conn: sqlite3.Connection, list_id: str, visibility: str, public_token: str | None = None
) -> None:
    """Targeted update for a visibility transition (routers/
    published_lists.py's visibility route) -- deliberately NOT routed
    through upsert_published_list, which requires re-supplying every
    column (name, label_filter, ...) on every call; a visibility toggle
    only ever touches these two columns. `public_token` is only written
    when the caller passes one (generated once, the first time a list
    becomes public -- see published_lists.py); passing None here leaves
    whatever token already exists untouched rather than clearing it."""
    if public_token is not None:
        conn.execute(
            "UPDATE published_lists SET visibility = ?, public_token = ? WHERE id = ?",
            (visibility, public_token, list_id),
        )
    else:
        conn.execute(
            "UPDATE published_lists SET visibility = ? WHERE id = ?", (visibility, list_id)
        )
    conn.commit()


def delete_published_list(conn: sqlite3.Connection, list_id: str) -> None:
    """A real delete -- see the CREATE TABLE comment above. Only removes
    this row; the caller (routers/published_lists.py) is responsible for
    also tearing down the actual Radicale collection via the bridge,
    same division of responsibility as delete_calendar_collection/
    delete_addressbook_collection used to have."""
    conn.execute("DELETE FROM published_lists WHERE id = ?", (list_id,))
    conn.commit()


def get_server_hlc_clock(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """The server's own HLC clock as (physical, logical) -- the stored
    state merge_server_hlc/mint_server_hlc read-modify-write. None before
    the server has ever minted or merged a write."""
    raw = get_app_meta(conn, _SERVER_HLC_KEY)
    if not raw:
        return None
    try:
        clock = json.loads(raw)
        return (clock[0], clock[1])
    except (TypeError, ValueError, IndexError):
        return None


def _put_server_hlc_clock(conn: sqlite3.Connection, clock: tuple[int, int]) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_SERVER_HLC_KEY, json.dumps([clock[0], clock[1]])),
    )


def merge_server_hlc(conn: sqlite3.Connection, observed: tuple[int, int, str]) -> None:
    """§3's receive-side HLC merge, applied whenever the server applies a
    device op (offline_sync.apply_op): advance the server's clock past
    what it just observed so its own next minted write outranks it."""
    prev = get_server_hlc_clock(conn) or (0, 0)
    if observed[0] == prev[0]:
        logical = max(prev[1], observed[1]) + 1
    elif observed[0] > prev[0]:
        logical = observed[1] + 1
    else:
        logical = prev[1]
    _put_server_hlc_clock(conn, (max(prev[0], observed[0]), logical))


def mint_server_hlc(conn: sqlite3.Connection) -> tuple[int, int, str]:
    """Mints a fresh server HLC -- the timestamp every server-written field
    change is recorded under. Physical time never goes backwards (the
    clock is monotonic across the process's own writes and every device op
    it has observed via merge_server_hlc), and two server writes within
    the same millisecond get distinct logical values."""
    prev = get_server_hlc_clock(conn) or (0, 0)
    now = int(time.time() * 1000)
    if prev[0] >= now:
        physical, logical = prev[0], prev[1] + 1
    else:
        physical, logical = now, 0
    _put_server_hlc_clock(conn, (physical, logical))
    return (physical, logical, SERVER_DEVICE_ID)


def record_server_sync_write(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    hlc: tuple[int, int, str] | None = None,
) -> None:
    """Records a server-side UI write into field_versions (the server-as-
    author mechanism above). Diffs the entity's sync-whitelist columns
    before vs. after the write and records each one that actually changed
    under a single server HLC -- recording every column unconditionally
    would overwrite a device's newer HLC on fields the server didn't touch
    (see the module comment), so only real changes move the field HLCs.
    Bumps the sync data version iff anything was recorded, exactly like a
    device push that changed state. `hlc` lets a caller seed with a known
    clock value instead of minting one (tests seeding pre-sync data)."""
    fields = ENTITY_SYNC_FIELDS.get(entity_type)
    if not fields or not current:
        return
    changed = [
        f
        for f in fields
        if f in current and (previous or {}).get(f) != current[f]
    ]
    if not changed:
        return
    if hlc is None:
        hlc = mint_server_hlc(conn)
    for f in changed:
        set_field_hlc(conn, entity_type, entity_uid, f, hlc)
    bump_sync_data_version(conn)


def record_server_delete(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    *,
    hlc: tuple[int, int, str] | None = None,
) -> None:
    """Records a server-side hard delete as a `deleted_at` field_versions
    entry -- the same tombstone a device's delete op creates, but with no
    stored value (the entity row is physically removed, unlike a sync
    soft-delete). offline_sync.pull() synthesizes a truthy deleted_at for
    a missing row (see _current_field_value), so a device's mirror learns
    "this entity is gone" and hides it. `hlc` lets a caller seed with a
    known clock value instead of minting one."""
    if hlc is None:
        hlc = mint_server_hlc(conn)
    set_field_hlc(conn, entity_type, entity_uid, "deleted_at", hlc)
    bump_sync_data_version(conn)


def backfill_server_sync_writes(conn: sqlite3.Connection) -> None:
    """One-time: records every existing task/event/contact's sync-whitelist
    columns into field_versions under a single server HLC, so a device's
    very first pull delivers the full pre-existing dataset. `INSERT OR
    IGNORE` (the field_versions primary key is entity_type+entity_uid+
    field_name) means a field a device has already synced keeps its own
    HLC untouched -- the backfill only ever adds *missing* entries and
    never overwrites device state. Idempotent: the app_meta marker is set
    even when there was nothing to backfill (a fresh database), so the
    scan never re-runs; the data version only moves when something was
    actually inserted."""
    if get_app_meta(conn, _SERVER_WRITES_BACKFILLED_KEY):
        return
    hlc = mint_server_hlc(conn)
    inserted = 0
    for entity_type, table in ENTITY_TABLES.items():
        uids = conn.execute(f"SELECT uid FROM {table}").fetchall()
        for (uid,) in uids:
            for field_name in ENTITY_SYNC_FIELDS[entity_type]:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO field_versions "
                    "(entity_type, entity_uid, field_name, hlc_physical, hlc_logical, hlc_device_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (entity_type, uid, field_name, hlc[0], hlc[1], hlc[2]),
                )
                inserted += cur.rowcount
    set_app_meta(conn, _SERVER_WRITES_BACKFILLED_KEY, "1")
    if inserted:
        bump_sync_data_version(conn)


def get_sync_applied_op(conn: sqlite3.Connection, op_id: str) -> dict[str, Any] | None:
    """§5's idempotency lookup -- a cached result means this exact op_id
    was already applied and should not be re-applied on a retried push."""
    row = conn.execute(
        "SELECT result_json FROM sync_applied_ops WHERE op_id = ?", (op_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def record_sync_applied_op(
    conn: sqlite3.Connection,
    op_id: str,
    entity_type: str,
    entity_uid: str,
    result: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sync_applied_ops (op_id, entity_type, entity_uid, result_json, applied_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (op_id, entity_type, entity_uid, json.dumps(result), datetime.now(timezone.utc).isoformat()),
    )


def get_sync_device(conn: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT device_id, last_pushed_physical, last_pushed_logical, last_pushed_device_id, "
        "last_pulled_physical, last_pulled_logical, last_pulled_device_id, last_seen_at "
        "FROM sync_devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "device_id": row[0],
        "last_pushed_hlc": (row[1], row[2], row[3]) if row[1] is not None else None,
        "last_pulled_hlc": (row[4], row[5], row[6]) if row[4] is not None else None,
        "last_seen_at": row[7],
    }


_SYNC_DATA_VERSION_KEY = "sync_data_version"


def get_sync_data_version(conn: sqlite3.Connection) -> int:
    """The server's current data version -- 0 before any sync write has
    ever been applied. Compared client-side (offline_sync_client.js's
    round-skip pre-check) against the version the device saved the last
    time it pulled successfully."""
    raw = get_app_meta(conn, _SYNC_DATA_VERSION_KEY)
    return int(raw) if raw else 0


def bump_sync_data_version(conn: sqlite3.Connection) -> int:
    """Advances the version by one and commits. Called once per batch
    (offline_sync.apply_batch) when at least one op in it actually
    changed server state, and by purge_expired when GC physically removes
    anything -- so the version changes iff a pull would return something
    new (or force a resync), and never regresses."""
    version = get_sync_data_version(conn) + 1
    set_app_meta(conn, _SYNC_DATA_VERSION_KEY, str(version))
    return version


def touch_sync_device(
    conn: sqlite3.Connection,
    device_id: str,
    last_pushed_hlc: tuple[int, int, str] | None = None,
    last_pulled_hlc: tuple[int, int, str] | None = None,
) -> None:
    """Upserts `sync_devices`. Either HLC arg may be omitted (a push-only
    or pull-only round keeps the other field as it already was) -- uses
    `COALESCE(excluded.x, sync_devices.x)` so a NULL passed through
    `excluded` (arg omitted) doesn't clobber a previously-recorded value."""
    now = datetime.now(timezone.utc).isoformat()
    pushed = last_pushed_hlc or (None, None, None)
    pulled = last_pulled_hlc or (None, None, None)
    conn.execute(
        "INSERT INTO sync_devices (device_id, last_pushed_physical, last_pushed_logical, "
        "last_pushed_device_id, last_pulled_physical, last_pulled_logical, last_pulled_device_id, "
        "last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET "
        "last_pushed_physical=COALESCE(excluded.last_pushed_physical, sync_devices.last_pushed_physical), "
        "last_pushed_logical=COALESCE(excluded.last_pushed_logical, sync_devices.last_pushed_logical), "
        "last_pushed_device_id=COALESCE(excluded.last_pushed_device_id, sync_devices.last_pushed_device_id), "
        "last_pulled_physical=COALESCE(excluded.last_pulled_physical, sync_devices.last_pulled_physical), "
        "last_pulled_logical=COALESCE(excluded.last_pulled_logical, sync_devices.last_pulled_logical), "
        "last_pulled_device_id=COALESCE(excluded.last_pulled_device_id, sync_devices.last_pulled_device_id), "
        "last_seen_at=excluded.last_seen_at",
        (device_id, *pushed, *pulled, now),
    )


def list_sync_devices(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT device_id, last_pushed_physical, last_pushed_logical, last_pushed_device_id, "
        "last_pulled_physical, last_pulled_logical, last_pulled_device_id, last_seen_at "
        "FROM sync_devices ORDER BY last_seen_at DESC"
    ).fetchall()
    return [
        {
            "device_id": row[0],
            "last_pushed_hlc": (row[1], row[2], row[3]) if row[1] is not None else None,
            "last_pulled_hlc": (row[4], row[5], row[6]) if row[4] is not None else None,
            "last_seen_at": row[7],
        }
        for row in rows
    ]


def create_sync_conflict(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    field_name: str,
    losing_value: Any,
    losing_hlc: tuple[int, int, str],
    winning_hlc: tuple[int, int, str],
) -> str:
    import uuid

    conflict_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_conflicts (id, entity_type, entity_uid, field_name, losing_value, "
        "losing_hlc, winning_hlc, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conflict_id, entity_type, entity_uid, field_name,
            None if losing_value is None else str(losing_value),
            _hlc_to_str(losing_hlc), _hlc_to_str(winning_hlc),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return conflict_id


def get_sync_conflict(conn: sqlite3.Connection, conflict_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sync_conflicts WHERE id = ?", (conflict_id,)).fetchone()
    return dict(row) if row else None


def list_sync_conflicts(conn: sqlite3.Connection, unresolved_only: bool = True) -> list[dict[str, Any]]:
    query = "SELECT * FROM sync_conflicts"
    if unresolved_only:
        query += " WHERE resolved_at IS NULL"
    query += " ORDER BY created_at DESC"
    return [dict(r) for r in conn.execute(query).fetchall()]


def resolve_sync_conflict(conn: sqlite3.Connection, conflict_id: str) -> None:
    """Dismiss -- the losing value is discarded for good, `resolved_at`
    set. Restoring the losing value instead is not a special "resolve"
    variant: it's a normal new `field_set` op with a fresh HLC (routers/
    settings.py's own restore action), applied through the same apply_op
    path as any other write, followed by this same dismissal call."""
    conn.execute(
        "UPDATE sync_conflicts SET resolved_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), conflict_id),
    )
    conn.commit()
