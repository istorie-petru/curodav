"""Labels (label-space rework Phase 2) -- replaces `routers/tags.py`
entirely and the Space/Project-management half of the old
`routers/projects.py`. See `features/architecture.md` §0/§2/§3 Phase 2
for the full model: a label is not an entity with a lifecycle (no
create/delete workflow, no cascading-delete concerns) -- it's a name that
tasks/events/contacts/habits/schedule_classes point at via the one
`object_labels` join table. Any color/icon/behavior config is a thin,
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
gone -- Course info/Homework on a Space's page (_project_university_
section.html) now always render whenever there's matching data, exactly
what leaving every checkbox unchecked already did for everyone who never
touched the control. The checkboxes only ever let someone deliberately
*hide* a section that had real data (nobody did), and two of its five
options (Tasks/Events/Contacts) never gated anything to begin with -- not
a real setting, just unused surface area. See label_modules.py's own
removal note for where the gating logic used to live.

No delete endpoint anywhere in this file, per §0.1: "removing" a label in
the UI is `clear_label` -- it empties `object_labels` for that name, not a
row deletion. `label_config` can keep a stale config row with nothing
pointing at it; that's harmless and expected, not cleaned up here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db, schedule
from ..deps import get_db, templates
from . import dashboard as dashboard_router
from .tasks import STATUS_COLORS, STATUS_LABELS

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
    labels = db.list_labels(conn)
    for lbl in labels:
        lbl["parent_display"] = lbl.get("parent_name") or "~ Ungrouped"
    labels.sort(key=lambda l: (l["parent_display"].lower(), l["name"].lower()))
    return templates.TemplateResponse(
        "labels_manage.html",
        {
            "request": request,
            "active_tab": "labels",
            "crumbs": [{"url": "/settings", "name": "Settings"}],
            "title": "Labels",
            "labels": labels,
            "colors": COLORS,
            "label_icons": LABEL_ICONS,
            "icon_groups": ICON_GROUPS,
        },
    )


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
    """Every task/event/contact/schedule_class directly tagged with `name`
    -- the "centralizes all tasks, events, contacts, classes" behavior the
    old project/space detail pages had, now driven off object_labels
    instead of project_uid/task_lists/calendars/addressbooks.

    2026-08-07: no more `databases` key here -- the Databases feature (and
    Grades, which was built on it) is removed entirely, not just
    unlinked. See _project_university_section.html's own removal note."""
    tasks = [t for t in db.list_tasks(conn) if name in (t.get("tags") or [])]
    events = [e for e in db.list_events(conn) if name in (e.get("tags") or [])]
    contacts = [c for c in db.list_contacts(conn) if name in (c.get("tags") or [])]
    classes = [c for c in db.list_schedule_classes(conn) if name in (c.get("tags") or [])]

    return {
        "tasks": tasks,
        "events": events,
        "contacts": contacts,
        "classes": classes,
    }


def _next_label(next_date: date, today: date) -> str:
    return schedule.next_label(next_date, today)


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
            # status_labels/status_colors drive the Homework table inside
            # _project_university_section.html. color/icon/parent editing
            # moved to the manage page (/labels) with the old inline
            # "Edit label" block's removal, so colors/icon_groups/
            # all_labels are no longer needed here.
            "status_labels": STATUS_LABELS,
            "status_colors": STATUS_COLORS,
        }
    )

    # §5 University module (preserved from the old project_detail):
    # Homework tasks, professor contacts, next-lecture badges -- unchanged
    # logic, just sourced from this label's own scope. 2026-08-07: no more
    # `project_databases`/linked-databases context -- the Databases
    # feature (and Grades, which was built on it) is removed entirely, see
    # _project_university_section.html's own removal note.
    ctx["homework_tasks"] = [
        t for t in scope["tasks"] if any(tag.lower() == "homework" for tag in (t.get("tags") or []))
    ]
    professor_contacts: dict[str, dict] = {}
    for cl in scope["classes"]:
        puid = cl.get("professor_contact_uid")
        if puid and puid not in professor_contacts:
            contact = db.get_contact(conn, puid)
            if contact:
                professor_contacts[puid] = contact
    ctx["professor_contacts"] = professor_contacts

    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    next_lecture: dict[str, dict] = {}
    today = date.today()
    for cl in scope["classes"]:
        next_date = schedule.next_occurrence(cl, settings, holidays, today)
        if next_date:
            next_lecture[cl["uid"]] = {"date": next_date, "label": _next_label(next_date, today)}
    ctx["class_next_lecture"] = next_lecture

    return templates.TemplateResponse("label_detail.html", ctx)
