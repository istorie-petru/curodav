"""Dashboard routes and their page context.

Part of the package whose __init__ re-exports every name.
"""

from __future__ import annotations

import calendar as py_calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from ... import clock, db, derived_state, habit_view, recurrence_expand
from ...deps import EDIT_MODE_KEY, PAGE_HEADER_BANNER_SCOPE, get_db, templates

from .widgets import _filtered_tasks, _scope_child_names, _agenda_show_from_form, _combine_tags, _greeting_for_hour, _now, _render_agenda, _render_at_a_glance, _render_contact_list, _render_group_members, _render_habit_checkin, _render_mini_month_calendar, _render_notebook_list, _render_scheduled_work_today, _render_spaces_projects, _render_weekly_schedule, _widget_width
from .layout import _backfill_mini_calendar_widget, _build_widget_contexts, _config_from_form, _dissolve_if_singleton, _dissolve_stack, _ensure_default_label_widgets, _ensure_default_widgets, _excluded_widget_types, _migrate_group_layout_2026_09_28, _migrate_widget_consolidation, _migrate_widget_removal_2026_08_30, _page_scope, _resolve_selection, _scoped_collections, _selection_from_widget, _widget_context, _widget_sources_for_scope, _widget_types_for_scope, _widget_views_for_scope


router = APIRouter(tags=["dashboard"])


# One-time default for the optional "Your name" Settings field: absent =
# no name, greeting reads "Good evening" alone rather than "Good evening,
# None". App-meta-backed (see routers/settings.py's own field for this).
DISPLAY_NAME_KEY = "dashboard_display_name"


NO_LABEL_SENTINEL = "__no_label__"


TASK_GRACE_MINUTES = 9


# --------------------------------------------------------------------- #
# Widget renderers -- each takes (conn, config) and returns a plain dict
# the widget's partial template renders. Registered below in WIDGET_TYPES.
# --------------------------------------------------------------------- #


AGENDA_RANGES: tuple[str, ...] = ("today", "next_7_days", "next_30_days", "all_upcoming")
AGENDA_SHOWS: tuple[str, ...] = ("overdue", "tasks", "events", "habits")
AGENDA_DEFAULT_SHOW: list[str] = ["overdue", "tasks", "events", "habits"]


_WEEKLY_SCHEDULE_MIN_SPAN_DAYS = 30
_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


WIDGET_WIDTHS: dict[str, dict] = {
    "quarter": {"label": "1/4 width", "span": 3},
    "third": {"label": "1/3 width", "span": 4},
    "half": {"label": "1/2 width", "span": 6},
    "two_thirds": {"label": "2/3 width", "span": 8},
    "three_quarters": {"label": "3/4 width", "span": 9},
    "full": {"label": "Full width", "span": 12},
}

WIDGET_WIDTH_CHOICES: tuple[str, ...] = ("quarter", "half", "three_quarters", "full")


WIDGET_TYPES: dict[str, dict] = {
    "at_a_glance": {
        "label": "At a Glance",
        "template": "_widget_at_a_glance.html",
        "render": _render_at_a_glance,
        "uses": {"tasks"},
        "default_width": "third",
    },
    "agenda": {
        "label": "Agenda",
        "template": "_widget_agenda.html",
        "render": _render_agenda,
        "uses": {"tasks", "events"},
        "default_width": "half",
    },
    "mini_month_calendar": {
        "label": "Mini Calendar",
        "template": "_widget_mini_month_calendar.html",
        "render": _render_mini_month_calendar,
        "uses": {"tasks", "events"},
        "default_width": "half",
    },
    "spaces_projects": {
        "label": "Groups & Labels",
        "template": "_widget_spaces_projects.html",
        "render": _render_spaces_projects,
        "uses": set(),
        "default_width": "third",
    },
    "habit_checkin": {
        "label": "Habit Check-in",
        "template": "_widget_habit_checkin.html",
        "render": _render_habit_checkin,
        # Habits H4: a habit is a task, so a habit created/edited/deleted
        # in a modal re-renders this card like any task widget.
        "uses": {"tasks"},
        "default_width": "half",
    },
    "contact_list": {
        "label": "Contact List",
        "template": "_widget_contact_list.html",
        "render": _render_contact_list,
        "uses": set(),
        "default_width": "third",
    },
    "notebook_list": {
        "label": "Notebook",
        "template": "_widget_notebook_list.html",
        "render": _render_notebook_list,
        "uses": set(),
        "default_width": "third",
    },
    "scheduled_work_today": {
        "label": "Scheduled Work Hours Today",
        "template": "_widget_scheduled_work_today.html",
        "render": _render_scheduled_work_today,
        "uses": {"events"},
        "default_width": "third",
    },
    "weekly_schedule": {
        "label": "Weekly Schedule",
        "template": "_widget_weekly_schedule.html",
        "render": _render_weekly_schedule,
        "uses": {"events"},
        "default_width": "half",
    },
    "group_members": {
        "label": "Group labels",
        "template": "_widget_group_members.html",
        "render": _render_group_members,
        "uses": {"tasks", "events"},
        "default_width": "full",
    },
}


WIDGET_SOURCES: dict[str, dict] = {
    "calendar_tasks": {"label": "WebDAV", "icon": "calendar"},
    "habits": {"label": "Habits", "icon": "activity"},
    "contacts": {"label": "Contacts", "icon": "users"},
    "spaces_projects": {"label": "Groups & Labels", "icon": "layers"},
    "group_members": {"label": "Group labels", "icon": "layers"},
    "notebooks": {"label": "Notebook", "icon": "notebook"},
}

