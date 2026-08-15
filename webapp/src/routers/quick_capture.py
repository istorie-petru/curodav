"""Quick Capture's HTTP surface (plans/quick-capture.md) -- the palette's
marker-triggered capture mode (static/command_palette.js) calls both of
these:

  - `GET /api/quick-capture/preview?text=...` -- parse-only, no writes, so
    the palette can show a live "here's what this will create" summary as
    you type. Labels are shown exactly as typed here, NOT run through
    `db.resolve_capture_label` -- that function persists a new alias on a
    fuzzy match (plans/quick-capture.md § Labels and Approximate
    Matching), and this endpoint fires on every debounced keystroke, so
    resolving (and potentially writing an alias for) every partially-typed
    label the user hasn't committed to yet would be real, unwanted write
    traffic. Resolution only happens at actual creation time, below.
  - `POST /api/quick-capture` -- parse, resolve labels, create the right
    entity (task/event/contact/note). src/quick_capture.py (the parser) is
    a pure module with no `conn` argument at all -- every actual database
    write lives here, not there."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db
from ..deps import get_db
from ..quick_capture import ParsedCapture, QuickCaptureError, parse

router = APIRouter(tags=["quick-capture"], prefix="/api/quick-capture")


def _preview_payload(result: ParsedCapture) -> dict:
    payload: dict = {"type": result.type, "labels": result.labels}
    if result.type == "task":
        payload["title"] = result.title
        payload["due_date"] = result.due_date_iso
        payload["timeblock_count"] = len(result.timeblocks)
    elif result.type == "event":
        payload["title"] = result.title
        payload["start"] = result.start_iso
        payload["end"] = result.end_iso
        payload["all_day"] = result.all_day
    elif result.type == "contact":
        payload["title"] = result.title
        payload["phone"] = result.phone
        payload["email"] = result.email
    else:  # note
        payload["title"] = result.content[:80]
    return payload


@router.get("/preview")
def preview(text: str = "", conn=Depends(get_db)):
    if not text.strip():
        return JSONResponse({"ok": False, "error": None})
    try:
        result = parse(text)
    except QuickCaptureError as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    return JSONResponse({"ok": True, **_preview_payload(result)})


def _create_from_capture(conn, result: ParsedCapture) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    resolved_labels = [db.resolve_capture_label(conn, name) for name in result.labels]
    uid = str(uuid.uuid4())

    if result.type == "task":
        db.upsert_task(
            conn,
            {
                "uid": uid,
                "title": result.title,
                "description": "",
                "status": "active",
                "tags": resolved_labels,
                "due_at": result.due_date_iso,
                "created_at": now,
            },
        )
        for tb in result.timeblocks:
            db.create_work_allocation(
                conn, uid, start_at=f"{tb.date_iso}T{tb.start}:00", end_at=f"{tb.date_iso}T{tb.end}:00"
            )
        return {"type": "task", "uid": uid, "title": result.title}

    if result.type == "event":
        db.upsert_event(
            conn,
            {
                "uid": uid,
                "title": result.title,
                "description": "",
                "start_at": result.start_iso,
                "end_at": result.end_iso,
                "all_day": result.all_day,
                "status": "active",
                "tags": resolved_labels,
                "created_at": now,
                "updated_at": now,
            },
        )
        return {"type": "event", "uid": uid, "title": result.title}

    if result.type == "contact":
        # Contacts field parity slice 2 of 6: Quick Capture has no way to
        # specify a phone/email TYPE from free text, so a captured number/
        # address goes straight into the new multi-value tables typed
        # "Other" -- the same default the legacy-column auto-migration uses
        # for the same reason (an unqualified single value). Writing the now
        # -dead `phone`/`email` columns instead would silently lose the
        # capture the instant it's viewed anywhere in the UI, which no
        # longer reads them.
        db.upsert_contact(
            conn,
            {
                "uid": uid,
                "full_name": result.title,
                "phones": [{"type": "Other", "value": result.phone}] if result.phone else [],
                "emails": [{"type": "Other", "value": result.email}] if result.email else [],
                "tags": resolved_labels,
                "created_at": now,
            },
        )
        return {"type": "contact", "uid": uid, "title": result.title}

    # note
    db.upsert_note(
        conn,
        {"uid": uid, "content": result.content, "tags": resolved_labels, "created_at": now, "updated_at": now},
    )
    return {"type": "note", "uid": uid, "title": db.note_title(db.get_note(conn, uid))}


@router.post("")
async def create(request: Request, conn=Depends(get_db)):
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Nothing to capture."}, status_code=400)
    try:
        result = parse(text)
    except QuickCaptureError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    try:
        created = _create_from_capture(conn, result)
    except db.MultipleProjectLabelsError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **created})
