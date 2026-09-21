"""Spaces -- generated pages for labels with generate_space=1.

A Space is a label with generate_space=1. Its page aggregates tasks,
events, and contacts (same underlying page as the old Space/Project
detail pages, now driven off object_labels + label_config).

2026-09-14 (Spaces -- labels-as-membership rework slice 3): that
aggregation is membership through the Space's child labels
(`parent_name`), not direct tagging of the Space's own name -- see
`_label_scope`'s own docstring below for the full rationale/history.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import db
from ..deps import get_db, templates
from . import dashboard as dashboard_router

router = APIRouter(prefix="/spaces", tags=["spaces"])


def _label_scope(conn, name: str) -> dict:
    """Every task/event/contact tagged with any label that belongs to this
    Space (`parent_name` pointing at it -- `db.list_child_labels`, the
    same call `dashboard.py::_scope_child_names`/the widget grid's hard
    top-level filter already makes internally, Spaces -- labels-as-
    membership rework slice 4, not a new implementation here) --
    membership, not direct tagging.

    2026-09-14 (Spaces -- labels-as-membership rework slice 3, reverses
    part of a decision `open-priority.md`'s "Spaces — context" section had
    marked confirmed-shipped 2026-08-14): used to be `name in tags`, a
    direct-membership-only filter -- items had to be tagged with the
    Space's own label name itself, e.g. "University", never transitively
    through a child like "Historiography". This slice is scoped to just
    that query (per `open.md`'s own ordered slice list) -- it does NOT
    also remove a Space's own name from the tag-picker vocabulary
    (`db.list_tag_names_in_use`/`list_all_known_label_names` -- checked,
    neither excludes `generate_space=1` labels today, same picker a plain
    label uses), so a task/event/contact can still be directly tagged
    with a Space's own name through the UI; that tag now simply has no
    effect on this page, matching slice 6's own "unread but not gone"
    framing for the legacy tags this same gap produces. Removing Spaces
    from the tag picker outright isn't one of the six planned slices --
    flagged here for STATE.md rather than silently assumed already
    handled."""
    child_names = {c["name"] for c in db.list_child_labels(conn, name)}
    tasks = [t for t in db.list_tasks(conn) if child_names & set(t.get("tags") or [])]
    events = [e for e in db.list_events(conn) if child_names & set(e.get("tags") or [])]
    contacts = [c for c in db.list_contacts(conn) if child_names & set(c.get("tags") or [])]

    return {
        "tasks": tasks,
        "events": events,
        "contacts": contacts,
    }


@router.get("/{name}")
def space_detail(name: str, request: Request, conn=Depends(get_db)):
    label = db.effective_label_config(conn, name)
    if not label.get("generate_space"):
        from fastapi import HTTPException
        raise HTTPException(404, "Not a space")

    dashboard_router._ensure_default_label_widgets(conn, name)
    ctx = dashboard_router.widget_page_context(conn, project_uid=name)
    scope = _label_scope(conn, name)
    ctx.update(scope)
    ctx.update(
        {
            "request": request,
            "active_tab": "space",
            "label": label,
            "is_space": True,
            # base.html's sidebar quick-add link reads this to restrict the
            # Labels picker to this Space's own children -- direct request:
            # "the label selector should only have labels from that
            # group." Not `scope` (the dict this route's own `_label_scope`
            # call above already assigned to that name).
            "page_label_scope": name,
            "children": db.list_child_labels(conn, name),
            "parent": db.effective_label_config(conn, label["parent_name"]) if label.get("parent_name") else None,
            # Dashboard Header (Expanded) avatar (2026-08-29, sidebar
            # redesign follow-up, direct request) -- see
            # routers/dashboard.py::dashboard_view's own comment; a Space
            # page (this route) is a "dashboard type" page too (same
            # widget grid, same banner system), so it gets the same user
            # avatar overlapping the banner's bottom-left.
            "profile_photo": db.get_profile_photo(conn),
            "display_name": db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY),
        }
    )
    # Page banner (2026-08-09, routers/banners.py; 2026-08-29 direct
    # request: falls back to the global Settings > Appearance default when
    # this page has no banner of its own) -- see
    # routers/dashboard.py::_page_banner_context's own comment.
    ctx.update(dashboard_router._page_banner_context(conn, name))

    return templates.TemplateResponse("label_detail.html", ctx)