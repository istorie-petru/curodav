"""Settings: Published Lists (Phase 6, label-space rework) -- create/edit/
delete a named boolean-filter-over-labels subset of the pool, materialized
into a real Radicale collection and published as a subscribable CalDAV/
CardDAV URL. See plans/label-space-rework.md §2/§3 Phase 6 and
src/published_lists.py for the filter evaluator + materializer this
router drives.

Unlike a label (routers/labels.py -- no delete endpoint, "removing" just
clears membership everywhere), a published List is a real thing with a
lifecycle: `delete_list` below is a genuine delete, tearing down both the
`published_lists` row AND the actual Radicale collection via the bridge.

v1 is read-only-from-the-subscriber's-side only (sync_direction is always
"read_only" here -- there's no UI to pick anything else) -- see
src/published_lists.py's own module docstring for why nothing here ever
parses a subscriber's edit back into a row.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates
from ..published_lists import collection_url, materialize

router = APIRouter(prefix="/published-lists", tags=["published-lists"])

ENTITY_TYPES = ["task", "event", "contact"]
ENTITY_LABELS = {"task": "Tasks", "event": "Events", "contact": "Contacts"}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "list"


def _unique_collection_path(conn, name: str, existing_id: str | None = None) -> str:
    """`published-{slug}` -- namespaced so a List's derived collection can
    never collide with the base pool's own default collection names
    (`calendar`/`tasks`/`contacts`, see config.py) or with another List's.
    Appends -2/-3/... on a slug collision with a *different* List (editing
    a List's own name keeps its existing collection path, handled by the
    caller passing `existing_id`)."""
    base = f"published-{_slugify(name)}"
    candidate = base
    n = 2
    taken = {
        row["radicale_collection_path"]
        for row in db.list_published_lists(conn)
        if row["id"] != existing_id
    }
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _filter_from_form(all_labels: list[str], any_labels: list[str], none_labels: list[str]) -> dict:
    return {
        "all": [n for n in all_labels if n],
        "any": [n for n in any_labels if n],
        "none": [n for n in none_labels if n],
    }


def _delete_collection(bridge, entity_type: str, collection_path: str) -> None:
    if entity_type == "task":
        bridge.delete_task_list_collection(collection_path)
    elif entity_type == "event":
        bridge.delete_calendar_collection(collection_path)
    elif entity_type == "contact":
        bridge.delete_addressbook_collection(collection_path)


@router.get("")
def list_index(request: Request, conn=Depends(get_db)):
    lists = db.list_published_lists(conn)
    base_url = request.app.state.settings.radicale_base_url
    for row in lists:
        row["subscribe_url"] = collection_url(base_url, row["entity_type"], row["radicale_collection_path"])
    return templates.TemplateResponse(
        "published_lists.html",
        {
            "request": request,
            "active_tab": "published_lists",
            # 2026-08-08: promoted to a direct Settings hub category (was
            # nested under "Data & backup," now deleted -- see
            # routers/settings.py's module docstring).
            "crumbs": [{"url": "/settings", "name": "Settings"}],
            "title": "Published lists",
            "lists": lists,
            "all_labels": db.list_all_label_names(conn),
            "entity_types": ENTITY_TYPES,
            "entity_labels": ENTITY_LABELS,
        },
    )


@router.post("/create")
def create_list(
    name: str = Form(...),
    entity_type: str = Form(...),
    filter_all: list[str] = Form([]),
    filter_any: list[str] = Form([]),
    filter_none: list[str] = Form([]),
    conn=Depends(get_db),
    bridge=Depends(get_bridge),
):
    name = (name or "").strip()
    if not name or entity_type not in ENTITY_TYPES:
        return RedirectResponse(url="/published-lists", status_code=303)
    list_id = uuid.uuid4().hex
    collection_path = _unique_collection_path(conn, name)
    row = {
        "id": list_id,
        "name": name,
        "entity_type": entity_type,
        "label_filter": _filter_from_form(filter_all, filter_any, filter_none),
        "radicale_collection_path": collection_path,
        "sync_direction": "read_only",
        "created_at": _now(),
    }
    db.upsert_published_list(conn, row)
    saved = db.get_published_list(conn, list_id)
    materialize(conn, bridge, saved)
    return RedirectResponse(url="/published-lists", status_code=303)


@router.post("/{list_id}/set")
def update_list(
    list_id: str,
    name: str = Form(...),
    filter_all: list[str] = Form([]),
    filter_any: list[str] = Form([]),
    filter_none: list[str] = Form([]),
    conn=Depends(get_db),
    bridge=Depends(get_bridge),
):
    existing = db.get_published_list(conn, list_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Published list not found")
    name = (name or "").strip() or existing["name"]
    db.upsert_published_list(
        conn,
        {
            "id": list_id,
            "name": name,
            "entity_type": existing["entity_type"],
            "label_filter": _filter_from_form(filter_all, filter_any, filter_none),
            # entity_type/radicale_collection_path never change after
            # creation -- a List is scoped to exactly one entity type for
            # its whole life (§3 Phase 6: "a List is scoped to exactly one"),
            # and re-slugging the collection path on a rename would break
            # any subscriber already pointed at the old URL.
            "radicale_collection_path": existing["radicale_collection_path"],
            "sync_direction": existing["sync_direction"],
            "created_at": existing["created_at"],
        },
    )
    saved = db.get_published_list(conn, list_id)
    materialize(conn, bridge, saved)
    return RedirectResponse(url="/published-lists", status_code=303)


@router.post("/{list_id}/delete")
def delete_list(list_id: str, conn=Depends(get_db), bridge=Depends(get_bridge)):
    """The one real "delete" left in this whole plan (§3 Phase 6) -- stops
    materializing this List AND removes its actual Radicale collection,
    unlike a label's "clear" (routers/labels.py) which only empties
    membership and never deletes anything."""
    existing = db.get_published_list(conn, list_id)
    if existing is not None:
        _delete_collection(bridge, existing["entity_type"], existing["radicale_collection_path"])
        db.delete_published_list(conn, list_id)
    return RedirectResponse(url="/published-lists", status_code=303)


@router.post("/{list_id}/resync")
def resync_list(list_id: str, conn=Depends(get_db), bridge=Depends(get_bridge)):
    """Manual "sync now" -- the background thread (sync.py) already
    materializes every List on a timer, this just lets a user force an
    immediate re-check right after editing labels, instead of waiting out
    the interval."""
    existing = db.get_published_list(conn, list_id)
    if existing is not None:
        materialize(conn, bridge, existing)
    return RedirectResponse(url="/published-lists", status_code=303)
