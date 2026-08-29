"""Published Lists (Phase 6, label-space rework) -- the one feature this
plan's whole rework was ultimately building toward: Settings lets the user
define a named boolean filter over labels, for exactly one entity type
(task/event/contact), and the app keeps a real Radicale collection in sync
with whatever currently matches that filter, publishing a subscribable
CalDAV/CardDAV URL. Read-only from the subscriber's side in this version --
this module only ever pushes rows *to* Radicale (`bridge.save_*_row`),
never parses anything back out of the published collection into a row (no
`ical_to_*_row`/`vcard_to_contact_row` call anywhere below) -- a client
that edits through the published URL will have its edit silently
overwritten on the next materialize() tick, by design, not a bug to fix
later without a real sync_direction="two_way" mode.

Two pieces, kept pure/testable separately:

  * `evaluate_label_filter` -- pure function over `object_labels`, no I/O
    beyond read-only SQL. Takes the small structured filter dict
    (`{"all": [...], "any": [...], "none": [...]}, not a query language --
    see db.py's `published_lists` table comment) and returns the current
    set of matching object ids.
  * `materialize` -- the actual sync: evaluate the filter, diff the
    resulting member set against what's currently in the target Radicale
    collection (via the bridge's existing `list_*_rows` methods -- already
    multi-collection capable, no bridge changes needed for this), and push
    creates/updates/deletes to make them equal. Idempotent -- calling it
    twice in a row with no membership change pushes the same rows again
    (a harmless PUT-with-same-content) and deletes nothing new.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import db


def evaluate_label_filter(
    conn: sqlite3.Connection, entity_type: str, filter_dict: dict[str, Any] | None
) -> list[str]:
    """Boolean label expression, structured not a query language (§5 of
    the plan doc): AND of everything in `all`, OR (at least one) of
    `any` if non-empty, then NOT any of `none` subtracted at the end.
    `all`/`any` are combined with AND between the two groups when both
    are given (e.g. `all=["University"], any=["Homework","Exam"]` means
    University AND (Homework OR Exam)). Neither `all` nor `any` given at
    all means "no positive criterion" -- returns nothing, rather than
    guessing "everything," since a List with zero criteria publishing the
    entire pool would be a surprising default for something meant to be a
    narrow, curated subscription."""
    filter_dict = filter_dict or {}
    all_names = [n for n in (filter_dict.get("all") or []) if n]
    any_names = [n for n in (filter_dict.get("any") or []) if n]
    none_names = [n for n in (filter_dict.get("none") or []) if n]

    if not all_names and not any_names:
        return []

    candidate_ids: set[str] | None = None

    if all_names:
        for name in all_names:
            ids = set(db.list_object_ids_for_label(conn, entity_type, name))
            candidate_ids = ids if candidate_ids is None else candidate_ids & ids

    if any_names:
        any_ids: set[str] = set()
        for name in any_names:
            any_ids |= set(db.list_object_ids_for_label(conn, entity_type, name))
        candidate_ids = any_ids if candidate_ids is None else candidate_ids & any_ids

    result: set[str] = candidate_ids or set()

    if none_names:
        exclude_ids: set[str] = set()
        for name in none_names:
            exclude_ids |= set(db.list_object_ids_for_label(conn, entity_type, name))
        result -= exclude_ids

    return sorted(result)


_GETTERS = {
    "task": db.get_task,
    "event": db.get_event,
    "contact": db.get_contact,
}
_LIST_ROWS = {
    "task": lambda bridge, path: bridge.list_task_rows(path),
    "event": lambda bridge, path: bridge.list_event_rows(path),
    "contact": lambda bridge, path: bridge.list_contact_rows(path),
}
_SAVE_ROW = {
    "task": lambda bridge, row: bridge.save_task_row(row),
    "event": lambda bridge, row: bridge.save_event_row(row),
    "contact": lambda bridge, row: bridge.save_contact_row(row),
}
_DELETE = {
    "task": lambda bridge, uid, path: bridge.delete_task(uid, path),
    "event": lambda bridge, uid, path: bridge.delete_event(uid, path),
    "contact": lambda bridge, uid, path: bridge.delete_contact(uid, path),
}
_PATH_FIELD = {
    "task": "list_path",
    "event": "calendar_path",
    "contact": "addressbook_path",
}


def materialize(conn: sqlite3.Connection, bridge: Any, list_row: dict[str, Any]) -> dict[str, int]:
    """Given one `published_lists` row (as returned by db.get_published_list
    /list_published_lists -- `label_filter` already decoded), evaluate its
    filter, then make the target Radicale collection's contents equal to
    the current member set. Returns a summary dict
    ({"created", "updated", "deleted", "member_count"}) for logging/tests.

    Safe to call repeatedly (idempotent): a second call with no membership
    change re-pushes every member (harmless, same content) and deletes
    nothing further."""
    entity_type = list_row["entity_type"]
    if entity_type not in _GETTERS:
        raise ValueError(f"unknown entity_type {entity_type!r}")
    collection_path = list_row["radicale_collection_path"]

    member_ids = set(evaluate_label_filter(conn, entity_type, list_row.get("label_filter")))
    existing_rows = _LIST_ROWS[entity_type](bridge, collection_path)
    existing_uids = {r["uid"] for r in existing_rows if r.get("uid")}

    created = updated = 0
    getter = _GETTERS[entity_type]
    path_field = _PATH_FIELD[entity_type]
    # Importance/Urgency are computed, not stored columns (side work,
    # post-1.1, src/derived_state.py) -- a task row from db.get_task no
    # longer carries them, but ical_rows.task_row_to_ical's PRIORITY
    # export still reads row.get("importance")/row.get("urgency"), so a
    # published task needs the effective values attached before the push
    # below, same as every other importance/urgency call site in this app
    # resolves label rules once rather than per row.
    label_rules = db.list_label_rules(conn) if entity_type == "task" else None
    for object_id in member_ids:
        row = getter(conn, object_id)
        if row is None:
            # Filter matched an object that vanished between evaluation and
            # push (deleted mid-materialize) -- just skip it, the next tick
            # will naturally not see it as a member either.
            continue
        if entity_type == "event" and not row.get("start_at"):
            # Undated work-session placeholders (the Work sessions "+" on a
            # task card) have no date yet -- nothing publishable until a
            # session is placed onto a grid slot. The uid stays in
            # member_ids, so this stays idempotent: it is skipped every
            # tick and never ends up in the deleted set either.
            continue
        push_row = dict(row)
        push_row[path_field] = collection_path
        if entity_type == "task":
            from . import derived_state
            push_row["importance"] = derived_state.effective_importance(row, label_rules) or None
            push_row["urgency"] = derived_state.effective_urgency(row, label_rules) or None
        _SAVE_ROW[entity_type](bridge, push_row)
        if object_id in existing_uids:
            updated += 1
        else:
            created += 1

    deleted = 0
    for stale_uid in existing_uids - member_ids:
        _DELETE[entity_type](bridge, stale_uid, collection_path)
        deleted += 1

    if list_row.get("id"):
        db.set_published_list_materialized_at(
            conn, list_row["id"], datetime.now(timezone.utc).isoformat()
        )

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "member_count": len(member_ids),
    }


def materialize_all(conn: sqlite3.Connection, bridge: Any) -> dict[str, dict[str, int]]:
    """Materializes every published List -- what sync.py's full_refresh
    calls on each periodic tick. One List's failure (e.g. a Radicale
    hiccup on that one collection) is isolated so it doesn't abort the
    rest -- same "per-collection failure isolation" principle this app's
    old multi-calendar full_refresh used to document before Phase 1
    removed that code path.

    2026-08-29: a List with `visibility == "archived"` is skipped
    entirely -- not materialized, not touched. "Archived" means paused:
    its Radicale collection was already torn down at the moment it was
    archived (routers/published_lists.py's visibility route calls
    teardown_collection there, once, rather than this function repeating
    a delete every tick), and the row itself is left alone here so
    switching back to private/public later just needs this function to
    resume normally -- no special "re-create" step, since materialize()
    already creates whatever the bridge needs on its next successful
    push, the same way a brand-new List does today."""
    import logging

    logger = logging.getLogger(__name__)
    results: dict[str, dict[str, int]] = {}
    for row in db.list_published_lists(conn):
        if row.get("visibility") == "archived":
            continue
        try:
            results[row["id"]] = materialize(conn, bridge, row)
        except Exception:
            logger.exception("Failed to materialize published list %r (%s)", row["name"], row["id"])
    return results


def collection_url(base_url: str, entity_type: str, collection_path: str) -> str:
    """Subscribable URL for a List's target collection -- same
    `{base}/{collection}/` shape CalDavBridge/CardDavClient already build
    internally (see caldav_bridge.py's CardDavClient._collection_url and
    CalDavBridge._object_url), just exposed here for the Settings UI to
    display without reaching into the bridge's private helpers."""
    base = base_url.rstrip("/")
    return f"{base}/{collection_path}/"


_DELETE_COLLECTION = {
    "task": lambda bridge, path: bridge.delete_task_list_collection(path),
    "event": lambda bridge, path: bridge.delete_calendar_collection(path),
    "contact": lambda bridge, path: bridge.delete_addressbook_collection(path),
}


def teardown_collection(bridge: Any, entity_type: str, collection_path: str) -> None:
    """Removes a List's actual Radicale collection -- shared by
    routers/published_lists.py's permanent delete route and its visibility
    route (switching a List to `archived`, see materialize_all's
    docstring above). `bridge` may be None (Radicale never configured/
    unreachable, see main.py's lifespan) -- a no-op in that case, there is
    nothing to tear down, and the caller doesn't need its own None
    check."""
    if bridge is None:
        return
    _DELETE_COLLECTION[entity_type](bridge, collection_path)


def new_public_token() -> str:
    """A random, unguessable token for a List's standalone public link
    (routers/public_lists.py) -- independent of the collection's own
    `published-{slug}` path (which IS guessable, by design, since it's
    only ever reached through the shared Radicale account, not this
    token). 32 bytes of entropy, the same `secrets.token_urlsafe` this
    app already uses for the session-signing secret (src/auth.py)."""
    import secrets

    return secrets.token_urlsafe(32)