WIDGET_VIEWS: dict[str, dict] = {
    "agenda_view": {"label": "Agenda", "source": "calendar_tasks", "has_range": True, "has_show": True, "has_limit": True},
    "at_a_glance_view": {"label": "At a glance (stats)", "source": "calendar_tasks", "has_range": False},
    "mini_calendar": {"label": "Mini calendar", "source": "calendar_tasks", "has_range": False},
    "checklist": {"label": "Checklist", "source": "habits", "has_range": False},
    "contact_list_view": {"label": "Contact list", "source": "contacts", "has_range": False, "has_limit": True},
    "scheduled_work_view": {"label": "Scheduled work hours today", "source": "calendar_tasks", "has_range": False},
    "spaces_projects_view": {"label": "Groups & Labels", "source": "spaces_projects", "has_range": False, "has_style": True},
    "weekly_schedule_view": {"label": "Weekly schedule", "source": "calendar_tasks", "has_range": False},
    "group_members_view": {"label": "Group labels", "source": "group_members", "has_range": False},
    "notebook_list_view": {"label": "Document list", "source": "notebooks", "has_range": False, "has_limit": True},
}

WIDGET_RANGES: dict[str, dict] = {
    "today": {"label": "Today", "views": {"agenda_view"}},
    "next_7_days": {"label": "Next 7 days", "views": {"agenda_view"}},
    "next_30_days": {"label": "Next 30 days", "views": {"agenda_view"}},
    "all_upcoming": {"label": "All upcoming", "views": {"agenda_view"}},
}

_SELECTION_TO_TYPE: dict[tuple[str, str | None], tuple[str, dict]] = {
    ("agenda_view", "today"): ("agenda", {"range": "today"}),
    ("agenda_view", "next_7_days"): ("agenda", {"range": "next_7_days"}),
    ("agenda_view", "next_30_days"): ("agenda", {"range": "next_30_days"}),
    ("agenda_view", "all_upcoming"): ("agenda", {"range": "all_upcoming"}),
    ("at_a_glance_view", None): ("at_a_glance", {}),
    ("mini_calendar", None): ("mini_month_calendar", {}),
    ("checklist", None): ("habit_checkin", {}),
    ("contact_list_view", None): ("contact_list", {}),
    ("scheduled_work_view", None): ("scheduled_work_today", {}),
    ("spaces_projects_view", None): ("spaces_projects", {}),
    ("weekly_schedule_view", None): ("weekly_schedule", {}),
    ("group_members_view", None): ("group_members", {}),
    ("notebook_list_view", None): ("notebook_list", {}),
}

# Reverse of the above, for pre-filling the edit form from an existing
# widget's stored `type` (+ `config.range` for Agenda). See
# _selection_from_widget for the type-aware key it builds.
_TYPE_TO_SELECTION: dict[tuple[str, str | None], tuple[str, str, str | None]] = {
    ("agenda", "today"): ("calendar_tasks", "agenda_view", "today"),
    ("agenda", "next_7_days"): ("calendar_tasks", "agenda_view", "next_7_days"),
    ("agenda", "next_30_days"): ("calendar_tasks", "agenda_view", "next_30_days"),
    ("agenda", "all_upcoming"): ("calendar_tasks", "agenda_view", "all_upcoming"),
    ("at_a_glance", None): ("calendar_tasks", "at_a_glance_view", None),
    ("mini_month_calendar", None): ("calendar_tasks", "mini_calendar", None),
    ("spaces_projects", None): ("spaces_projects", "spaces_projects_view", None),
    ("habit_checkin", None): ("habits", "checklist", None),
    ("contact_list", None): ("contacts", "contact_list_view", None),
    ("scheduled_work_today", None): ("calendar_tasks", "scheduled_work_view", None),
    ("weekly_schedule", None): ("calendar_tasks", "weekly_schedule_view", None),
    ("group_members", None): ("group_members", "group_members_view", None),
    ("notebook_list", None): ("notebooks", "notebook_list_view", None),
}


_SCOPE_EXCLUDED_TYPES: dict[str, set[str]] = {
    "project": {"spaces_projects", "group_members"},
    "": {"group_members"},
}


_DEFAULT_TODAY_AGENDA_CONFIG: dict = {"width": "half", "range": "today"}
_DEFAULT_STACK_CONFIG: dict = {"width": "half"}
_DEFAULT_STACK_MEMBER_TYPES: list[tuple[str, dict, str]] = [
    ("at_a_glance", {}, "At a glance"),
    ("agenda", {"range": "all_upcoming", "show": ["events", "tasks"]}, "Upcoming"),
]

_HOME_TODAY_AGENDA_CONFIG: dict = {"width": "quarter", "range": "today", "show": ["overdue", "tasks", "events"]}
_HOME_HABIT_CHECKIN_CONFIG: dict = {"width": "quarter"}

_GROUP_MEMBERS_QUARTER_CONFIG: dict = {"width": "quarter"}

_MINI_CALENDAR_BACKFILL_KEY = "dashboard_mini_calendar_backfilled_v1"
_HOME_SEEDED_KEY = "dashboard_home_seeded_v1"


_WIDGET_CONSOLIDATION_KEY = "dashboard_widget_consolidation_v1"


_WIDGET_REMOVAL_2026_08_30_KEY = "dashboard_widget_removal_2026_08_30"


