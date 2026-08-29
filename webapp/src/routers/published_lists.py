"""Settings: Published Lists -- share a filtered subset of your data via a
unique link.

This is a clean, minimalist sharing tool -- not a server administration
panel. A List has one of three visibility states (2026-08-29):

  - `private` (default) -- the original behavior: materialized into a
    Radicale collection, reachable only by whoever has the shared
    Radicale/CalDAV account (CC_RADICALE_USER/PASSWORD). Not reachable via
    the standalone public link below.
  - `public` -- everything `private` gets, PLUS a standalone, unguessable
    link (`GET /public/lists/{token}.ics`/`.vcf`, routers/public_lists.py)
    that serves a live read-only feed with no login and no Radicale
    account needed -- works even when Radicale isn't configured at all,
    since the public feed is generated on demand from the same label
    filter, not read back out of the Radicale collection. This is the
    "share with a friend/colleague" case.
  - `archived` -- paused. Its Radicale collection is torn down and the
    public link (if any) stops serving, but the List's own definition
    (name, filter, and its `public_token` if it had one) stays in the
    database so re-activating it later doesn't need reconfiguring.

Radicale is optional for this whole feature now -- every mutating route
below is best-effort about the bridge (materialize/teardown are skipped,
not hard failures, when bridge is None), so creating/sharing a List works
on an install that never configured Radicale at all.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates
from ..published_lists import collection_url, materialize, new_public_token, teardown_collection

router = APIRouter(prefix="/published-lists", tags=["published-lists"])
logger = logging.getLogger(__name__)

ENTITY_TYPES = ["task", "event", "contact"]
ENTITY_LABELS = {"task": "Tasks", "event": "Events", "contact": "Contacts"}
VISIBILITIES = ["private", "public", "archived"]
_PUBLIC_FEED_EXT = {"task": "ics", "event": "ics", "contact": "vcf"}

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


def _public_feed_url(request: Request, row: dict) -> str | None:
    """The standalone public link for a `visibility == "public"` row, or
    None otherwise. Built off the request's own base URL, not the
    Radicale base URL (`collection_url` below) -- this feed is served by
    this app directly, independent of Radicale."""
    if row.get("visibility") != "public" or not row.get("public_token"):
        return None
    ext = _PUBLIC_FEED_EXT[row["entity_type"]]
    return str(request.base_url).rstrip("/") + f"/public/lists/{row['public_token']}.{ext}"


def _try_materialize(conn, bridge, list_id: str) -> None:
    """Best-effort re-materialize (un-archiving, or a fresh public/private
    List) -- Radicale being unreachable here must not block the visibility
    change itself, which has already been committed to the DB by the time
    this runs; the next successful background sync tick
    (published_lists.materialize_all) will catch it up regardless."""
    if bridge is None:
        return
    try:
        saved = db.get_published_list(conn, list_id)
        if saved is not None:
            materialize(conn, bridge, saved)
    except Exception:
        logger.exception("Best-effort materialize failed for published list %s", list_id)


def _try_teardown(bridge, entity_type: str, collection_path: str) -> None:
    """Best-effort Radicale collection teardown -- see _try_materialize's
    reasoning. A failed teardown here leaves a stale (but no-longer-
    updated) Radicale collection behind until the operator retries;
    that's a lesser problem than refusing to archive/delete the List at
    all over a transient Radicale hiccup."""
    try:
        teardown_collection(bridge, entity_type, collection_path)
    except Exception:
        logger.exception(
            "Best-effort Radicale collection teardown failed (%s, %s)", entity_type, collection_path
        )


@router.get("")
def list_index(request: Request, conn=Depends(get_db)):
    lists = db.list_published_lists(conn)
    base_url = request.app.state.settings.radicale_base_url
    for row in lists:
        row["subscribe_url"] = collection_url(base_url, row["entity_type"], row["radicale_collection_path"])
        row["public_url"] = _public_feed_url(request, row)
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
            "visibilities": VISIBILITIES,
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
    visibility: str = Form("private"),
    conn=Depends(get_db),
    bridge=Depends(get_bridge),
):
    name = (name or "").strip()
    if not name or entity_type not in ENTITY_TYPES:
        return RedirectResponse(url="/published-lists", status_code=303)
    if visibility not in VISIBILITIES:
        visibility = "private"
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
        "visibility": visibility if visibility != "archived" else "private",
        "public_token": new_public_token() if visibility == "public" else None,
    }
    db.upsert_published_list(conn, row)
    # Radicale is optional (module docstring) -- a List is saved and
    # shareable (if public) regardless of whether the bridge is up;
    # materializing into Radicale is best-effort on top of that.
    _try_materialize(conn, bridge, list_id)
    return RedirectResponse(url="/published-lists", status_code=303)


@router.post("/{list_id}/visibility")
def set_visibility(list_id: str, visibility: str = Form(...), conn=Depends(get_db), bridge=Depends(get_bridge)):
    """Change a List's visibility (private/public/archived, see the
    module docstring). The DB write always succeeds regardless of
    Radicale's reachability; the Radicale-side effect (tearing down the
    collection on archive, re-materializing on un-archive) is best-effort
    on top of it, same reasoning as create_list."""
    existing = db.get_published_list(conn, list_id)
    if existing is None or visibility not in VISIBILITIES:
        return RedirectResponse(url="/published-lists", status_code=303)

    old_visibility = existing.get("visibility") or "private"
    public_token = None
    if visibility == "public" and not existing.get("public_token"):
        public_token = new_public_token()
    db.set_published_list_visibility(conn, list_id, visibility, public_token)

    if old_visibility != "archived" and visibility == "archived":
        _try_teardown(bridge, existing["entity_type"], existing["radicale_collection_path"])
    elif old_visibility == "archived" and visibility != "archived":
        _try_materialize(conn, bridge, list_id)

    return RedirectResponse(url="/published-lists", status_code=303)


@router.post("/{list_id}/delete")
def delete_list(list_id: str, conn=Depends(get_db), bridge=Depends(get_bridge)):
    """Permanently delete a published list and its Radicale collection
    (best-effort -- see the module docstring; the DB row is removed
    either way)."""
    existing = db.get_published_list(conn, list_id)
    if existing is not None:
        _try_teardown(bridge, existing["entity_type"], existing["radicale_collection_path"])
        db.delete_published_list(conn, list_id)
    return RedirectResponse(url="/published-lists", status_code=303)