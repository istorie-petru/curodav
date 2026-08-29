"""Published Lists' standalone public feed (2026-08-29) -- the "share with
a friend/colleague" surface, deliberately independent of Radicale. A List's
`public_token` (routers/published_lists.py) resolves here to a live,
read-only calendar/contacts feed built directly from the current label
filter -- the same evaluate_label_filter + row-getter pattern
published_lists.materialize uses to push into Radicale, just rendered to
bytes on request instead of PUT to a CalDAV/CardDAV collection. No Radicale
bridge involved at all, so this works whether or not Radicale is even
configured (see routers/published_lists.py's module docstring).

Exempt from login (src/auth.py's AuthMiddleware -- `/public/` is a public
path prefix, checked before both the normal auth gate and the forced
first-run /setup redirect) -- the whole point is a link an outside viewer
can open with no account of any kind. GET-only, so CSRFMiddleware never
looks at these routes either (it only inspects state-changing methods).

A token that doesn't exist, or exists but isn't currently `visibility ==
"public"` (private, archived, or never-published), gets the same plain 404
either way -- not distinguishing "wrong token" from "right token, not
public anymore" avoids turning this into an oracle for probing whether a
particular token used to work.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response

from .. import db, ical_rows, vcard_rows
from ..deps import get_db
from ..published_lists import evaluate_label_filter

router = APIRouter(prefix="/public/lists", tags=["public-lists"])

_EXT = {"task": "ics", "event": "ics", "contact": "vcf"}


def _get_public_list(conn, token: str) -> dict:
    """The one lookup+gate every route below needs. Raises the same 404
    whether the token is unknown or simply not public right now -- see
    the module docstring."""
    row = db.get_published_list_by_token(conn, token)
    if row is None or row.get("visibility") != "public":
        raise HTTPException(status_code=404, detail="Not found")
    return row


def _ics_feed(conn, row: dict) -> Response:
    from icalendar import Calendar as ICalCalendar, Event, Todo

    entity_type = row["entity_type"]
    member_ids = evaluate_label_filter(conn, entity_type, row.get("label_filter"))
    cal = ICalCalendar()
    cal.add("prodid", "-//Command Center//published-list.ics//EN")
    cal.add("version", "2.0")
    if entity_type == "task":
        for object_id in member_ids:
            task = db.get_task(conn, object_id)
            if task is None:
                continue
            cal.add_component(Todo.from_ical(ical_rows.task_row_to_ical(dict(task))))
    else:
        for object_id in member_ids:
            event = db.get_event(conn, object_id)
            if event is None or not event.get("start_at"):
                # Same "undated work-session placeholder" skip export.py's
                # events.ics uses -- nothing publishable until it has a date.
                continue
            cal.add_component(Event.from_ical(ical_rows.event_row_to_ical(event)))
    return Response(cal.to_ical(), media_type="text/calendar")


def _vcf_feed(conn, row: dict) -> Response:
    member_ids = evaluate_label_filter(conn, "contact", row.get("label_filter"))
    parts = []
    for object_id in member_ids:
        contact = db.get_contact(conn, object_id)
        if contact is None:
            continue
        parts.append(vcard_rows.contact_row_to_vcard(contact).strip())
    body = ("\r\n".join(parts) + "\r\n") if parts else ""
    return Response(body.encode("utf-8"), media_type="text/vcard")


@router.get("/{token}.ics")
def public_list_ics(token: str, conn=Depends(get_db)):
    row = _get_public_list(conn, token)
    if row["entity_type"] not in ("task", "event"):
        raise HTTPException(status_code=404, detail="Not found")
    return _ics_feed(conn, row)


@router.get("/{token}.vcf")
def public_list_vcf(token: str, conn=Depends(get_db)):
    row = _get_public_list(conn, token)
    if row["entity_type"] != "contact":
        raise HTTPException(status_code=404, detail="Not found")
    return _vcf_feed(conn, row)


# Bare token URL, no extension -- registered LAST, after the .ics/.vcf
# routes above. Starlette matches routes in registration order and a
# plain `{token}` path parameter's default (str) converter happily
# swallows dots, so `/public/lists/{token}.ics` would otherwise match
# THIS route first (with token="<token>.ics") instead of the more
# specific one -- same ordering hazard main.py documents for
# timeline.router needing to be registered before tasks.router's
# catch-all `/tasks/{uid}`.
@router.get("/{token}")
def public_list_redirect(token: str, conn=Depends(get_db)):
    """Convenience for anyone who pastes just the token without the
    extension the app's own "Copy link" button always includes --
    redirects to the canonical `.ics`/`.vcf` URL for this List's
    entity_type."""
    row = _get_public_list(conn, token)
    ext = _EXT[row["entity_type"]]
    return RedirectResponse(url=f"/public/lists/{token}.{ext}", status_code=302)
