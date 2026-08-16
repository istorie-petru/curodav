"""Universal command surface -- 1.2 side work (plans/open.md § Universal
command surface). Step 1 (`db.search_entities`, 2026-08-13) built the query
layer; this router exposes it: a JSON API the shared picker overlay
(static/command_palette.js) calls in every one of its invocation modes, plus
a standalone `/search` page for the "no JS yet, or you just want a URL to
bookmark" case.

Two invocation shapes share one endpoint (`GET /api/search`):

  - **Global mode** -- `q`/`types`/`labels` only, no `for_task`/`for_event`.
    Used by Ctrl-K and `/search`. Returns free-standing results the caller
    navigates to.
  - **Relation-picker mode** -- `for_task=<uid>` or `for_event=<uid>` (never
    both). This is the implicit-filter case the command-surface spec
    describes: the caller only wants candidates that (a) are the other
    type, (b) share at least one label with the source object -- the
    app's one relation rule, `_shares_label` in routers/tasks.py/
    calendar.py -- and (c) aren't already linked. Replaces the old
    `linkable_events`/`linkable_tasks` context lists that routers/tasks.py
    and routers/calendar.py used to precompute and hand the template a
    full `<select>` pool for; the picker now asks for exactly the page of
    candidates it needs, filtered server-side the same way.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db
from ..deps import get_db, templates

router = APIRouter(tags=["search"])

# Page navigation (direct feedback, 2026-08-15: "I would like it to also
# allow to navigate to pages") -- global mode's results now include the
# app's own primary destinations, not just entities. A fixed list (every
# primary tabbar destination, base.html) plus every Space (generate_space=1
# label, db.list_space_labels -- a real per-install page, not a built-in
# one) matched the same substring-on-title way entities are. These are
# synthetic rows, never touched by db.search_entities/_picker_result -- a
# page isn't a database row, it has no uid/tags/status, just a title and a
# URL to navigate straight to (static/command_palette.js's selectResult
# special-cases type == "page" to a plain navigation, not CCModal.open).
_STATIC_PAGES = [
    {"title": "Dashboard", "url": "/", "subtitle": "Home"},
    {"title": "Calendar", "url": "/calendar", "subtitle": ""},
    {"title": "Tasks", "url": "/tasks", "subtitle": ""},
    {"title": "Contacts", "url": "/contacts", "subtitle": ""},
    {"title": "Notes", "url": "/notes", "subtitle": ""},
    {"title": "Settings", "url": "/settings", "subtitle": ""},
]


def _matching_pages(conn, q: str, limit: int = 5) -> list[dict]:
    pages = list(_STATIC_PAGES)
    for space in db.list_space_labels(conn):
        pages.append({"title": space["name"], "url": f"/labels/{space['name']}", "subtitle": "Space"})
    if not q:
        return pages[:limit]
    q_lower = q.lower()
    return [p for p in pages if q_lower in p["title"].lower()][:limit]


def _page_result(page: dict) -> dict:
    return {"type": "page", "uid": page["url"], "url": page["url"], "title": page["title"], "subtitle": page["subtitle"], "tags": [], "status": None}


def _picker_result(row: dict) -> dict:
    # Compact surface only -- title/subtitle/tags/type/uid, never the full
    # `entity` row `search_entities` also returns. The picker only ever
    # renders this much, and dropping `entity` keeps the JSON payload small
    # and trivially serializable (no risk of a stray non-JSON-safe field
    # on the full row leaking into the response).
    #
    # Command palette actions (open.md § Command palette actions) -- a
    # task's `status` is the one extra field the palette's action buttons
    # need (to hide "Mark done" on an already-done task), so it rides
    # along here too, `None` for the other two types. Every existing
    # consumer of this shape (search.html, the relations picker) reads
    # only the fields it already knew about and ignores the rest.
    return {
        "type": row["type"],
        "uid": row["uid"],
        "title": row["title"],
        "subtitle": row["subtitle"],
        "tags": row["tags"],
        "status": row["entity"].get("status") if row["type"] == "task" else None,
    }


@router.get("/api/search")
def api_search(
    q: str = "",
    types: list[str] | None = None,
    labels: list[str] | None = None,
    for_task: str = "",
    for_event: str = "",
    limit: int = 20,
    conn=Depends(get_db),
):
    context_title: str | None = None
    exclude_uids: dict[str, set[str]] | None = None
    effective_types = types or None
    effective_labels = labels or None

    if for_task and for_event:
        return JSONResponse({"results": [], "context": None, "error": "for_task and for_event are mutually exclusive"}, status_code=400)

    if for_task:
        task = db.get_task(conn, for_task)
        if task is None:
            return JSONResponse({"results": [], "context": None})
        context_title = task["title"]
        effective_types = ["event"]
        effective_labels = task.get("tags") or []
        if not effective_labels:
            # No labels -> the shared-label rule can never match anything;
            # short-circuit rather than run a query that's guaranteed empty
            # (same "Add a label to relate" case the old template branch
            # handled -- see _task_relations.html's has_labels check).
            return JSONResponse({"results": [], "context": context_title, "no_labels": True})
        already = {e["uid"] for e in db.related_events_for_task(conn, for_task)}
        exclude_uids = {"event": already}
    elif for_event:
        event = db.get_event(conn, for_event)
        if event is None:
            return JSONResponse({"results": [], "context": None})
        context_title = event["title"]
        effective_types = ["task"]
        effective_labels = event.get("tags") or []
        if not effective_labels:
            return JSONResponse({"results": [], "context": context_title, "no_labels": True})
        already = {t["uid"] for t in db.related_tasks_for_event(conn, for_event)}
        exclude_uids = {"task": already}

    results = db.search_entities(
        conn,
        q=q or None,
        types=effective_types,
        labels=effective_labels,
        exclude_uids=exclude_uids,
        limit=limit,
    )
    picked = [_picker_result(r) for r in results]
    if not for_task and not for_event and not types:
        # Global mode only, and only when the caller hasn't already
        # narrowed to specific entity types (relation-picker mode always
        # does; a caller that explicitly asked for just tasks/events/
        # contacts/notes gets exactly that, no pages mixed in) -- a page
        # isn't linkable to anything, and a type-filtered request has
        # already said it doesn't want anything outside that filter.
        picked.extend(_page_result(p) for p in _matching_pages(conn, q))
    return JSONResponse({"results": picked, "context": context_title})


@router.get("/api/labels")
def api_labels(q: str = "", limit: int = 20, conn=Depends(get_db)):
    # Command palette actions (open.md § Command palette actions) --
    # backs the palette's label-assign sub-mode: type-to-filter over every
    # label already in use, the same vocabulary list_tag_names_in_use
    # already serves to every entity form's chip picker, just exposed as
    # JSON so a fetch()-driven overlay can filter it live instead of
    # relying on a server-rendered <datalist>.
    names = db.list_tag_names_in_use(conn)
    if q:
        q_lower = q.lower()
        names = [n for n in names if q_lower in n.lower()]
    return JSONResponse({"labels": names[:limit]})


@router.post("/api/entities/{entity_type}/{uid}/labels")
async def add_entity_label(entity_type: str, uid: str, request: Request, conn=Depends(get_db)):
    # Command palette actions -- the "assign a label" action, additive to
    # the existing per-entity label pickers (task/event/contact forms'
    # own multiselect fields), not a replacement for them. One label per
    # call, added (not replaced) -- the palette's own compact UI only ever
    # offers "add this one label", never a full picker.
    payload = await request.json()
    label = (payload.get("label") or "").strip()
    if not label:
        return JSONResponse({"error": "label is required"}, status_code=400)

    if entity_type == "task":
        task = db.get_task(conn, uid)
        if task is None:
            return JSONResponse({"error": "task not found"}, status_code=404)
        tags = sorted(set(task.get("tags") or []) | {label})
        row = dict(task)
        row["tags"] = tags
        try:
            db.upsert_task(conn, row)
        except db.MultipleProjectLabelsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    elif entity_type == "event":
        event = db.get_event(conn, uid)
        if event is None:
            return JSONResponse({"error": "event not found"}, status_code=404)
        db.add_object_label(conn, "event", uid, label)
    elif entity_type == "contact":
        contact = db.get_contact(conn, uid)
        if contact is None:
            return JSONResponse({"error": "contact not found"}, status_code=404)
        db.add_object_label(conn, "contact", uid, label)
    elif entity_type == "note":
        note = db.get_note(conn, uid)
        if note is None:
            return JSONResponse({"error": "note not found"}, status_code=404)
        db.add_object_label(conn, "note", uid, label)
    else:
        return JSONResponse({"error": f"unknown entity type '{entity_type}'"}, status_code=400)

    return JSONResponse({"ok": True})


@router.get("/search")
def search_page(request: Request, q: str = "", conn=Depends(get_db)):
    # Server-rendered first page (works with no JS, bookmarkable); once
    # loaded, command_palette.js takes over live filtering against
    # /api/search the same way Ctrl-K does, so this page and the overlay
    # share one client-side implementation instead of two.
    results = db.search_entities(conn, q=q or None, limit=40) if q else []
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "q": q,
            "results": [_picker_result(r) for r in results],
            "active_tab": "search",
        },
    )
