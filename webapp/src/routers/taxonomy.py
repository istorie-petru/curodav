"""Settings > Taxonomy & Data: labels, projects, groups and holidays in one
table. A dropdown in the header picks the view; switching swaps only the rows
and column captions (`/settings/taxonomy/rows`). The old per-list URLs
(/settings/labels, ...) still work and open this page on their view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db, finance
from ..deps import get_db, templates

router = APIRouter(prefix="/settings/taxonomy", tags=["taxonomy"])

VIEWS = {
    "labels": {"name": "Labels", "noun": "label", "url": "/settings/labels", "new_url": "/settings/labels/new", "cols": ["Label", "Group", "Usage"]},
    "groups": {"name": "Groups", "noun": "group", "url": "/settings/groups", "new_url": "/groups/new", "cols": ["Group", "Labels", "Usage"]},
    "projects": {"name": "Projects", "noun": "project", "url": "/settings/projects", "new_url": "/settings/projects/new", "cols": ["Project", "Due", "Usage"]},
    "tags": {"name": "Transaction tags", "noun": "tag", "url": "/settings/taxonomy?view=tags", "new_url": "/finance/tags/new", "cols": ["Tag", "Group", "Usage"]},
    "frontmatter": {"name": "Frontmatter", "noun": "field", "url": "/settings/taxonomy?view=frontmatter", "new_url": "/settings/notebook/new", "cols": ["Field", "Type", "Default"]},
    "holidays": {"name": "Holidays", "noun": "holiday", "url": "/settings/holidays", "new_url": "/settings/holidays/new", "cols": ["Holiday", "Calendar", "Date range"]},
}


def _view_key(view: str) -> str:
    return view if view in VIEWS else "labels"


def rows_context(conn, request: Request, view: str) -> dict:
    from . import label_pages, labels

    view = _view_key(view)
    if view in ("labels", "projects"):
        ctx = labels._labels_context(conn, request, view)
    elif view == "groups":
        ctx = label_pages._groups_context(conn, request)
    elif view == "frontmatter":
        ctx = {"request": request, "fields": [{**f, "templates": db.list_templates_using_field(conn, f["key"])}
                                              for f in db.list_notebook_field_config(conn)]}
    elif view == "tags":
        ctx = {"request": request, "tags": finance.list_tags(conn)}
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
        "title": "Taxonomy & Data",
        "views": [{"value": k, "name": v["name"]} for k, v in VIEWS.items()],
    })
    return templates.TemplateResponse("taxonomy.html", ctx)


@router.get("")
def taxonomy_page(request: Request, view: str = "labels", conn=Depends(get_db)):
    return page_response(conn, request, view)


@router.get("/rows")
def taxonomy_rows(request: Request, view: str = "labels", conn=Depends(get_db)):
    if view not in VIEWS:
        return JSONResponse({"error": f"unknown view: {view}"}, status_code=400)
    html = templates.get_template("_taxonomy_rows.html").render(rows_context(conn, request, view))
    spec = VIEWS[view]
    return JSONResponse({"view": view, "headers": spec["cols"], "rows": html, "url": spec["url"]})
