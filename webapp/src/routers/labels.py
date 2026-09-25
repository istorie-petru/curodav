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
  1. The manage page (`/settings/labels`) -- rename/merge/recolor/icon/
     parent/generate_space/"clear" (strip from everywhere), same "flat row
     list" pattern tags.py/projects.py used to have.
  2. A redirect from the old label page URL (`/settings/labels/{name}`)
     to `/labels/{name}`. The page itself is in routers/label_pages.py
     since labels-as-modules slice b (2026-09-25).

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

from datetime import date, datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import get_db, templates

router = APIRouter(prefix="/settings/labels", tags=["labels"])


def _reject_reserved_label_name(name: str) -> None:
    """2026-09-07 fix (flagged in an earlier audit) -- guards every write
    path that can set a label's *name* against colliding with one of the
    sentinel banner scopes (db.PAGE_HEADER_BANNER_SCOPE /
    db.SEASON_BANNER_SCOPES). Both live in the exact same
    `page_banner_<key>` app_meta namespace a real label's own banner does
    (db.get_page_banner/set_page_banner's `page_key` is just a free-form
    string) -- nothing previously stopped a label literally named e.g.
    "__page_header__" from silently reading/writing the app-wide default
    banner instead of getting its own. The reserved names are already
    double-underscore-wrapped specifically so no name a person would
    naturally type collides with them; this just makes that non-collision
    enforced instead of assumed."""
    reserved = {db.PAGE_HEADER_BANNER_SCOPE, *db.SEASON_BANNER_SCOPES.values()}
    if name in reserved:
        raise HTTPException(400, f'"{name}" is a reserved name and can\'t be used for a label.')
    # Slice c (2026-09-25): "group:<name>" is a group page's storage key
    # (db.group_page_key), so no label may start with it.
    if name.startswith(db.GROUP_KEY_PREFIX):
        raise HTTPException(400, f'A label name can\'t start with "{db.GROUP_KEY_PREFIX}".')


def _clean_group(label_group) -> str | None:
    """The label form's Group field (labels-as-modules slice c, 2026-09-25):
    free text, trimmed, blank = no group. It replaced the Space dropdown
    (`parent_name`), so no validation against existing groups: typing a new
    name creates the group. The isinstance guard covers direct calls from
    tests, where an unset param is FastAPI's Form marker object."""
    if not isinstance(label_group, str):
        return None
    return " ".join(label_group.split())[:60] or None


def _clean_description(description) -> str | None:
    """The label form's Description (2026-09-25, UI audit L17): trimmed,
    capped at 500 characters, blank = none. Same isinstance guard as
    _clean_group for direct calls from tests."""
    if not isinstance(description, str):
        return None
    return description.strip()[:500] or None


def _page_fields(page_fields, deadline_date, has_dashboard, agenda_widget, tasks_widget, contacts_widget,
                 sidebar_pin="", widget_pin="") -> dict:
    """labels-as-modules slice b (2026-09-25): the label form's Deadline and
    Page fields as label_config columns. Returns {} when the form didn't
    carry them (no `page_fields` marker), so an older caller that posts
    without them leaves the stored values alone. Checkboxes send nothing
    when unticked, so absent means off. The isinstance guards cover direct
    (non-request) calls from tests, where an unset param is still FastAPI's
    Form marker object."""
    def s(v):
        return v.strip() if isinstance(v, str) else ""

    if s(page_fields) != "1":
        return {}
    deadline = s(deadline_date)[:10] or None
    if deadline:
        try:
            date.fromisoformat(deadline)
        except ValueError:
            raise HTTPException(400, "Deadline must be a date (YYYY-MM-DD).")

    def on(v):
        return 1 if s(v) in ("1", "true", "on") else 0

    return {
        "has_deadline": 1 if deadline else 0,
        "deadline_date": deadline,
        "has_dashboard": on(has_dashboard),
        "agenda_widget": on(agenda_widget),
        "tasks_widget": on(tasks_widget),
        "contacts_widget": on(contacts_widget),
        "sidebar_pin": on(sidebar_pin),
        "widget_pin": on(widget_pin),
    }


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
    # Added 2026-09-13 (direct request: "a bigger library of icons that fit
    # the actual uses of the app") -- curated against the user's real label
    # list (University, Asociația de Dezbateri, Birthday, Creangă Debate,
    # Debate, Family, High School), which had nothing more specific than
    # generic book/award/users glyphs to work with. New symbols drawn in
    # _icons_sprite.html; see that file's own comment for the full list.
    "School & University": [
        "graduation-cap", "school", "backpack", "pencil", "ruler",
        "calculator", "id-card", "chalkboard", "notebook", "atom",
    ],
    "Debate & Speech": [
        "message-circle", "message-square", "megaphone", "podium", "gavel",
        "trophy", "medal", "handshake", "quote", "scale",
    ],
    "Family & Celebrations": [
        "cake", "balloon", "party-popper", "baby", "family-tree",
        "candle", "confetti", "sparkles", "ribbon", "home-heart",
    ],
}

