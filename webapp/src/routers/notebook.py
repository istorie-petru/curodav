"""Notebook -- Phase 1 backend
skeleton of the 0-to-MVP roadmap: a top-level, block-based note-taking
module with two modes (see db.py's `notebook_documents` schema comment for
the full column rationale):

  * Browser mode -- this router's plain list/create/delete routes, server-
    rendered Jinja2 like every other feature.
  * Editor mode -- the `/notebook/{uid}` page, which mounts Editor.js
    (Phase 2) against the one deliberate JSON exception below.

MVP scope only: no citations, no cross-referencing, no Calibre Web, no
absorption of the old quick-capture `notes` feature (Phase 4) -- see the
roadmap for what's intentionally not here yet. The Groups/Labels widget
itself (Phase 3) lives in routers/dashboard.py's WIDGET_TYPES registry,
not here -- this router only needed to support create-with-label (already
present below) for that widget to work.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import tags as tag_store
from .. import citation_formats, clock, db, icon_font, notebook_fields, notebook_find, notebook_mentions
from ..deps import get_db, respond, templates, wants_json
from .labels import COLORS, icon_groups_for

router = APIRouter(prefix="/notebook", tags=["notebook"])

BROWSE_PAGE_SIZE = 30


def _folder_agenda(conn, name: str) -> dict:
    """The next event's date and the next three dated open tasks for a label or project folder."""
    from . import label_pages

    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    items = label_pages._agenda_items(conn, {name}, {}, tasks, 1000)
    event = next((i for i in items if i.get("kind") not in ("task", "habit") and not i.get("is_deadline")), None)
    return {"event": event, "tasks": [i for i in items if i.get("kind") == "task"][:3]}


def _folder_context(conn, request: Request, kind: str, name: str, note_type: str, sort: str, limit: int, offset: int) -> dict:
    from .labels import COLORS  # noqa: F401  (the palette the folder icon colors come from)

    if kind not in ("project", "label", "unfiled", "journal"):
        kind = "unfiled"
    name = "" if kind == "unfiled" else name
    documents, total = db.list_notebook_folder_documents(conn, kind, name, note_type, sort, "", limit, offset)
    type_looks = db.notebook_note_type_looks(conn)
    for d in documents:
        look = type_looks.get(d.get("note_type") or "", db.NOTEBOOK_TYPE_LOOK_FALLBACK)
        d["type_icon"], d["type_color"] = look["icon"], look["color"]
    cfg = db.effective_label_config(conn, name) if name else {}
    params = {k: v for k, v in (("kind", kind), ("name", name), ("note_type", note_type), ("sort", sort if sort in ("title", "updated") else "")) if v}
    return {
        "request": request,
        "active_tab": "notebook",
        "kind": kind,
        "name": name,
        "folder_name": name or "Unfiled",
        "folder_icon_name": "calendar" if kind == "journal" else cfg.get("icon") or ("inbox" if kind == "unfiled" else "folder"),
        "current_week": db.week_key(clock.today()),
        "journal_weeks": db.journal_year_weeks(conn, name, db.week_key(clock.today())) if kind == "journal" and re.fullmatch(r"\d{4}", name) else [],
        "folder_color": cfg.get("color") or "gray",
        "documents": documents,
        "total": total,
        "note_type": note_type,
        "sort": sort if sort in ("title", "updated") else "created",
        "type_items": [{"value": t, "name": t} for t in db.list_notebook_note_types_in_use(conn)],
        "has_more": offset + limit < total,
        "next_offset": offset + limit,
        "more_href": "/notebook/folder?" + urlencode({**params, "limit": limit + BROWSE_PAGE_SIZE}),
        "rows_query": urlencode(params),
        "crumbs": [{"url": "/notebook", "name": "Notebook"}],
        "back_to": "/notebook/folder?" + urlencode({k: v for k, v in (("kind", kind), ("name", name)) if v}),
        "back_label": name or "Unfiled",
        "readme": db.get_folder_readme(conn, name) if kind in ("project", "label") else "",
        "agenda": _folder_agenda(conn, name) if kind in ("project", "label") else None,
    }


@router.get("")
def list_documents(request: Request, conn=Depends(get_db)):
    """The Notebook home: generated folders (open projects, labels, Unfiled) and the library folders."""
    import json as _json

    folders = db.list_notebook_folders(conn)
    recent = db.latest_notebook_document(conn)
    report = db.get_app_meta(conn, "notebook_label_report")
    return templates.TemplateResponse(
        "notebook_home.html",
        {
            "request": request,
            "active_tab": "notebook",
            "folders": folders,
            "continue_note": recent,
            "label_report": _json.loads(report) if report else [],
            "glossary_count": len(db.list_glossary_terms(conn)),
            "citation_count": len(db.list_citations(conn)),
            "template_count": len(db.list_notebook_documents(conn, scope="templates")),
            "journal_count": sum(m["count"] for m in db.list_journal_years(conn)),
            "pinned": db.list_pinned_notebook_documents(conn),
        },
    )


@router.get("/folder")
def folder_view(
    request: Request, kind: str = "unfiled", name: str = "", note_type: str = "", sort: str = "created",
    limit: int = BROWSE_PAGE_SIZE, conn=Depends(get_db),
):
    return templates.TemplateResponse(
        "notebook_folder.html",
        _folder_context(conn, request, kind.strip(), name.strip(), note_type.strip(), sort.strip(),
                        max(BROWSE_PAGE_SIZE, min(limit, 1000)), 0),
    )


@router.post("/folder/readme")
def save_folder_readme(kind: str = Form("label"), name: str = Form(""), body: str = Form(""), conn=Depends(get_db)):
    """Saves the quick-thoughts readme of a label or project folder."""
    name = name.strip()
    if kind in ("project", "label") and name:
        db.set_folder_readme(conn, name, body[:20000])
    return RedirectResponse(url="/notebook/folder?" + urlencode({"kind": kind, "name": name}), status_code=303)


@router.get("/folder/rows")
def folder_rows(
    request: Request, kind: str = "unfiled", name: str = "", note_type: str = "", sort: str = "created",
    offset: int = 0, conn=Depends(get_db),
):
    """The next page of a folder's rows, for the Load more button."""
    ctx = _folder_context(conn, request, kind.strip(), name.strip(), note_type.strip(), sort.strip(),
                          BROWSE_PAGE_SIZE, max(offset, 0))
    html = templates.get_template("_notebook_folder_rows.html").render(ctx)
    return JSONResponse({"html": html, "has_more": ctx["has_more"], "next_offset": ctx["next_offset"]})


@router.get("/journal")
def journal_home(request: Request, conn=Depends(get_db)):
    """The Journal folder: one folder per year that has weekly notes, and a button for this week's note."""
    return templates.TemplateResponse(
        "notebook_journal.html",
        {"request": request, "active_tab": "notebook", "years": db.list_journal_years(conn), "current_week": db.week_key(clock.today()),
         "crumbs": [{"url": "/notebook", "name": "Notebook"}]},
    )


@router.post("/journal/week")
def open_journal_week(week: str = Form(...), conn=Depends(get_db)):
    """Opens the journal note of a week (`2026-42`), making it from the journal template when it does not exist yet."""
    week = week.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", week)
    if not m or not 1 <= int(m.group(2)) <= db.weeks_in_year(int(m.group(1))):
        return RedirectResponse(url="/notebook/journal", status_code=303)
    uid = db.create_journal_entry(conn, week, db.get_journal_template(conn))
    return RedirectResponse(url=f"/notebook/{uid}", status_code=303)


@router.get("/label-report")
def label_report(request: Request, conn=Depends(get_db)):
    import json as _json

    raw = db.get_app_meta(conn, "notebook_label_report")
    return templates.TemplateResponse(
        "notebook_label_report_modal.html", {"request": request, "active_tab": "notebook", "report": _json.loads(raw) if raw else []}
    )


@router.post("/label-report/dismiss")
def dismiss_label_report(conn=Depends(get_db)):
    db.set_app_meta(conn, "notebook_label_report", "")
    return RedirectResponse(url="/notebook", status_code=303)


_NONE = "__none__"


@router.get("/bulk-edit-modal")
def bulk_edit_modal(uids: str, request: Request, conn=Depends(get_db)):
    """Bulk-select "Edit": sets the same tag and Type on every selected document."""
    tag_options = [(_NONE, "No tag")] + [(i["name"], i["name"]) for i in tag_store.picker(conn, "notebook", "", [])["items"]]
    types = [(t, t.capitalize()) for t in db.list_notebook_note_types_in_use(conn)]
    fields = [
        {"name": "tag", "label": "Tag", "kind": "select", "options": tag_options},
        {"name": "note_type", "label": "Type", "kind": "select", "options": types},
    ]
    return templates.TemplateResponse(
        "bulk_edit_modal.html",
        {"request": request, "uids": [u for u in uids.split(",") if u], "noun": "document", "fields": fields,
         "post_url": "/notebook/bulk-edit", "change_type": "notebook", "back_url": "/notebook"},
    )


