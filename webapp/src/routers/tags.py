"""Global tag registry management: create/rename/recolor/group/merge/delete
a tag, plus tag groups. See db.py's `tags`/`tag_groups` CREATE TABLE
comment for the full architecture rationale -- short version: the tag
*registry* (this router) is local-only, but tag *assignment* is real,
already-synced data (tasks/events/contacts.tags_json, round-tripped
through CATEGORIES). That means rename/merge/delete-everywhere here can't
just touch this app's SQLite cache -- they have to rewrite every affected
task/event/contact's tags_json AND push that change back through the
CalDAV/CardDAV bridge, or the change looks right for the rest of the
session and silently reverts on the next background sync (the exact bug
class desktop's own tag-rename fix documents, see
features/tags-and-linking.md)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates

router = APIRouter(prefix="/tags", tags=["tags"])

# Matches the `.tag-*` CSS classes already defined in style.css (used to
# render every tag chip on tasks_list.html/contacts_list.html/etc.) --
# deliberately a different palette from task_lists/calendars/addressbooks'
# COLORS (`.cal-*`), which is a separate set of CSS classes/variables.
TAG_COLORS = ["blue", "green", "orange", "red", "purple", "yellow", "brown", "pink", "gray"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rewrite_tag_everywhere(conn, bridge, old_name: str, new_name: str | None) -> None:
    """Renames (new_name given) or removes (new_name=None) `old_name`
    (case-insensitive match) across every task/event/contact that carries
    it, writing through the CalDAV/CardDAV bridge before updating the
    local cache -- see the module docstring. Deduplicates against any tag
    the object already carries under the new name (case-insensitive), same
    as desktop's merge behavior ("deduped, not duplicated")."""
    old_key = old_name.strip().lower()

    def _process(rows: list[dict], save_fn: Callable, upsert_fn: Callable) -> None:
        for r in rows:
            tags = r.get("tags") or []
            if not any(str(t).strip().lower() == old_key for t in tags):
                continue
            new_tags: list[str] = []
            seen: set[str] = set()
            for t in tags:
                replacement = new_name if str(t).strip().lower() == old_key else t
                if replacement is None:
                    continue
                key = str(replacement).strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    new_tags.append(replacement)
            row = dict(r)
            row["tags"] = new_tags
            row["updated_at"] = _now()
            saved = save_fn(row)
            upsert_fn(conn, saved)

    _process(db.list_tasks(conn), bridge.save_task_row, db.upsert_task)
    _process(db.list_events(conn), bridge.save_event_row, db.upsert_event)
    _process(db.list_contacts(conn), bridge.save_contact_row, db.upsert_contact)


@router.get("")
def manage_tags(request: Request, conn=Depends(get_db)):
    groups = db.list_tag_groups(conn)
    group_names = {g["uid"]: g["name"] for g in groups}
    tags = db.list_tags(conn)
    for t in tags:
        # "~ " sorts after any normal group name (ASCII), so ungrouped tags
        # cluster at the end of the manage list rather than wherever "U"
        # happens to land alphabetically -- see also projects.py's
        # identical trick for the same grouped-display request.
        t["group_name"] = group_names.get(t["group_uid"]) or "~ Ungrouped"
    tags.sort(key=lambda t: (t["group_name"].lower(), t["name"].lower()))
    return templates.TemplateResponse(
        "tags_manage.html",
        {
            "request": request,
            "active_tab": "tasks",
            "tags": tags,
            "groups": groups,
            "colors": TAG_COLORS,
        },
    )


@router.post("")
def create_tag(name: str = Form(...), color: str = Form("blue"), group_uid: str = Form(""), conn=Depends(get_db)):
    name = name.strip()
    if name and not db.get_tag_by_name(conn, name):
        db.upsert_tag(
            conn,
            {
                "uid": str(uuid.uuid4()),
                "name": name,
                "color": color,
                "group_uid": group_uid or None,
                "created_at": _now(),
            },
        )
    return RedirectResponse(url="/tags", status_code=303)


@router.post("/{uid}/edit")
def edit_tag(
    uid: str,
    name: str = Form(...),
    color: str = Form("blue"),
    group_uid: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    existing = db.get_tag(conn, uid)
    if existing is None:
        return RedirectResponse(url="/tags", status_code=303)
    new_name = name.strip() or existing["name"]
    # A rename that collides (case-insensitively) with a different existing
    # tag is treated as "merge into that tag" instead of raising a unique-
    # constraint error the user can't act on from a plain form -- picking
    # the existing tag's own destination-based Merge action if that's what
    # they actually meant is one extra click, but silently failing the
    # whole edit (or crashing) on a name collision is worse.
    collision = db.get_tag_by_name(conn, new_name)
    if collision and collision["uid"] != uid:
        return _merge(uid, collision["uid"], bridge, conn)
    if new_name.lower() != existing["name"].lower():
        _rewrite_tag_everywhere(conn, bridge, existing["name"], new_name)
    db.upsert_tag(
        conn,
        {"uid": uid, "name": new_name, "color": color, "group_uid": group_uid or None, "created_at": existing.get("created_at")},
    )
    return RedirectResponse(url="/tags", status_code=303)


def _merge(source_uid: str, dest_uid: str, bridge, conn) -> RedirectResponse:
    source = db.get_tag(conn, source_uid)
    dest = db.get_tag(conn, dest_uid)
    if source and dest and source_uid != dest_uid:
        _rewrite_tag_everywhere(conn, bridge, source["name"], dest["name"])
        db.delete_tag(conn, source_uid)
    return RedirectResponse(url="/tags", status_code=303)


@router.post("/{uid}/merge")
def merge_tag(uid: str, dest_uid: str = Form(...), bridge=Depends(get_bridge), conn=Depends(get_db)):
    return _merge(uid, dest_uid, bridge, conn)


@router.post("/{uid}/delete")
def delete_tag(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Deletes the tag everywhere -- strips it from every task/event/
    contact that carries it (write-through, see module docstring) and then
    removes the registry row. This is deliberately more than
    db.delete_tag's own scope (registry-only, see its docstring) -- the
    composition of "strip from every object" + "delete the registry row"
    is what a user clicking Delete on a tag manager actually expects,
    matching desktop's tag-delete behavior ("cascades to object_tags")."""
    existing = db.get_tag(conn, uid)
    if existing:
        _rewrite_tag_everywhere(conn, bridge, existing["name"], None)
        db.delete_tag(conn, uid)
    return RedirectResponse(url="/tags", status_code=303)


# --------------------------------------------------------------------- #
# Tag groups
# --------------------------------------------------------------------- #


@router.post("/groups")
def create_tag_group(name: str = Form(...), conn=Depends(get_db)):
    name = name.strip()
    if name:
        db.upsert_tag_group(conn, {"uid": str(uuid.uuid4()), "name": name, "created_at": _now()})
    return RedirectResponse(url="/tags", status_code=303)


@router.post("/groups/{uid}/edit")
def edit_tag_group(uid: str, name: str = Form(...), conn=Depends(get_db)):
    if name.strip():
        db.upsert_tag_group(conn, {"uid": uid, "name": name.strip(), "created_at": None})
    return RedirectResponse(url="/tags", status_code=303)


@router.post("/groups/{uid}/delete")
def delete_tag_group(uid: str, conn=Depends(get_db)):
    db.delete_tag_group(conn, uid)
    return RedirectResponse(url="/tags", status_code=303)