_GROUP_LAYOUT_2026_09_28_KEY = "dashboard_group_layout_migrated_2026_09_28"


def _return_url(label_name: str | None, _legacy: str | None = None, conn=None) -> str:
    """Where a widget-mutating POST should redirect back to -- Home ("/")
        when the acted-on widget has no page identity, or that label's
        page otherwise (`/labels/{name}`, routers/label_pages.py -- one URL
        for every kind of label since labels-as-modules slice b; `conn` is no
        longer needed and only kept for existing callers). Derived from the
        widget itself wherever one already exists (edit/resize/stack/unstack/
        delete/move/reorder below); only add_widget has no existing widget to
        derive it from, so it takes `label_name` as a hidden form field
        instead (see _widget_builder_fields.html). `_legacy` accepts a second
        positional arg so every pre-Phase-2 call site passing (space_uid,
        project_uid) -- both now the same value, see _widget_row_to_dict's
        aliasing -- keeps working unchanged; only the first non-empty of the
        two is used.

        No longer takes an `edit` flag -- edit mode is a persistent, app-wide Settings > Appearance
        toggle (EDIT_MODE_KEY) now, not a per-page `?edit=1` query param a
        redirect needed to preserve, so every caller lands on the plain page
        URL regardless of whether edit mode is on.
    """
    label_name = label_name or _legacy
    if not label_name:
        return "/"
    group = db.group_from_page_key(label_name)
    if group is not None:
        return f"/groups/{group}"
    return f"/labels/{label_name}"


def widget_page_context(conn, space_uid: str | None = None, project_uid: str | None = None, nav: dict | None = None) -> dict:
    """Every piece of context _widget_workspace.html needs to render one
        page's widget grid (Add-widget form, live preview pane, the grid
        itself, each widget's own Filters panel) -- shared by dashboard_view
        (label_name=None, below) and routers/labels.py's label_detail (a
        label's generated page) so both pages run through the exact same
        widget machinery -- add/edit/resize/stack/reorder, all further below
        -- rather than a second parallel implementation living on the label
        route. `space_uid`/`project_uid` (kept as this function's own
        parameter names -- both now the same value, Phase 2 label-space
        rework) are the label whose page this is; only one is ever passed by
        any real caller. The widget *options* offered to each page are scoped
        by _widget_types_for_scope/_widget_views_for_scope/
        _widget_sources_for_scope and the collection dropdowns by
        _scoped_collections, so a label page never offers widgets or filters
        that can't mean anything there. `edit_mode` in the returned context is
        read straight off EDIT_MODE_KEY -- no longer a caller-supplied `edit` flag threaded through from
        a `?edit=1` query param, since edit mode is now a persistent, app-wide
        Settings > Appearance toggle rather than a per-page one.
    """
    _migrate_widget_consolidation(conn)
    _migrate_widget_removal_2026_08_30(conn)
    _migrate_group_layout_2026_09_28(conn)
    label_name = project_uid or space_uid
    widgets = db.list_dashboard_widgets(conn, label_name=label_name)
    widget_contexts = _build_widget_contexts(conn, widgets, nav)
    scope = _page_scope(conn, label_name)
    projects, task_lists, calendars = _scoped_collections(conn, label_name)
    tag_names = db.list_tag_names_in_use(conn)
    return {
        "space_uid": label_name or "",
        "project_uid": label_name or "",
        "label_name": label_name or "",
        "page_scope": scope,
        "page_url": _return_url(label_name, conn=conn),
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "widget_contexts": widget_contexts,
        "widget_types": _widget_types_for_scope(scope),
        "widget_sources": _widget_sources_for_scope(scope),
        "widget_views": _widget_views_for_scope(scope),
        "widget_ranges": WIDGET_RANGES,
        "projects": projects,
        "task_lists": task_lists,
        "calendars": calendars,
        "tag_names": tag_names,
        "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
    }


def _page_banner_context(conn, scope: str, name: str | None = None) -> dict:
    """Every piece of context _page_banner.html needs to render one page's
        banner -- Home ("" scope) and every Space/Project page
        (routers/labels.py::label_detail, routers/spaces.py::space_detail)
        all call this the same way.

        `has_own_banner` (not `banner`) is what the "Add banner"/"Change
        banner" edit-mode button's label reads: it's about whether THIS page
        has its own override, not whether a banner happens to be showing at
        all (the default rendering through doesn't mean this page has "added"
        one). `banner_image_scope` is which banner is actually being
        rendered (this page's own scope, or the sentinel default scope) --
        kept separate from `banner_scope` (this page's own identity, always
        used by the edit button/upload/remove forms regardless of which image
        is currently showing) so _page_banner.html's `/banners/image` URL
        points at the right stored image rather than looking up this page's
        own (unset) scope with the default banner's version hash.

        `name` -- the label/group/project's own
        display name, passed through to `db.effective_page_banner` so a page
        with no upload of its own can still default to a flair match. Only a
        label/group/project page passes it (routers/label_pages.py); Home
        leaves it None (no name to match a flair against at all), same as
        every OTHER scope this function has never applied a flair default to
        either. Confirmed via AskUserQuestion: a flair default renders here
        exactly like a real upload, no visual distinction -- so `has_own_
        banner` (and the Add/Change button label it drives) now also treats a
        flair match as "has one," the same "no special-casing" answer applied
        everywhere else this default shows up.
    """
    own_banner = db.effective_page_banner(conn, scope, name=name)
    if own_banner:
        return {
            "banner": own_banner,
            "has_own_banner": True,
            "banner_scope": scope,
            "banner_image_scope": scope,
        }
    return {
        "banner": db.get_page_banner(conn, PAGE_HEADER_BANNER_SCOPE),
        "has_own_banner": False,
        "banner_scope": scope,
        "banner_image_scope": PAGE_HEADER_BANNER_SCOPE,
    }


