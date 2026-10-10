"""Renders the Secretariat page type for Home, a group or a label.

Feature notes: curodav-notes/documentation/features/home-and-secretariat.md.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import clock, db, habit_view, secretariat
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router


def render(conn, request: Request, *, scope_key: str | None, title: str, icon_name: str, icon_color: str | None,
           banner_ctx: dict, page_url: str, label: dict | None = None, header_edit_url: str | None = None):
    """`scope_key` is a label name, a group page key, or None for Home (everything)."""
    today = clock.today()
    config = {"label_name": scope_key}
    scope = dashboard_router._scope_child_names(conn, scope_key)
    tasks = dashboard_router._agenda_with_grace(conn, config, lambda t: True)
    events = dashboard_router._filtered_events_expanded(
        conn, config, today, today + timedelta(days=secretariat.UPCOMING_EVENT_DAYS)
    )
    habits = [
        h for h in habit_view.habit_items(conn)
        if h["due_today"] and not h["is_avoid"] and dashboard_router._passes_scope(h["tags"], scope)
    ]
    display_name = db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY)
    ctx = {
        "request": request,
        "active_tab": "dashboard" if scope_key is None else "label",
        "page": secretariat.build(today, tasks, events, habits),
        "today": today.isoformat(),
        "greeting": secretariat.greeting(clock.local_hour()),
        "display_name": display_name,
        "profile_photo": db.get_profile_photo(conn),
        "page_title": title,
        "page_icon": icon_name,
        "page_icon_color": icon_color,
        "page_url": page_url,
        "label": label,
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "header_edit_url": header_edit_url,
    }
    ctx.update(banner_ctx)
    return templates.TemplateResponse("secretariat.html", ctx)


home_router = APIRouter(prefix="/home", tags=["home-page"])


@home_router.get("/page")
def home_page_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "home_page_modal.html",
        {"request": request, "page_types": [(k, db.PAGE_TYPE_LABELS[k]) for k in db.PAGE_TYPES],
         "page_type": db.get_home_page_type(conn)},
    )


@home_router.post("/page")
def set_home_page(page_type: str = Form(...), conn=Depends(get_db)):
    db.set_home_page_type(conn, page_type)
    return RedirectResponse(url="/", status_code=303)
