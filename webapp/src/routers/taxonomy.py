"""Settings pages for labels, groups, projects and holidays: one shared table
builder, one page per view. Frontmatter fields and transaction tags render
the same rows inside Notebook and Finance settings. `/settings/taxonomy/rows`
reloads the rows after a change."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, modules, tags
from ..deps import get_db, templates

router = APIRouter(prefix="/settings/taxonomy", tags=["taxonomy"])

VIEWS = {
    "labels": {"name": "Shelves", "noun": "shelf", "url": "/settings/labels", "new_url": "/settings/labels/new", "cols": ["Shelf", "Space", "Usage"]},
    "label_tags": {"name": "Tags", "noun": "tag", "url": "/settings/tags", "new_url": "/settings/labels/new", "cols": ["Tag", "Shelf", "Usage"]},
    "groups": {"name": "Spaces", "noun": "space", "url": "/settings/groups", "new_url": "/groups/new", "cols": ["Space", "Shelves", "Usage"]},
    "frontmatter": {"name": "Frontmatter", "noun": "field", "url": "/settings/notebook", "new_url": "/settings/notebook/new", "cols": ["Field", "Type", "Default"]},
    "time_blocks": {"name": "Sleep & Leisure", "noun": "time block", "url": "/settings/calendar?view=time-blocks", "new_url": "/settings/time-blocks/new",
                    "cols": ["Block", "Hours", "Days"]},
    "holidays": {"name": "Holidays", "noun": "holiday", "url": "/settings/calendar", "new_url": "/settings/holidays/new", "cols": ["Holiday", "Calendar", "Date range"]},
}


_PAGE_ICONS = {"labels": "tag", "label_tags": "tag", "groups": "folder", "holidays": "calendar", "time_blocks": "calendar", "frontmatter": "file-text"}


def _view_key(view: str) -> str:
    view = view.replace("-", "_")
    return view if view in VIEWS else "labels"


def rows_context(conn, request: Request, view: str) -> dict:
    from . import label_pages, labels

    view = _view_key(view)
    if view == "labels":
        ctx = labels._labels_context(conn, request, view)
    elif view == "groups":
        ctx = label_pages._groups_context(conn, request)
    elif view == "frontmatter":
        ctx = {"request": request, "fields": [{**f, "templates": db.list_templates_using_field(conn, f["key"])}
                                              for f in db.list_notebook_field_config(conn)]}
    elif view == "label_tags":
        ctx = {"request": request, "label_tags": tags.list_tags(conn),
               "label_looks": {l["name"]: l for l in db.list_labels(conn)}}
    elif view == "time_blocks":
        from .settings import _time_block_days_label

        blocks = db.list_time_blocks(conn, "sleep") + db.list_time_blocks(conn, "leisure")
        for block in blocks:
            block["days_label"] = _time_block_days_label(block.get("days") or "")
        ctx = {"request": request, "time_blocks": blocks}
    else:
        ctx = {"request": request, "holidays": db.list_holidays(conn)}
    ctx.update({"view": view, "spec": VIEWS[view], "noun": VIEWS[view]["noun"], "new_url": VIEWS[view]["new_url"]})
    return ctx


def page_response(conn, request: Request, view: str):
    view = _view_key(view)
    ctx = rows_context(conn, request, view)
    ctx.update({
        "active_tab": "labels",
        "crumbs": [{"url": "/settings", "name": "Settings"}],
        "title": VIEWS[view]["name"],
        "page_icon": _PAGE_ICONS[view],
    })
    return templates.TemplateResponse("taxonomy.html", ctx)


@router.get("/rows")
def taxonomy_rows(request: Request, view: str = "labels", conn=Depends(get_db)):
    if view not in VIEWS:
        return JSONResponse({"error": f"unknown view: {view}"}, status_code=400)
    html = templates.get_template("_taxonomy_rows.html").render(rows_context(conn, request, view))
    spec = VIEWS[view]
    return JSONResponse({"view": view, "headers": spec["cols"], "rows": html, "url": spec["url"]})


settings_router = APIRouter(prefix="/settings/tags", tags=["tags-settings"])


@settings_router.get("")
def manage_tags(request: Request, conn=Depends(get_db)):
    return page_response(conn, request, "label_tags")


@settings_router.get("/move-modal")
def move_tag_modal(request: Request, name: str, conn=Depends(get_db)):
    tag = tags.get_tag(conn, name)
    if not tag:
        raise HTTPException(404, f"There is no tag named {name}")
    owner = tags.managed_by(conn, tag["label_name"])
    if owner:
        return templates.TemplateResponse("managed_notice_modal.html", {"request": request, "name": tag["name"], "module": modules.get(owner)})
    shelves = sorted((l["name"] for l in db.list_labels(conn) if l["name"] != tag["label_name"] and not l.get("archived_at")), key=str.lower)
    return templates.TemplateResponse("tag_move_modal.html", {"request": request, "tag": tag, "shelf_names": shelves})


@settings_router.post("/move")
def move_tag(name: str = Form(...), dest: str = Form(""), conn=Depends(get_db)):
    error = tags.move_error(conn, name, dest.strip())
    if error:
        raise HTTPException(400, error)
    tags.move_tag(conn, name, dest.strip())
    return RedirectResponse(url="/settings/tags", status_code=303)


@settings_router.get("/merge-modal")
def merge_tag_modal(request: Request, name: str, conn=Depends(get_db)):
    tag = tags.get_tag(conn, name)
    if not tag:
        raise HTTPException(404, f"There is no tag named {name}")
    owner = tags.managed_by(conn, tag["label_name"])
    if owner:
        return templates.TemplateResponse("managed_notice_modal.html", {"request": request, "name": tag["name"], "module": modules.get(owner)})
    others = sorted((t["name"] for t in tags.list_tags(conn)
                     if t["name"] != tag["name"] and not tags.managed_by(conn, t["label_name"]) and not tags.merge_error(conn, tag["name"], t["name"])),
                    key=str.lower)
    return templates.TemplateResponse("tag_merge_modal.html", {"request": request, "tag": tag, "tag_names": others})


@settings_router.post("/merge")
def merge_tag(name: str = Form(...), dest: str = Form(""), conn=Depends(get_db)):
    error = tags.merge_error(conn, name, dest.strip())
    if error:
        raise HTTPException(400, error)
    tags.merge_tags(conn, name, dest.strip())
    return RedirectResponse(url="/settings/tags", status_code=303)


calendar_router = APIRouter(prefix="/settings/calendar", tags=["calendar-settings"])


@calendar_router.get("")
def manage_calendar(request: Request, view: str = "holidays", conn=Depends(get_db)):
    """One table with two views: holiday calendars and sleep and leisure hours."""
    return page_response(conn, request, view if view.replace("-", "_") in ("holidays", "time_blocks") else "holidays")
