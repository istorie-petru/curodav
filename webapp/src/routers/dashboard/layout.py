"""Widget layout: seeding, migrations, scopes and contexts.

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

from .widgets import _agenda_range, _now, _tags_list, _widget_width


def _resolve_selection(source: str, view: str, range_: str | None) -> tuple[str, dict]:
    """(source, view, range) from the form -> (type, extra_config) to
    actually store/render. Falls back to the first valid view for the
    source (and drops an inapplicable range) on anything malformed or
    stale rather than erroring -- a selector that's out of sync with its
    own source (e.g. JS hasn't filtered it yet, or a no-JS submission
    sent a range that view doesn't use) should still produce *a* working
    widget, not a 400."""
    from .views import WIDGET_RANGES, WIDGET_VIEWS, _SELECTION_TO_TYPE
    if view not in WIDGET_VIEWS or WIDGET_VIEWS[view]["source"] != source:
        view = next(v for v, spec in WIDGET_VIEWS.items() if spec["source"] == source)
    if not WIDGET_VIEWS[view]["has_range"]:
        range_ = None
    elif range_ not in WIDGET_RANGES or view not in WIDGET_RANGES[range_]["views"]:
        range_ = next(r for r, spec in WIDGET_RANGES.items() if view in spec["views"])
    return _SELECTION_TO_TYPE[(view, range_)]


def _selection_from_widget(widget: dict) -> tuple[str, str, str | None]:
    """Stored widget -> (source, view, range) to pre-select in the form.
    Agenda is keyed on its own `config["range"]` string (defaulting to
    "today" for a not-yet-migrated/hand-built config, via `_agenda_range`
    -- same tolerant fallback the render function itself uses); every
    other type has exactly one selection regardless of config. Unknown/
    legacy types (shouldn't happen once `_migrate_widget_consolidation`
    has run, but _widget_context already tolerates a None spec for
    exactly this kind of "the type on disk doesn't match anything live"
    case) fall back to the first source/view rather than crashing the
    edit form."""
    from .views import _TYPE_TO_SELECTION
    wtype = widget["type"]
    if wtype == "agenda":
        key = (wtype, _agenda_range(widget.get("config") or {}))
    else:
        key = (wtype, None)
    if key not in _TYPE_TO_SELECTION:
        return "calendar_tasks", "agenda_view", "today"
    return _TYPE_TO_SELECTION[key]


def _page_scope(conn, label_name: str | None) -> str:
    """The scope name for a page identity -- "project" / "space" / "" (Home).
    Phase 2 (label-space rework) collapsed space_uid/project_uid into one
    `label_name` column -- which kind of page it is (Space vs. plain
    label/"project" page) is derived here from label_config.generate_space
    rather than which of two columns was set."""
    if not label_name:
        return ""
    # A group's page keeps the old Space page's widget-type rules.
    return "space" if db.group_from_page_key(label_name) is not None else "project"


def _excluded_widget_types(scope: str) -> set[str]:
    from .views import _SCOPE_EXCLUDED_TYPES
    return _SCOPE_EXCLUDED_TYPES.get(scope) or set()


def _type_for_view(view: str) -> str | None:
    """The widget `type` a view maps to (any range) -- for scoping the View
    picker to views whose type is allowed on the page. Views map to exactly
    one type per range, but the type is the same for every range a view
    supports (agenda -> today_agenda/weekly_overview depending on range),
    so just return the first mapping found."""
    from .views import _SELECTION_TO_TYPE
    for (v, _r), (t, _d) in _SELECTION_TO_TYPE.items():
        if v == view:
            return t
    return None


def _widget_types_for_scope(scope: str) -> dict[str, dict]:
    from .views import WIDGET_TYPES
    excluded = _excluded_widget_types(scope)
    return {k: v for k, v in WIDGET_TYPES.items() if k not in excluded}


def _widget_views_for_scope(scope: str) -> dict[str, dict]:
    from .views import WIDGET_VIEWS
    excluded = _excluded_widget_types(scope)
    return {k: v for k, v in WIDGET_VIEWS.items() if _type_for_view(k) not in excluded}


def _widget_sources_for_scope(scope: str) -> dict[str, dict]:
    """Sources that still have at least one allowed view -- a source whose
    every view is excluded (e.g. Projects on a project page, once both
    `cards` and `filled_cards_view` are gone) disappears from the picker
    entirely rather than showing a dead Source with no View choices."""
    from .views import WIDGET_SOURCES
    allowed_sources = {v["source"] for v in _widget_views_for_scope(scope).values()}
    return {k: v for k, v in WIDGET_SOURCES.items() if k in allowed_sources}


def _scoped_collections(conn, label_name: str | None) -> tuple[list[dict], list[dict], list[dict]]:
    """(projects, task_lists, calendars) the Customize/Filter forms may
        offer for one page's grid -- Home offers every plain label; a Space's
        page only its own child labels; a plain label's own page just itself.
        Phase 1 dropped `task_lists`/
        `calendars` -- those two elements of the tuple are always empty now;
        kept as an empty list, not removed from the return shape, so every
        existing caller (widget_page_context below) keeps unpacking a 3-tuple
        unchanged. "projects" here means "labels" -- kept as the historical
        name templates already read (`projects` context key).
    """
    if label_name is not None:
        group = db.group_from_page_key(label_name)
        if group is not None:
            projects = [db.effective_label_config(conn, n) for n in db.group_member_names(conn, group)]
        else:
            projects = [db.effective_label_config(conn, label_name)]
    else:
        projects = db.list_labels(conn)
    return projects, [], []


def _seed_agenda_stack_layout(conn, label_name: str | None, now: str) -> None:
    """Writes the default layout for one page's grid -- Home when
        `label_name` is None, otherwise that label's generated Space/Project
        page -- shared by _ensure_default_widgets and
        _ensure_default_label_widgets so both seed with the identical
        screenshot-driven look: Today's Agenda beside a stack of At a
        Glance / Upcoming events. Building the stack this way (a
        `type="stack"` row + group_uid members) mirrors stack_widget()'s own
        shape exactly, not a new mechanism.

        Every widget/stack row is scoped to this page via the `label_name`
        column (None means Home -- see db.upsert_dashboard_widget), and each
        *widget's own config* additionally gets `label_name` set (label pages
        only) so its data query is filtered to this label, same as every
        other label-page widget (see _effective_tags_filter).

        Home and a group page both get the 25/50/25 row -- Today at
        quarter width, the stack at half, and a quarter-width third widget
        after it: Habit Check-in on Home, `group_members` (this group's own
        label list) on a group page. A plain label/Space/Project page keeps
        the half/half pair, no third widget.
    """
    from .views import _DEFAULT_STACK_CONFIG, _DEFAULT_STACK_MEMBER_TYPES, _DEFAULT_TODAY_AGENDA_CONFIG, _GROUP_MEMBERS_QUARTER_CONFIG, _HOME_HABIT_CHECKIN_CONFIG, _HOME_TODAY_AGENDA_CONFIG
    home = label_name is None
    is_group = label_name is not None and label_name.startswith(db.GROUP_KEY_PREFIX)
    quarter_row = home or is_group
    agenda_config = dict(_HOME_TODAY_AGENDA_CONFIG if quarter_row else _DEFAULT_TODAY_AGENDA_CONFIG)
    if label_name:
        agenda_config["label_name"] = label_name
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": str(uuid.uuid4()), "type": "agenda", "title": "Today",
            "config": agenda_config, "position": 0.0, "created_at": now, "label_name": label_name,
        },
    )
    stack_uid = str(uuid.uuid4())
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": stack_uid, "type": "stack", "title": None,
            "config": dict(_DEFAULT_STACK_CONFIG), "position": 1.0, "created_at": now, "label_name": label_name,
        },
    )
    for i, (wtype, extra_config, title) in enumerate(_DEFAULT_STACK_MEMBER_TYPES):
        member_config = dict(extra_config)
        if label_name:
            member_config["label_name"] = label_name
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()), "type": wtype, "title": title, "config": member_config,
                "position": float(i), "created_at": now, "group_uid": stack_uid, "label_name": label_name,
            },
        )
    if home:
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()), "type": "habit_checkin", "title": "Habits",
                "config": dict(_HOME_HABIT_CHECKIN_CONFIG), "position": 2.0, "created_at": now, "label_name": None,
            },
        )
    elif is_group:
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()), "type": "group_members", "title": "Shelves in this group",
                "config": {**_GROUP_MEMBERS_QUARTER_CONFIG, "label_name": label_name}, "position": 2.0,
                "created_at": now, "label_name": label_name,
            },
        )


def _ensure_default_widgets(conn) -> None:
    """A brand-new install gets a working dashboard out of the box
        (unfiltered today/week/upcoming) -- "customizable" means you can
        reshape it from there, not that you start from a blank page.

        A one-time-only seed: once seeded (tracked via app_meta), it never
        re-seeds -- even if the user deletes every widget. This honors the
        "No widgets yet" empty state instead of silently re-creating defaults
        on every reload after a full clear. Same convention as the existing
        _backfill_mini_calendar_widget one-time migration and
        ensure_default_calendar/ensure_default_task_list/ensure_default_addressbook
        (db.py), but scoped per-page.
    """
    from .views import _HOME_SEEDED_KEY, _MINI_CALENDAR_BACKFILL_KEY
    if db.get_app_meta(conn, _HOME_SEEDED_KEY):
        return
    if db.list_dashboard_widgets(conn):
        db.set_app_meta(conn, _HOME_SEEDED_KEY, "1")
        return
    _seed_agenda_stack_layout(conn, None, _now())
    # Found during this pass, not anticipated going in: _backfill_mini_
    # calendar_widget (below) is a one-time *migration* for dashboards
    # that already existed before mini_month_calendar/calendar_agenda
    # were invented -- it injects a standalone mini_month_calendar when
    # neither type is present. Since this fresh seed no longer includes
    # calendar_agenda either, a truly brand-new install would otherwise
    # trip that same "neither present" condition and get an uninvited
    # mini_month_calendar widget nobody asked for. Marking the backfill
    # done here (this dashboard has no history to migrate) is the fix --
    # genuinely pre-existing installs (the `list_dashboard_widgets(conn)`
    # branch above) are untouched and still get the real migration.
    db.set_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY, "1")
    # Found during Phase 1 implementation, not in this phase's original
    # scope: this branch never marked itself seeded after actually
    # writing the fresh defaults (only the "widgets already existed"
    # branch above did), so every subsequent call re-seeded on top of a
    # full delete instead of respecting the "no widgets yet" empty state
    # the function's own docstring promises. Fixed here since it blocks
    # the full suite going green, not because it's part of the
    # label-space rework.
    db.set_app_meta(conn, _HOME_SEEDED_KEY, "1")


def _ensure_default_label_widgets(conn, label_name: str) -> None:
    """Same one-time-only seeding as _ensure_default_widgets, scoped to
        one label's page -- never re-seeds once _that label_ has been seeded,
        even if the user later deletes every widget from it (honors the empty
        state instead of silently re-creating defaults). Checked independently
        of every other label's/Home's own widgets.
    """
    seeded_key = f"dashboard_label_{label_name}_seeded_v1"
    if db.get_app_meta(conn, seeded_key):
        return
    if db.list_dashboard_widgets(conn, label_name=label_name):
        db.set_app_meta(conn, seeded_key, "1")
        return
    _seed_agenda_stack_layout(conn, label_name, _now())
    db.set_app_meta(conn, seeded_key, "1")


def _backfill_mini_calendar_widget(conn) -> None:
    """One-time migration, NOT the same idempotent-forever pattern
        _ensure_default_widgets uses. mini_month_calendar was added to
        _DEFAULT_WIDGETS after real dashboards already existed -- Widget
        seeding only runs on a completely empty dashboard, so anyone who'd
        already visited before this change never got it. Runs exactly once
        (tracked in app_meta), inserting it right after Today's Agenda if
        that widget exists, so deleting it afterward sticks instead of it
        reappearing on the next load like a true default would.
    """
    from .views import _MINI_CALENDAR_BACKFILL_KEY
    if db.get_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY):
        return
    widgets = db.list_dashboard_widgets(conn)
    has_mini_cal = any(w["type"] == "mini_month_calendar" for w in widgets)
    has_cal_agenda = any(w["type"] == "calendar_agenda" for w in widgets)
    if has_cal_agenda:
        db.set_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY, "1")
        return
    if widgets and not has_mini_cal:
        today_idx = next((i for i, w in enumerate(widgets) if w["type"] == "today_agenda"), None)
        if today_idx is not None and today_idx + 1 < len(widgets):
            position = (widgets[today_idx]["position"] + widgets[today_idx + 1]["position"]) / 2
        elif today_idx is not None:
            position = widgets[today_idx]["position"] + 0.5
        else:
            position = db.next_dashboard_widget_position(conn)
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()),
                "type": "mini_month_calendar",
                "title": None,
                "config": {},
                "position": position,
                "created_at": _now(),
            },
        )
    db.set_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY, "1")


def _migrate_widget_consolidation(conn) -> None:
    """One-time migration -- rewrites every existing dashboard_widgets
        row still carrying one of the seven now-removed types in place, so no
        existing dashboard silently loses a widget just because this version
        is running. Runs exactly once (tracked in app_meta), same
        non-idempotent-forever pattern _backfill_mini_calendar_widget uses
        below (this only ever needs to run once, not "until the condition is
        no longer true").

        - today_agenda/weekly_overview/upcoming_events/overdue_tasks all
          become "agenda", each config translated to the exact Range/Show
          combination that reproduces its old content -- every one of these
          four preserves the underlying task/event set unchanged, just under
          the new registry (see AGENDA_RANGES/AGENDA_SHOWS and _render_agenda's
          own docstring for what each combination renders).
        - project_preview/filled_cards become "spaces_projects" with
          style="list"/"cards" respectively.
        - calendar_agenda splits into two widgets in its old row's place: the
          row itself becomes an "agenda" (range=next_7_days,
          show=[tasks, events], matching the old embedded 7-day agenda), and
          a brand-new "mini_month_calendar" row is inserted right beside it,
          sharing the same group_uid -- a calendar_agenda that was already
          inside a stack keeps both halves stacked together; a standalone one
          gets two standalone widgets at (roughly) the same position. Doesn't
          nest a new stack around them -- stacks aren't nestable (see
          stack_widget's own comment), and reusing calendar_agenda's existing
          group_uid (None or a real stack) sidesteps that restriction
          entirely.
    """
    from .views import _WIDGET_CONSOLIDATION_KEY
    if db.get_app_meta(conn, _WIDGET_CONSOLIDATION_KEY):
        return
    now = _now()
    for w in db.list_all_dashboard_widgets(conn):
        wtype = w["type"]
        cfg = dict(w.get("config") or {})
        if wtype in ("today_agenda", "weekly_overview", "upcoming_events", "overdue_tasks"):
            range_days = cfg.pop("range_days", None)
            if wtype == "today_agenda":
                cfg.update({"range": "today", "show": ["overdue", "tasks", "events"]})
            elif wtype == "weekly_overview":
                cfg.update({"range": "next_30_days" if range_days == 30 else "next_7_days", "show": ["tasks", "events"]})
            elif wtype == "upcoming_events":
                if range_days == 7:
                    cfg["range"] = "next_7_days"
                elif range_days == 30:
                    cfg["range"] = "next_30_days"
                else:
                    cfg["range"] = "all_upcoming"
                cfg["show"] = ["events"]
            else:  # overdue_tasks
                cfg.update({"range": "today", "show": ["overdue"]})
            row = dict(w)
            row["type"], row["config"] = "agenda", cfg
            db.upsert_dashboard_widget(conn, row)
        elif wtype in ("project_preview", "filled_cards"):
            cfg["style"] = "list" if wtype == "project_preview" else "cards"
            row = dict(w)
            row["type"], row["config"] = "spaces_projects", cfg
            db.upsert_dashboard_widget(conn, row)
        elif wtype == "calendar_agenda":
            agenda_cfg = dict(cfg)
            agenda_cfg.update({"range": "next_7_days", "show": ["tasks", "events"]})
            row = dict(w)
            row["type"], row["config"] = "agenda", agenda_cfg
            db.upsert_dashboard_widget(conn, row)
            cal_cfg = {}
            if cfg.get("tags"):
                cal_cfg["tags"] = cfg["tags"]
            if cfg.get("label_name"):
                cal_cfg["label_name"] = cfg["label_name"]
            db.upsert_dashboard_widget(
                conn,
                {
                    "uid": str(uuid.uuid4()),
                    "type": "mini_month_calendar",
                    "title": None,
                    "config": cal_cfg,
                    "position": w["position"] - 0.001,
                    "created_at": now,
                    "group_uid": w.get("group_uid"),
                    "label_name": w.get("label_name"),
                },
            )
    db.set_app_meta(conn, _WIDGET_CONSOLIDATION_KEY, "1")


def _migrate_widget_removal_2026_08_30(conn) -> None:
    """One-time migration -- same
        non-idempotent-forever pattern as `_migrate_widget_consolidation`
        above (runs exactly once, tracked in its own app_meta key so it
        doesn't re-run and doesn't collide with that migration's own guard).

        - Every existing "quick_links" row becomes "spaces_projects" with
          `style="cards"` in place (same rewrite-in-place approach
          `_migrate_widget_consolidation` already uses for project_preview/
          filled_cards) -- `_render_spaces_projects`'s own cards branch now
          renders the identical "every Space + every open project" tile set
          Quick Links used to when unscoped, so nothing is lost, just
          relabeled onto the surviving type.
        - Every existing "next_deadline"/"organize_today"/"streak" row is
          deleted outright -- there's no replacement type to rewrite onto (a
          straight removal, not a merge), and leaving the row in place would
          otherwise render as `_widget_inner.html`'s generic "Unknown widget
          type" empty state forever (`_widget_context` already degrades a
          row whose `type` isn't in `WIDGET_TYPES` that way -- harmless, but
          not what "remove" means here). `db.delete_dashboard_widget` is a
          plain row delete; a removed widget that happened to be inside a
          stack just stops appearing among that stack's children (nothing
          else references it back).
    """
    from .views import _WIDGET_REMOVAL_2026_08_30_KEY
    if db.get_app_meta(conn, _WIDGET_REMOVAL_2026_08_30_KEY):
        return
    for w in db.list_all_dashboard_widgets(conn):
        wtype = w["type"]
        if wtype == "quick_links":
            row = dict(w)
            row["type"] = "spaces_projects"
            row["config"] = {**(w.get("config") or {}), "style": "cards"}
            db.upsert_dashboard_widget(conn, row)
        elif wtype in ("next_deadline", "organize_today", "streak"):
            db.delete_dashboard_widget(conn, w["uid"])
    db.set_app_meta(conn, _WIDGET_REMOVAL_2026_08_30_KEY, "1")


def _migrate_group_layout_2026_09_28(conn) -> None:
    """One-time migration -- converts every group page that
        was already seeded under the old design (a half-width Today +
        half-width stack, plus a separate always-pinned, full-width
        `group_members` widget at position -1.0 -- see the now-unused
        `_ensure_group_members_widget`) into the new one (see
        `_seed_agenda_stack_layout`'s own docstring): Today moves to quarter
        width, and the pinned `group_members` widget moves out of its own row
        into the ordinary quarter-width third column, position 2.0 (after the
        half-width stack), same as a group page seeded fresh now gets.

        Same non-idempotent-forever pattern as the migrations above (runs
        exactly once, tracked in its own app_meta key). Scoped to top-level
        widgets only (`group_uid is None`) on a group page (`label_name`
        starting with `db.GROUP_KEY_PREFIX`) -- a group page's stack members
        are untouched (the stack itself stays half width), and this can never
        touch Home or a plain label/Space/Project page, which never had a
        pinned `group_members` widget to migrate away from.
    """
    from .views import _GROUP_LAYOUT_2026_09_28_KEY
    if db.get_app_meta(conn, _GROUP_LAYOUT_2026_09_28_KEY):
        return
    for w in db.list_all_dashboard_widgets(conn):
        label_name = w.get("label_name")
        if not label_name or not label_name.startswith(db.GROUP_KEY_PREFIX) or w.get("group_uid"):
            continue
        if w["type"] == "group_members":
            row = dict(w)
            row["config"] = {**(w.get("config") or {}), "width": "quarter"}
            row["position"] = 2.0
            db.upsert_dashboard_widget(conn, row)
        elif w["type"] == "agenda" and (w.get("config") or {}).get("width") != "quarter":
            row = dict(w)
            row["config"] = {**(w.get("config") or {}), "width": "quarter"}
            db.upsert_dashboard_widget(conn, row)
    db.set_app_meta(conn, _GROUP_LAYOUT_2026_09_28_KEY, "1")


def _is_bare_tile_widget(widget: dict) -> bool:
    return widget["type"] == "spaces_projects" and (widget.get("config") or {}).get("style") == "cards"


def _widget_context(conn, widget: dict, nav: dict | None = None) -> dict:
    from .views import WIDGET_TYPES
    spec = WIDGET_TYPES.get(widget["type"])
    width = _widget_width(widget, spec)
    source, view, range_ = _selection_from_widget(widget)
    selection = {"source": source, "view": view, "range": range_}
    bare = _is_bare_tile_widget(widget)
    if spec is None:
        return {"widget": widget, "spec": None, "data": None, "width": width, "selection": selection, "is_stack": False, "bare": bare}
    data = spec["render"](conn, widget["config"], nav)
    return {"widget": widget, "spec": spec, "data": data, "width": width, "selection": selection, "is_stack": False, "bare": bare}


def _build_widget_contexts(conn, widgets: list[dict], nav: dict | None = None) -> list[dict]:
    """Top-level render list -- plain widgets via _widget_context as
        before, plus stacks: a stack is just another
        dashboard_widgets row (type="stack", no spec/render of its own,
        _widget_context already treats an unrecognized type as "no spec"),
        grouping whatever other widgets have `group_uid` pointing at it. Its
        members are excluded from this top-level list entirely -- they only
        ever get rendered nested inside their stack's own `children`, in
        `position` order among just that stack's members (not comparable to
        any other widget's position, same as this file's docstring on
        group_uid already explains).
    """
    children_by_group: dict[str, list[dict]] = {}
    for w in widgets:
        gid = w.get("group_uid")
        if gid:
            children_by_group.setdefault(gid, []).append(w)
    for kids in children_by_group.values():
        kids.sort(key=lambda w: w["position"])

    contexts = []
    for w in widgets:
        if w.get("group_uid"):
            continue  # rendered nested under its stack instead
        if w["type"] == "stack":
            width = _widget_width(w, None)
            children = [_widget_context(conn, c, nav) for c in children_by_group.get(w["uid"], [])]
            contexts.append({"widget": w, "spec": None, "data": None, "width": width, "selection": None, "is_stack": True, "children": children})
        else:
            contexts.append(_widget_context(conn, w, nav))
    return contexts


def _config_from_form(
    project_uid: str,
    tags: str,
    task_list_uids: list[str],
    calendar_uids: list[str],
    limit: str,
    extra: dict | None = None,
    style: str = "",
    show: list[str] | None = None,
    scope: str = "",
    width: str = "",
) -> dict:
    from .views import WIDGET_WIDTH_CHOICES
    config: dict = {}
    tag_list = _tags_list(tags)
    if project_uid:
        # Phase 2 (label-space rework): the widget builder's "Project"
        # picker filters content by one label now -- folded straight into
        # the tags filter (a label IS a tag, see _passes_filters) rather
        # than a separate config["project_uid"] key, which is reserved for
        # the widget's own page-scope identity now (see
        # dashboard_widgets.label_name / config["label_name"]).
        if project_uid not in tag_list:
            tag_list.append(project_uid)
    if tag_list:
        config["tags"] = tag_list
    if limit:
        try:
            config["limit"] = int(limit)
        except ValueError:
            pass
    if extra:
        config.update(extra)
    if style:
        config["style"] = style
    if scope:
        config["scope"] = scope
    if show is not None:
        config["show"] = show
    if width in WIDGET_WIDTH_CHOICES:
        config["width"] = width
    return config


def _dissolve_stack(conn, stack: dict) -> None:
    """Ungroups every member of `stack` back to the top level, in their
    existing relative order, landing at the stack's own old position and
    inheriting its shared width -- used both when a stack is explicitly
    deleted (dissolve, don't destroy -- see delete_widget below) and when
    unstacking a widget leaves a stack with fewer than 2 members (a
    "stack" of one thing isn't a stack, it's just that widget). Height is
    not shared/propagated here the way width is -- stack members render
    one above another in a single card, each just sizing to its own
    content (see .widget-content in _widget_workspace.html), not one
    height split across all of them the way "same width, side by side"
    makes sense for width."""
    stack_uid = stack["uid"]
    stack_width = (stack.get("config") or {}).get("width")
    children = sorted(
        (w for w in db.list_all_dashboard_widgets(conn) if w.get("group_uid") == stack_uid),
        key=lambda w: w["position"],
    )
    for i, child in enumerate(children):
        child = dict(child)
        child["group_uid"] = None
        # Small offsets keep them in the same relative order rather than
        # colliding on one exact position value; landing at the stack's
        # own position keeps them roughly where the stack used to sit in
        # the overall top-level order instead of jumping to the end.
        child["position"] = stack["position"] + (i * 0.001)
        if stack_width:
            child_config = dict(child.get("config") or {})
            child_config["width"] = stack_width
            child["config"] = child_config
        db.upsert_dashboard_widget(conn, child)
    db.delete_dashboard_widget(conn, stack_uid)


def _dissolve_if_singleton(conn, stack_uid: str) -> None:
    """After a widget leaves a stack (via /unstack, or via plain delete of
    one member), a stack with 0 or 1 members left doesn't make sense as
    its own container any more -- pop the last one back to the top level
    and remove the now-empty/pointless stack row."""
    stack = db.get_dashboard_widget(conn, stack_uid)
    if not stack or stack["type"] != "stack":
        return
    remaining = [w for w in db.list_all_dashboard_widgets(conn) if w.get("group_uid") == stack_uid]
    if len(remaining) <= 1:
        _dissolve_stack(conn, stack)