@router.get("/")
def dashboard_view(
    request: Request,
    cal_year: int | None = None,
    cal_month: int | None = None,
    conn=Depends(get_db),
):
    page_type = db.get_home_page_type(conn)
    from .. import label_pages, secretariat_page

    view = label_pages.requested_view(request)
    if view:
        banner_ctx = _page_banner_context(conn, "")
        if view == "agenda":
            return secretariat_page.render(
                conn, request, scope_key=None, title="Home", icon_name="home", icon_color=None,
                banner_ctx=banner_ctx, page_url="/", header_edit_url="/home/page", view="agenda",
            )
        tasks = [t for t in _filtered_tasks(conn, {"label_name": None}, open_only=False) if t["status"] != "archived"]
        label = {"name": "Home", "icon": "home", "color": "blue", "tasks_widget": 1}
        return label_pages.scope_board_page(
            conn, request, _scope_child_names(conn, None), None, label, tasks, "/", banner_ctx, "/home/page"
        )
    if page_type != "dashboard":
        from .. import label_pages, secretariat_page

        banner_ctx = _page_banner_context(conn, "")
        if page_type == "secretariat":
            return secretariat_page.render(
                conn, request, scope_key=None, title="Home", icon_name="home", icon_color=None,
                banner_ctx=banner_ctx, page_url="/", header_edit_url="/home/page",
            )
        return label_pages._pooled_sections_page(
            conn, request, None, "Home", "home", "blue", "/", banner_ctx, "/home/page"
        )
    _ensure_default_widgets(conn)
    _backfill_mini_calendar_widget(conn)
    # Month nav (cal_year/cal_month) is a plain query param on this same
    # route, not a per-widget one -- same "prev/next just re-requests the
    # page with different params" convention routers/calendar.py's month
    # view already uses, no JS required. Applies to every
    # mini_month_calendar widget on the page (there's normally just one);
    # a second instance would page together rather than independently,
    # which is an acceptable shared tradeoff for how much simpler it
    # keeps this than per-widget-uid params.
    nav = {"year": cal_year, "month": cal_month} if (cal_year and cal_month) else None
    ctx = widget_page_context(conn, space_uid=None, nav=nav)
    display_name = db.get_app_meta(conn, DISPLAY_NAME_KEY)
    ctx.update(
        {
            "request": request,
            "active_tab": "dashboard",
            "greeting": _greeting_for_hour(clock.local_hour(), display_name),
            "profile_photo": db.get_profile_photo(conn),
            "display_name": display_name,
        }
    )
    ctx.update(_page_banner_context(conn, ""))
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/today")
def today_redirect():
    """important_urgent has since been
        removed outright along with the rest of the Importance/Urgency feature
        -- see src/derived_state.py's module docstring.
    """
    return RedirectResponse(url="/", status_code=302)


def _quick_next_rows(conn, q: str) -> list[dict]:
    from ... import quick_next
    from ..dashboard import widgets

    q = q.strip()
    if q:
        return quick_next.from_search(db.search_entities(conn, q=q, types=["task", "event", "contact"], limit=20))
    today = clock.today()
    config = {"label_name": None}
    tasks = widgets._filtered_tasks(conn, config)
    events = widgets._filtered_events_expanded(conn, config, today, today + timedelta(days=quick_next.CURATED_DAYS))
    return quick_next.curated(today, tasks, events)


@router.get("/quick/next")
def quick_next_rows(request: Request, q: str = "", conn=Depends(get_db)):
    return templates.TemplateResponse("_quick_next_rows.html", {"request": request, "next_rows": _quick_next_rows(conn, q), "q": q.strip()})


@router.get("/quick/add")
def quick_add_form(
    request: Request, default_tab: str = "task", scope: str = "", label: str = "", focus: str = "", conn=Depends(get_db)
):
    from ..labels import COLORS, LABEL_ICON_GROUPS
    from ..tasks import STATUS_ITEMS, STATUSES

    if default_tab not in ("task", "event", "contact", "label"):
        default_tab = "task"

    tag_names = db.list_tag_names_in_use(conn)
    if scope:
        allowed = db.label_selector_scope(conn, scope)
        if allowed is not None:
            tag_names = allowed
    label = (label or "").strip()
    if label and label not in tag_names:
        tag_names = sorted(tag_names + [label], key=str.lower)
    return templates.TemplateResponse(
        "quick_add.html",
        {
            "request": request,
            "active_tab": "dashboard",
            "next_rows": _quick_next_rows(conn, ""),
            "focus_search": focus == "search",
            "q": "",
            "default_tab": default_tab,
            # Task-side context -- the shared field-grid partial
            # (_task_form_fields.html) needs the same items new_task_form
            # passes; task is None, so the edit-only branches don't render.
            # (Importance/Urgency have no items here anymore -- side work,
            # post-1.1, both are computed, not manually set.)
            "task": None,
            "statuses": STATUSES,
            "status_items": STATUS_ITEMS,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "prefill_tags": [label] if label else [],
            **db.project_picker_context(conn),
            "today": clock.today().isoformat(),
            "habit_label": db.get_task_habit_settings(conn)["habit_label"],
            # Event-side context -- same union new_event_form passes, all
            # blank so the event form starts empty.
            "event": None,
            "prefill_start": None,
            "prefill_end": None,
            "prefill_all_day": False,
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
            # Contact-side context -- same union new_contact_form
            # (routers/contacts.py) passes; contact is None, so the
            # edit-only branches (remove-photo checkbox) don't render.
            "contact": None,
            "phone_types": db.CONTACT_PHONE_TYPES,
            "email_types": db.CONTACT_EMAIL_TYPES,
            "website_types": db.CONTACT_WEBSITE_TYPES,
            "address_types": db.CONTACT_ADDRESS_TYPES,
            "social_types": db.CONTACT_SOCIAL_TYPES,
            # Label-side context -- same union new_label_modal
            # (routers/labels.py) passes; l is None, so the edit-only
            # banner branch doesn't render and role starts "none" (a
            # brand-new label is always a plain label until Role is
            # changed client-side).
            "l": None,
            "colors": COLORS,
            "icon_groups": LABEL_ICON_GROUPS,  # nav icons reserved (UI audit L3)
            "role": "none",
            "group_options": [g["name"] for g in db.list_groups(conn)],
        },
    )


