"""Settings: Published Lists -- share a filtered subset of your data via a unique link.

This is a clean, minimalist sharing tool -- not a server administration panel.
All lists are shareable by default (read-only). No public/private toggle,
no advanced options, no technical jargon.
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


def _filter_from_form(labels: list[str]) -> dict:
    """Simple filter: items matching ANY selected label."""
    return {"any": [n for n in labels if n]}


def _delete_collection(bridge, entity_type: str, collection_path: str) -> None:
    if entity_type == "task":
        bridge.delete_task_list_collection(collection_path)
    elif entity_type == "event":
        bridge.delete_calendar_collection(collection_path)
    elif entity_type == "contact":
        bridge.delete_addressbook_collection(collection_path)


def _require_bridge(bridge) -> None:
    """Published Lists are materialized into a real Radicale collection, so
    every mutating route needs the bridge -- but the app now boots without
    one (main.py's lifespan sets bridge=None when Radicale is unreachable;
    see routers/tasks.py's "no bridge in this path anymore" notes). Fail
    cleanly instead of crashing on a None attribute."""
    if bridge is None:
        raise HTTPException(status_code=503, detail="Sync server is not reachable")


@router.get("")
def list_index(request: Request, conn=Depends(get_db)):
    lists = db.list_published_lists(conn)
    base_url = request.app.state.settings.radicale_base_url
    for row in lists:
        row["subscribe_url"] = collection_url(base_url, row["entity_type"], row["radicale_collection_path"])
        # Convert label_filter to simple label list for display
        if "label_filter" in row and isinstance(row["label_filter"], dict):
            row["filter_labels"] = row["label_filter"].get("any", [])
        else:
            row["filter_labels"] = []
    return templates.TemplateResponse(
        "published_lists.html",
        {
            "request": request,
            "active_tab": "published_lists",
            "crumbs": [{"url": "/settings", "name": "Settings"}],
            "title": "Published Lists",
            "lists": lists,
            "all_labels": db.list_all_label_names(conn),
            "entity_types": ENTITY_TYPES,
            "entity_labels": ENTITY_LABELS,
        },
    )


@router.get("/new")
def new_list_modal(request: Request, conn=Depends(get_db)):
    """Modal entry point for creating a new published list."""
    labels = db.list_all_label_names(conn)
    return templates.TemplateResponse(
        "published_list_create_modal.html",
        {
            "request": request,
            "all_labels": labels,
            "entity_types": ENTITY_TYPES,
            "entity_labels": ENTITY_LABELS,
        },
    )


@router.post("/create")
def create_list(
    name: str = Form(...),
    entity_type: str = Form(...),
    labels: list[str] = Form([]),
    conn=Depends(get_db),
    bridge=Depends(get_bridge),
):
    name = (name or "").strip()
    if not name or entity_type not in ENTITY_TYPES:
        return RedirectResponse(url="/published-lists", status_code=303)
    _require_bridge(bridge)
    list_id = uuid.uuid4().hex
    collection_path = _unique_collection_path(conn, name)
    row = {
        "id": list_id,
        "name": name,
        "entity_type": entity_type,
        "label_filter": _filter_from_form(labels),
        "radicale_collection_path": collection_path,
        "sync_direction": "read_only",
        "created_at": _now(),
    }
    db.upsert_published_list(conn, row)
    saved = db.get_published_list(conn, list_id)
    materialize(conn, bridge, saved)
    return RedirectResponse(url="/published-lists", status_code=303)


@router.post("/{list_id}/delete")
def delete_list(list_id: str, conn=Depends(get_db), bridge=Depends(get_bridge)):
    """Delete a published list and its Radicale collection."""
    existing = db.get_published_list(conn, list_id)
    if existing is not None:
        _require_bridge(bridge)
        _delete_collection(bridge, existing["entity_type"], existing["radicale_collection_path"])
        db.delete_published_list(conn, list_id)
    return RedirectResponse(url="/published-lists", status_code=303)