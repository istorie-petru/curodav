"""Export / portfolio (command-center-rework Phase 10).

The app's tasks/events/contacts are synced data -- their real home is the
Radicale server (CalDAV/CardDAV), which is the source of truth, and the
SQLite cache this app reads/writes is exactly that: a cache. That fact is
the whole reason this page exists. A CalDAV client (the phone's calendar
app, a desktop client) can already read all of it without this app's help;
the exports here make sure the *local-only* data -- Spaces, Projects, Tag
metadata -- is portable too, and provide a full JSON backup/restore
round-trip so nobody is ever trapped in this app's cache. Each standard-
format export also double-checks that the synced objects survive an
app-independent round-trip (ICS/VCF re-parse cleanly).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import clock, data_exchange, db, finance, ical_rows, vcard_rows
from ..deps import get_db, templates

router = APIRouter(prefix="/export", tags=["export"])


def _now() -> str:
    return clock.now().isoformat()


def _attachment(filename: str, body: bytes, media_type: str) -> Response:
    """Every export is an attachment (Content-Disposition) so the browser
    downloads the file instead of rendering a text dump in the tab."""
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("")
def export_index(request: Request, conn=Depends(get_db)):
    """in the advanced page") --
        the standard-format/JSON downloads and restore forms this used to
        render (export_index.html, deleted) are now inlined directly into
        Settings > Data & Maintenance (routers/settings.py's
        settings_data_maintenance, settings_data_maintenance.html's "Export &
        import" section -- Advanced's old home, folded into that page 2026-08-
        17) instead of living behind a link to a separate page. This route
        stays registered as a plain redirect rather than being deleted
        outright, so an old bookmark/link to /export still lands somewhere
        real.
    """
    return RedirectResponse(url="/settings", status_code=303)


@router.get("/modal")
def export_modal(request: Request, conn=Depends(get_db)):
    """The Export dialog: Data + Format dropdowns and a Download button,
    posting the same GET /export/download form the old card did. The
    per-option `data-dm-preview` phrases feed the modal's live
    "Includes: ..." line (static/data_maintenance.js)."""
    ctx = {"request": request, "active_tab": "settings_data_maintenance"}
    ctx.update(export_context(conn))
    return templates.TemplateResponse("export_modal.html", ctx)


@router.get("/import-modal")
def import_modal(request: Request):
    """The Import dialog: the single content-sniffing drop zone (.ics/
    .vcf/.csv/.json), posting to the unchanged /export/import/auto.
    Success closes the dialog and reloads the page (the same close-and-
    reload every other modal form gets); the server-side note rides back
    as a redirect the fetch follows."""
    return templates.TemplateResponse(
        "import_modal.html",
        {"request": request, "active_tab": "settings_data_maintenance"},
    )


def export_context(conn) -> dict:
    """The data Settings > Data & Maintenance's "Export & import" section
    needs -- factored out of the old export_index page route (above) so
    routers/settings.py's settings_data_maintenance can call it directly
    instead of importing a page-rendering function. Deliberately takes
    `conn` only, not `request` -- radicale_url is fetched separately by
    the caller (it needs `request.app.state`, which this function has no
    use for otherwise), keeping this a plain data function."""
    return {
        "contact_count": len(db.list_contacts(conn, include_archived=True)),
        "event_count": len(db.list_events(conn)),
        "task_count": len(db.list_tasks(conn, include_habit_tasks=True)),
        "note_count": len(db.list_notebook_documents(conn, scope="all")),
        "account_count": len(finance.list_accounts(conn)),
        "transaction_count": len(finance.all_transactions(conn)),
        "citation_count": len(db.list_citations(conn)),
        "glossary_count": len(db.list_glossary_terms(conn)),
    }


# --------------------------------------------------------------------- #
# Standard formats (portable to any CalDAV/CardDAV app)
# --------------------------------------------------------------------- #


@router.get("/events.ics")
def export_events_ics(conn=Depends(get_db)):
    from icalendar import Calendar as ICalCalendar, Event

    cal = ICalCalendar()
    cal.add("prodid", "-//Command Center//command-center.ics//EN")
    cal.add("version", "2.0")
    events = db.list_events(conn)
    for row in events:
        if not row.get("start_at"):
            # Undated work-session placeholders (the Work sessions "+" on a
            # task card) have no date yet -- nothing to publish until a
            # session is placed onto a grid slot.
            continue
        cal.add_component(Event.from_ical(ical_rows.event_row_to_ical(row)))
    return _attachment("events.ics", cal.to_ical(), "text/calendar")


@router.get("/tasks.ics")
def export_tasks_ics(conn=Depends(get_db)):
    from icalendar import Calendar as ICalCalendar, Todo

    cal = ICalCalendar()
    cal.add("prodid", "-//Command Center//command-center.ics//EN")
    cal.add("version", "2.0")
    for row in db.list_tasks(conn, include_habit_tasks=True):
        cal.add_component(Todo.from_ical(ical_rows.task_row_to_ical(dict(row))))
    return _attachment("tasks.ics", cal.to_ical(), "text/calendar")


@router.get("/contacts.vcf")
def export_contacts_vcf(conn=Depends(get_db)):
    # include_archived=True: a manual .vcf export is a portability/backup
    # action, not a "what am I looking at right now" view -- same
    # reasoning as export_context/full_backup's own include_archived=True.
    parts = [vcard_rows.contact_row_to_vcard(r).strip() for r in db.list_contacts(conn, include_archived=True)]
    return _attachment("contacts.vcf", ("\r\n".join(parts) + "\r\n").encode("utf-8"), "text/vcard")


# --------------------------------------------------------------------- #
# Spreadsheet formats (convenience for a human in a spreadsheet app)
# --------------------------------------------------------------------- #


def _csv_response(filename: str, header: list[str], rows: list[list[Any]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return _attachment(filename, buf.getvalue().encode("utf-8"), "text/csv")


@router.get("/tasks.csv")
def export_tasks_csv(conn=Depends(get_db)):
    rows = [
        [t["uid"], t["title"], t["status"], t["due_at"], ", ".join(t.get("tags") or [])]
        for t in db.list_tasks(conn, include_habit_tasks=True)
    ]
    return _csv_response("tasks.csv", ["UID", "Title", "Status", "Due", "Tags"], rows)


@router.get("/events.csv")
def export_events_csv(conn=Depends(get_db)):
    rows = [
        [
            e["uid"], e["title"], e["start_at"] or "", e["end_at"] or "",
            "yes" if e["all_day"] else "no", e["location"] or "", e["meeting_url"] or "",
            ", ".join(e.get("tags") or []),
        ]
        for e in db.list_events(conn)
    ]
    return _csv_response(
        "events.csv",
        ["UID", "Title", "Start", "End", "All day", "Location", "Meeting URL", "Tags"],
        rows,
    )


@router.get("/contacts.csv")
def export_contacts_csv(conn=Depends(get_db)):
    def _first(items: list[dict] | None) -> str:
        return items[0]["value"] if items else ""

    rows = [
        [
            c["uid"], c["full_name"], c["org"] or "",
            _first(c.get("phones")), _first(c.get("emails")),
            c["address"] or "", ", ".join(c.get("tags") or []),
        ]
        # include_archived=True: see export_contacts_vcf's own comment.
        for c in db.list_contacts(conn, include_archived=True)
    ]
    return _csv_response("contacts.csv", ["UID", "Name", "Organization", "Phone", "Email", "Address", "Tags"], rows)


# --------------------------------------------------------------------- #
# JSON (the app's own local-only data + full backup/restore)
# --------------------------------------------------------------------- #


def _json_response(filename: str, payload: Any) -> Response:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return _attachment(filename, body, "application/json")


@router.get("/labels.json")
def export_labels_json(conn=Depends(get_db)):
    """Phase 2 (label-space rework): tags, projects, and spaces are all
        just labels now (see db.py's Phase 2 comments). This exports every
        label's config plus its current object_labels membership -- the one
        export for all of it.
    """
    return _json_response(
        "labels.json",
        {"labels": db.list_labels(conn), "object_labels": data_exchange.object_label_rows(conn)},
    )


def build_backup_payload(conn) -> dict[str, Any]:
    """The full-backup dict -- every synced object plus all local-only
        data. Factored out of export_data_json (below) so it has exactly one
        definition: the download route wraps it as a JSON response,
        `src/data_health.py`'s create_backup writes the identical dict straight
        to a file on disk -- Data Health's server-side backups and this route's
        on-demand download are the same bytes, never two payload-building code
        paths that could quietly drift apart.
    """
    return {
        "exported_at": _now(),
        "events": db.list_events(conn),
        "tasks": db.list_tasks(conn, include_habit_tasks=True),
        "contacts": db.list_contacts(conn, include_archived=True),
        "labels": db.list_labels(conn),
        "object_labels": data_exchange.object_label_rows(conn),
        "schedule_holidays": db.list_holidays(conn),
        "task_completions": db.list_task_completions(conn),
        "habit_pauses": db.list_habit_pauses(conn),
        "event_task_relations": db.list_event_task_relations(conn),
        "notebook_documents": db.list_notebook_documents(conn, scope="all"),
        "notebook_field_config": db.list_notebook_field_config(conn),
        "notebook_images": data_exchange.notebook_image_rows(conn),
        "citations": db.list_citations(conn),
        "notebook_citations": data_exchange.notebook_citation_rows(conn),
        "glossary_terms": db.list_glossary_terms(conn),
        "notebook_glossary_terms": data_exchange.notebook_glossary_term_rows(conn),
        "glossary_term_references": data_exchange.glossary_reference_rows(conn),
        "glossary_term_sections": data_exchange.glossary_section_rows(conn),
        "glossary_section_refs": data_exchange.glossary_section_ref_rows(conn),
        # Auto-detect override bookkeeping (roadmap item H, session 7) --
        # same "can't ride along nested under one document" treatment as
        # notebook_glossary_terms above.
        "notebook_glossary_excluded_terms": data_exchange.notebook_glossary_excluded_rows(conn),
        **finance.backup_rows(conn),
    }


@router.get("/data.json")
def export_data_json(conn=Depends(get_db)):
    """Full backup download -- the restore-able round-trip; the standard-
    format exports above are for handing data to other apps, this one is
    for backing up this app's whole world. See build_backup_payload above
    for the actual payload shape."""
    return _json_response("data.json", build_backup_payload(conn))


def _zip_response(filename: str, files: list[tuple[str, bytes]]) -> Response:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, body in files:
            bundle.writestr(name, body)
    return _attachment(filename, buf.getvalue(), "application/zip")


_SELECTIVE_EXPORTS: dict[tuple[str, str], tuple[str, Any]] = {
    ("events", "standard"): ("events.ics", lambda conn: export_events_ics(conn=conn)),
    ("events", "csv"): ("events.csv", lambda conn: export_events_csv(conn=conn)),
    ("tasks", "standard"): ("tasks.ics", lambda conn: export_tasks_ics(conn=conn)),
    ("tasks", "csv"): ("tasks.csv", lambda conn: export_tasks_csv(conn=conn)),
    ("contacts", "standard"): ("contacts.vcf", lambda conn: export_contacts_vcf(conn=conn)),
    ("contacts", "csv"): ("contacts.csv", lambda conn: export_contacts_csv(conn=conn)),
}


@router.get("/download")
def download_selective(
    data_type: str = "all",
    file_format: str = "standard",
    conn=Depends(get_db),
):
    if data_type == "labels":
        return export_labels_json(conn=conn)
    if data_type == "notes":
        return _zip_response("notes-markdown.zip", data_exchange.notes_files(conn))
    if data_type == "finance":
        return _zip_response("finance.zip", data_exchange.finance_files(conn))
    if data_type == "citations":
        return _attachment("citations.csv", data_exchange.citations_csv(conn), "text/csv")
    if data_type == "glossary":
        return _attachment("glossary.csv", data_exchange.glossary_csv(conn), "text/csv")
    if data_type == "all":
        if file_format == "csv":
            return _zip_response(
                "data-spreadsheets.zip",
                [
                    ("events.csv", export_events_csv(conn=conn).body),
                    ("tasks.csv", export_tasks_csv(conn=conn).body),
                    ("contacts.csv", export_contacts_csv(conn=conn).body),
                    ("citations.csv", data_exchange.citations_csv(conn)),
                    ("glossary.csv", data_exchange.glossary_csv(conn)),
                    *data_exchange.finance_files(conn),
                    *data_exchange.notes_files(conn),
                ],
            )
        return _zip_response(
            "data-standard.zip",
            [
                ("events.ics", export_events_ics(conn=conn).body),
                ("tasks.ics", export_tasks_ics(conn=conn).body),
                ("contacts.vcf", export_contacts_vcf(conn=conn).body),
                ("citations.csv", data_exchange.citations_csv(conn)),
                ("glossary.csv", data_exchange.glossary_csv(conn)),
                *data_exchange.finance_files(conn),
                *data_exchange.notes_files(conn),
            ],
        )
    entry = _SELECTIVE_EXPORTS.get((data_type, "csv" if file_format == "csv" else "standard"))
    if entry is None:
        return _redirect_with_error("/settings", f"Unknown export selection ({data_type} / {file_format}).")
    return entry[1](conn)


# --------------------------------------------------------------------- #
# Import / restore
# --------------------------------------------------------------------- #


def _import_ics_text(conn, text: str, skip_existing: bool = False) -> tuple[int, int]:
    """Import one iCalendar blob; returns (events_added, tasks_added). A
    single .ics may legitimately carry both VEVENTs and VTODOs, so the
    unified importer walks once and writes each component to its own pool."""
    from icalendar import Calendar as ICalCalendar

    events_added = tasks_added = 0
    try:
        parsed = ICalCalendar.from_ical(text)
    except (ValueError, IndexError):
        return (0, 0)
    for component in parsed.walk():
        if component.name == "VEVENT":
            row = ical_rows.ical_to_event_row(component, one_time=True)
            if skip_existing and db.get_event(conn, row["uid"]) is not None:
                continue
            db.upsert_event(conn, row)
            events_added += 1
        elif component.name == "VTODO":
            row = ical_rows.ical_to_task_row(component)
            if skip_existing and db.get_task(conn, row["uid"]) is not None:
                continue
            db.upsert_task(conn, row)
            tasks_added += 1
    return (events_added, tasks_added)


def _import_vcf_text(conn, text: str, skip_existing: bool = False) -> int:
    import vobject

    added = 0
    for card in vobject.readComponents(io.StringIO(text)):
        row = vcard_rows.vcard_to_contact_row(card)
        if skip_existing and db.get_contact(conn, row["uid"]) is not None:
            continue
        db.upsert_contact(conn, row)
        added += 1
    return added


def _restore_json_text(conn, raw: bytes, skip_existing: bool = False) -> int:
    """Parse a data.json backup and restore it; returns the number of rows
    written. Raises ValueError on unparseable/non-backup JSON so callers
    can turn that into a user-facing error redirect."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("not a JSON backup") from exc
    if not isinstance(payload, dict):
        raise ValueError("not a JSON backup")
    if skip_existing:
        payload = {
            **payload,
            "events": [r for r in payload.get("events", []) if db.get_event(conn, r["uid"]) is None],
            "tasks": [r for r in payload.get("tasks", []) if db.get_task(conn, r["uid"]) is None],
            "contacts": [r for r in payload.get("contacts", []) if db.get_contact(conn, r["uid"]) is None],
        }
    return restore_backup_payload(conn, payload)


@router.post("/import/events")
def import_events(file: UploadFile, conn=Depends(get_db)):
    """Re-import an .ics exported by this app or any CalDAV app into the
        universal events pool. Phase 1 (label-space rework) dropped
        `calendars` -- there's no collection to pick anymore, plain SQL write
        straight into `events` (see db.py's Phase 1 comments).
    """
    events_added, _ = _import_ics_text(conn, file.file.read().decode("utf-8"))
    return _redirect_with_note("/settings", f"Imported {events_added} event(s).")


@router.post("/import/tasks")
def import_tasks(file: UploadFile, conn=Depends(get_db)):
    _, tasks_added = _import_ics_text(conn, file.file.read().decode("utf-8"))
    return _redirect_with_note("/settings", f"Imported {tasks_added} task(s).")


@router.post("/import/contacts")
def import_contacts(file: UploadFile, conn=Depends(get_db)):
    added = _import_vcf_text(conn, file.file.read().decode("utf-8"))
    return _redirect_with_note("/settings", f"Imported {added} contact(s).")


@router.post("/import/json")
def import_json(file: UploadFile, conn=Depends(get_db)):
    """Full-backup restore. Every row (tasks/events/contacts included) is
    upserted straight into the cache -- Phase 1 (label-space rework)
    dropped the bridge from this path along with everything else in base
    CRUD (see db.py's Phase 1 comments)."""
    try:
        _restore_json_text(conn, file.file.read())
    except ValueError:
        return _redirect_with_error("/settings", "That file isn't a readable backup.")
    return _redirect_with_note("/settings", "Backup restored.")


_CSV_SHAPES: dict[str, list[str]] = {
    "tasks": ["uid", "title", "status", "due", "tags"],
    "events": ["uid", "title", "start", "end", "all day", "location", "meeting url", "tags"],
    "contacts": ["uid", "name", "organization", "phone", "email", "address", "tags"],
}


def _csv_kind(text: str) -> str | None:
    """Which of this app's own CSV export shapes `text`'s header row is
    ("tasks"/"events"/"contacts"), or None. Only the first record is
    parsed -- cheap sniffing, same spirit as the VCARD/VCALENDAR checks."""
    try:
        first = next(csv.reader(io.StringIO(text)))
    except (StopIteration, csv.Error):
        return None
    cells = [cell.strip().lower() for cell in first]
    for kind, shape in _CSV_SHAPES.items():
        if cells == shape:
            return kind
    return None


def _split_csv_labels(raw: str) -> list[str]:
    return [label.strip() for label in raw.split(",") if label.strip()]


def _import_csv_text(conn, text: str, skip_existing: bool = False) -> str:
    """Import rows from one of this app's own CSV exports; returns the
    user-facing note (import_auto redirects with it). Rows without a UID
    are skipped -- uid-less rows can't round-trip or be merge-checked.
    Raises ValueError only when the kind somehow shifted between sniffing
    and here (defensive; callers treat it as unknown-file)."""
    kind = _csv_kind(text)
    if kind is None:
        raise ValueError("not a recognized CSV export")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return f"Nothing to import -- that {kind}.csv has no data rows."
    keys = {name.strip().lower(): name for name in reader.fieldnames}

    def cell(row: dict[str, str], name: str) -> str:
        actual = keys.get(name)
        return (row.get(actual) or "").strip() if actual else ""

    now = clock.now().isoformat()
    added = 0
    skipped = 0
    for row in reader:
        uid = cell(row, "uid")
        if not uid:
            continue
        if skip_existing and (
            db.get_task(conn, uid) if kind == "tasks"
            else db.get_event(conn, uid) if kind == "events"
            else db.get_contact(conn, uid)
        ) is not None:
            skipped += 1
            continue
        tags = _split_csv_labels(cell(row, "tags"))
        if kind == "tasks":
            db.upsert_task(conn, {
                "uid": uid,
                "title": cell(row, "title"),
                # upsert_* name every column explicitly, so each NOT NULL
                # column must be given its real default here (an explicit
                # NULL never falls back to the column's own DEFAULT).
                "description": "",
                "status": cell(row, "status") or "todo",
                "due_at": cell(row, "due") or None,
                "created_at": now, "updated_at": now,
                "tags": tags,
            })
        elif kind == "events":
            db.upsert_event(conn, {
                "uid": uid,
                "title": cell(row, "title"),
                "description": "",
                "start_at": cell(row, "start") or None,
                "end_at": cell(row, "end") or None,
                "all_day": 1 if cell(row, "all day").lower() in ("yes", "true", "1") else 0,
                # upsert_event names every column explicitly, so a NOT NULL
                # column must be given its real default here (an explicit
                # NULL never falls back to the column's own DEFAULT).
                "status": "active",
                "location": cell(row, "location") or None,
                "meeting_url": cell(row, "meeting url") or None,
                "created_at": now, "updated_at": now,
                "tags": tags,
            })
        else:
            phone = cell(row, "phone")
            email = cell(row, "email")
            address = cell(row, "address")
            db.upsert_contact(conn, {
                "uid": uid,
                "full_name": cell(row, "name"),
                "org": cell(row, "organization") or None,
                "created_at": now, "updated_at": now,
                "tags": tags,
                "phones": [{"type": "Other", "value": phone}] if phone else [],
                "emails": [{"type": "Other", "value": email}] if email else [],
                "addresses": [{"type": "Other", "street": address}] if address else [],
            })
        added += 1
    noun = {"tasks": "task", "events": "event", "contacts": "contact"}[kind]
    parts = [f"Imported {added} {noun}(s)."]
    if skipped:
        parts.append(f"{skipped} already existed (left untouched).")
    return " ".join(parts)


@router.post("/import/auto")
def import_auto(file: UploadFile, merge: str = Form(""), conn=Depends(get_db)):
    """The unified import endpoint behind Data & Maintenance's single
        drag-and-drop zone: sniffs the uploaded bytes and dispatches --
        BEGIN:VCARD -> contacts; BEGIN:VCALENDAR -> events and/or tasks (one
        walk, both pools); this app's own CSV export shapes -> their pools;
        anything else must parse as a data.json backup or it's rejected.
        Detection is by *content*, not filename, so a renamed/misnamed file
        still lands correctly.

        `merge`: the zone's "Merge with existing data" checkbox (checked in the
        UI sends "1"; an unchecked checkbox sends nothing at all, hence the ""
        default). Checked (the default experience) is today's upsert-merge;
        unchecked is add-only -- existing uids are left untouched, so a nervous
        first import can't overwrite anything.
    """
    raw = file.file.read()
    skip_existing = merge != "1"
    name = file.filename or ""
    if zipfile.is_zipfile(io.BytesIO(raw)):
        notes = []
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            for member in bundle.namelist():
                if member.endswith("/") or not member.lower().endswith(_IMPORTABLE_SUFFIXES):
                    continue
                try:
                    notes.append(_import_one(conn, member, bundle.read(member), skip_existing))
                except ValueError:
                    notes.append(f"Skipped {member} (not recognised).")
        if not notes:
            return _redirect_with_error("/settings", "That zip holds no importable files (.md, .csv, .ics, .vcf or .json).")
        return _redirect_with_note("/settings", _merge_notes(notes))
    try:
        note = _import_one(conn, name, raw, skip_existing)
    except ValueError as exc:
        return _redirect_with_error("/settings", str(exc) or _UNKNOWN_FILE)
    return _redirect_with_note("/settings", note)


def _merge_notes(notes: list[str]) -> str:
    """Joins per-file notes, adding up the plain "Imported N things." lines (singular and plural nouns alike)."""
    totals: dict[str, int] = {}
    others = []
    for note in notes:
        m = re.fullmatch(r"Imported (\d+) ([a-z ]+?)(?:s|\(s\))?\.", note)
        if m:
            totals[m.group(2)] = totals.get(m.group(2), 0) + int(m.group(1))
        else:
            others.append(note)
    return " ".join([f"Imported {_plural(n, noun)}." for noun, n in totals.items()] + others)


_IMPORTABLE_SUFFIXES = (".md", ".markdown", ".csv", ".ics", ".vcf", ".json")
_UNKNOWN_FILE = (
    "Couldn't detect the file type -- use an .ics calendar, .vcf contacts, .csv spreadsheet, "
    ".md note, a .zip of those, or a data.json backup."
)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' if count != 1 else ''}"


def _import_extra_csv(conn, kind: str, text: str, skip_existing: bool) -> str:
    if kind == "finance accounts":
        added, problems = data_exchange.import_accounts_csv(conn, text, skip_existing)
        note = f"Imported {_plural(added, 'account')}."
    elif kind == "finance transactions":
        added, problems = data_exchange.import_transactions_csv(conn, text, skip_existing)
        note = f"Imported {_plural(added, 'transaction')}."
    elif kind == "citations":
        note, problems = f"Imported {_plural(data_exchange.import_citations_csv(conn, text, skip_existing), 'citation')}.", []
    else:
        note, problems = f"Imported {_plural(data_exchange.import_glossary_csv(conn, text, skip_existing), 'glossary term')}.", []
    return note + (f" {len(problems)} row(s) skipped: {problems[0]}" if problems else "")


def _import_one(conn, name: str, raw: bytes, skip_existing: bool) -> str:
    """Imports one file by content (Markdown by file name); returns the note to show. Raises ValueError when
    the file isn't a recognised type."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Couldn't read that file as text (.ics/.vcf/.csv/.md/.json expected).")
    head = text.lstrip("\ufeff \t\r\n")[:64].upper()
    if name.lower().endswith((".md", ".markdown")):
        return f"Imported {_plural(int(data_exchange.import_note(conn, text, name, skip_existing)), 'note')}."
    if head.startswith("BEGIN:VCARD"):
        return f"Imported {_import_vcf_text(conn, text, skip_existing=skip_existing)} contact(s)."
    if "BEGIN:VCALENDAR" in head or "BEGIN:VCALENDAR" in text[:4096].upper():
        events_added, tasks_added = _import_ics_text(conn, text, skip_existing=skip_existing)
        parts = []
        if events_added:
            parts.append(f"{events_added} event(s)")
        if tasks_added:
            parts.append(f"{tasks_added} task(s)")
        return f"Imported {', '.join(parts)}." if parts else "Nothing to import -- no events or tasks found in that file."
    extra = _extra_csv_kind(text)
    if extra:
        return _import_extra_csv(conn, extra, text, skip_existing)
    if _csv_kind(text) is not None:
        return _import_csv_text(conn, text, skip_existing=skip_existing)
    try:
        count = _restore_json_text(conn, raw, skip_existing=skip_existing)
    except ValueError:
        raise ValueError(_UNKNOWN_FILE)
    return f"Backup restored ({count} item{'s' if count != 1 else ''})."


def _extra_csv_kind(text: str) -> str | None:
    try:
        first = next(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    except (StopIteration, csv.Error):
        return None
    cells = [c.strip().lower() for c in first]
    return next((kind for kind, shape in data_exchange.EXTRA_CSV_SHAPES.items() if cells == shape), None)


def restore_backup_payload(conn, payload: dict[str, Any]) -> int:
    """Upserts every row in a build_backup_payload-shaped dict back into
    the live pool. Public (renamed from `_restore`) so `src/data_health.py`
    -- the server-side backup/restore/verify service used by both Settings
    > Data health and scripts/data_health.py -- shares this one restore
    path instead of re-implementing it; import_json (above) is now a thin
    wrapper around it."""
    count = 0
    for row in payload.get("events", []):
        db.upsert_event(conn, row)
        count += 1
    for row in payload.get("tasks", []):
        db.upsert_task(conn, row)
        # upsert_task always auto-computes completed_at from the
        # done/not-done transition (see its own docstring for why it
        # can't just trust a passed-in value) -- a restore needs to
        # override that with the backup's real historical value instead,
        # so a task's actual completion date survives a backup/restore
        # round-trip instead of being silently reset to "now" (or wiped)
        # by the transition-detection logic.
        if row.get("completed_at") is not None:
            db.set_task_completed_at(conn, row["uid"], row["completed_at"])
        # Habit-only columns upsert_task never writes (dedicated setters,
        # see db.set_task_reminder_time / set_task_habit_look).
        if row.get("reminder_time"):
            db.set_task_reminder_time(conn, row["uid"], row["reminder_time"])
        if row.get("habit_icon") or row.get("habit_color"):
            db.set_task_habit_look(conn, row["uid"], row.get("habit_icon"), row.get("habit_color"))
        count += 1
    for row in payload.get("contacts", []):
        db.upsert_contact(conn, row)
        count += 1
    # Phase 2 (label-space rework): "spaces"/"projects"/"tags"/"tag_groups"
    # are gone -- a backup now carries "labels" (label_config rows) and
    # "object_labels" (raw membership rows) instead, see export_data_json/
    # export_labels_json above.
    for row in payload.get("labels", []):
        db.upsert_label_config(conn, row)
    for row in payload.get("object_labels", []):
        db.add_object_label(conn, row["object_type"], row["object_id"], row["label_name"])
    # 1.6 (Schedule & recurrence rework): no more `payload.get(
    # "schedule_classes", [])` restore loop -- a class is a real event now
    # (already restored by the "events" loop above). A backup file from
    # before this rework that still carries a "schedule_classes" key simply
    # has that key ignored on restore now, same "old key silently ignored"
    # treatment every other removed feature gets here (see the "grades"
    # note below).
    for row in payload.get("schedule_holidays", []):
        db.upsert_holiday(conn, row)
    for row in payload.get("task_completions", []):
        db.upsert_task_completion(
            conn, row["task_uid"], row["due_date"], row["completed_at"],
            row.get("value") or 1, row.get("note"),
        )
    existing_pauses = {p["uid"] for p in db.list_habit_pauses(conn)}
    for row in payload.get("habit_pauses", []):
        if row.get("uid") and row["uid"] not in existing_pauses:
            existing_pauses.add(row["uid"])
            db.add_habit_pause(
                conn, row["uid"], row.get("task_uid"), row["start_date"], row["end_date"], row.get("created_at")
            )
    # Relations reference both an event and a task, so they must restore
    # after both pools are up. add_event_task_relation is idempotent, so a
    # backup with duplicate rows (or a re-restore) is harmless.
    for row in payload.get("event_task_relations", []):
        db.add_event_task_relation(
            conn, row["event_uid"], row["task_uid"], row.get("is_work_allocation", 0)
        )
        db.restore_work_session_fields(conn, row)
    for row in payload.get("notebook_images", []):
        data = base64.b64decode(row.get("data_b64", ""))
        if db.get_notebook_image(conn, hashlib.sha256(data).hexdigest()) is None:
            db.store_notebook_image(conn, data, row.get("mime", "image/png"))
    for row in payload.get("notebook_documents", []):
        db.upsert_notebook_document(conn, row)
        count += 1
    for row in payload.get("notebook_field_config", []):
        db.upsert_notebook_field_config(conn, row)
    for row in payload.get("citations", []):
        db.upsert_citation(conn, row)
    for row in payload.get("notebook_citations", []):
        db.attach_notebook_citation(
            conn, row["notebook_uid"], row["citation_uid"], row.get("position", 0), row.get("created_at")
        )
    for row in payload.get("glossary_terms", []):
        db.upsert_glossary_term(conn, row)
    for row in payload.get("notebook_glossary_terms", []):
        db.attach_notebook_glossary_term(
            conn, row["notebook_uid"], row["term_uid"], row.get("position", 0), row.get("created_at"),
            row.get("auto", 0),
        )
    for row in payload.get("glossary_term_sections", []):
        db.restore_glossary_section(conn, row)
    for row in payload.get("glossary_section_refs", []):
        db.set_glossary_section_ref(conn, row["term_uid"], row["section_key"], row["citation_uid"], row.get("page_start", ""), row.get("page_end", ""))
    for row in payload.get("glossary_term_references", []):
        db.attach_glossary_term_reference(
            conn, row["term_uid"], row["ref_type"], row["ref_uid"], row.get("position", 0), row.get("created_at"),
            row.get("page_start", ""), row.get("page_end", ""),
        )
    # Auto-detect override bookkeeping (roadmap item H, session 7) -- order
    # doesn't matter relative to the two blocks above (it has no FK target
    # of its own to wait on, just a plain (notebook_uid, term_uid) pair),
    # restored last anyway for locality with the glossary block it belongs
    # to.
    for row in payload.get("notebook_glossary_excluded_terms", []):
        db.attach_notebook_glossary_excluded_term(conn, row["notebook_uid"], row["term_uid"], row.get("created_at"))
    count += finance.restore_rows(conn, payload)
    return count


def _redirect(url: str, note: str, error: bool) -> Any:
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"{url}?{'error' if error else 'note'}={note}", status_code=303)


def _redirect_with_note(url: str, note: str) -> Any:
    from urllib.parse import quote

    return _redirect(url, quote(note), False)


def _redirect_with_error(url: str, error: str) -> Any:
    from urllib.parse import quote

    return _redirect(url, quote(error), True)
