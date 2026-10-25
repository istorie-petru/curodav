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
     since labels-as-modules slice b.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import clock, db, modules, tags
from ..deps import get_db, templates

router = APIRouter(prefix="/settings/labels", tags=["labels"])


def _reject_reserved_label_name(name: str) -> None:
    """Both live in the exact same
        `page_banner_<key>` app_meta namespace a real label's own banner does
        (db.get_page_banner/set_page_banner's `page_key` is just a free-form
        string) -- nothing previously stopped a label literally named e.g. "__page_header__" from silently reading/writing the app-wide default
        banner instead of getting its own. The reserved names are already
        double-underscore-wrapped specifically so no name a person would
        naturally type collides with them; this just makes that non-collision
        enforced instead of assumed.
    """
    reserved = {db.PAGE_HEADER_BANNER_SCOPE, *db.SEASON_BANNER_SCOPES.values()}
    if name in reserved:
        raise HTTPException(400, f'"{name}" is a reserved name and can\'t be used for a label.')
    if name.startswith(db.GROUP_KEY_PREFIX):
        raise HTTPException(400, f'A label name can\'t start with "{db.GROUP_KEY_PREFIX}".')


def _clean_group(label_group) -> str | None:
    """The label form's Group field:
        free text, trimmed, blank = no group. It replaced the Space dropdown
        (`parent_name`), so no validation against existing groups: typing a new
        name creates the group. The isinstance guard covers direct calls from
        tests, where an unset param is FastAPI's Form marker object.
    """
    if not isinstance(label_group, str):
        return None
    return " ".join(label_group.split())[:60] or None


def _clean_description(description) -> str | None:
    """The label form's Description: trimmed,
        capped at 500 characters, blank = none. Same isinstance guard as
        _clean_group for direct calls from tests.
    """
    if not isinstance(description, str):
        return None
    return description.strip()[:500] or None


def _page_fields(page_fields, deadline_date, page_type, agenda_widget, tasks_widget, contacts_widget,
                 notebook_widget="", sidebar_pin="", widget_pin="") -> dict:
    """labels-as-modules slice b: the label form's Deadline and
        Page fields as label_config columns. Returns {} when the form didn't
        carry them (no `page_fields` marker), so an older caller that posts
        without them leaves the stored values alone. Checkboxes send nothing
        when unticked, so absent means off. The isinstance guards cover direct
        (non-request) calls from tests, where an unset param is still FastAPI's
        Form marker object.
    """
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
        "page_type": s(page_type) if s(page_type) in db.page_types() else "sections",
        "agenda_widget": on(agenda_widget),
        "tasks_widget": on(tasks_widget),
        "contacts_widget": on(contacts_widget),
        "notebook_widget": on(notebook_widget),
        "sidebar_pin": on(sidebar_pin),
        "widget_pin": on(widget_pin),
    }


COLORS = [
    "red", "coral", "orange", "amber", "yellow", "lime", "sage", "green", "mint", "teal", "cyan", "sky",
    "blue", "indigo", "violet", "purple", "plum", "magenta", "rose", "pink", "sand", "brown", "gray", "slate",
]

CAL_COLOR_HEX = {
    "red": "#c35045", "orange": "#a1672b", "yellow": "#b59b33", "lime": "#96a93e",
    "green": "#398156", "mint": "#278172", "teal": "#2a7f91", "cyan": "#2c7d9f",
    "blue": "#3778bd", "indigo": "#575dcf", "purple": "#8a56c1", "magenta": "#ac4e93",
    "pink": "#be4e77", "brown": "#8b713f", "gray": "#70767d", "slate": "#5b6b7d",
    "coral": "#fea387", "amber": "#e6b463", "sage": "#a8c7ad", "sky": "#6cc9fd",
    "violet": "#bcb2fe", "plum": "#eca1db", "rose": "#fd9eb0", "sand": "#cabca1",
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
    "coral": "#1d1d1f", "amber": "#1d1d1f", "sage": "#1d1d1f", "sky": "#1d1d1f",
    "violet": "#1d1d1f", "plum": "#1d1d1f", "rose": "#1d1d1f", "sand": "#1d1d1f",
}

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
    return clock.now().isoformat()


# --------------------------------------------------------------------- #
# Manage page
# --------------------------------------------------------------------- #