def _reset_dashboard(conn, label_name: str | None) -> None:
    """"Have a clear default dashboard that the user could revert back to
    anytime, via settings." -- deletes every widget for one page's scope
    (Home when `label_name` is None, that label's own page otherwise) and
    clears the matching one-time "seeded" app_meta flag, then immediately
    re-seeds so the user lands back on a populated default layout, not a
    blank grid. Doesn't touch `_ensure_default_widgets`/
    `_ensure_default_label_widgets`'s own "seed once, never again"
    contract -- clearing the flag here is exactly what makes them willing
    to seed again, same as if this page had never been visited."""
    for w in db.list_dashboard_widgets(conn, label_name=label_name):
        db.delete_dashboard_widget(conn, w["uid"])
    if label_name:
        db.set_app_meta(conn, f"dashboard_label_{label_name}_seeded_v1", "")
        _ensure_default_label_widgets(conn, label_name)
    else:
        db.set_app_meta(conn, _HOME_SEEDED_KEY, "")
        _ensure_default_widgets(conn)


@router.post("/dashboard/reset")
def reset_dashboard(label_name: str = Form(""), conn=Depends(get_db)):
    """Reset-to-default-layout -- one generic route for both Home
    (`label_name` omitted/empty) and a label page (`label_name` set),
    rather than a second `/labels/{name}/dashboard/reset` route in
    routers/labels.py, since the only thing that differs is which scope's
    widgets get cleared and which seed function runs, both already
    handled by `_reset_dashboard`. Surfaced as a button in Settings'
    Widgets group (Home) and in a label page's own edit-mode toolbar
    (Settings has no per-space subpage to host that one) -- both go
    through a `data-confirm-sheet` form (static/app.js's confirm-sheet
    pattern), same mechanism every other destructive action in this app
    already uses, not a second confirmation UI."""
    _reset_dashboard(conn, label_name or None)
    return RedirectResponse(url=_return_url(label_name or None, conn=conn), status_code=303)


def _flatten_customize(contexts: list[dict]) -> list[dict]:
    """Flattens the (possibly stacked) widget-context list into the one
    list the Customize modal renders: each top-level widget becomes one
    row, a stack container becomes one group header row (its /delete
    dissolves, not destroys), and each stack member becomes an indented
    child row of that container."""
    flat: list[dict] = []
    for wc in contexts:
        if wc["is_stack"]:
            flat.append({"is_stack_header": True, "wc": wc, "widget": wc["widget"]})
            for child in wc["children"]:
                flat.append({
                    "is_stack_header": False, "wc": child,
                    "widget": child.get("widget", {}), "in_stack": True,
                })
        else:
            flat.append({"is_stack_header": False, "wc": wc, "widget": wc["widget"], "in_stack": False})
    return flat


@router.get("/dashboard/customize")
def dashboard_customize(request: Request, space_uid: str = "", project_uid: str = "", conn=Depends(get_db)):
    """The Customize modal -- a friendly surface for adding widgets. Shows
         the two-pane Widget Builder with configuration form + always-live
         preview -- always available. Reuses widget_page_context for source/view/range/
         project/tag/calendar data needed by _widget_builder_fields.html.
         `space_uid`/`project_uid` scope it exactly like the grid
         it manages -- Home has neither, a Space page passes space_uid, a
         Project page project_uid.
    """
    ctx = widget_page_context(conn, space_uid or None, project_uid or None)
    page_label = "Space dashboard" if space_uid else ("Project dashboard" if project_uid else "dashboard")
    ctx.update(
        {
            "request": request,
            "active_tab": "dashboard",
            "space_uid": space_uid,
            "project_uid": project_uid,
            "page_label": page_label,
        }
    )
    return templates.TemplateResponse("dashboard_customize.html", ctx)