LABEL_ICONS = [name for group in ICON_GROUPS.values() for name in group]

# 2026-09-25 (UI audit L3): the icons the nav rail itself uses (base.html:
# Home, Calendar, Planner, Tasks, Habits, Contacts, Search, Settings, the
# sidebar toggle). A label or group pinned in the rail with one of these
# looked like a second Home/Calendar entry, so the label and group icon
# pickers don't offer them. ICON_GROUPS itself is unchanged (habits use it
# and never appear in the rail). A label that already has one keeps it:
# icon_groups_for() adds it back as a "Current" option.
NAV_RESERVED_ICONS = frozenset({
    "home", "calendar", "clock", "check-square", "repeat", "address-book",
    "command", "settings", "sidebar",
})

LABEL_ICON_GROUPS: dict[str, list[str]] = {
    group: [n for n in names if n not in NAV_RESERVED_ICONS]
    for group, names in ICON_GROUPS.items()
}


def icon_groups_for(current: str | None) -> dict[str, list[str]]:
    """The label/group icon picker's groups. When `current` isn't offered
    (a reserved nav icon, or one since dropped from the list), it's added
    back first under "Current": the picker's radios are the form's only
    `icon` field, so with no radio for it, saving would silently clear it."""
    offered = {n for names in LABEL_ICON_GROUPS.values() for n in names}
    if current and current not in offered:
        return {"Current": [current], **LABEL_ICON_GROUPS}
    return LABEL_ICON_GROUPS


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
    return templates.TemplateResponse("labels_manage.html", _labels_context(conn, request))


@router.get("/regions")
def labels_regions(region: str, request: Request, conn=Depends(get_db)):
    """async-CRUD region fragment (features/async-crud.md): re-renders the
    labels list body after a label edit/merge instead of a full reload."""
    if region == "list":
        return templates.TemplateResponse("_labels_table_body.html", _labels_context(conn, request))
    return JSONResponse({"error": f"unknown labels region: {region}"}, status_code=400)


def _labels_context(conn, request: Request) -> dict:
    from .label_pages import deadline_info

    labels = db.list_labels(conn)
    for lbl in labels:
        # Status is only needed for is_project rows (the badge shows it) --
        # skipped for everything else rather than calling db.project_status
        # on every label.
        if lbl.get("is_project") or lbl.get("has_deadline"):
            lbl["project_status"] = db.project_status(conn, lbl)
        # 2026-09-25 (UI audit L7): the row's deadline badge, same states
        # as the label's page (overdue / due soon / later / archived).
        lbl["deadline"] = deadline_info(lbl)

    # Sorted by group, then type (project before plain), then name
    # (2026-09-13 request, "sorted by Groups first, then by type"). Since
    # slice c (2026-09-25) the group is the text label_group; there are no
    # Space rows heading a table any more, each group's table is headed by
    # the group's own name and links to its page.
    labels.sort(key=lambda l: ((l.get("label_group") or "").lower(), _ROLE_SORT_RANK[_label_role(l)], l["name"].lower()))
    by_group: dict[str, list[dict]] = {}
    ungrouped: list[dict] = []
    for lbl in labels:
        group = lbl.get("label_group")
        if group:
            by_group.setdefault(group, []).append(lbl)
        else:
            ungrouped.append(lbl)
    # 2026-09-25 (UI audit L3): each group row shows the group's own icon.
    label_groups = [
        {"name": g, "labels": by_group[g], **db.get_group_style(conn, g)} for g in sorted(by_group, key=str.lower)
    ]

    return {
        "request": request,
        "active_tab": "labels",
        "crumbs": [{"url": "/settings", "name": "Settings"}],
        "title": "Labels",
        "labels": labels,
        "has_labels": bool(labels),
        "label_groups": label_groups,
        "ungrouped_labels": ungrouped,
    }