@router.get("")
def manage_labels(request: Request, conn=Depends(get_db)):
    """The list is grouped by Space membership only: "Group" (formerly "Parent label") is a
        dropdown of Spaces only now (see update_label's own validation), so
        every group a label can land in corresponds to a real Space label,
        never an arbitrary/stale free-text value -- a group heading IS that
        Space's own row (rendered bold/tinted, `.is-space`) with its children
        indented directly under it, not a second, disconnected divider row
        naming the same string. A Space that itself has another Space as its
        Group nests as a (still visually `.is-space`) child row rather than
        also getting its own top-level section, so it's never rendered twice.
    """
    from .taxonomy import page_response

    return page_response(conn, request, "labels")


def _labels_context(conn, request: Request, kind: str = "labels") -> dict:
    from .label_pages import deadline_info

    labels = list(db.list_labels(conn))
    show = request.query_params.get("show", "")
    if show not in ("archived", "all"):
        show = ""
    if show == "archived":
        labels = [lbl for lbl in labels if lbl.get("archived_at")]
    elif show == "":
        labels = [lbl for lbl in labels if not lbl.get("archived_at")]
    for lbl in labels:
        if lbl.get("has_deadline"):
            lbl["project_status"] = db.project_status(conn, lbl)
        lbl["deadline"] = deadline_info(lbl)
        if lbl.get("label_group"):
            lbl["group_style"] = db.get_group_style(conn, lbl["label_group"])

    labels.sort(key=lambda l: (
        0 if l.get("label_group") else 1,
        (l.get("label_group") or "").lower(),
        l["name"].lower(),
    ))

    return {
        "request": request,
        "active_tab": "labels",
        "crumbs": [{"url": "/settings", "name": "Settings"}],
        "kind": "labels",
        "noun": "shelf",
        "new_url": "/settings/labels/new",
        "page_icon": "tag",
        "group_default_icon": db.GROUP_DEFAULT_ICON,
        "title": "Shelves",
        "labels": labels,
        "has_labels": bool(labels),
        "show": show,
    }


async def _tag_rows(request: Request) -> list[dict]:
    return tags.parse_rows(await request.form())


def _rows_of(tag_rows) -> list[dict]:
    """Direct calls (tests, internal callers) leave the Depends default in place; that means no tag rows."""
    return tag_rows if isinstance(tag_rows, list) else []


@router.get("/{name}/edit")
def edit_label_modal(name: str, request: Request, conn=Depends(get_db)):
    """The label edit modal -- uses the unified label_form_modal.html."""
    cfg = db.effective_label_config(conn, name)
    if cfg.get("managed_by"):
        return templates.TemplateResponse("managed_notice_modal.html", {"request": request, "name": name, "module": modules.get(cfg["managed_by"])})
    banner = db.get_page_banner(conn, name)
    return templates.TemplateResponse(
        "label_form_modal.html",
        {
            "request": request,
            "l": cfg,
            "colors": COLORS,
            "icon_groups": icon_groups_for(cfg.get("icon")),
            "group_options": [g["name"] for g in db.list_groups(conn)],
            "label_tags": tags.tags_of_label(conn, name),
            "banner": banner,
        },
    )


@router.get("/{name}/merge-modal")
def merge_modal(name: str, request: Request, conn=Depends(get_db)):
    """Small standalone modal -- just the destination
        picker, posting to the unchanged /labels/{name}/merge below.
    """
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
    page_fields: str = Form(""),
    deadline_date: str = Form(""),
    page_type: str = Form(""),
    agenda_widget: str = Form(""),
    tasks_widget: str = Form(""),
    contacts_widget: str = Form(""),
    notebook_widget: str = Form(""),
    sidebar_pin: str = Form(""),
    widget_pin: str = Form(""),
    tag_rows: list[dict] = Depends(_tag_rows),
    request: Request = None,
    conn=Depends(get_db),
):
    new_name = (new_name or "").strip() or name
    tag_rows = _rows_of(tag_rows)
    error = tags.validate_rows(conn, new_name, tag_rows)
    if error:
        raise HTTPException(400, error)
    icon = (icon or "").strip() or None
    page = _page_fields(page_fields, deadline_date, page_type, agenda_widget, tasks_widget, contacts_widget,
                        notebook_widget, sidebar_pin, widget_pin)

    renamed_from = None
    if new_name != name:
        _reject_reserved_label_name(new_name)
        db.rename_label(conn, name, new_name)
        renamed_from, name = name, new_name

    existing = db.get_label_config(conn, name) or {}
    row = {
        "name": name,
        "color": color if color in COLORS else "blue",
        "icon": icon,
        "label_group": _clean_group(label_group),
        "description": _clean_description(description),
        "created_at": existing.get("created_at") or _now(),
        **page,
    }
    # archived_at is left alone: archiving is its own explicit action on
    # the label's page (routers/label_pages.py), not a side effect of
    # changing the role.
    db.upsert_label_config(conn, row)
    tags.apply_rows(conn, name, tag_rows, COLORS)
    if renamed_from and request is not None:
        ref = urlparse(request.headers.get("referer") or "")
        if unquote(ref.path) == f"/labels/{renamed_from}":
            return RedirectResponse(url=f"/labels/{quote(name, safe='')}", status_code=303)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/rename")