@router.get("/dashboard/widgets/{uid}")
def widget_card_region(request: Request, uid: str, conn=Depends(get_db)):
    """Async-CRUD single-widget region fragment (features/async-crud.md) --
        re-renders one plain widget's card (the .widget-card with
        id="widget-{uid}") so static/async_crud.js's refreshRegion() can swap
        it in place after a task change instead of reloading the whole page.
        Shares _widget_card.html/_widget_inner.html with the full grid, so the
        fragment is pixel-identical to what widget_page_context renders (one
        source of truth). A stack (or stack child) returns the same card
        markup, but a stack child has no #widget-<uid> container on the page,
        so refreshRegion() no-ops for those -- documented scope cut, see
        _widget_card.html's own comment.

        `edit_mode` used to be
        hardcoded False here, which was harmless for the one caller that
        existed at the time (a *task* change refreshing a task-using widget,
        always skipped in edit mode -- see async_crud.js's cc-entity-changed
        listener, which never calls this route while editing at all). It
        stopped being harmless once a widget's OWN Filters/Width edit needed
        to refresh its own card live (dashboard_widget_preview.js's
        autosave() below) -- that only ever happens *while* in edit mode (the
        Filters form only opens there), and a hardcoded False would silently
        render the refreshed card without its drag handle/Edit/Delete chrome,
        which is exactly what the old task-change listener's own comment
        warned against doing. Reads the real, current edit_mode the same way
        widget_page_context already does, rather than assuming a caller-
        specific constant.
    """
    widget = db.get_dashboard_widget(conn, uid)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"widget not found: {uid}")
    wc = _widget_context(conn, widget, None)
    label_name = widget.get("label_name") or ""
    ctx = {
        "request": request,
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "space_uid": label_name,
        "project_uid": label_name,
        "label_name": label_name,
        "wc": wc,
    }
    html = templates.env.get_template("_widget_card.html").render(ctx)
    return HTMLResponse(html)


@router.get("/dashboard/widgets/{uid}/edit")
def widget_edit_form(request: Request, uid: str, space_uid: str = "", conn=Depends(get_db)):
    """Per-widget Filters editor as a modal (edit mode only) -- opened via the
    Filters button on each widget card. Returns a modal target fragment that
    static/modal.js shows as a dialog instead of an inline <details>.
    Gated behind edit_mode on the caller (the button only renders in edit mode)."""
    widget = db.get_dashboard_widget(conn, uid)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"widget not found: {uid}")
    wc = _widget_context(conn, widget)
    space_uid = widget.get("space_uid") or ""
    project_uid = widget.get("project_uid") or ""
    nav = {"year": 0, "month": 0}
    page_ctx = widget_page_context(conn, space_uid or None, project_uid or None, nav=nav)
    page_ctx.update({
        "request": request,
        "widget": wc["widget"],
        "wc": wc,
        "spec": wc["spec"],
        "space_uid": space_uid,
        "project_uid": project_uid,
    })
    return templates.TemplateResponse("_widget_edit_modal.html", page_ctx)


@router.post("/dashboard/widgets/preview")
def preview_widget(
    request: Request,
    source: str = Form(...),
    view: str = Form(""),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    style: str = Form(""),
    scope: str = Form(""),
    width: str = Form(""),
    show: list[str] = Form([]),
    space_uid: str = Form(""),
    conn=Depends(get_db),
):
    """Live preview -- Source/View/Range/filter changes in the
        Add-widget or per-widget Filters form fetch this on every change
        (static/dashboard_widget_preview.js) and swap the result into a
        preview pane, so you see the *actual* widget -- real data, real
        render function, same partial template -- before committing to it,
        not a mockup. `widget.uid` is a placeholder ("preview") since nothing
        has been saved; the only template that reads it (Mini Calendar's
        prev/next links) just gets a link that doesn't scroll anywhere
        meaningful, harmless in a preview pane. `space_uid` and `project_uid` are
        only ever present when previewing from a Space/Project page's own
        Customize form -- see add_widget below for why the preview has to
        auto-scope the same way the real save does. `tags_labels`
        is the Labels chip multiselect's checkboxes -- see _combine_tags.
        `style`/`show` are Spaces & Projects' Style radio and
        Agenda's Show checkboxes; `width` is the
        Width radio -- see _config_from_form. The preview
        card itself ignores width visually either way (`.widget-preview-card`
        is reset to `position:static; width:auto`, static/style.css), but it's
        threaded through anyway so the previewed widget's data/behavior stays
        consistent with what a real save would produce.
    """
    if source not in WIDGET_SOURCES:
        return templates.TemplateResponse(
            "_dashboard_widget_preview.html",
            {"request": request, "widget": {"uid": "preview", "title": title}, "spec": None, "data": None},
        )
    wtype, extra = _resolve_selection(source, view, range or None)
    spec = WIDGET_TYPES[wtype]
    show = _agenda_show_from_form(show) if wtype == "agenda" else None
    config = _config_from_form(
        project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit,
        extra=extra, style=style if wtype == "spaces_projects" else "",
        scope=scope if wtype == "spaces_projects" else "", show=show, width=width,
    )
    page_label = space_uid or project_uid
    if page_label:
        config["label_name"] = page_label
    data = spec["render"](conn, config, None)
    return templates.TemplateResponse(
        "_dashboard_widget_preview.html",
        {"request": request, "widget": {"uid": "preview", "title": title.strip() or None}, "spec": spec, "data": data},
    )


