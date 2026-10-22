"""Renders the Secretariat page type for Home, a group or a label.

Feature notes: curodav-notes/documentation/features/home-and-secretariat.md.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import clock, db, habit_view, secretariat
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router


def _filter_options(conn) -> list[dict]:
    """Header filter choices: every project, then every other label."""
    names = db.project_picker_context(conn)["project_names"]
    others = [n for n in db.list_tag_names_in_use(conn) if n not in names]
    return ([{"value": n, "name": n, "section": "Projects"} for n in names]
            + [{"value": n, "name": n, "section": "Labels"} for n in others])


def render(conn, request: Request, *, scope_key: str | None, title: str, icon_name: str, icon_color: str | None,
           banner_ctx: dict, page_url: str, label: dict | None = None, header_edit_url: str | None = None,
           view: str = "overview"):
    """`scope_key` is a label name, a group page key, or None for Home (everything)."""
    today = clock.today()
    is_home = scope_key is None
    filter_options = _filter_options(conn)
    chosen = (parse_qs(request.scope.get("query_string", b"").decode()).get("scope") or [""])[0].strip()
    if chosen and chosen in {o["value"] for o in filter_options}:
        scope_key = chosen
    else:
        chosen = ""
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
    notes = [n for n in db.list_notebook_documents(conn) if dashboard_router._passes_scope(n.get("tags"), scope)]
    note_looks = db.notebook_note_type_looks(conn)
    for n in notes:
        look = note_looks.get(n.get("note_type") or "", db.NOTEBOOK_TYPE_LOOK_FALLBACK)
        n["type_icon"], n["type_color"] = look["icon"], look["color"]
    display_name = db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY)
    ctx = {
        "request": request,
        "active_tab": "dashboard" if is_home else "label",
        "page": secretariat.build(today, tasks, events, habits, notes),
        "scope_choice": chosen,
        "scope_options": [{"value": "", "name": "Everything"}] + filter_options,
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
        "scope_view": view,
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