def rename_label(name: str, new_name: str = Form(...), conn=Depends(get_db)):
    _reject_reserved_label_name((new_name or "").strip())
    if new_name.strip().lower() != name.lower() and tags.get_tag(conn, new_name.strip()):
        raise HTTPException(400, "A tag with that name already exists")
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
def new_label_modal(request: Request, return_to: str = "", copy: str = "", conn=Depends(get_db)):
    """The "+ New Label" entry point -- opens the same label_form_modal.html
        the Edit buttons open, empty. Opens via data-modal, posts to create_label below.
        `return_to` (modal-stack Cancel fix, same family as
        routers/notebook.py's `_safe_return_to` -- see that function's own
        comment): when this modal is opened from inside another modal that has
        no label to pick yet (published_list_create_modal.html's "Create one"
        link, shown when `all_labels` is empty), Cancel should swap back into
        that picker instead of closing the whole overlay back to
        /settings/labels. Same same-origin-relative-only guard as every other
        return_to/back_to/next param in this app (routers/label_pages.py's
        `back_to`, this module's own `set_label`'s `return_to`, routers/
        auth.py's `next`) -- an unvalidated value becomes an href fetched by
        modal.js's openModal(), which would happily fetch an absolute/
        off-origin URL if allowed through.
    """
    if not isinstance(return_to, str) or not return_to.startswith("/") or return_to.startswith("//"):
        return_to = ""
    prefill = db.effective_label_config(conn, copy) if copy else None
    return templates.TemplateResponse(
        "label_form_modal.html",
        {
            "request": request,
            "l": None,
            "prefill": prefill,
            "colors": COLORS,
            "icon_groups": icon_groups_for(prefill.get("icon")) if prefill else LABEL_ICON_GROUPS,
            "group_options": [g["name"] for g in db.list_groups(conn)],
            "return_to": return_to,
            "label_tags": [],
        },
    )


@router.post("/create")
def create_label(
    new_name: str = Form(...),
    color: str = Form("blue"),
    icon: str = Form(""),
    label_group: str = Form(""),
    description: str = Form(""),
    page_fields: str = Form(""),
    deadline_date: str = Form(""),
    page_type: str = Form(""),
    agenda_widget: str = Form(""),
    tasks_widget: str = Form(""),
    contacts_widget: str = Form(""),
    notebook_widget: str = Form(""),
    sidebar_pin: str = Form(""),
    widget_pin: str = Form(""),
    tag_rows: list[dict] = Depends(_tag_rows),
    conn=Depends(get_db),
):
    """Create a new label with zero items attached -- labels are first-class
        organizational tools, not tied to any object.
    """
    new_name = new_name.strip()
    if not new_name:
        raise HTTPException(400, "Shelf name is required")
    _reject_reserved_label_name(new_name)

    icon = (icon or "").strip() or None
    page = _page_fields(page_fields, deadline_date, page_type, agenda_widget, tasks_widget, contacts_widget,
                        notebook_widget, sidebar_pin, widget_pin)

    row = {
        "name": new_name,
        "color": color if color in COLORS else "blue",
        "icon": icon,
        "label_group": _clean_group(label_group),
        "description": _clean_description(description),
        "created_at": _now(),
        **page,
    }
    if tags.name_taken(conn, new_name):
        raise HTTPException(400, "A tag or shelf with that name already exists")
    tag_rows = _rows_of(tag_rows)
    error = tags.validate_rows(conn, new_name, tag_rows)
    if error:
        raise HTTPException(400, error)
    db.upsert_label_config(conn, row)
    tags.add_default_tag(conn, new_name, row["color"], icon or "")
    tags.apply_rows(conn, new_name, tag_rows, COLORS)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/delete")