@router.post("/dashboard/widgets")
def add_widget(
    source: str = Form(...),
    view: str = Form(...),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    style: str = Form(""),
    scope: str = Form(""),
    width: str = Form(""),
    show: list[str] = Form([]),
    space_uid: str = Form(""),
    conn=Depends(get_db),
):
    """`space_uid` and `project_uid` -- hidden fields on the Customize
        form's widget builder, empty on Home, set to the Space's/Project's own
        uid on their pages. This is the one mutating route that can't derive
        its page from an existing widget (there isn't one yet), so it's the
        one place the page identity is threaded through the form instead of
        read back off a row. Every widget added from a Space auto-scopes to it
        via config["group_uid"]; every widget added from a project via
        config["project_uid"] -- the user never has to pick a Project filter just to
        keep a widget from leaking other spaces'/projects' data. Widget types
        excluded for the page's scope (e.g. Spaces & Projects on a project
        page) are rejected as a no-op the same way an unknown source is, so a
        stale/excluded combo never silently creates a widget that can't mean
        anything on the page. `width` -- see WIDGET_WIDTHS/_widget_width's own comment.
    """
    page_label = space_uid or project_uid or None
    if source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    wtype, extra = _resolve_selection(source, view, range or None)
    if wtype in _excluded_widget_types(_page_scope(conn, page_label)):
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    show = _agenda_show_from_form(show) if wtype == "agenda" else None
    config = _config_from_form(
        project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit,
        extra=extra, style=style if wtype == "spaces_projects" else "",
        scope=scope if wtype == "spaces_projects" else "", show=show, width=width,
    )
    if page_label:
        config["label_name"] = page_label
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": str(uuid.uuid4()),
            "type": wtype,
            "title": title.strip() or None,
            "config": config,
            "position": db.next_dashboard_widget_position(conn, page_label),
            "created_at": _now(),
            "label_name": page_label,
        },
    )
    return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)


@router.post("/dashboard/widgets/{uid}/edit")
def edit_widget(
    uid: str,
    source: str = Form(...),
    view: str = Form(...),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    style: str = Form(""),
    scope: str = Form(""),
    width: str = Form(""),
    show: list[str] = Form([]),
    conn=Depends(get_db),
):
    existing = db.get_dashboard_widget(conn, uid)
    if existing is None:
        return RedirectResponse(url="/", status_code=303)
    page_label = existing.get("label_name")
    orig_source, orig_view, orig_range = _selection_from_widget(existing)
    if source == orig_source and view == orig_view and (range or None) == orig_range and source not in WIDGET_SOURCES:
        wtype = existing["type"]
        extra = {}
    elif source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    else:
        wtype, extra = _resolve_selection(source, view, range or None)
    if wtype in _excluded_widget_types(_page_scope(conn, page_label)):
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    row = dict(existing)
    show = _agenda_show_from_form(show) if wtype == "agenda" else None
    new_config = _config_from_form(
        project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit,
        extra=extra, style=style if wtype == "spaces_projects" else "",
        scope=scope if wtype == "spaces_projects" else "", show=show, width=width,
    )
    if page_label:
        new_config["label_name"] = page_label
    row.update({"type": wtype, "title": title.strip() or None, "config": new_config})
    db.upsert_dashboard_widget(conn, row)
    return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)


@router.post("/dashboard/widgets/{uid}/stack-onto")
def stack_widget(uid: str, target_uid: str = Form(...), conn=Depends(get_db)):
    """Drag-onto-another-card target (static/app.js's dashboard drag
    handler posts here instead of /reorder when the drop lands in a
    card's center "stack" zone, not its top/bottom "reorder" edges) --
    merges `uid` into whatever stack `target_uid` belongs to, creating a
    new one first if target isn't already grouped. This is the actual
    fix for "small calendar on top, today's events directly under it,
    same width, and it stays that way" -- a plain auto-flow grid can't
    guarantee that pairing once anything else on the page changes size,
    but two widgets sharing one group_uid always render together in one
    card regardless of what else is on the dashboard."""
    if uid == target_uid:
        return JSONResponse({"error": "cannot stack a widget onto itself"}, status_code=400)
    moved = db.get_dashboard_widget(conn, uid)
    target = db.get_dashboard_widget(conn, target_uid)
    if moved is None or target is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if moved["type"] == "stack":
        # Stacks aren't nestable -- keeping this to one level deep avoids
        # a whole extra class of "what does resizing a stack-in-a-stack
        # even mean" questions for a feature whose whole point is "two
        # widgets, same width, stacked."
        return JSONResponse({"error": "a stack can't be stacked onto something else"}, status_code=400)
    if moved.get("space_uid") != target.get("space_uid") or moved.get("project_uid") != target.get("project_uid"):
        return JSONResponse({"error": "cannot stack widgets from different pages together"}, status_code=400)

    old_group = moved.get("group_uid")

    if target["type"] == "stack":
        stack_uid = target["uid"]
        after_position = None  # append at the end
    elif target.get("group_uid"):
        stack_uid = target["group_uid"]
        after_position = target["position"]  # land right after target within its stack
    else:
        # Target is an ordinary top-level widget, not yet grouped with
        # anything -- create the stack now, at target's own old position
        # and width, with target as its first member.
        stack_uid = str(uuid.uuid4())
        target_width = _widget_width(target, WIDGET_TYPES.get(target["type"]))["key"]
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": stack_uid,
                "type": "stack",
                "title": None,
                "config": {"width": target_width},
                "position": target["position"],
                "created_at": _now(),
                # Same page as the two widgets being merged (guaranteed
                # equal by the space_uid/project_uid check above).
                "space_uid": target.get("space_uid"),
                "project_uid": target.get("project_uid"),
            },
        )
        target = dict(target)
        target["group_uid"] = stack_uid
        target["position"] = 0.0
        db.upsert_dashboard_widget(conn, target)
        after_position = 0.0

    siblings = [w for w in db.list_all_dashboard_widgets(conn) if w.get("group_uid") == stack_uid and w["uid"] != uid]
    if after_position is None:
        new_position = (max((s["position"] for s in siblings), default=-1.0) + 1.0)
    else:
        later = [s["position"] for s in siblings if s["position"] > after_position]
        new_position = (after_position + min(later)) / 2.0 if later else after_position + 1.0

    moved["group_uid"] = stack_uid
    moved["position"] = new_position
    db.upsert_dashboard_widget(conn, moved)

    # If `moved` was itself the last widget holding some *other* stack
    # together, that stack no longer has enough members to justify
    # existing.
    if old_group and old_group != stack_uid:
        _dissolve_if_singleton(conn, old_group)

    return JSONResponse({"ok": True, "stack_uid": stack_uid})