@router.post("/bulk-edit")
def bulk_edit(
    uids: list[str] = Form([]),
    tag: str = Form(""),
    note_type: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    now = clock.now().isoformat()
    for uid in uids:
        row = db.get_notebook_document(conn, uid)
        if row is None:
            continue
        if tag:  # a note has one tag: the new one replaces it, or "No tag" clears it
            current = row.get("tags") or []
            row["tags"] = [] if tag == _NONE else tag_store.bulk_change(conn, "notebook", uid, current, [tag], [], single=True)
            if tag == _NONE:
                tag_store.record(conn, "notebook", uid, [])
        if note_type.strip():
            row["note_type"] = note_type.strip()
        row["updated_at"] = now
        db.upsert_notebook_document(conn, row)
    return respond(x_requested_with, "/notebook", count=len(uids))


@router.post("/bulk-delete")
async def bulk_delete(request: Request, conn=Depends(get_db)):
    payload = await request.json()
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no documents selected"}, status_code=400)
    for uid in uids:
        db.delete_notebook_document(conn, uid)
    return JSONResponse({"ok": True, "count": len(uids)})


def _s(v) -> str:
    """Same isinstance guard as routers/labels.py's `_page_fields.s` --
    covers a direct (non-request) call from a test, where an unset Form
    param is still FastAPI's own `Form` marker object, not a real str."""
    return v.strip() if isinstance(v, str) else ""


async def _typed_field_values(request: Request) -> dict:
    """The properties modal's typed schema inputs (`field__<key>`); a multi-select posts several values."""
    form = await request.form()
    return {k: form.getlist(k) for k in form.keys() if k.startswith("field__")}


@router.post("")
def create_document(
    label: str = Form(""),
    template_uid: str = Form(""),
    title: str = Form(""),
    open_note: str = Form(""),
    note_type: str | None = Form(None),
    note_type_new: str = Form(""),
    tags_labels: list[str] = Form([]),
    item_tags: list[str] = Form([]),
    item_tags_field: str = Form(""),
    project: str = Form(""),
    project_field: str = Form(""),
    typed=Depends(_typed_field_values),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Creates a note: blank, or from a template's body, type and frontmatter. The New note form can also set the
    title, type, labels, project and every frontmatter field up front; without those fields (the label-page
    widget, tests) the note starts as bare as before. `label` pre-attaches the label page it was created from.
    With open_note the answer is a redirect into the editor."""
    from . import dashboard as dashboard_router

    now = clock.now().isoformat()
    uid = str(uuid.uuid4())
    template_uid = _s(template_uid)
    template = db.get_notebook_document(conn, template_uid) if template_uid else None
    if template is not None and not template["is_template"]:
        template = None
    fields = db.list_notebook_field_config(conn)
    schema_keys = {f["key"].lower() for f in notebook_fields.schema_fields(fields)}
    free = [{"key": p["key"], "value": p["value"]} for p in (template["properties"] if template else [])
            if p["key"].lower() not in schema_keys]
    typed = typed if isinstance(typed, dict) else {}
    properties, errors = notebook_fields.build_properties(fields, typed, free)
    if errors:
        detail = [{"loc": ["body", name], "msg": msg} for name, msg in errors.items()]
        return JSONResponse({"detail": detail}, status_code=422)
    if item_tags_field == "1":
        tags_labels = tag_store.labels_of(conn, item_tags[:1])
    tags = [t for t in (tags_labels if isinstance(tags_labels, list) else [])]
    if isinstance(label, str) and label and label not in tags:
        tags.append(label)
    tags = dashboard_router._tags_list(dashboard_router._with_project(conn, ",".join(tags), project, project_field))
    kind = _resolve_note_type(note_type, _s(note_type_new)) if isinstance(note_type, str) else (template["note_type"] if template else "")
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": _s(title) or "Untitled",
        "content_json": template["content_json"] if template is not None else '{"blocks": []}',
        "document_type": "full", "note_type": kind, "created_at": now, "updated_at": now,
        "tags": tags, "properties": properties,
    })
    if item_tags_field == "1":
        tag_store.record(conn, "notebook", uid, item_tags[:1])
    if open_note == "1":
        return RedirectResponse(url=f"/notebook/{uid}", status_code=303)
    return respond(x_requested_with, f"/notebook/{uid}", status_code=201, uid=uid)


FIND_TOAST_THRESHOLD = 5


def _find_hits(conn, q: str, case: bool, whole: bool) -> list[dict]:
    hits = []
    for row in db.list_notebook_content_rows(conn):
        try:
            blocks = json.loads(row["content_json"] or "{}").get("blocks", [])
        except (ValueError, AttributeError):
            continue
        report = notebook_find.find(blocks, q, case=case, whole=whole)
        if report.count:
            hits.append({"uid": row["uid"], "title": row["title"], "count": report.count, "snippets": report.snippets})
    return hits


@router.get("/templates")
def templates_page(request: Request, conn=Depends(get_db)):
    """The Templates page: every note marked as a template, opened from the Browse header."""
    type_looks = db.notebook_note_type_looks(conn)
    rows = []
    for d in db.list_notebook_documents(conn, scope="templates"):
        look = type_looks.get(d.get("note_type") or "", dict(db.NOTEBOOK_TYPE_LOOK_FALLBACK))
        rows.append({**d, "type_icon": look["icon"], "type_color": look["color"]})
    return templates.TemplateResponse(
        "notebook_templates.html",
        {"request": request, "active_tab": "notebook", "crumbs": _NOTEBOOK_HOME_CRUMB, "documents": rows},
    )


@router.post("/templates")
def create_template(x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    now = clock.now().isoformat()
    uid = str(uuid.uuid4())
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": "Untitled template", "content_json": '{"blocks": []}', "document_type": "full",
        "note_type": "", "is_template": 1, "created_at": now, "updated_at": now,
    })
    return respond(x_requested_with, f"/notebook/{uid}", status_code=201, uid=uid)


def _new_note_templates(conn) -> list[dict]:
    type_looks = db.notebook_note_type_looks(conn)
    items = [{"uid": "", "name": "Blank note"}]
    for d in db.list_notebook_documents(conn, scope="templates"):
        look = type_looks.get(d.get("note_type") or "", db.NOTEBOOK_TYPE_LOOK_FALLBACK)
        items.append({"uid": d["uid"], "name": d["title"], **look})
    return items


def _template_field_values(conn, template_uid: str) -> list[dict]:
    """Every frontmatter field as an input, prefilled with the chosen template's values."""
    template = db.get_notebook_document(conn, template_uid) if template_uid else None
    if template is not None and not template["is_template"]:
        template = None
    schema = notebook_fields.schema_fields(db.list_notebook_field_config(conn))
    return _typed_fields(schema, template["properties"] if template else [])


def new_note_context(request: Request, conn, label: str = "", template_uid: str = "") -> dict:
    """What the new-note form needs; shared by the New note modal and the sidebar's New modal."""
    template = db.get_notebook_document(conn, template_uid) if template_uid else None
    if template is not None and not template["is_template"]:
        template, template_uid = None, ""
    type_looks = db.notebook_note_type_looks(conn)
    types = [{"uid": "", "name": "No type"}] + [
        {"uid": n, "name": n, **type_looks.get(n, db.NOTEBOOK_TYPE_LOOK_FALLBACK)} for n in db.list_notebook_note_types_in_use(conn)]
    tag_names = db.list_tag_names_in_use(conn)
    label = label.strip()
    project_ctx = db.project_picker_context(conn)
    return {
        "request": request, "label": label, "template_items": _new_note_templates(conn), "template_uid": template_uid,
        "note_type_items": types, "note_type": template["note_type"] if template else "",
        "typed_fields": _template_field_values(conn, template_uid), "typed_form_id": "notebook-new-form",
        "tag_name_items": [{"uid": n, "name": n} for n in tag_names if n not in project_ctx["project_names"]],
        "labels_selected": [label] if label and label not in project_ctx["project_names"] else [],
        "pf_tags": [label] if label else [], **project_ctx,
    }


@router.get("/new")
def new_note_modal(request: Request, label: str = "", template: str = "", conn=Depends(get_db)):
    return templates.TemplateResponse("notebook_new_modal.html", {"nn": new_note_context(request, conn, label, template), "request": request})


@router.get("/new/fields")
def new_note_fields(request: Request, template: str = "", conn=Depends(get_db)):
    """The type and frontmatter inputs for the chosen template, swapped into the creation form."""
    return templates.TemplateResponse(
        "_notebook_new_fields.html", {"request": request, "nn": new_note_context(request, conn, "", template)})


@router.get("/find")
def find_modal(request: Request):
    return templates.TemplateResponse("notebook_find_modal.html", {"request": request})


@router.get("/find/preview")
def find_preview(request: Request, q: str = "", case: bool = False, whole: bool = False, conn=Depends(get_db)):
    """What a replace would touch, per document. Nothing is changed here."""
    hits = _find_hits(conn, q, case, whole) if q.strip() else []
    return templates.TemplateResponse(
        "_notebook_find_results.html",
        {"request": request, "hits": hits, "q": q, "total": sum(h["count"] for h in hits),
         "toast_threshold": FIND_TOAST_THRESHOLD},
    )


@router.post("/find/replace")
def find_replace(
    q: str = Form(""),
    replacement: str = Form(""),
    case: bool = Form(False),
    whole: bool = Form(False),
    uids: list[str] = Form([]),
    conn=Depends(get_db),
):
    """Replaces only in the documents the preview listed and the user left ticked."""
    if not q.strip():
        return JSONResponse({"error": "nothing to find"}, status_code=400)
    documents = replacements = 0
    for uid in uids:
        document = db.get_notebook_document(conn, uid)
        if document is None:
            continue
        try:
            content = json.loads(document["content_json"] or "{}")
        except ValueError:
            continue
        blocks, count = notebook_find.replace(content.get("blocks", []), q, replacement, case=case, whole=whole)
        if not count:
            continue
        content["blocks"] = blocks
        document["content_json"] = json.dumps(content)
        document["updated_at"] = clock.now().isoformat()
        db.upsert_notebook_document(conn, document)
        documents += 1
        replacements += count
    return JSONResponse({"ok": True, "documents": documents, "replacements": replacements,
                         "warn": documents > FIND_TOAST_THRESHOLD})


@router.get("/link-search")
def link_search(q: str = "", exclude: str = "", kinds: str = "all", conn=Depends(get_db)):
    """The link picker's results: entries and notes in groups, each with a subtitle, icon and color."""
    return JSONResponse(db.search_link_targets(conn, q, exclude_uid=exclude or None, kinds=kinds))


@router.get("/search")
def search_documents(
    request: Request, q: str = "", exclude: str = "", limit: int = 20, ranked: int = 0, conn=Depends(get_db)
):
    """The wikilink inline tool's own search/pick autocomplete (static/
    notebook/notebook_wikilinks.js) -- the other JSON exception in this
    router (db.search_notebook_documents's own docstring has the full
    reasoning). Registered before `/{uid}` below so "search" is never
    captured as a document uid -- same router-ordering care the
    citations/glossary routers' own prefix placement in main.py already
    needed (see [[notebook-citations-core]])."""
    docs = db.search_notebook_documents(
        conn, q, exclude_uid=exclude or None, limit=limit, rank_for=(exclude or None) if ranked else None
    )
    return JSONResponse(
        [
            {"uid": d["uid"], "title": d["title"], "note_type": d.get("note_type") or "", "color": d["color"], "icon": d["icon"]}
            for d in docs
        ]
    )


@router.get("/mentions")
def mention_candidates(kind: str = "", q: str = "", conn=Depends(get_db)):
    """Matches for the editor's `@` (contact), `$` (task or event) and `:` (icon) pickers."""
    from ..deps import _sprite_icon_names

    q = q.strip()
    if kind == "contact":
        rows = notebook_mentions.contacts(conn, q)
    elif kind == "item":
        rows = notebook_mentions.items(conn, q)
    elif kind == "icon":
        rows = notebook_mentions.icons(sorted(_sprite_icon_names()), q)
    else:
        return JSONResponse({"error": "unknown kind"}, status_code=400)
    return JSONResponse(rows)


_NOTEBOOK_HOME_CRUMB = [{"url": "/notebook", "name": "Notebook"}]


MAX_IMAGE_BYTES = 8 * 1024 * 1024


@router.post("/images")
async def upload_image(request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """A figure's picture, sent as the raw request body; returns the URL a note refers to it by."""
    from ..image_sniff import sniff_image_type

    data = await request.body()
    kind = sniff_image_type(data[:32]) if data else None
    if kind is None:
        return JSONResponse({"error": "Only JPEG, PNG, GIF and WebP images can be added"}, status_code=415)
    if len(data) > MAX_IMAGE_BYTES:
        return JSONResponse({"error": "That image is too large"}, status_code=413)
    image_id = db.store_notebook_image(conn, data, f"image/{kind}")
    return JSONResponse({"id": image_id, "url": db.IMAGE_URL_PREFIX + image_id})


@router.get("/images/{image_id}")
def serve_image(image_id: str, conn=Depends(get_db)):
    image = db.get_notebook_image(conn, image_id)
    if image is None:
        raise HTTPException(404)
    return Response(
        content=image["data"], media_type=image["mime"],
        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{uid}")
def document_page(uid: str, request: Request, back_to: str = "", back_label: str = "", editor: str = "", conn=Depends(get_db)):
    """`back_to`/`back_label` --
        the Document editor is reachable from several different contexts
        (Browse list, a label page's Notebook widget, a group dashboard's
        Notebook widget, another document's wikilink/backlink), unlike the
        Citations/Glossary library pages' own `crumbs`, which are always
        opened from exactly one place and so can stay hardcoded to Notebook
        home. Every link that navigates here carries its own origin as these
        two query params (see _widget_notebook_list.html, notebook_document.
        html's backlinks loop, and notebook_wikilinks.js's renderRelationships)
        so the header's back arrow returns to wherever the user actually came
        from, falling back to Notebook home (same target the two library
        pages already use) for a bookmarked/typed-in-directly URL that never
        carried either param.
    """
    document = db.get_notebook_document(conn, uid)
    if document is None:
        return RedirectResponse(url="/notebook", status_code=303)
    back_to = _safe_return_to(back_to)
    crumbs = [{"url": back_to, "name": back_label or "Notebook"}] if back_to else _NOTEBOOK_HOME_CRUMB
    if document["is_template"] and not back_to:
        crumbs = [{"url": "/notebook/templates", "name": "Templates"}]
    citations = db.list_notebook_citations(conn, uid)
    style = db.get_citation_format(conn)
    for c in citations:
        c["display"] = db.format_citation_display(c)
        c["bibliography"] = citation_formats.bibliography(c, style)
    return templates.TemplateResponse(
        "notebook_document.html",
        {
            "request": request, "active_tab": "notebook", "document": document,
            "citations": citations,
            "entry_groups": db.group_entries_by_kind(conn, db.list_notebook_glossary_terms(conn, uid)),
            "crumbs": crumbs,
            "journal_weeks": db.journal_year_weeks(conn, document["journal_week"][:4], db.week_key(clock.today())) if document.get("journal_week") else [],
            "sidebar_layout": db.get_notebook_settings(conn)["sidebar_layout"],
            "self_url": f"/notebook/{uid}", "self_title": document["title"],
            "new_editor": editor != "legacy",
            "toolbar_icons": icon_font.toolbar_icons(),
            "editor_choice": editor,
        },
    )


def _typed_fields(schema: list[dict], properties: list[dict]) -> list[dict]:
    stored = {p["key"].lower(): p["value"] for p in properties}
    return [
        {**f, "input_name": notebook_fields.input_name(f), "value": stored.get(f["key"].lower(), ""),
         "values": notebook_fields.stored_list(stored.get(f["key"].lower(), "")) if f["type"] == "multi-select" else []}
        for f in schema
    ]


@router.post("/{uid}/pin")
def pin_document(uid: str, pinned: str = Form("1"), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """Pins a note so it also shows at the root of the Notebook, or unpins it."""
    db.set_notebook_pinned(conn, uid, pinned == "1")
    return respond(x_requested_with, f"/notebook/{uid}")


@router.get("/{uid}/export.md")
def export_document_markdown(uid: str, conn=Depends(get_db)):
    """One note as a Markdown file, with its metadata as frontmatter."""
    from urllib.parse import quote as _quote

    from .. import notebook_markdown

    doc = db.get_notebook_document(conn, uid)
    if doc is None:
        return RedirectResponse(url="/notebook", status_code=303)
    blocks = db.inline_content_images(conn, db.get_notebook_document_content(conn, uid) or {}).get("blocks", [])
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", doc["title"] or "Untitled").strip(" .") or "Untitled"
    return Response(
        notebook_markdown.note_to_markdown(doc, blocks), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(name)}.md"},
    )


@router.get("/{uid}/properties")
def document_properties_modal(uid: str, request: Request, conn=Depends(get_db)):
    """The document-properties modal --
        title/label(s)/note_type/custom properties in one place, reachable
        from the Editor page's header icon button and, as of the same date,
        each Browser-mode document row (_notebook_browse_list.html/
        _widget_notebook_list.html). Same dual-mode contract every other form
        template in this app follows (a real page, and an in-place modal via
        data-modal) -- works with no JS either way. `document["properties"]`
        (this document's custom key/value rows) comes attached for free --
        db.get_notebook_document already does it, same as `document["tags"]`.
    """
    document = db.get_notebook_document(conn, uid)
    if document is None:
        return RedirectResponse(url="/notebook", status_code=303)
    tag_names = db.list_tag_names_in_use(conn)
    note_types = db.list_notebook_note_types_in_use(conn)
    property_keys = db.list_notebook_property_keys_in_use(conn)
    type_looks = db.notebook_note_type_looks(conn)
    schema = notebook_fields.schema_fields(db.list_notebook_field_config(conn))
    schema_keys = {f["key"].lower() for f in schema}
    typed_fields = _typed_fields(schema, document["properties"])
    free_properties = [p for p in document["properties"] if p["key"].lower() not in schema_keys]
    project_ctx = db.project_picker_context(conn)
    return templates.TemplateResponse(
        "notebook_properties_modal.html",
        {
            "request": request,
            "document": document,
            "typed_fields": typed_fields,
            "free_properties": free_properties,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "labels_selected": [t for t in document["tags"] if t not in project_ctx["project_names"]],
            "pf_tags": document["tags"], **project_ctx,
            "kind_items": [{"uid": "note", "name": "Note"}, {"uid": "template", "name": "Template"}],
            "property_key_items": property_keys,
            # A real leading "No type" item, not just an empty `ms_selected`
            # -- _widget_list_multiselect.html's single mode defaults an
            # empty selection to its *first* item (sensible for Settings >
            # Holidays' Calendar picker, wrong here: it would display
            # whatever's first in `note_types` as if chosen on a brand-new
            # document that has no type picked at all yet). Same fix
            # contact_form.html's own single-label picker already uses for
            # "no label selected" -- an explicit sentinel item, not relying
            # on the widget's own fallback.
            "note_type_items": (
                [{"uid": "", "name": "No type"}]
                + [{"uid": n, "name": n, **type_looks.get(n, db.NOTEBOOK_TYPE_LOOK_FALLBACK)} for n in note_types]
            ),
        },
    )


def _resolve_note_type(note_type: str, note_type_new: str) -> str:
    """Same "typed value always wins over the picked radio" rule as
        routers/settings.py's `_resolve_calendar_name` -- see
        _widget_list_multiselect.html's own `ms_allow_new` docstring for why
        single-mode's two fields (`note_type` from the radios, `note_type_new`
        from the always-present text input) need resolving explicitly rather
        than sharing one name.

        No fallback-to-existing-value branch -- unlike `_resolve_calendar_name` (where a blank
        radio can genuinely mean "nothing available to pick"), this picker
        always has a real, always-present "No type" sentinel radio
        (`document_properties_modal`'s `note_type_items`), so a blank `note_type`
        here is never ambiguous: it's the user explicitly choosing "No type",
        not "nothing was selected." Falling back to the previous value made it
        impossible to ever clear an already-set type back to blank -- picking
        "No type" silently kept whatever type the document already had. Blank
        now means blank, same as `tags_labels`' already-established "empty
        submission clears it" contract on this same route.
    """
    new = (note_type_new or "").strip()
    if new:
        return new
    return (note_type or "").strip()


@router.post("/{uid}")
def update_document_properties(
    uid: str,
    title: str = Form(...),
    note_type: str = Form(""),
    note_type_new: str = Form(""),
    tags_labels: list[str] = Form([]),
    item_tags: list[str] = Form([]),
    item_tags_field: str = Form(""),
    project: str = Form(""),
    project_field: str = Form(""),
    kind: str = Form(""),
    property_key: list[str] = Form([]),
    property_value: list[str] = Form([]),
    typed=Depends(_typed_field_values),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Saves the properties modal's fields in one request -- title,
        note_type (`_resolve_note_type` above), labels (`tags_labels`:
        object_labels, no separate `_new` field needed here since select mode
        shares one field name between its checkboxes and its allow-new text
        input -- see _widget_list_multiselect.html's own ms_allow_new
        docstring), and custom properties. Same `respond()`-based
        JSON-or-redirect shape every other mutation route in this app uses.
    """
    existing = db.get_notebook_document(conn, uid)
    if existing is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "document not found"}, status_code=404)
        return RedirectResponse(url="/notebook", status_code=303)
    row = dict(existing)
    row["title"] = title.strip() or "Untitled"
    row["note_type"] = _resolve_note_type(note_type, note_type_new)
    row["is_template"] = 1 if kind == "template" else 0
    if row["is_template"]:
        row["tags"] = []
    else:
        from . import dashboard as dashboard_router

        if item_tags_field == "1":
            tags_labels = tag_store.labels_of(conn, item_tags[:1])

        row["tags"] = dashboard_router._tags_list(dashboard_router._with_project(
            conn, ",".join(tags_labels if isinstance(tags_labels, list) else []),
            project if isinstance(project, str) else "", project_field if isinstance(project_field, str) else ""))
    free = [{"key": k, "value": v} for k, v in zip(property_key, property_value)]
    items, errors = notebook_fields.build_properties(
        db.list_notebook_field_config(conn), typed if isinstance(typed, dict) else {}, free)
    if errors:
        if wants_json(x_requested_with):
            detail = [{"loc": ["body", name], "msg": msg} for name, msg in errors.items()]
            return JSONResponse({"detail": detail}, status_code=422)
        return RedirectResponse(
            url=f"/notebook/{uid}/properties?error={quote(next(iter(errors.values())))}", status_code=303)
    row["properties"] = items
    row["updated_at"] = clock.now().isoformat()
    db.upsert_notebook_document(conn, row)
    if item_tags_field == "1" and not row["is_template"]:
        tag_store.record(conn, "notebook", uid, item_tags[:1])
    return respond(x_requested_with, f"/notebook/{uid}")


@router.post("/{uid}/delete")
def delete_document(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.delete_notebook_document(conn, uid)
    return respond(x_requested_with, "/notebook")


@router.get("/{uid}/bibliography")
def document_bibliography_modal(uid: str, request: Request, conn=Depends(get_db)):
    document = db.get_notebook_document(conn, uid)
    if document is None:
        return RedirectResponse(url="/notebook", status_code=303)
    attached = db.list_notebook_citations(conn, uid)
    return templates.TemplateResponse(
        "notebook_bibliography_modal.html",
        {
            "request": request,
            "document": document,
            "attached_uids": [c["uid"] for c in attached],
            "citation_items": [
                {"uid": c["uid"], "name": db.format_citation_display(c)} for c in db.list_citations(conn)
            ],
        },
    )


@router.post("/{uid}/bibliography")
def update_document_bibliography(
    uid: str,
    citation_uids: list[str] = Form([]),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    if db.get_notebook_document(conn, uid) is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "document not found"}, status_code=404)
        return RedirectResponse(url="/notebook", status_code=303)
    db.set_notebook_citations(conn, uid, citation_uids)
    return respond(x_requested_with, f"/notebook/{uid}")


@router.get("/{uid}/glossary")
def document_glossary_modal(uid: str, request: Request, conn=Depends(get_db)):
    document = db.get_notebook_document(conn, uid)
    if document is None:
        return RedirectResponse(url="/notebook", status_code=303)
    attached = db.list_notebook_glossary_terms(conn, uid)
    return templates.TemplateResponse(
        "notebook_glossary_attach_modal.html",
        {
            "request": request,
            "document": document,
            "attached_uids": [t["uid"] for t in attached],
            "term_items": [{"uid": t["uid"], "name": t["term"]} for t in db.list_glossary_terms(conn)],
        },
    )


@router.post("/{uid}/glossary/autofill")
def autofill_document_glossary(uid: str, conn=Depends(get_db)):
    """Attach every glossary term found in the saved document (the sidebar's Auto-fill button)."""
    if db.get_notebook_document(conn, uid) is None:
        return JSONResponse({"error": "document not found"}, status_code=404)
    return JSONResponse(db.autofill_notebook_glossary_terms(conn, uid))


@router.get("/{uid}/glossary/list")
def document_entries_list(uid: str, request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "_notebook_entries_list.html",
        {"request": request, "entry_groups": db.group_entries_by_kind(conn, db.list_notebook_glossary_terms(conn, uid))},
    )


@router.get("/{uid}/glossary/names")
def document_entry_names(uid: str, conn=Depends(get_db)):
    """The attached entries and their names, for the dotted links in the editor."""
    return JSONResponse(db.list_document_entry_names(conn, uid))


@router.post("/{uid}/glossary/{term_uid}/detach")
def detach_document_entry(uid: str, term_uid: str, conn=Depends(get_db)):
    db.detach_notebook_glossary_term(conn, uid, term_uid)
    return JSONResponse({"ok": True})


@router.post("/{uid}/glossary")
def update_document_glossary(
    uid: str,
    term_uids: list[str] = Form([]),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    if db.get_notebook_document(conn, uid) is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "document not found"}, status_code=404)
        return RedirectResponse(url="/notebook", status_code=303)
    db.set_notebook_glossary_terms(conn, uid, term_uids)
    return respond(x_requested_with, f"/notebook/{uid}")


# The one deliberate JSON exception in this router (db.py's
# `notebook_documents` schema comment has the full reasoning): Editor.js's
# own API is JS-object in/out, and there's no HTML fragment that can
# represent live rich-block-editor state, so this pair talks raw JSON
# instead of this app's normal server-rendered-fragment convention.
@router.get("/{uid}/content")
def get_document_content(uid: str, conn=Depends(get_db)):
    db.migrate_document_images(conn, uid)
    content = db.get_notebook_document_content(conn, uid)
    if content is None:
        return JSONResponse({"error": "document not found"}, status_code=404)
    return JSONResponse(content)


@router.put("/{uid}/content")
async def put_document_content(uid: str, request: Request, conn=Depends(get_db)):
    content = await request.json()
    if not db.set_notebook_document_content(conn, uid, content):
        return JSONResponse({"error": "document not found"}, status_code=404)
    return JSONResponse({"ok": True})


field_settings_router = APIRouter(prefix="/settings/notebook", tags=["notebook-field-settings"])

_FIELD_SETTINGS_CRUMB = [{"url": "/settings/notebook", "name": "Notebook"}]


def _field_option_rows_from_form(values: list[str], colors: list[str], icons: list[str]) -> list[dict]:
    """Zips the option rows' three parallel form arrays (same shape
    `property_key[]`/`property_value[]` already establishes for Notebook's
    own properties form) back into the list set_notebook_field_options
    expects. A short `colors`/`icons` list (a row added with no Look picked
    yet) zip-truncates to as many rows as `values` actually has -- can't
    happen from the real form (every row renders all three inputs), but
    keeps this safe to call directly from a test with partial data."""
    return [
        {"value": v, "color": c or None, "icon": i or None}
        for v, c, i in zip(values, colors + [""] * len(values), icons + [""] * len(values))
    ]


def _field_edit_context(request: Request, conn, field: dict | None, form_action: str) -> dict:
    return {
        "request": request,
        "crumbs": _FIELD_SETTINGS_CRUMB,
        "f": field,
        "form_action": form_action,
        "field_types": db.NOTEBOOK_FIELD_TYPES,
        "option_types": sorted(db.NOTEBOOK_FIELD_OPTION_TYPES),
        "colors": COLORS,
        "icon_groups_for": icon_groups_for,
    }


@field_settings_router.get("")
def settings_notebook(request: Request, conn=Depends(get_db)):
    """Notebook settings page: how a document page lays out its sidebar."""
    return templates.TemplateResponse(
        "settings_notebook.html",
        {
            "request": request,
            "active_tab": "settings_notebook",
            "crumbs": [{"url": "/settings", "name": "Settings"}],
            "title": "Notebook",
            "sidebar_layout": db.get_notebook_settings(conn)["sidebar_layout"],
            "citation_format": db.get_citation_format(conn),
            "journal_template": db.get_journal_template(conn),
            "entry_kinds": db.list_entry_kinds(conn),
            "fields": [{**f, "templates": db.list_templates_using_field(conn, f["key"])} for f in db.list_notebook_field_config(conn)],
            "journal_templates": [{"uid": "", "name": "None"}] + [
                {"uid": t["uid"], "name": t["title"] or "Untitled"} for t in db.list_notebook_documents(conn, scope="templates")],
            "citation_styles": [{"uid": k, "name": v} for k, v in citation_formats.STYLES.items()],
        },
    )


@field_settings_router.post("/journal-template")
def save_journal_template(journal_template: str = Form(""), conn=Depends(get_db)):
    db.set_journal_template(conn, journal_template.strip())
    return RedirectResponse(url="/settings/notebook", status_code=303)


@field_settings_router.post("/citation-format")
def save_citation_format(citation_format: str = Form("chicago"), conn=Depends(get_db)):
    db.set_citation_format(conn, citation_format)
    return RedirectResponse(url="/settings/notebook", status_code=303)


def _kind_modal(request: Request, conn, kind: dict | None):
    kind = kind or {"name": "", "icon": "tag", "color": "teal", "fields": []}
    return templates.TemplateResponse(
        "entry_kind_modal.html",
        {"request": request, "active_tab": "settings_notebook", "kind": kind, "is_new": not kind["name"], "colors": COLORS,
         "icon_groups": icon_groups_for(kind["icon"]), "in_use": sum(1 for e in db.list_glossary_terms(conn) if e["kind"] == kind["name"])},
    )


@field_settings_router.get("/entry-kinds/new")
def new_entry_kind_modal(request: Request, conn=Depends(get_db)):
    return _kind_modal(request, conn, None)


@field_settings_router.get("/entry-kinds/edit")
def edit_entry_kind_modal(request: Request, name: str, conn=Depends(get_db)):
    kind = next((k for k in db.list_entry_kinds(conn) if k["name"] == name), None)
    if kind is None:
        return RedirectResponse(url="/settings/notebook", status_code=303)
    return _kind_modal(request, conn, kind)


def _kind_error(error: dict, x_requested_with):
    if wants_json(x_requested_with):
        return JSONResponse({"detail": [{"loc": ["body", error["field"]], "msg": error["message"]}]}, status_code=422)
    return RedirectResponse(url="/settings/notebook?" + urlencode({"error": error["message"]}), status_code=303)


@field_settings_router.post("/entry-kinds")
def save_entry_kind_form(
    original: str = Form(""), name: str = Form(""), color: str = Form("teal"), icon: str = Form("tag"),
    field_keep: list[str] = Form([]), field_new: list[str] = Form([]),
    x_requested_with: str | None = Header(default=None), conn=Depends(get_db),
):
    error = db.save_entry_kind(conn, _s(original), name, _s(icon), color if color in COLORS else "teal",
                               field_keep if isinstance(field_keep, list) else [], field_new if isinstance(field_new, list) else [])
    if error:
        return _kind_error(error, x_requested_with)
    return respond(x_requested_with, "/settings/notebook")


@field_settings_router.post("/entry-kinds/delete")
def delete_entry_kind_form(name: str = Query(...), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    error = db.delete_entry_kind(conn, name)
    if error:
        return _kind_error(error, x_requested_with)
    return respond(x_requested_with, "/settings/notebook")


frontmatter_settings_router = APIRouter(prefix="/settings/frontmatter", tags=["notebook-frontmatter-settings"])


@frontmatter_settings_router.get("")
def settings_frontmatter():
    """Old bookmark: the frontmatter fields live in Taxonomy & Data."""
    return RedirectResponse(url="/settings/notebook", status_code=303)


@field_settings_router.post("/layout")
def save_notebook_layout(sidebar_layout: str = Form("stacked"), conn=Depends(get_db)):
    """The Document editor's "sidebar layout" preference -- see db.save_notebook_settings' own docstring and
        notebook_document.html's own header comment for what each of the two
        values actually changes. A plain `data-change-submit` <select>, same
        pattern settings_your_profile.html's Nickname field uses -- no Save
        button needed.
    """
    db.save_notebook_settings(conn, sidebar_layout)
    return RedirectResponse(url="/settings/notebook", status_code=303)


@field_settings_router.get("/new")
def new_notebook_field_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "notebook_field_edit_modal.html",
        _field_edit_context(request, conn, None, "/settings/notebook"),
    )


@field_settings_router.get("/{uid}/edit")
def edit_notebook_field_modal(uid: str, request: Request, conn=Depends(get_db)):
    field = db.get_notebook_field_config(conn, uid)
    if field is None:
        return RedirectResponse(url="/settings/notebook", status_code=303)
    context = _field_edit_context(request, conn, field, f"/settings/notebook/{uid}/update")
    context["using_templates"] = db.list_templates_using_field(conn, field["key"])
    return templates.TemplateResponse("notebook_field_edit_modal.html", context)


@field_settings_router.post("")
def create_notebook_field(
    label: str = Form(""),
    type: str = Form("text"),
    default_value: str = Form(""),
    option_value: list[str] = Form([]),
    option_color: list[str] = Form([]),
    option_icon: list[str] = Form([]),
    conn=Depends(get_db),
):
    label = _s(label)
    if not label:
        return RedirectResponse(url="/settings/notebook", status_code=303)
    uid = db.upsert_notebook_field_config(
        conn,
        {
            "key": db.new_notebook_field_key(conn, label), "label": label, "type": type,
            "default_value": _s(default_value) or None,
        },
    )
    if type in db.NOTEBOOK_FIELD_OPTION_TYPES:
        db.set_notebook_field_options(conn, uid, _field_option_rows_from_form(option_value, option_color, option_icon))
    return RedirectResponse(url="/settings/notebook", status_code=303)


def _rebuild_builtin_options(existing_options: list[dict], colors: list[str], icons: list[str]) -> list[dict]:
    """A builtin field's option VALUES are fixed -- only each option's color/icon is user-editable, so
        this rebuilds the list from the field's own existing option order,
        pairing in the submitted color/icon positionally and ignoring whatever
        `option_value` the form posted entirely. A short submitted colors/
        icons list (shouldn't happen -- the form always renders one Look
        picker per existing option) falls back to that option's current look
        rather than clearing it.
    """
    rows = []
    for i, opt in enumerate(existing_options):
        color = colors[i] if i < len(colors) else opt.get("color")
        icon = icons[i] if i < len(icons) else opt.get("icon")
        rows.append({"value": opt["value"], "color": color or None, "icon": icon or None})
    return rows


@field_settings_router.post("/{uid}/update")
def update_notebook_field(
    uid: str,
    label: str = Form(""),
    type: str = Form("text"),
    default_value: str = Form(""),
    option_value: list[str] = Form([]),
    option_color: list[str] = Form([]),
    option_icon: list[str] = Form([]),
    conn=Depends(get_db),
):
    existing = db.get_notebook_field_config(conn, uid)
    if existing is None:
        return RedirectResponse(url="/settings/notebook", status_code=303)
    if existing["builtin"]:
        label = _s(label) or existing["label"]
        db.upsert_notebook_field_config(conn, {
            "uid": uid, "key": existing["key"], "label": label, "type": existing["type"],
            "default_value": existing["default_value"],
        })
        if existing["type"] in db.NOTEBOOK_FIELD_OPTION_TYPES:
            db.set_notebook_field_options(
                conn, uid, _rebuild_builtin_options(existing["options"], option_color, option_icon)
            )
        return RedirectResponse(url="/settings/notebook", status_code=303)

    label = _s(label)
    if not label:
        return RedirectResponse(url="/settings/notebook", status_code=303)
    db.upsert_notebook_field_config(
        conn,
        {
            "uid": uid, "key": existing["key"], "label": label, "type": type,
            "default_value": _s(default_value) or None,
        },
    )
    if type in db.NOTEBOOK_FIELD_OPTION_TYPES:
        db.set_notebook_field_options(conn, uid, _field_option_rows_from_form(option_value, option_color, option_icon))
    else:
        # A field switched away from Select/Multi-select no longer has an
        # option list to show -- same "the stored shape follows the
        # current type" rule _attach_notebook_field_options already
        # applies on read; this is that same rule's write-time mirror, so
        # a later switch back to Select doesn't resurrect stale options.
        db.set_notebook_field_options(conn, uid, [])
    return RedirectResponse(url="/settings/notebook", status_code=303)


@field_settings_router.post("/{uid}/delete")
def delete_notebook_field(uid: str, conn=Depends(get_db)):
    existing = db.get_notebook_field_config(conn, uid)
    if existing is not None and not existing["builtin"]:
        db.delete_notebook_field_config(conn, uid)
    return RedirectResponse(url="/settings/notebook", status_code=303)


citations_router = APIRouter(prefix="/notebook/citations", tags=["notebook-citations"])

_CITATIONS_CRUMB = [{"url": "/notebook", "name": "Notebook"}]


def _citation_authors_from_form(families: list[str], givens: list[str]) -> list[dict[str, str]]:
    """Zips the create/edit modal's parallel `author_family[]`/
    `author_given[]` arrays (contact_phone_email_rows.js's generic
    repeatable-row convention, see _contact_form_fields.html's phone/email
    rows for the precedent) into the list db.upsert_citation expects.
    Rows where both fields are blank (an added-then-abandoned row) are
    dropped, same "blank row is absent" rule set_notebook_properties
    already uses for a blank key."""
    authors = []
    for family, given in zip(families, givens):
        family, given = family.strip(), given.strip()
        if family or given:
            authors.append({"family": family, "given": given})
    return authors


def _safe_return_to(return_to: str) -> str:
    """Same same-origin-relative-only guard as routers/labels.py's
    `return_to` Form field and routers/auth.py's `next` param -- this one
    is a GET query param instead (the "new citation"/"new glossary term"
    link from an attach-picker modal, item I's modal-stack Cancel fix), but
    the risk is identical: an unvalidated value becomes an href fetched by
    modal.js's openModal(), which would happily fetch an absolute/
    off-origin URL if allowed through."""
    return return_to if return_to.startswith("/") and not return_to.startswith("//") else ""


def _citation_edit_context(request: Request, c: dict | None, form_action: str, return_to: str = "") -> dict:
    return {
        "request": request,
        "crumbs": _CITATIONS_CRUMB,
        "c": c,
        "form_action": form_action,
        "citation_types": db.CITATION_TYPES,
        "return_to": _safe_return_to(return_to),
    }


CITATION_SORT_OPTIONS = [
    ("title", "Title (A-Z)"),
    ("type", "Type"),
    ("year", "Year (newest first)"),
    ("author", "Author"),
]
_CITATION_SORT_KEYS = frozenset(k for k, _ in CITATION_SORT_OPTIONS)


def _resolve_citation_year_range(year_from: str, year_to: str) -> tuple[int | None, int | None]:
    """Both blank by default -- "don't
        autocomplete" unless Start actually has a value, at which point a
        blank End is filled in as "present day" (today's year), not left open-
        ended -- an unbounded "from 1900 onward" range reads as a mistake more
        often than an intentional one. The reverse isn't true: End alone (no
        Start) is a perfectly normal "everything up to year X" query and needs
        no default for Start.
    """
    lo = db.parse_citation_year(year_from)
    hi = db.parse_citation_year(year_to)
    if lo is not None and hi is None:
        hi = clock.now().year
    return lo, hi


def _citation_sort_value(c: dict, field: str):
    """One field's own sort key for a citation -- `title` (the default/
        fallback for any unrecognized value) is a plain casefolded string,
        `type`/`author` are likewise single comparable values, `year` is
        already a ready-made tuple (db.citation_year_sort_key). Shared by
        both the primary and secondary sort fields,
        so there's exactly one place that knows how to compare citations by
        any given field, not two near-duplicate branches.
    """
    if field == "type":
        return c["type_label"].casefold()
    if field == "year":
        return db.citation_year_sort_key(c["year"])
    if field == "author":
        # Citations with no authors at all sort after every citation that
        # has one, regardless of which field is actually being compared.
        return (not c["author_keys"], c["author_keys"][0].casefold() if c["author_keys"] else "")
    return c["title"].casefold()


def _filter_and_sort_citations(
    citations: list[dict],
    type_vals: list[str],
    author_vals: list[str],
    year_from: str,
    year_to: str,
    sort: str,
    sort2: str,
) -> list[dict]:
    """Shared by the library page and (eventually) any other citation list
        view -- filters are a plain AND across dimensions, same convention the
        Browse page's rail already established. Author matching checks
        EVERY author on a citation, not just the first.

        Sort is primary (`sort`) + secondary (`sort2`) -- two independent
        fields, not one combined picker. Title is
        always appended as an unconditional third/tiebreaker level regardless
        of what's picked, so the result stays fully deterministic even when
        Primary and Secondary end up equal for two citations (or are the same
        field picked twice, which simply makes Secondary a no-op).
    """
    selected_types, selected_authors = set(type_vals), set(author_vals)
    if selected_types:
        citations = [c for c in citations if c["type"] in selected_types]
    if selected_authors:
        citations = [c for c in citations if selected_authors & set(c["author_keys"])]
    year_lo, year_hi = _resolve_citation_year_range(year_from, year_to)
    if year_lo is not None or year_hi is not None:
        def _in_range(c: dict) -> bool:
            year = db.parse_citation_year(c["year"])
            if year is None:
                return False
            if year_lo is not None and year < year_lo:
                return False
            if year_hi is not None and year > year_hi:
                return False
            return True
        citations = [c for c in citations if _in_range(c)]
    citations = sorted(
        citations,
        key=lambda c: (_citation_sort_value(c, sort), _citation_sort_value(c, sort2), c["title"].casefold()),
    )
    return citations


@citations_router.get("")
def citations_library(
    request: Request,
    type: list[str] = Query([]),
    author: list[str] = Query([]),
    year_from: str = "",
    year_to: str = "",
    sort: str = "title",
    sort2: str = "title",
    q: str = "",
    conn=Depends(get_db),
):
    sort = sort if sort in _CITATION_SORT_KEYS else "title"
    sort2 = sort2 if sort2 in _CITATION_SORT_KEYS else "title"
    type_labels = dict(db.CITATION_TYPES)
    citations = db.list_citations(conn)
    for c in citations:
        c["display_authors"] = db.format_citation_authors(c["authors"])
        c["type_label"] = type_labels.get(c["type"], c["type"])
        c["author_keys"] = [db.citation_author_key(a) for a in c["authors"]]
    needle = q.strip().casefold()
    if needle:
        citations = [c for c in citations if needle in c["title"].casefold() or needle in c["display_authors"].casefold()]
    citations = _filter_and_sort_citations(citations, type, author, year_from, year_to, sort, sort2)
    return templates.TemplateResponse(
        "notebook_citations_list.html",
        {
            "request": request,
            "q": q,
            "active_tab": "notebook",
            "crumbs": _CITATIONS_CRUMB,
            "citations": citations,
            # Carried straight through to the "Filters" link so reopening
            # the modal shows the picker pre-set to whatever's already
            # applied on this page, not a blank form.
            "current_query": request.url.query,
            # Year is one range, not one count per picked value -- either
            # bound being set counts as a single active filter. Sort is
            # likewise one count covering both Primary and Secondary
            # together, not two separate increments.
            "active_filter_count": (
                len(type) + len(author) + (1 if (year_from or year_to) else 0)
                + (1 if (sort != "title" or sort2 != "title") else 0)
            ),
        },
    )


@citations_router.get("/filters")
def citations_filters_modal(
    request: Request,
    type: list[str] = Query([]),
    author: list[str] = Query([]),
    year_from: str = "",
    year_to: str = "",
    sort: str = "title",
    sort2: str = "title",
    conn=Depends(get_db),
):
    """The Filters modal. Author options are built from
        `list_citation_authors_in_use` (distinct values actually in the data,
        same shape as the property-key picker), not a fixed list -- Type is
        the other fixed, small (7-value) list; Year is a from/to interval, two plain number inputs, not a
        dropdown at all -- `_resolve_citation_year_range`'s own comment has
        the "blank End defaults to the present year, but only once Start is
        set" rule. Sort is Primary (`sort`) + Secondary (`sort2`), two
        independent single-select dropdowns sharing the
        same CITATION_SORT_OPTIONS list -- `_citation_sort_value`/
        `_filter_and_sort_citations` have the actual comparison logic. Type/
        Author render with `ms_search=true` (the new
        in-dropdown fuzzy filter, static/app.js's multiselect IIFE) so a
        library with hundreds of authors stays usable. The Apply button's
        href is server-rendered to already match the current query string (so
        clicking it with no changes just closes the modal via a real
        navigation back to the same filtered view); static/
        notebook_citations_filters.js keeps it in sync live as the user
        changes any control (including auto-filling End once Start gets a
        value) -- see that file's own header comment for why a GET form can't
        just submit itself through modal.js's generic (POST-shaped) form
        handler.
    """
    current_query = request.url.query
    # Same "render the common case server-side, let JS sync the rest"
    # convention this app's other pre-paint defaults use -- the End field
    # shows "present day" the moment Start has a value even before any JS
    # runs (notebook_citations_filters.js does the equivalent live, for a
    # Start typed *after* the modal's already open).
    display_year_to = year_to or (str(clock.now().year) if year_from else "")
    return templates.TemplateResponse(
        "notebook_citations_filters_modal.html",
        {
            "request": request,
            "type_items": [{"uid": k, "name": v} for k, v in db.CITATION_TYPES],
            "selected_types": type,
            "author_items": [{"uid": a, "name": a} for a in db.list_citation_authors_in_use(conn)],
            "selected_authors": author,
            "selected_year_from": year_from,
            "selected_year_to": display_year_to,
            "sort_items": [{"uid": k, "name": v} for k, v in CITATION_SORT_OPTIONS],
            "selected_sort": sort,
            "selected_sort2": sort2,
            "apply_href": "/notebook/citations" + (f"?{current_query}" if current_query else ""),
        },
    )


@citations_router.get("/search")
def search_citations(q: str = "", limit: int = 20, conn=Depends(get_db)):
    """JSON autocomplete for the footnote slash-menu's "Page citation"
        action (static/notebook/notebook_footnotes.js) -- the third JSON
        exception in this router, same shape as `/notebook/search` above
        (search_documents' own docstring) and `/notebook/search`'s router-
        ordering care: registered before `/{uid}/edit` below so "search" is
        never captured as a citation uid. Plain case-insensitive substring
        match on title/container/author surnames (not the client-fuzzy
        subsequence match `ms_search` does -- this is a live server round-trip
        per keystroke, same tradeoff `/notebook/search` already made, not a
        new one introduced here) -- good enough for picking one citation out
        of a personal library, not a general search feature. Returns enough
        fields for the client to both render a result row and assemble the
        one hardcoded Chicago-inspired footnote string itself without a second round trip.
    """
    citations = db.list_citations(conn)
    needle = q.strip().casefold()
    if needle:
        def _matches(c: dict) -> bool:
            haystack = c["title"] + " " + c.get("container_title", "") + " " + " ".join(
                a.get("family", "") + " " + a.get("given", "") for a in c.get("authors", [])
            )
            return needle in haystack.casefold()
        citations = [c for c in citations if _matches(c)]
    citations = citations[:limit]
    return JSONResponse(
        [
            {
                "uid": c["uid"],
                "title": c["title"],
                "type": c["type"],
                "year": c.get("year") or "",
                "authors": c.get("authors") or [],
                "display": db.format_citation_display(c),
            }
            for c in citations
        ]
    )


@citations_router.post("/footnote")
async def citation_footnote(request: Request, conn=Depends(get_db)):
    """The text of a generated endnote in the chosen citation format."""
    payload = await request.json()
    kind = payload.get("kind") or "page_citation"
    pick = lambda key: db.get_citation(conn, payload.get(key) or "")
    citation = pick("citation") or pick("original")
    if kind != "ibidem" and citation is None:
        return JSONResponse({"error": "citation not found"}, status_code=404)
    text = citation_formats.repeated(kind, citation, db.get_citation_format(conn), payload.get("page") or "", secondary=pick("secondary"))
    return JSONResponse({"text": text})


@citations_router.get("/new")
def new_citation_modal(request: Request, return_to: str = "", conn=Depends(get_db)):
    return templates.TemplateResponse(
        "citation_edit_modal.html",
        _citation_edit_context(request, None, "/notebook/citations", return_to),
    )


@citations_router.get("/{uid}")
def citation_view_modal(uid: str, request: Request, return_to: str = "", conn=Depends(get_db)):
    c = db.get_citation(conn, uid)
    if c is None:
        return RedirectResponse(url="/notebook/citations", status_code=303)
    type_label = dict(db.CITATION_TYPES).get(c["type"], c["type"])
    rows = [(label, c.get(key)) for key, label in _CITATION_VIEW_FIELDS if c.get(key)]
    return templates.TemplateResponse(
        "citation_view_modal.html",
        {
            "request": request, "active_tab": "notebook", "c": c, "type_label": type_label, "rows": rows,
            "authors": db.format_citation_authors(c["authors"]), "entries": db.list_entries_citing(conn, uid),
            "return_to": _safe_return_to(return_to),
        },
    )


_CITATION_VIEW_FIELDS = [
    ("container_title", "Container"), ("editors", "Editors"), ("edition", "Edition"), ("volume", "Volume"), ("issue", "Issue"),
    ("pages", "Pages"), ("publisher", "Publisher"), ("place", "Place of publication"), ("institution", "Institution"),
    ("degree", "Degree"), ("isbn", "ISBN"), ("issn", "ISSN"), ("accessed", "Accessed"), ("doi", "DOI"), ("url", "URL"), ("note", "Note"),
]


@citations_router.get("/{uid}/edit")
def edit_citation_modal(uid: str, request: Request, conn=Depends(get_db)):
    c = db.get_citation(conn, uid)
    if c is None:
        return RedirectResponse(url="/notebook/citations", status_code=303)
    return templates.TemplateResponse(
        "citation_edit_modal.html",
        _citation_edit_context(request, c, f"/notebook/citations/{uid}/update"),
    )


@citations_router.post("")
def create_citation(
    type: str = Form("book"),
    title: str = Form(...),
    year: str = Form(""),
    container_title: str = Form(""),
    doi: str = Form(""),
    url: str = Form(""),
    author_family: list[str] = Form([]),
    author_given: list[str] = Form([]),
    subtitle: str = Form(""),
    edition: str = Form(""),
    volume: str = Form(""),
    issue: str = Form(""),
    pages: str = Form(""),
    publisher: str = Form(""),
    place: str = Form(""),
    isbn: str = Form(""),
    issn: str = Form(""),
    accessed: str = Form(""),
    institution: str = Form(""),
    degree: str = Form(""),
    editors: str = Form(""),
    note: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    title = title.strip()
    if not title:
        return RedirectResponse(url="/notebook/citations", status_code=303)
    uid = db.upsert_citation(
        conn,
        {
            "type": type, "title": title, "year": year.strip(),
            "container_title": container_title.strip(), "doi": doi.strip(), "url": url.strip(),
            "authors": _citation_authors_from_form(author_family, author_given), **{k: _s(v) for k, v in dict(subtitle=subtitle, edition=edition, volume=volume, issue=issue, pages=pages, publisher=publisher, place=place, isbn=isbn, issn=issn, accessed=accessed, institution=institution, degree=degree, editors=editors, note=note).items()},
        },
    )
    return respond(x_requested_with, "/notebook/citations", uid=uid)


@citations_router.post("/{uid}/update")
def update_citation(
    uid: str,
    type: str = Form("book"),
    title: str = Form(...),
    year: str = Form(""),
    container_title: str = Form(""),
    doi: str = Form(""),
    url: str = Form(""),
    author_family: list[str] = Form([]),
    author_given: list[str] = Form([]),
    subtitle: str = Form(""),
    edition: str = Form(""),
    volume: str = Form(""),
    issue: str = Form(""),
    pages: str = Form(""),
    publisher: str = Form(""),
    place: str = Form(""),
    isbn: str = Form(""),
    issn: str = Form(""),
    accessed: str = Form(""),
    institution: str = Form(""),
    degree: str = Form(""),
    editors: str = Form(""),
    note: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    existing = db.get_citation(conn, uid)
    if existing is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "citation not found"}, status_code=404)
        return RedirectResponse(url="/notebook/citations", status_code=303)
    title = title.strip() or existing["title"]
    db.upsert_citation(
        conn,
        {
            "uid": uid, "type": type, "title": title, "year": year.strip(),
            "container_title": container_title.strip(), "doi": doi.strip(), "url": url.strip(),
            "authors": _citation_authors_from_form(author_family, author_given), **{k: _s(v) for k, v in dict(subtitle=subtitle, edition=edition, volume=volume, issue=issue, pages=pages, publisher=publisher, place=place, isbn=isbn, issn=issn, accessed=accessed, institution=institution, degree=degree, editors=editors, note=note).items()},
        },
    )
    return respond(x_requested_with, "/notebook/citations")


@citations_router.post("/{uid}/delete")
def delete_citation(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.delete_citation(conn, uid)
    return respond(x_requested_with, "/notebook/citations")


glossary_router = APIRouter(prefix="/notebook/glossary", tags=["notebook-glossary"])

_GLOSSARY_CRUMB = [{"url": "/notebook", "name": "Notebook"}]


def _glossary_reference_items(conn) -> list[dict]:
    """Citations-only list for the term edit
    form's References picker (notes were dropped from it) (roadmap item F) -- one fuzzy-searchable
    multiselect over both pools rather than two separate fields, since a
    term's "further reading" is equally likely to be either. Each uid is
    prefixed with its own type (`notebook:<uid>`/`citation:<uid>`) so the
    submitted form can tell which table a given pick belongs to without a
    second round-trip -- the two uid spaces can't actually collide (both
    are independent uuid4s), but the prefix is still the honest encoding
    of what PRIMARY KEY (term_uid, ref_type, ref_uid) stores."""
    return [
        {"uid": f"citation:{c['uid']}", "name": db.format_citation_display(c), "data": {"web": "1"} if c.get("type") == "webpage" else {}}
        for c in db.list_citations(conn)
    ]


async def _reference_pages(request: Request) -> dict:
    """The per-reference page boxes of an entry form (`refstart:<uid>` / `refend:<uid>`)."""
    form = await request.form()
    return {k: str(v).strip() for k, v in form.items() if k.startswith(("refstart:", "refend:", "refkey_", "refstart_", "refend_", "refurl_", "mref_", "fref_", "sref_"))}


def _parse_reference_keys(keys: list[str], pages: dict | None = None) -> list[tuple[str, str, str, str]]:
    """Splits the References picker's `type:uid` submitted values back into
    (ref_type, ref_uid) pairs for db.set_glossary_term_references. Silently
    drops anything that doesn't carry the separator -- not a shape the form
    itself can ever submit, so this only guards a hand-crafted request.
    isinstance guard for the same reason routers/label_pages.py's `members`
    has one: a direct (non-request) call -- this suite's own test style --
    leaves an unset `list[str] = Form([])` param holding FastAPI's own Form
    marker object, not a real list."""
    keys = keys if isinstance(keys, list) else []
    out = []
    for key in keys:
        ref_type, sep, ref_uid = key.partition(":")
        if sep and ref_type == "citation" and ref_uid:
            pages = pages if isinstance(pages, dict) else {}
            out.append((ref_type, ref_uid, pages.get(f"refstart:{ref_uid}", ""), pages.get(f"refend:{ref_uid}", "")))
    # Rows of the entry form: `refkey_<n>` holds the chosen citation, `refstart_<n>` and `refend_<n>` its pages.
    pages = pages if isinstance(pages, dict) else {}
    seen = {(o[0], o[1]) for o in out}
    rows = sorted((k.removeprefix("refkey_") for k in pages if k.startswith("refkey_")), key=lambda n: (len(n), n))
    for n in rows:
        ref_type, sep, ref_uid = pages[f"refkey_{n}"].partition(":")
        if sep and ref_type == "citation" and ref_uid and (ref_type, ref_uid) not in seen:
            seen.add((ref_type, ref_uid))
            url = pages.get(f"refurl_{n}", "")
            if url:
                # A web page reference stores its address in the start-page slot; only http(s) addresses are kept.
                out.append((ref_type, ref_uid, url if url.lower().startswith(("http://", "https://")) else "", ""))
            else:
                out.append((ref_type, ref_uid, pages.get(f"refstart_{n}", ""), pages.get(f"refend_{n}", "")))
    return out


def _section_ref(pages: dict, prefix: str) -> tuple[str, str, str] | None:
    """The reference chosen in one section's row: (citation uid, page start, page end), or None. A web page
    reference carries its address (http or https only) in the page slot."""
    pages = pages if isinstance(pages, dict) else {}
    ref_type, sep, ref_uid = pages.get(f"{prefix}_key", "").partition(":")
    if not (sep and ref_type == "citation" and ref_uid):
        return None
    url = pages.get(f"{prefix}_url", "")
    if url:
        return (ref_uid, url if url.lower().startswith(("http://", "https://")) else "", "")
    return (ref_uid, pages.get(f"{prefix}_start", ""), pages.get(f"{prefix}_end", ""))


def _entry_section_refs(conn, kind: str, pages, section_ids, section_title, section_body) -> dict:
    """{section key: reference} from the entry form: the main section, each field of the kind, each kept extra section."""
    refs = {}
    main = _section_ref(pages, "mref")
    if main:
        refs["main"] = main
    groups = [k for k in db.list_entry_kinds(conn) if k["fields"]]
    for gi, group in enumerate(groups):
        if group["name"] != kind:
            continue
        for fi, name in enumerate(group["fields"]):
            ref = _section_ref(pages, f"fref_{gi}_{fi}")
            if ref:
                refs[f"field:{name}"] = ref
    fields = set(db.entry_kind_fields(conn, kind))
    ids = section_ids if isinstance(section_ids, list) else []
    titles = section_title if isinstance(section_title, list) else []
    bodies = section_body if isinstance(section_body, list) else []
    n = 0
    for i, (t, b) in enumerate(zip(titles, bodies)):
        if (t or "").strip() in fields or not ((t or "").strip() or (b or "").strip()):
            continue
        n += 1
        ref = _section_ref(pages, f"sref_{ids[i]}") if i < len(ids) else None
        if ref:
            refs[f"extra:{n}"] = ref
    return refs


async def _kind_field_values(request: Request) -> dict:
    """The kind-field boxes of an entry form (`kfield:<kind>:<field>`)."""
    form = await request.form()
    return {k: str(v) for k, v in form.items() if k.startswith("kfield:")}


def _entry_sections(conn, kind: str, kfields, section_title, section_body) -> list[tuple[str, str]]:
    """The entry's titled boxes: the kind's fields first (when filled), then its own extra boxes."""
    kfields = kfields if isinstance(kfields, dict) else {}
    fields = db.entry_kind_fields(conn, kind)
    pairs = [(f, kfields.get(f"kfield:{kind}:{f}", "").strip()) for f in fields]
    pairs = [(f, v) for f, v in pairs if v]
    extra = [(t, b) for t, b in zip(section_title if isinstance(section_title, list) else [], section_body if isinstance(section_body, list) else [])
             if (t or "").strip() not in fields]
    return pairs + extra


def _entry_extras(aliases, wiki_uid) -> dict:
    """The alternate names (one per comma) and the wiki note of an entry form."""
    return {
        "aliases": [a for a in (_s(aliases).split(",")) if a.strip()],
        "wiki_uid": _s(wiki_uid),
    }


def _glossary_edit_context(request: Request, t: dict | None, form_action: str, conn, return_to: str = "") -> dict:
    selected = db.list_glossary_term_references(conn, t["uid"]) if t else []
    return {
        "request": request,
        "crumbs": _GLOSSARY_CRUMB,
        "t": t,
        "form_action": form_action,
        "return_to": _safe_return_to(return_to),
        "reference_items": _glossary_reference_items(conn),
        "selected_reference_keys": [f"{r['ref_type']}:{r['ref_uid']}" for r in selected if r["ref_type"] == "citation"],
        "selected_references": [r for r in selected if r["ref_type"] == "citation"],
        "sections": db.entry_custom_sections(conn, t["uid"], t["kind"]) if t else [],
        "section_refs": db.list_glossary_section_refs(conn, t["uid"]) if t else {},
        "kind_field_groups": [k for k in db.list_entry_kinds(conn) if k["fields"]],
        "field_values": db.entry_field_values(conn, t["uid"], t["kind"]) if t else {},
        "current_kind": t["kind"] if t else "Term",
        "kind_items": [{"uid": k["name"], "name": k["name"]} for k in db.list_entry_kinds(conn)],
        "wiki_items": [{"uid": "", "name": "None"}] + [
            {"uid": d["uid"], "name": d["title"] or "Untitled"} for d in db.list_notebook_documents(conn)
        ],
    }


@glossary_router.get("")
def glossary_library(request: Request, q: str = "", kind: str = "", conn=Depends(get_db)):
    """The Entries list: every entry grouped by kind, found by name, alternate name or text."""
    entries = db.list_glossary_terms(conn, q, kind)
    looks = db.entry_kind_looks(conn)
    groups = []
    for k in db.list_entry_kinds(conn):
        members = [e for e in entries if e["kind"] == k["name"]]
        if members:
            groups.append({"kind": k["name"], "icon": k["icon"], "color": k["color"], "entries": members})
    return templates.TemplateResponse(
        "notebook_glossary_list.html",
        {
            "request": request,
            "active_tab": "notebook",
            "crumbs": _GLOSSARY_CRUMB,
            "groups": groups,
            "looks": looks,
            "total": len(entries),
            "q": q,
            "kind": kind,
            "kind_items": [{"value": "", "name": "All kinds"}] + [{"value": k["name"], "name": k["name"]} for k in db.list_entry_kinds(conn)],
        },
    )


@glossary_router.get("/new")
def new_glossary_term_modal(request: Request, return_to: str = "", conn=Depends(get_db)):
    return templates.TemplateResponse(
        "glossary_term_edit_modal.html",
        _glossary_edit_context(request, None, "/notebook/glossary", conn, return_to),
    )


@glossary_router.get("/{uid}/card")
def entry_card(uid: str, request: Request, conn=Depends(get_db)):
    """The small hover card: kind, short text and a link to the wiki note."""
    entry = db.get_glossary_term(conn, uid)
    if entry is None:
        return JSONResponse({"error": "entry not found"}, status_code=404)
    return templates.TemplateResponse(
        "_entry_card.html", {"request": request, "entry": entry, "look": db.entry_kind_looks(conn).get(entry["kind"], {"icon": "tag", "color": "teal"}),
                             "wiki": db.get_notebook_document(conn, entry["wiki_uid"]) if entry["wiki_uid"] else None},
    )


@glossary_router.get("/{uid}")
def entry_view_modal(uid: str, request: Request, return_to: str = "", conn=Depends(get_db)):
    entry = db.get_glossary_term(conn, uid)
    if entry is None:
        return RedirectResponse(url="/notebook/glossary", status_code=303)
    references = [r for r in db.list_glossary_term_references(conn, uid) if r["ref_type"] == "citation"]
    return templates.TemplateResponse(
        "entry_view_modal.html",
        {
            "request": request,
            "active_tab": "notebook",
            "entry": entry,
            "look": db.entry_kind_looks(conn).get(entry["kind"], {"icon": "tag", "color": "teal"}),
            "sections": db.entry_custom_sections(conn, uid, entry["kind"]),
            "field_values": {k: v for k, v in db.entry_field_values(conn, uid, entry["kind"]).items() if v},
            "references": references,
            "section_refs": db.list_glossary_section_refs(conn, uid),
            "mentions": db.list_entry_mentions(conn, uid),
            "wiki": db.get_notebook_document(conn, entry["wiki_uid"]) if entry["wiki_uid"] else None,
            "return_to": _safe_return_to(return_to),
        },
    )


@glossary_router.get("/{uid}/edit")
def edit_glossary_term_modal(uid: str, request: Request, conn=Depends(get_db)):
    t = db.get_glossary_term(conn, uid)
    if t is None:
        return RedirectResponse(url="/notebook/glossary", status_code=303)
    return templates.TemplateResponse(
        "glossary_term_edit_modal.html",
        _glossary_edit_context(request, t, f"/notebook/glossary/{uid}/update", conn),
    )


@glossary_router.post("")
def create_glossary_term(
    term: str = Form(...),
    definition: str = Form(""),
    kind: str = Form(""),
    kind_new: str = Form(""),
    aliases: str = Form(""),
    wiki_uid: str = Form(""),
    reference_keys: list[str] = Form([]),
    section_title: list[str] = Form([]),
    section_body: list[str] = Form([]),
    section_id: list[str] = Form([]),
    kfields=Depends(_kind_field_values),
    ref_pages=Depends(_reference_pages),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    term = term.strip()
    if not term:
        return RedirectResponse(url="/notebook/glossary", status_code=303)
    uid = db.upsert_glossary_term(conn, {"term": term, "definition": definition.strip(), "kind": _s(kind_new) or _s(kind), **_entry_extras(aliases, wiki_uid)})
    db.set_glossary_term_references(conn, uid, _parse_reference_keys(reference_keys, ref_pages))
    entry_kind = db.get_glossary_term(conn, uid)["kind"]
    db.set_glossary_sections(conn, uid, _entry_sections(conn, entry_kind, kfields, section_title, section_body))
    db.set_glossary_section_refs(conn, uid, _entry_section_refs(conn, entry_kind, ref_pages, section_id, section_title, section_body))
    return respond(x_requested_with, "/notebook/glossary", uid=uid)


@glossary_router.post("/{uid}/update")
def update_glossary_term(
    uid: str,
    term: str = Form(...),
    definition: str = Form(""),
    kind: str = Form(""),
    kind_new: str = Form(""),
    aliases: str = Form(""),
    wiki_uid: str = Form(""),
    reference_keys: list[str] = Form([]),
    section_title: list[str] = Form([]),
    section_body: list[str] = Form([]),
    section_id: list[str] = Form([]),
    kfields=Depends(_kind_field_values),
    ref_pages=Depends(_reference_pages),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    existing = db.get_glossary_term(conn, uid)
    if existing is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "term not found"}, status_code=404)
        return RedirectResponse(url="/notebook/glossary", status_code=303)
    term = term.strip() or existing["term"]
    db.upsert_glossary_term(conn, {"uid": uid, "term": term, "definition": definition.strip(), "kind": _s(kind_new) or _s(kind), **_entry_extras(aliases, wiki_uid)})
    db.set_glossary_term_references(conn, uid, _parse_reference_keys(reference_keys, ref_pages))
    entry_kind = db.get_glossary_term(conn, uid)["kind"]
    db.set_glossary_sections(conn, uid, _entry_sections(conn, entry_kind, kfields, section_title, section_body))
    db.set_glossary_section_refs(conn, uid, _entry_section_refs(conn, entry_kind, ref_pages, section_id, section_title, section_body))
    return respond(x_requested_with, "/notebook/glossary")


@glossary_router.post("/{uid}/delete")
def delete_glossary_term(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.delete_glossary_term(conn, uid)
    return respond(x_requested_with, "/notebook/glossary")