def delete_label(name: str, conn=Depends(get_db)):
    db.delete_label_config(conn, name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/bulk-delete")
async def bulk_delete_labels(request: Request, conn=Depends(get_db)):
    """JSON endpoint for `static/bulk_select.js`'s Labels
        instance -- a plain loop over `db.clear_label`, same as a single row's
        own Delete button (see delete_label above): removes each label from
        every object that carries it, `label_config` rows kept harmlessly. `uids` here are label names, not real uids -- `static/bulk_select.js`
        doesn't care what the identifier actually is, it just round-trips
        whatever each row's checkbox `data-uid` carries.
    """
    payload = await request.json()
    names = payload.get("uids") or []
    if not names:
        return JSONResponse({"error": "no shelves selected"}, status_code=400)
    for name in names:
        db.delete_label_config(conn, name)
    return JSONResponse({"ok": True, "count": len(names)})


@router.get("/bulk-merge-modal")
def bulk_merge_modal(uids: str, request: Request, conn=Depends(get_db)):
    """Direct request: "in the labels table bulk select i would like an
        option to merge labels into one". Opened via `static/bulk_select.js`'s
        Merge button (see labels_manage.html's CCBulkSelect.init call) using
        `window.CCModal.open`, same mechanism the per-row Edit button already
        uses -- `uids` arrives as a comma-joined query string (a GET link, not
        a JSON body) since this is a plain data-modal navigation, not a fetch
        call. Destination list is every existing label.
    """
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
        raise HTTPException(400, "Choose a shelf to merge into")
    _reject_reserved_label_name(dest_name)
    for name in uids:
        if name and name != dest_name:
            db.merge_labels(conn, name, dest_name)
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.get("/bulk-edit-modal")
def bulk_edit_modal(uids: str, request: Request, conn=Depends(get_db)):
    """Bulk-select "Edit": color, group, end date and archive state for every selected label or project."""
    names = [n for n in uids.split(",") if n]
    noun = "shelf"
    fields = [
        {"name": "color", "label": "Color", "kind": "select", "options": [(c, c.title()) for c in COLORS]},
        {"name": "label_group", "label": "Group", "kind": "select",
         "options": [(_NO_GROUP, "No group")] + [(g["name"], g["name"]) for g in db.list_groups(conn)]},
        {"name": "end_date", "label": "Deadline", "kind": "date"},
        {"name": "clear_end", "label": "Remove deadline", "kind": "select",
         "options": [("1", "Remove it")]},
        {"name": "archive", "label": "Archive", "kind": "select", "options": [("archive", "Archive"), ("restore", "Restore")]},
    ]
    return templates.TemplateResponse(
        "bulk_edit_modal.html",
        {"request": request, "uids": names, "noun": noun, "fields": fields,
         "post_url": "/settings/labels/bulk-edit", "change_type": "label",
         "back_url": "/settings/labels"},
    )


_NO_GROUP = "__none__"


@router.post("/bulk-edit")
def bulk_edit_labels(
    uids: list[str] = Form([]),
    color: str = Form(""),
    label_group: str = Form(""),
    end_date: str = Form(""),
    clear_end: str = Form(""),
    archive: str = Form(""),
    conn=Depends(get_db),
):
    # Direct (non-request) calls leave an unset Form param as FastAPI's marker object, so non-strings count as blank.
    color, label_group, end_date, clear_end, archive = (v if isinstance(v, str) else "" for v in (color, label_group, end_date, clear_end, archive))
    if color and color not in COLORS:
        raise HTTPException(400, f"unknown color '{color}'")
    end_date = end_date.strip()[:10]
    if end_date:
        try:
            date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(400, "End date must be a date (YYYY-MM-DD).")
    for name in uids:
        # A label that is only in use (no settings row yet) gets one.
        config = db.get_label_config(conn, name) or {"name": name, "created_at": _now()}
        row = {"name": name, "created_at": config.get("created_at") or _now()}
        if color:
            row["color"] = color
        if label_group:
            row["label_group"] = None if label_group == _NO_GROUP else _clean_group(label_group)
        if end_date or clear_end:
            value = end_date or None
            row["has_deadline"] = 1 if value else 0
            row["deadline_date"] = value
        if len(row) > 2:
            db.upsert_label_config(conn, row)
        if archive == "archive":
            db.archive_project(conn, name)
        elif archive == "restore":
            db.unarchive_label(conn, name)
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


@router.get("/{name}")
def label_detail_redirect(name: str):
    return RedirectResponse(url=f"/labels/{quote(name)}", status_code=301)


projects_settings_router = APIRouter(prefix="/settings/projects", tags=["projects-settings"])


@projects_settings_router.get("")
def projects_settings_redirect():
    """Projects are tags on the Projects shelf now; the old page is gone."""
    return RedirectResponse(url="/settings/tags", status_code=301)