@router.post("/dashboard/widgets/{uid}/unstack")
def unstack_widget(uid: str, conn=Depends(get_db)):
    """The explicit "pop this one back out to the top level" control on
    each widget inside a stack -- the counterpart to stack-onto above.
    Plain redirecting POST like the rest of this router's non-drag
    actions (delete, edit), not a fetch target, since there's no
    optimistic client-side state worth preserving across it."""
    widget = db.get_dashboard_widget(conn, uid)
    if widget is None or not widget.get("group_uid"):
        return RedirectResponse(url="/", status_code=303)
    space_uid = widget.get("space_uid")
    project_uid = widget.get("project_uid")
    stack_uid = widget["group_uid"]
    stack = db.get_dashboard_widget(conn, stack_uid)
    widget = dict(widget)
    widget["group_uid"] = None
    widget["position"] = db.next_dashboard_widget_position(conn, space_uid, project_uid)
    if stack:
        widget_config = dict(widget.get("config") or {})
        widget_config["width"] = (stack.get("config") or {}).get("width", widget_config.get("width"))
        widget["config"] = widget_config
    db.upsert_dashboard_widget(conn, widget)
    _dissolve_if_singleton(conn, stack_uid)
    return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)


@router.post("/dashboard/widgets/{uid}/delete")
def delete_widget(uid: str, conn=Depends(get_db)):
    widget = db.get_dashboard_widget(conn, uid)
    if widget is not None:
        space_uid = widget.get("space_uid")
        project_uid = widget.get("project_uid")
        if widget["type"] == "stack":
            # Dissolve, don't destroy -- a stack is a layout grouping, not
            # a real owner of the widgets inside it, so removing it should
            # never take your Filters config for those widgets with it.
            _dissolve_stack(conn, widget)
            return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)
        stack_uid = widget.get("group_uid")
        db.delete_dashboard_widget(conn, uid)
        if stack_uid:
            _dissolve_if_singleton(conn, stack_uid)
        return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)
    db.delete_dashboard_widget(conn, uid)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/widgets/{uid}/move")
def move_widget(uid: str, direction: str = Form(...), conn=Depends(get_db)):
    target_widget = db.get_dashboard_widget(conn, uid)
    if target_widget is None:
        return RedirectResponse(url="/", status_code=303)
    space_uid = target_widget.get("space_uid")
    project_uid = target_widget.get("project_uid")
    widgets = db.list_dashboard_widgets(conn, space_uid=space_uid, project_uid=project_uid)
    idx = next((i for i, w in enumerate(widgets) if w["uid"] == uid), None)
    if idx is None:
        return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(widgets):
        db.swap_dashboard_widget_positions(conn, widgets[idx]["uid"], widgets[swap_idx]["uid"])
    return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)


@router.post("/dashboard/widgets/{uid}/reorder")
def reorder_widget(uid: str, after_uid: str = Form(""), conn=Depends(get_db)):
    """JSON-free but still a POST (form body, not JSON, to match the rest
        of this router) drag-and-drop reorder target -- static/app.js's
        dashboard drag handler (edit-mode only) posts here after a drop
        instead of the old move-one-step-at-a-time /move endpoint above.
        `after_uid` is the uid of the widget this one should land immediately
        after in the new order, or "" to become the first widget -- computed
        client-side from wherever the card was dropped, same "read the final
        DOM order, tell the server where it landed" contract Kanban's own
        drag-and-drop uses for task status.

        Scoped to whichever collection `uid` itself already belongs to -- top-level widgets (group_uid IS NULL) if it's a plain
        widget or a stack container, or that stack's own members if it's
        inside one (static/app.js's intra-stack drag handler posts here too,
        not just the top-level one). `after_uid` has to belong to that same
        collection -- position values aren't comparable across a stack's
        members and the rest of the dashboard (see the group_uid migration
        comment in db.py), so an after_uid from the wrong collection is
        rejected rather than silently doing the wrong math.
    """
    moved = db.get_dashboard_widget(conn, uid)
    if moved is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    all_widgets = db.list_dashboard_widgets(conn, space_uid=moved.get("space_uid"), project_uid=moved.get("project_uid"))
    scope = moved.get("group_uid")
    others = [w for w in all_widgets if w["uid"] != uid and w.get("group_uid") == scope]

    if not after_uid:
        new_position = (others[0]["position"] - 1.0) if others else 0.0
    else:
        idx = next((i for i, w in enumerate(others) if w["uid"] == after_uid), None)
        if idx is None:
            return JSONResponse({"error": "after_uid not found in the same collection"}, status_code=400)
        if idx == len(others) - 1:
            new_position = others[idx]["position"] + 1.0
        else:
            new_position = (others[idx]["position"] + others[idx + 1]["position"]) / 2.0

    moved["position"] = new_position
    db.upsert_dashboard_widget(conn, moved)
    return JSONResponse({"ok": True})
