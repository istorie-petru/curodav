"""Spaces -- generated pages for labels with generate_space=1.

A Space is a label with generate_space=1. Its page aggregates tasks,
events, and contacts directly tagged with that label (same underlying
page as the old Space/Project detail pages, now driven off object_labels
+ label_config).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import db
from ..deps import get_db, templates
from . import dashboard as dashboard_router

router = APIRouter(prefix="/spaces", tags=["spaces"])


def _label_scope(conn, name: str) -> dict:
    """Every task/event/contact directly tagged with `name`."""
    tasks = [t for t in db.list_tasks(conn) if name in (t.get("tags") or [])]
    events = [e for e in db.list_events(conn) if name in (e.get("tags") or [])]
    contacts = [c for c in db.list_contacts(conn) if name in (c.get("tags") or [])]

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