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


def _picker_result(row: dict) -> dict:
    # Compact surface only -- title/subtitle/tags/type/uid, never the full
    # `entity` row `search_entities` also returns. The picker only ever
    # renders this much, and dropping `entity` keeps the JSON payload small
    # and trivially serializable (no risk of a stray non-JSON-safe field
    # on the full row leaking into the response).
    return {
        "type": row["type"],
        "uid": row["uid"],
        "title": row["title"],
        "subtitle": row["subtitle"],
        "tags": row["tags"],
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
    return JSONResponse({"results": [_picker_result(r) for r in results], "context": context_title})


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