def _label_role(cfg: dict) -> str:
    """"none" / "project" -- a label's Role. "space" was the third role
    until labels-as-modules slice c (2026-09-25) turned Spaces into text
    groups."""
    return "project" if cfg.get("is_project") else "none"


# 2026-09-13: sort-order weights for _labels_context's Settings > Labels
# table sort (direct request: "space first, then projects, then plain") --
# a separate mapping from _label_role's own return values rather than
# hardcoding numbers inline at the one call site, so the requested order
# reads directly off this table instead of needing _label_role's docstring
# cross-referenced to see what "space"/"project"/"none" even mean here.
_ROLE_SORT_RANK = {"project": 0, "none": 1}


@router.get("/{name}/edit")
def edit_label_modal(name: str, request: Request, conn=Depends(get_db)):
    """The label edit modal -- uses the unified label_form_modal.html."""
    cfg = db.effective_label_config(conn, name)
    banner = db.get_page_banner(conn, name)
    return templates.TemplateResponse(
        "label_form_modal.html",
        {
            "request": request,
            "l": cfg,
            "colors": COLORS,
            "icon_groups": icon_groups_for(cfg.get("icon")),
            "role": _label_role(cfg),
            "group_options": [g["name"] for g in db.list_groups(conn)],
            # 2026-08-30 (direct request): a label's banner used to be
            # reachable only through a dashboard page's own edit-mode "Add/
            # Change banner" button (routers/banners.py, generate_space/
            # is_project pages only, since only those render _page_banner.
            # html) -- this is the same banner (db.get_page_banner keyed by
            # label name), just also surfaced here so ANY label can get one,
            # not only a Space/Project that happens to have a dashboard
            # page. See db.banner_for_task's priority chain (tasks/kanban
            # banner strip) for the other consumer of this same data.
            "banner": banner,
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
    label_group: str = Form(""),
    description: str = Form(""),
    role: str = Form("none"),
    page_fields: str = Form(""),
    deadline_date: str = Form(""),
    has_dashboard: str = Form(""),
    agenda_widget: str = Form(""),
    tasks_widget: str = Form(""),
    contacts_widget: str = Form(""),
    sidebar_pin: str = Form(""),
    widget_pin: str = Form(""),
    conn=Depends(get_db),
):
    """The label edit modal's single Save button -- handles the unified
    label_form_modal.html form's Role radio group (2026-08-29: replaced the
    old Space/Project checkbox pair, see label_form_modal.html's own
    comment -- "none"/"space"/"project" is mutually exclusive by
    construction now, a radio group can't submit two values at once, so
    there's no "both somehow submitted" case left to resolve here.

    2026-09-03 bug fix (direct report: "chose icons individually and they
    don't save"): `icon` was never declared as a Form param here even
    though _icon_swatch_picker.html's radios (`name="icon"`) have posted
    into this exact form since the icon picker existed -- FastAPI silently
    drops any submitted field a route doesn't declare, and `db.
    upsert_label_config`'s own "only touch what you're told to" partial-
    update contract (its own docstring) means an absent key isn't
    "cleared", it's "left exactly as it was" -- so every Save from this
    modal silently no-opped the Icon picker's selection, while `color`/
    `label_group`/`description` (all declared) saved fine right next to
    it. The now-orphaned `set_label` route below (`/{name}/set`, no
    template posts to it any more -- superseded by this one when
    label_form_modal.html was built) already had the correct `icon.strip()
    or None` pattern; mirrored here."""
    new_name = (new_name or "").strip() or name
    icon = (icon or "").strip() or None
    page = _page_fields(page_fields, deadline_date, has_dashboard, agenda_widget, tasks_widget, contacts_widget,
                        sidebar_pin, widget_pin)
    is_project = 1 if role == "project" else 0

    if new_name != name:
        _reject_reserved_label_name(new_name)
        db.rename_label(conn, name, new_name)
        name = new_name

    existing = db.get_label_config(conn, name) or {}
    row = {
        "name": name,
        "color": color if color in COLORS else "blue",
        "icon": icon,
        "label_group": _clean_group(label_group),
        "description": _clean_description(description),
        "is_project": is_project,
        "created_at": existing.get("created_at") or _now(),
        **page,
    }
    # archived_at is left alone: archiving is its own explicit action on
    # the label's page (routers/label_pages.py), not a side effect of
    # changing the role.
    db.upsert_label_config(conn, row)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/rename")
def rename_label(name: str, new_name: str = Form(...), conn=Depends(get_db)):
    _reject_reserved_label_name((new_name or "").strip())
    db.rename_label(conn, name, new_name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/merge")
def merge_label(name: str, dest_name: str = Form(...), conn=Depends(get_db)):
    if dest_name and dest_name != name:
        _reject_reserved_label_name(dest_name.strip())
        db.merge_labels(conn, name, dest_name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/clear")
def clear_label(name: str, conn=Depends(get_db)):
    """"Remove from everything" -- strips this label from every object.
    Deliberately not named/routed as "delete" (§0.1): there is no entity
    being deleted, just membership being emptied. `label_config` keeps
    whatever stale row it had, harmlessly."""
    db.clear_label(conn, name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.get("/new")
def new_label_modal(request: Request, conn=Depends(get_db)):
    """The "+ New Label" entry point -- opens the same label_form_modal.html
    the Edit buttons open, empty. Opens via data-modal, posts to create_label below."""
    return templates.TemplateResponse(
        "label_form_modal.html",
        {
            "request": request,
            "l": None,
            "colors": COLORS,
            "icon_groups": LABEL_ICON_GROUPS,
            "role": "none",
            "group_options": [g["name"] for g in db.list_groups(conn)],
        },
    )


@router.post("/create")
def create_label(
    new_name: str = Form(...),
    color: str = Form("blue"),
    icon: str = Form(""),
    label_group: str = Form(""),
    description: str = Form(""),
    role: str = Form("none"),
    page_fields: str = Form(""),
    deadline_date: str = Form(""),
    has_dashboard: str = Form(""),
    agenda_widget: str = Form(""),
    tasks_widget: str = Form(""),
    contacts_widget: str = Form(""),
    sidebar_pin: str = Form(""),
    widget_pin: str = Form(""),
    conn=Depends(get_db),
):
    """Create a new label with zero items attached -- labels are first-class
    organizational tools, not tied to any object. `role` (2026-08-29: see
    update_label's own comment) is the single Role radio value now, not two
    separately-submitted checkboxes.

    2026-09-03 bug fix -- same missing-`icon`-Form-param bug as
    update_label right above (see its own comment); a brand-new label
    created with an icon already picked in the New Label modal silently
    got no icon at all, not just an edit losing one."""
    new_name = new_name.strip()
    if not new_name:
        raise HTTPException(400, "Label name is required")
    _reject_reserved_label_name(new_name)

    icon = (icon or "").strip() or None
    page = _page_fields(page_fields, deadline_date, has_dashboard, agenda_widget, tasks_widget, contacts_widget,
                        sidebar_pin, widget_pin)

    row = {
        "name": new_name,
        "color": color if color in COLORS else "blue",
        "icon": icon,
        "label_group": _clean_group(label_group),
        # 2026-09-25 (UI audit L17): the form has a Description field now.
        "description": _clean_description(description),
        "is_project": 1 if role == "project" else 0,
        "created_at": _now(),
        **page,
    }
    db.upsert_label_config(conn, row)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/delete")
def delete_label(name: str, conn=Depends(get_db)):
    """Remove this label from every object (same as clear) -- the config row
    remains harmlessly. Named "delete" in the UI for clarity."""
    db.clear_label(conn, name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/bulk-delete")
async def bulk_delete_labels(request: Request, conn=Depends(get_db)):
    """2026-08-29 (STATE.md backlog item 1, direct request: "bulk actions
    on tables"). JSON endpoint for `static/bulk_select.js`'s Labels
    instance -- a plain loop over `db.clear_label`, same as a single row's
    own Delete button (see delete_label above): removes each label from
    every object that carries it, `label_config` rows kept harmlessly.
    `uids` here are label names, not real uids -- `static/bulk_select.js`
    doesn't care what the identifier actually is, it just round-trips
    whatever each row's checkbox `data-uid` carries."""
    payload = await request.json()
    names = payload.get("uids") or []
    if not names:
        return JSONResponse({"error": "no labels selected"}, status_code=400)
    for name in names:
        db.clear_label(conn, name)
    return JSONResponse({"ok": True, "count": len(names)})


@router.get("/bulk-merge-modal")
def bulk_merge_modal(uids: str, request: Request, conn=Depends(get_db)):
    """Direct request: "in the labels table bulk select i would like an
    option to merge labels into one". Opened via `static/bulk_select.js`'s
    Merge button (see labels_manage.html's CCBulkSelect.init call) using
    `window.CCModal.open`, same mechanism the per-row Edit button already
    uses -- `uids` arrives as a comma-joined query string (a GET link, not
    a JSON body) since this is a plain data-modal navigation, not a fetch
    call. Destination list is every existing label (2026-09-13 direct
    answer to a clarifying question: "pick any existing label" -- not
    restricted to the selected rows themselves, so a merge target outside
    the current selection is allowed, same freedom the single-row Merge
    modal already gives)."""
    selected = [n for n in uids.split(",") if n]
    all_names = sorted((l["name"] for l in db.list_labels(conn)), key=str.lower)
    return templates.TemplateResponse(
        "label_bulk_merge_modal.html",
        {"request": request, "selected_names": selected, "all_label_names": all_names},
    )


@router.post("/bulk-merge")
def bulk_merge_labels(uids: list[str] = Form([]), dest_name: str = Form(...), conn=Depends(get_db)):
    """Merges every selected label in `uids` into `dest_name` -- a plain
    loop over the existing single-pair `db.merge_labels` (see merge_label
    above), same underlying semantics: each source label's usage moves
    onto `dest_name` and its own `label_config` row is dropped. `dest_name`
    itself is skipped if it's also among `uids` (merging a label into
    itself is a no-op `db.merge_labels` already guards against, but
    skipping here avoids the pointless call)."""
    dest_name = (dest_name or "").strip()
    if not dest_name:
        raise HTTPException(400, "Choose a label to merge into")
    _reject_reserved_label_name(dest_name)
    for name in uids:
        if name and name != dest_name:
            db.merge_labels(conn, name, dest_name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/set")
def set_label(
    name: str,
    color: str = Form("blue"),
    icon: str = Form(""),
    description: str = Form(""),
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
    _reject_reserved_label_name(name)
    abbreviation = abbreviation if isinstance(abbreviation, str) else ""
    abbreviation = abbreviation.strip()[:5] or None
    db.upsert_label_config(
        conn,
        {
            "name": name,
            "color": color if color in COLORS else "blue",
            "icon": icon.strip() or None,
            "description": description,
            "abbreviation": abbreviation,
            "created_at": _now(),
        },
    )
    redirect_url = return_to if isinstance(return_to, str) and return_to.startswith("/") else "/settings/labels"
    return RedirectResponse(url=redirect_url, status_code=303)


# --------------------------------------------------------------------- #
# Old label page URL. A label's page lives at /labels/{name} now
# (routers/label_pages.py, labels-as-modules slice b, 2026-09-25); this
# keeps old links and bookmarks working. Declared last so the literal
# routes above (/new, /regions, ...) still win.
# --------------------------------------------------------------------- #


@router.get("/{name}")
def label_detail_redirect(name: str):
    return RedirectResponse(url=f"/labels/{quote(name)}", status_code=301)
