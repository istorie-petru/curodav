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

2026-08-07: the Grades export (/export/grades.csv) is gone along with the
rest of the Databases/Grades feature -- see features/architecture.md's
removal note.

2026-08-15: the dedicated /export/schedule.json export is gone along with
the whole Schedule module -- see plans/STATE.md's removal entry. A class
was already a real recurring event by 1.6, so nothing schedule-specific
survives outside the ordinary events/labels exports.

2026-08-08: every db.list_tasks(conn) call here passes
include_habit_tasks=True -- db.list_tasks defaults to hiding habit-labeled
tasks (they only show on Tasks > Habits, see routers/tasks.py's
habits_view), but that exclusion exists for normal *browsing* views, not
backups -- a habit-labeled task disappearing from tasks.csv/data.json/
tasks.ics just because of which label it carries would be real, silent
data loss on restore.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import db, derived_state, ical_rows, vcard_rows
from ..deps import get_db, templates

router = APIRouter(prefix="/export", tags=["export"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attachment(filename: str, body: bytes, media_type: str) -> Response:
    """Every export is an attachment (Content-Disposition) so the browser
    downloads the file instead of rendering a text dump in the tab."""
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Phase 1 (label-space rework, 2026-08-06): the app no longer mirrors a
# class's VEVENT into a separate "target calendar" to exclude -- there's
# just one universal `events` pool now (see db.py's Phase 1 comments).
# Every class's mirrored event is a real row in that pool, uid-stable, and
# is included in exports like any other event.


@router.get("")
def export_index(request: Request, conn=Depends(get_db)):
    """2026-08-08: no longer its own page -- direct feedback ("export and
    backup should be fully with all buttons... in the advanced page") --
    the standard-format/JSON downloads and restore forms this used to
    render (export_index.html, deleted) are now inlined directly into
    Settings > Data & Maintenance (routers/settings.py's
    settings_data_maintenance, settings_data_maintenance.html's "Export &
    import" section -- Advanced's old home, folded into that page 2026-08-
    17) instead of living behind a link to a separate page. This route
    stays registered as a plain redirect rather than being deleted
    outright, so an old bookmark/link to /export still lands somewhere
    real."""
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


# The two export/import dialogs (2026-08-26 third pass: the Data &
# Maintenance page's standalone Export & import card is gone -- Export…
# and Import… are menu items on the Sync status card now, each opening one
# of these modals. Same #modal-target shape as every other utility modal.)

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
        "contact_count": len(db.list_contacts(conn)),
        "event_count": len(db.list_events(conn)),
        "task_count": len(db.list_tasks(conn, include_habit_tasks=True)),
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
    # Importance/Urgency are computed, not stored columns (side work,
    # post-1.1) -- attach the effective values before handing each row to
    # ical_rows.task_row_to_ical, which still reads row["importance"]/
    # row["urgency"] to build PRIORITY (see that module's own comment: this
    # app is the write-source, export still round-trips the effective
    # urgency-dominant value).
    label_rules = db.list_label_rules(conn)
    for row in db.list_tasks(conn, include_habit_tasks=True):
        row = dict(row)
        row["importance"] = derived_state.effective_importance(row, label_rules) or None
        row["urgency"] = derived_state.effective_urgency(row, label_rules) or None
        cal.add_component(Todo.from_ical(ical_rows.task_row_to_ical(row)))
    return _attachment("tasks.ics", cal.to_ical(), "text/calendar")


@router.get("/contacts.vcf")
def export_contacts_vcf(conn=Depends(get_db)):
    parts = [vcard_rows.contact_row_to_vcard(r).strip() for r in db.list_contacts(conn)]
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
    # Importance/Urgency are computed, not stored columns (side work,
    # post-1.1, src/derived_state.py) -- label rules resolved once for the
    # whole export rather than per row, same convention every other
    # importance/urgency call site in this app follows. The CSV column
    # values are now the *effective* values, not a raw explicit field.
    label_rules = db.list_label_rules(conn)
    rows = [
        [
            t["uid"], t["title"], t["status"], t["due_at"],
            derived_state.effective_importance(t, label_rules) or "",
            derived_state.effective_urgency(t, label_rules) or "",
            ", ".join(t.get("tags") or []),
        ]
        for t in db.list_tasks(conn, include_habit_tasks=True)
    ]
    return _csv_response("tasks.csv", ["UID", "Title", "Status", "Due", "Importance", "Urgency", "Tags"], rows)


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
    # Contacts field parity slice 2 of 6: `c["phone"]`/`c["email"]` (the
    # legacy flat columns) are dead going forward -- a contact saved after
    # this slice always has NULL there even with real phones/emails, so a
    # plain CSV export needs its own "first entry" read, same convention
    # contacts_list.html's row subtitle and db._search_contacts' subtitle
    # use (oldest/lowest-position row, no separate "primary" flag).
    def _first(items: list[dict] | None) -> str:
        return items[0]["value"] if items else ""

    rows = [
        [
            c["uid"], c["full_name"], c["org"] or "",
            _first(c.get("phones")), _first(c.get("emails")),
            c["address"] or "", ", ".join(c.get("tags") or []),
        ]
        for c in db.list_contacts(conn)
    ]
    return _csv_response("contacts.csv", ["UID", "Name", "Organization", "Phone", "Email", "Address", "Tags"], rows)


# 2026-08-07: GET /export/grades.csv (export_grades_csv) removed along
# with the `grades` table -- see this module's docstring.


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
    export for all of it. Consolidated 2026-08-07 from two duplicate
    routes (`/export/spaces.json` and `/export/tags.json`, which returned
    byte-identical payloads under different names) into this single one --
    keeping both was exactly the kind of compatibility-layer cruft this
    app's own house rules rule out (see features/architecture.md's "no
    compatibility layer" rule); there was never a real reason for two URLs."""
    return _json_response(
        "labels.json",
        {"labels": db.list_labels(conn), "object_labels": _export_object_labels(conn)},
    )


def _export_object_labels(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT object_type, object_id, label_name FROM object_labels").fetchall()
    return [dict(r) for r in rows]


def build_backup_payload(conn) -> dict[str, Any]:
    """The full-backup dict -- every synced object plus all local-only
    data. Factored out of export_data_json (below) so it has exactly one
    definition: the download route wraps it as a JSON response,
    `src/data_health.py`'s create_backup writes the identical dict straight
    to a file on disk -- Data Health's server-side backups and this route's
    on-demand download are the same bytes, never two payload-building code
    paths that could quietly drift apart.

    2026-08-07: no more "grades" key -- the `grades` table (and the rest
    of Databases/Grades) is removed entirely, not just excluded from the
    backup.

    2026-08-15: no more "schedule_settings" key or dedicated /schedule.json
    export -- the whole Schedule module (and its `schedule_settings` table)
    is removed, see plans/STATE.md's removal entry. "schedule_holidays"
    stays -- named holiday calendars are a generic mechanism any recurring
    event can use, unrelated to Schedule specifically. No more
    "schedule_classes" key either -- a class was already a real event by
    1.6, already covered by the "events" key above."""
    return {
        "exported_at": _now(),
        "events": db.list_events(conn),
        "tasks": db.list_tasks(conn, include_habit_tasks=True),
        "contacts": db.list_contacts(conn),
        "labels": db.list_labels(conn),
        "object_labels": _export_object_labels(conn),
        "schedule_holidays": db.list_holidays(conn),
        "task_completions": db.list_task_completions(conn),
        # 2026-08-09 Relations -- deliberate user-made links, same
        # local-only-data backup treatment as task_completions.
        "event_task_relations": db.list_event_task_relations(conn),
    }


@router.get("/data.json")
def export_data_json(conn=Depends(get_db)):
    """Full backup download -- the restore-able round-trip; the standard-
    format exports above are for handing data to other apps, this one is
    for backing up this app's whole world. See build_backup_payload above
    for the actual payload shape."""
    return _json_response("data.json", build_backup_payload(conn))


# --------------------------------------------------------------------- #
# Selective download (2026-08-26 redesign) -- one endpoint behind Data &
# Maintenance's two-dropdown "Download" control, replacing the wall of
# per-type links. Every (type, format) combination resolves to exactly one
# real file: a single type picks its own format's builder; "all" bundles
# the three entity exports into one .zip (a mixed ICS+VCF can't be one
# file, and a zip is still a single one-click download); labels always come
# out as labels.json regardless of format -- that's the only lossless label
# export there is. Each cell delegates to the same route function the old
# individual link used, so there is exactly one definition of every export.
# --------------------------------------------------------------------- #


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
    if data_type == "all":
        if file_format == "csv":
            return _zip_response(
                "data-spreadsheets.zip",
                [
                    ("events.csv", export_events_csv(conn=conn).body),
                    ("tasks.csv", export_tasks_csv(conn=conn).body),
                    ("contacts.csv", export_contacts_csv(conn=conn).body),
                ],
            )
        return _zip_response(
            "data-standard.zip",
            [
                ("events.ics", export_events_ics(conn=conn).body),
                ("tasks.ics", export_tasks_ics(conn=conn).body),
                ("contacts.vcf", export_contacts_vcf(conn=conn).body),
            ],
        )
    entry = _SELECTIVE_EXPORTS.get((data_type, "csv" if file_format == "csv" else "standard"))
    if entry is None:
        return _redirect_with_error("/settings/data-maintenance", f"Unknown export selection ({data_type} / {file_format}).")
    return entry[1](conn)


# --------------------------------------------------------------------- #
# Import / restore
# --------------------------------------------------------------------- #


# The four historical per-type endpoints below share their real work with
# the unified /import/auto endpoint (2026-08-26 redesign of Data &
# Maintenance's Export & import section into one drop zone) through these
# content-sniffing helpers. Each takes the file *text* (not the upload) and
# returns how many rows it wrote; `skip_existing=True` is the unified
# endpoint's "merge" checkbox unchecked -- only rows whose uid isn't in the
# pool yet are written, so nothing the user already has is overwritten.
# The old per-type endpoints always merge (their behavior before this
# refactor, unchanged).


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
            row = ical_rows.ical_to_event_row(component)
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
    straight into `events` (see db.py's Phase 1 comments). Kept as its own
    URL after the 2026-08-26 unified-import redesign for old bookmarks and
    direct callers; the page itself posts to /import/auto now."""
    events_added, _ = _import_ics_text(conn, file.file.read().decode("utf-8"))
    return _redirect_with_note("/settings/data-maintenance", f"Imported {events_added} event(s).")


@router.post("/import/tasks")
def import_tasks(file: UploadFile, conn=Depends(get_db)):
    _, tasks_added = _import_ics_text(conn, file.file.read().decode("utf-8"))
    return _redirect_with_note("/settings/data-maintenance", f"Imported {tasks_added} task(s).")


@router.post("/import/contacts")
def import_contacts(file: UploadFile, conn=Depends(get_db)):
    added = _import_vcf_text(conn, file.file.read().decode("utf-8"))
    return _redirect_with_note("/settings/data-maintenance", f"Imported {added} contact(s).")


@router.post("/import/json")
def import_json(file: UploadFile, conn=Depends(get_db)):
    """Full-backup restore. Every row (tasks/events/contacts included) is
    upserted straight into the cache -- Phase 1 (label-space rework)
    dropped the bridge from this path along with everything else in base
    CRUD (see db.py's Phase 1 comments)."""
    try:
        _restore_json_text(conn, file.file.read())
    except ValueError:
        return _redirect_with_error("/settings/data-maintenance", "That file isn't a readable backup.")
    return _redirect_with_note("/settings/data-maintenance", "Backup restored.")


# The drop zone's .csv acceptance (2026-08-26 page redesign): a CSV is
# recognized only when its header row is exactly one of this app's own
# three export shapes (tasks.csv/events.csv/contacts.csv above, compared
# case-insensitively) -- an arbitrary spreadsheet from anywhere else isn't
# silently half-imported, it's rejected with the standard unknown-file
# error. Round-trip scope matches what the CSV exports themselves carry:
# tasks keep title/status/due/labels; events add start/end/all-day/
# location/meeting URL; contacts keep name/org/address and land their
# first phone/email into the real child tables (the flat columns the CSV
# columns are named after are dead for display -- see export_contacts_csv's
# own comment). Importance/Urgency columns are accepted-and-ignored: they
# were computed values on the way out (see export_tasks_csv), never stored.

_CSV_SHAPES: dict[str, list[str]] = {
    "tasks": ["uid", "title", "status", "due", "importance", "urgency", "tags"],
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

    now = datetime.now(timezone.utc).isoformat()
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
    walk, both pools); this app's own CSV export shapes -> their pools
    (2026-08-26 page redesign added the drop zone's .csv acceptance);
    anything else must parse as a data.json backup or it's rejected.
    Detection is by *content*, not filename, so a renamed/misnamed file
    still lands correctly.

    `merge`: the zone's "Merge with existing data" checkbox (checked in the
    UI sends "1"; an unchecked checkbox sends nothing at all, hence the ""
    default). Checked (the default experience) is today's upsert-merge;
    unchecked is add-only -- existing uids are left untouched, so a nervous
    first import can't overwrite anything."""
    raw = file.file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _redirect_with_error("/settings/data-maintenance", "Couldn't read that file as text (.ics/.vcf/.csv/.json expected).")
    head = text.lstrip("\ufeff \t\r\n")[:64].upper()
    skip_existing = merge != "1"
    try:
        if head.startswith("BEGIN:VCARD"):
            added = _import_vcf_text(conn, text, skip_existing=skip_existing)
            note = f"Imported {added} contact(s)."
        elif "BEGIN:VCALENDAR" in head or "BEGIN:VCALENDAR" in text[:4096].upper():
            events_added, tasks_added = _import_ics_text(conn, text, skip_existing=skip_existing)
            parts = []
            if events_added:
                parts.append(f"{events_added} event(s)")
            if tasks_added:
                parts.append(f"{tasks_added} task(s)")
            note = f"Imported {', '.join(parts)}." if parts else "Nothing to import -- no events or tasks found in that file."
        elif _csv_kind(text) is not None:
            note = _import_csv_text(conn, text, skip_existing=skip_existing)
        else:
            count = _restore_json_text(conn, raw, skip_existing=skip_existing)
            note = f"Backup restored ({count} item{'s' if count != 1 else ''})."
    except ValueError:
        return _redirect_with_error(
            "/settings/data-maintenance",
            "Couldn't detect the file type -- use an .ics calendar, .vcf contacts, .csv spreadsheet, or a data.json backup.",
        )
    return _redirect_with_note("/settings/data-maintenance", note)


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
            conn.execute("UPDATE tasks SET completed_at = ? WHERE uid = ?", (row["completed_at"], row["uid"]))
            conn.commit()
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
    # 2026-08-15: no more `payload.get("schedule_settings")` restore step --
    # the whole Schedule module (and `schedule_settings`) is removed, see
    # plans/STATE.md's removal entry. A backup file from before this
    # removal that still carries a "schedule_settings" key simply has it
    # ignored on restore now, same treatment as "grades" below.
    #
    # 2026-08-07: no more `payload.get("grades", [])` restore loop here --
    # the `grades` table (and db.upsert_grade) is gone. A backup file from
    # before this removal that still carries a "grades" key simply has
    # that key ignored on restore now.
    for row in payload.get("task_completions", []):
        db.upsert_task_completion(conn, row["task_uid"], row["due_date"], row["completed_at"])
    # Relations reference both an event and a task, so they must restore
    # after both pools are up. add_event_task_relation is idempotent, so a
    # backup with duplicate rows (or a re-restore) is harmless.
    for row in payload.get("event_task_relations", []):
        db.add_event_task_relation(
            conn, row["event_uid"], row["task_uid"], row.get("is_work_allocation", 0)
        )
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
