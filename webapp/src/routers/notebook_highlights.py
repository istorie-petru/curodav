"""The Notebook's picker for book highlights: search and filter the highlights made in the reader, then put one into a Quote block
with its citation.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .. import book_annotations, citation_formats, db
from ..deps import get_db, templates

router = APIRouter(prefix="/notebook/highlights", tags=["notebook-highlights"])


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", markup or "")).strip()


def _with_citations(conn, found: dict) -> dict:
    notes: dict[str, str] = {}
    for item in found["items"]:
        uid = item["citation_uid"]
        if uid not in notes:
            c = db.get_citation(conn, uid)
            notes[uid] = _plain(citation_formats.footnote(c)) if c else item["title"]
        item["citation"] = notes[uid]
    return found


@router.get("")
def highlights_modal(request: Request, q: str = "", book: list[str] = Query([]), color: list[str] = Query([]), notes: str = "", conn=Depends(get_db)):
    found = _with_citations(conn, book_annotations.search(conn, q, book, color, bool(notes)))
    return templates.TemplateResponse("notebook_highlights_modal.html", {
        "request": request, "items": found["items"], "total": found["total"], "q": q,
        "book_items": [{"uid": b["uid"], "name": f"{b['title']} ({b['n']})"} for b in book_annotations.books_with_highlights(conn)],
        "colors": [{"uid": c, "name": c.capitalize()} for c in book_annotations.COLORS], "selected_books": book, "selected_colors": color, "only_notes": bool(notes),
    })


@router.get("/list")
def highlights_list(request: Request, q: str = "", book: list[str] = Query([]), color: list[str] = Query([]), notes: str = "", conn=Depends(get_db)):
    found = _with_citations(conn, book_annotations.search(conn, q, book, color, bool(notes)))
    return templates.TemplateResponse("_notebook_highlights_list.html", {"request": request, "items": found["items"], "total": found["total"]})


@router.post("/attach")
def attach_citation(notebook_uid: str = Form(""), citation_uid: str = Form(""), conn=Depends(get_db)):
    """Adds the book to the document's bibliography when it is not there yet (the quote's source)."""
    if db.get_citation_raw(conn, citation_uid) is None or db.get_notebook_document(conn, notebook_uid) is None:
        raise HTTPException(404)
    have = {c["citation_uid"] if "citation_uid" in c else c["uid"] for c in db.list_notebook_citations(conn, notebook_uid)}
    if citation_uid not in have:
        db.attach_notebook_citation(conn, notebook_uid, citation_uid, position=len(have))
    return JSONResponse({"ok": True})
