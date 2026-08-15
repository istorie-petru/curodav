"""Labels (label-space rework Phase 2) -- replaces `routers/tags.py`
entirely and the Space/Project-management half of the old
`routers/projects.py`. See `features/architecture.md` §0/§2/§3 Phase 2
for the full model: a label is not an entity with a lifecycle (no
create/delete workflow, no cascading-delete concerns) -- it's a name that
tasks/events/contacts/habits point at via the one `object_labels` join
table. Any color/icon/behavior config is a thin,
optional dict keyed by the label's name (`label_config`), not a row other
tables hold a hard foreign key into.

This router owns:
  1. The manage page (`/labels`) -- rename/merge/recolor/icon/parent/
     generate_space/"clear" (strip from everywhere), same "flat row list"
     pattern tags.py/projects.py used to have.
  2. The generated label page (`/labels/{name}`) -- for a `generate_space`
     label this is what used to be a Space's own page (aggregating its
     child labels' content); for a plain label it's what used to be a
     Project's own page (that label's own tasks/events/contacts/classes).
     Both are the same underlying page now -- see `_label_scope` below --
     driven off `label_config` + `object_labels` instead of
     `project_groups`/`projects`.

2026-08-07: `databases` dropped from the object types a label can carry
-- the Databases feature (and Grades, built on it) is removed entirely.

2026-08-08: the Phase 4 `enabled_modules`/"Sections" checkbox group is
gone. See label_modules.py's own removal note for where the gating logic
used to live.

2026-08-15: the University module (Course info/Homework,
`_project_university_section.html`) is removed entirely, alongside the
whole Schedule module it depended on for its only source of data (a
"class" was a Schedule-created recurring event) -- see plans/STATE.md's
removal entry. A label's scope is just tasks/events/contacts again.

No delete endpoint anywhere in this file, per §0.1: "removing" a label in
the UI is `clear_label` -- it empties `object_labels` for that name, not a
row deletion. `label_config` can keep a stale config row with nothing
pointing at it; that's harmless and expected, not cleaned up here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db, templates
from . import dashboard as dashboard_router

router = APIRouter(prefix="/labels", tags=["labels"])

# 2026-08-08: grew from 8 to 16 -- direct feedback ("more colors options
# (16) with small label under each color"). Order is a rough rainbow
# sweep (warm to cool) ending in the two neutrals, so the picker grid
# reads left-to-right/top-to-bottom the way a real color wheel would,
# not an arbitrary list. The original 8 keep their exact names/values
# (see style.css's --tag-*/.cal-* comments) -- every label/habit that
# already picked one of them is unaffected; these are pure additions.
COLORS = [
    "red", "orange", "yellow", "lime", "green", "mint", "teal", "cyan",
    "blue", "indigo", "purple", "magenta", "pink", "brown", "gray", "slate",
]

# Label color name -> the hex it paints with, mirroring style.css's
# `.cal-*` swatch classes (COLORS above is the picker order; this is the
# actual paint). Consumers that need a real color value for a label by
# name -- e.g. routers/timeline.py painting a label block's task bars in
# the label's assigned color -- import this rather than restating hexes.
#
# 2026-08-09: the swatch set went pastel, then converged again -- the two
# theme packs (deep tints / pale pastels) were merged into one set of
# *mixed* medium tones (moderate brightness + saturation) that reads on
# both a light and a dark surface; the dark theme redefines nothing.
# These are the medium-tone *backgrounds* of that set, kept hex-for-hex
# in sync with style.css's :root --cal-bg-* variables. The foregrounds
# are text colors and never painted onto a bar here, so only the
# backgrounds live in this map.
CAL_COLOR_HEX = {
    "red": "#c6594f", "orange": "#bf7a33", "yellow": "#b59b33", "lime": "#96a93e",
    "green": "#3f8f60", "mint": "#2f9c8a", "teal": "#2f8fa3", "cyan": "#2f86ab",
    "blue": "#3778bd", "indigo": "#575dcf", "purple": "#8a56c1", "magenta": "#ac4e93",
    "pink": "#c1577e", "brown": "#967a44", "gray": "#70767d", "slate": "#5b6b7d",
}

# The contrast-picked foreground of each medium swatch above -- white on
# the deeper hues, near-black on the two inherently light ones (yellow,
# lime) -- the text side of the .cal-* pair (mirroring style.css's .cal-*
# classes, same one-source-of-truth rule as CAL_COLOR_HEX). Consumers
# that paint a bar / block / icon *on top of* a swatch background use
# this so the glyph stays legible; only the backgrounds live in
# CAL_COLOR_HEX.
CAL_COLOR_FOREGROUND = {
    "red": "#ffffff", "orange": "#ffffff", "yellow": "#1d1d1f", "lime": "#1d1d1f",
    "green": "#ffffff", "mint": "#ffffff", "teal": "#ffffff", "cyan": "#ffffff",
    "blue": "#ffffff", "indigo": "#ffffff", "purple": "#ffffff", "magenta": "#ffffff",
    "pink": "#ffffff", "brown": "#ffffff", "gray": "#ffffff", "slate": "#ffffff",
}

# 2026-08-08: grouped into named categories (direct feedback: "more icons
# grouped into very useful icons") instead of one flat, ungrouped list --
# see templates/_icon_swatch_picker.html for how this renders (a labeled
# section per group, not a single wall of ~140 undifferentiated glyphs).
# Nearly every icon in the shared sprite (templates/_icons_sprite.html) is
# offered now, not just the ~100 originally curated -- the only ones left
# out are pure UI-chrome (chevrons, x, plus, external-link, move, merge,
# a bare square, trash/trash-2, a second "edit") that read as app actions,
# not something you'd pick to *represent* a label/habit/Space.
#
# `LABEL_ICONS` (a flat list, used by any code that just needs "is this a
# known icon name" or a plain count -- e.g. habits.py's `ICONS` alias)
# stays derived from this dict rather than hand-duplicated, so the two
# can never drift apart.
#
# 2026-08-08 follow-up (reverted same day): a first attempt moved
# activity/calendar/repeat/address-book/watch/home into Organization and
# the "No icon" reset option inside it -- direct feedback was that
# Organization was fine as it was, revert. Kept instead: a new "Academic"
# group (below), per separate direct feedback asking for icons that
# actually fit this app's own university-course side (Schedule's classes,
# Homework tasks, the whole `_project_university_section.html` "Course
# info"/"Homework" story) -- university/courses, history, writing, and
# debate specifically. Built by re-homing already-offered icons that
# genuinely fit better here than where they sat (a course textbook is
# "Academic," not "Documents" in general; a bar chart of grades/research
# data fits here more than "Finance & Shopping"), not by inventing new
# glyphs outside the sprite: book/book-open (courses/textbooks), archive
# (history/records), globe/map/compass (history/geography), bar-chart/
# bar-chart-2/pie-chart (research/grades data), mic (debate/presentations),
# thumbs-up (debate agree/disagree), award (academic achievement),
# bookmark (citations/references). Each of those six other groups keeps
# every icon it had before minus only the ones moved here -- nothing else
# about them changed.
ICON_GROUPS: dict[str, list[str]] = {
    "Organization": [
        "folder", "folder-plus", "folder-minus", "briefcase", "clipboard",
        "inbox", "box", "package", "list", "tag", "flag",
        "star", "check-square", "target", "crosshair",
        "filter", "sliders",
    ],
    "Academic": [
        "book", "book-open", "award", "archive", "globe", "map", "compass",
        "bar-chart", "bar-chart-2", "pie-chart", "mic", "bookmark", "thumbs-up",
    ],
    "Documents": [
        "file", "file-text", "edit-3", "pen-tool",
        "type", "printer", "paperclip",
    ],
    "Layout": ["layers", "layout", "grid", "sidebar", "columns"],
    "Tech & Devices": [
        "code", "terminal", "cpu", "monitor", "smartphone", "tablet",
        "server", "hard-drive", "database", "wifi", "bluetooth", "cast",
        "airplay", "github", "git-branch", "git-commit", "git-pull-request",
        "command", "disc", "download", "upload", "battery", "zap", "zap-off",
    ],
    "Communication": [
        "share", "share-2", "link", "link-2", "rss", "mail", "phone",
        "send", "at-sign", "hash", "address-book",
    ],
    "People": ["user", "users", "user-plus", "user-check", "heart", "smile"],
    "Media": [
        "camera", "video", "film", "music", "headphones", "image",
        "scissors", "aperture", "play", "pause", "stop-circle", "volume-2",
        "radio", "tv", "speaker",
    ],
    "Finance & Shopping": [
        "dollar-sign", "credit-card", "trending-up", "trending-down",
        "shopping-cart", "shopping-bag", "gift", "truck",
    ],
    "Nature & Lifestyle": [
        "sun", "moon", "cloud", "cloud-rain", "wind", "thermometer",
        "droplet", "umbrella", "sunrise", "sunset", "coffee", "feather",
    ],
    "Places & Travel": ["map-pin", "navigation", "navigation-2", "anchor", "shuffle"],
    "Time & Security": [
        "shield", "lock", "unlock", "key", "life-buoy", "eye", "watch",
        "clock", "bell", "tool", "settings", "activity", "calendar",
        "home", "repeat",
    ],
}

LABEL_ICONS = [name for group in ICON_GROUPS.values() for name in group]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- #
# Manage page
# --------------------------------------------------------------------- #


@router.get("")
def manage_labels(request: Request, conn=Depends(get_db)):
    """The list is grouped by Space membership only (side work, 2026-08-15
    follow-up direct feedback): "Group" (formerly "Parent label") is a
    dropdown of Spaces only now (see update_label's own validation), so
    every group a label can land in corresponds to a real Space label,
    never an arbitrary/stale free-text value -- a group heading IS that
    Space's own row (rendered bold/tinted, `.is-space`) with its children
    indented directly under it, not a second, disconnected divider row
    naming the same string. A Space that itself has another Space as its
    Group nests as a (still visually `.is-space`) child row rather than
    also getting its own top-level section, so it's never rendered twice."""
    labels = db.list_labels(conn)
    for lbl in labels:
        # Status is only needed for is_project rows (the badge shows it) --
        # skipped for everything else rather than calling db.project_status
        # on every label.
        if lbl.get("is_project"):
            lbl["project_status"] = db.project_status(conn, lbl)

    space_names = {l["name"] for l in labels if l.get("generate_space")}
    children_of: dict[str, list[dict]] = {}
    top_level_spaces = []
    ungrouped = []
    for lbl in labels:
        parent = lbl.get("parent_name")
        if lbl.get("generate_space"):
            if parent in space_names and parent != lbl["name"]:
                children_of.setdefault(parent, []).append(lbl)
            else:
                top_level_spaces.append(lbl)
        elif parent in space_names:
            children_of.setdefault(parent, []).append(lbl)
        else:
            ungrouped.append(lbl)

    top_level_spaces.sort(key=lambda l: l["name"].lower())
    ungrouped.sort(key=lambda l: l["name"].lower())
    for name in children_of:
        children_of[name].sort(key=lambda l: l["name"].lower())
    space_groups = [dict(s, children=children_of.get(s["name"], [])) for s in top_level_spaces]

    return templates.TemplateResponse(
        "labels_manage.html",
        {
            "request": request,
            "active_tab": "labels",
            "crumbs": [{"url": "/settings", "name": "Settings"}],
            "title": "Labels",
            # Named `space_groups`, not `spaces` -- base.html's nav rail
            # already binds a template-local `spaces` via `{% set %}` (the
            # sidebar's own Space list), which would silently shadow a
            # same-named context variable for this page's whole render.
            # See labels_manage.html's own comment on this.
            "space_groups": space_groups,
            "has_multiple_labels": len(labels) > 1,
            "ungrouped": ungrouped,
            "has_labels": bool(labels),
        },
    )


def _label_role(cfg: dict) -> str:
    """"none" / "space" / "project" -- the mutually-exclusive Role a label
    can have (side work, 2026-08-15 direct feedback: "becoming a project
    should be mutually exclusive to a space"). `is_project` wins if a
    pre-existing label somehow still has both flags set (from before this
    rework) -- a label edited through this page from now on can never
    reach that state again, see update_label below, but nothing here
    forces a one-time migration of old rows that were never re-saved."""
    if cfg.get("is_project"):
        return "project"
    if cfg.get("generate_space"):
        return "space"
    return "none"


@router.get("/{name}/edit")
def edit_label_modal(name: str, request: Request, conn=Depends(get_db)):
    """The label edit modal (side work, 2026-08-15 direct feedback: "a
    button that opens a modal window to edit labels with all the colors,
    icons, etc."). Replaces labels_manage.html's old per-row inline forms
    (rename/color/icon/parent/abbreviation/space-checkbox) AND the Project
    <details> popover (promote/dates/archive/demote) that had briefly
    lived there (2026-08-15, same day) -- both now live in one form here,
    submitted together to update_label below.

    2026-08-15 follow-up: "Group" (formerly "Parent label") only ever
    offers actual Space labels -- `space_label_names` below, everything
    else about a label's grouping is display-only (manage_labels' own
    Space-children grouping). Merge moved back out to its own small
    modal (merge_modal below), so it's no longer built here."""
    cfg = db.effective_label_config(conn, name)
    role = _label_role(cfg)
    has_children = bool(db.list_child_labels(conn, name))
    project_status = db.project_status(conn, cfg) if role == "project" else None
    space_label_names = sorted(
        (l["name"] for l in db.list_labels(conn) if l.get("generate_space") and l["name"] != name),
        key=str.lower,
    )
    # A stale parent_name from before this rework (any label could be a
    # parent) might not name a current Space -- keep it selectable so
    # Save can't silently drop it just because the label opened this
    # modal without touching Group at all.
    if cfg.get("parent_name") and cfg["parent_name"] not in space_label_names:
        space_label_names = sorted(space_label_names + [cfg["parent_name"]], key=str.lower)
    return templates.TemplateResponse(
        "label_edit_modal.html",
        {
            "request": request,
            "l": cfg,
            "role": role,
            "has_children": has_children,
            "project_status": project_status,
            "colors": COLORS,
            "icon_groups": ICON_GROUPS,
            "space_label_names": space_label_names,
        },
    )


@router.get("/{name}/merge-modal")
def merge_modal(name: str, request: Request, conn=Depends(get_db)):
    """Small standalone modal (side work, 2026-08-15 follow-up direct
    feedback: "Merge should be a button in the list... it should open a
    small modal window where the user selects") -- just the destination
    picker, posting to the unchanged /labels/{name}/merge below."""
    other_names = sorted((l["name"] for l in db.list_labels(conn) if l["name"] != name), key=str.lower)
    return templates.TemplateResponse(
        "label_merge_modal.html",
        {"request": request, "name": name, "other_label_names": other_names},
    )


@router.post("/{name}/update")
def update_label(
    name: str,
    new_name: str = Form(""),
    color: str = Form("blue"),
    icon: str = Form(""),
    description: str = Form(""),
    parent_name: str = Form(""),
    abbreviation: str = Form(""),
    role: str = Form("none"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    conn=Depends(get_db),
):
    """The label edit modal's single Save button -- one endpoint for every
    field the old rename/set/promote/dates/demote endpoints each handled
    separately, since they're now one form instead of five small ones.
    Those older endpoints (this file's rename_label/set_label,
    routers/projects.py's promote/set_dates/demote/archive) are untouched
    and still work standalone -- nothing else in the app calls them, but
    removing them isn't this slice's job and `tests/test_project_stack.py`
    still exercises routers/projects.py's directly.

    Role replaces the old independent generate_space checkbox + is_project
    promote flow with one mutually-exclusive choice (side work, 2026-08-15
    direct feedback) -- picking "project" always clears generate_space and
    picking "space" always clears is_project/dates/archived_at, so a label
    saved through this form can never end up with both set at once.

    2026-08-15 follow-up (same day): two more direct-feedback changes --
    (1) overlapping project periods are always allowed now, no confirm
    step (the old `confirm_overlap` checkbox/409-conflict flow removed
    entirely, per "Allow this period to overlap another project shouldn't
    exist because it should always be true"); (2) `parent_name` ("Group")
    must be blank or name an actual Space -- the modal's own dropdown
    already only offers Spaces, this is the server-side backstop for
    whatever it's handed."""
    new_name = (new_name or "").strip() or name
    abbreviation = abbreviation if isinstance(abbreviation, str) else ""
    abbreviation = abbreviation.strip()[:5] or None
    start_date = start_date.strip() if isinstance(start_date, str) else ""
    end_date = end_date.strip() if isinstance(end_date, str) else ""
    role = role if role in ("space", "project") else "none"
    parent_name = (parent_name or "").strip() or None

    if role == "project" and (not start_date or not end_date):
        raise HTTPException(400, "A project needs both a start and end date.")

    if parent_name:
        parent_cfg = db.get_label_config(conn, parent_name)
        if parent_name == name or not parent_cfg or not parent_cfg.get("generate_space"):
            raise HTTPException(400, f'"{parent_name}" is not a Space -- Group can only be an existing Space.')

    if new_name != name:
        db.rename_label(conn, name, new_name)
        # rename_label merges into new_name if it already names a
        # different existing label (see its own docstring) -- either way,
        # every field below now belongs under new_name.
        name = new_name

    existing = db.get_label_config(conn, name) or {}
    row = {
        "name": name,
        "color": color or "blue",
        "icon": icon.strip() or None,
        "description": description,
        "parent_name": parent_name,
        "abbreviation": abbreviation,
        "generate_space": 1 if role == "space" else 0,
        "is_project": 1 if role == "project" else 0,
        "created_at": existing.get("created_at") or _now(),
    }
    if role == "project":
        row["start_date"] = start_date
        row["end_date"] = end_date
        # Keep an existing project's archived_at as-is (editing dates on an
        # archived project shouldn't quietly unarchive it); a fresh
        # promotion (wasn't already is_project) always starts unarchived.
        row["archived_at"] = existing.get("archived_at") if existing.get("is_project") else None
    else:
        row["start_date"] = None
        row["end_date"] = None
        row["archived_at"] = None
    db.upsert_label_config(conn, row)
    return RedirectResponse(url="/labels", status_code=303)


@router.post("/{name}/rename")
def rename_label(name: str, new_name: str = Form(...), conn=Depends(get_db)):
    db.rename_label(conn, name, new_name)
    return RedirectResponse(url="/labels", status_code=303)


@router.post("/{name}/merge")
def merge_label(name: str, dest_name: str = Form(...), conn=Depends(get_db)):
    if dest_name and dest_name != name:
        db.merge_labels(conn, name, dest_name)
    return RedirectResponse(url="/labels", status_code=303)


@router.post("/{name}/clear")
def clear_label(name: str, conn=Depends(get_db)):
    """"Remove from everything" -- strips this label from every object.
    Deliberately not named/routed as "delete" (§0.1): there is no entity
    being deleted, just membership being emptied. `label_config` keeps
    whatever stale row it had, harmlessly."""
    db.clear_label(conn, name)
    return RedirectResponse(url="/labels", status_code=303)


@router.post("/{name}/set")
def set_label(
    name: str,
    color: str = Form("blue"),
    icon: str = Form(""),
    description: str = Form(""),
    parent_name: str = Form(""),
    generate_space: str = Form(""),
    abbreviation: str = Form(""),
    return_to: str = Form(""),
    conn=Depends(get_db),
):
    # An abbreviation is capped at 5 characters -- anything longer a form
    # somehow submits is truncated, never stored (the manage page's input
    # enforces maxlength="5" client-side too, this is the server-side
    # backstop). Blank collapses to None so a cleared field actually
    # clears the stored value rather than writing an empty string. The
    # isinstance guard is for direct (non-request) calls, e.g. this app's
    # own test suite invoking the router function as plain Python -- there
    # `abbreviation` still holds FastAPI's Form("") marker object, not the
    # "" a real request would inject (same coercion _combine_tags does for
    # its Form([]) default).
    abbreviation = abbreviation if isinstance(abbreviation, str) else ""
    abbreviation = abbreviation.strip()[:5] or None
    db.upsert_label_config(
        conn,
        {
            "name": name,
            "color": color or "blue",
            "icon": icon.strip() or None,
            "description": description,
            "parent_name": parent_name.strip() or None,
            "generate_space": 1 if generate_space in ("1", "true", "on") else 0,
            "abbreviation": abbreviation,
            "created_at": _now(),
        },
    )
    redirect_url = return_to if isinstance(return_to, str) and return_to.startswith("/") else "/labels"
    return RedirectResponse(url=redirect_url, status_code=303)


# --------------------------------------------------------------------- #
# Generated label page -- a Space (generate_space=1) or a plain label's
# own page (the former Project page). Direct object_labels membership
# only, never transitive through parent_name/child labels (§2/§5).
# --------------------------------------------------------------------- #


def _label_scope(conn, name: str) -> dict:
    """Every task/event/contact directly tagged with `name` -- the
    "centralizes all tasks, events, contacts" behavior the old
    project/space detail pages had, now driven off object_labels instead
    of project_uid/task_lists/calendars/addressbooks.

    2026-08-07: no more `databases` key here -- the Databases feature (and
    Grades, which was built on it) is removed entirely, not just
    unlinked.

    2026-08-15: no more `classes` key here -- the Schedule module (and the
    University module built on it) is removed entirely, see this file's
    header comment."""
    tasks = [t for t in db.list_tasks(conn) if name in (t.get("tags") or [])]
    events = [e for e in db.list_events(conn) if name in (e.get("tags") or [])]
    contacts = [c for c in db.list_contacts(conn) if name in (c.get("tags") or [])]

    return {
        "tasks": tasks,
        "events": events,
        "contacts": contacts,
    }


@router.get("/{name}")
def label_detail(name: str, request: Request, edit: bool = False, conn=Depends(get_db)):
    label = db.effective_label_config(conn, name)
    is_space = label.get("generate_space")

    dashboard_router._ensure_default_label_widgets(conn, name)
    ctx = dashboard_router.widget_page_context(conn, project_uid=name, edit=edit)
    scope = _label_scope(conn, name)
    ctx.update(scope)
    ctx.update(
        {
            "request": request,
            # "label", not "labels": the manage page (/labels) lives inside
            # Settings and must light the Settings rail icon, but a label's
            # own generated page is an independent destination (base.html's
            # Space rail link highlights itself via its own path match) --
            # sharing "labels" here made the Settings icon light up next to
            # the Space link on every Space/Project page.
            "active_tab": "label",
            "label": label,
            "is_space": is_space,
            "children": db.list_child_labels(conn, name),
            "parent": db.effective_label_config(conn, label["parent_name"]) if label.get("parent_name") else None,
            # Page banner (2026-08-09, routers/banners.py) -- this label
            # page's banner + the page key (the label name) the banner
            # editor's hidden scope field and _page_banner.html's edit-mode
            # button read.
            "banner": db.get_page_banner(conn, name),
            "banner_scope": name,
        }
    )

    return templates.TemplateResponse("label_detail.html", ctx)
