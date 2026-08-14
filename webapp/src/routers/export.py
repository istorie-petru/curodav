"""Export / portfolio (command-center-rework Phase 10).

The app's tasks/events/contacts are synced data -- their real home is the
Radicale server (CalDAV/CardDAV), which is the source of truth, and the
SQLite cache this app reads/writes is exactly that: a cache. That fact is
the whole reason this page exists. A CalDAV client (the phone's calendar
app, a desktop client) can already read all of it without this app's help;
the exports here make sure the *local-only* data -- Spaces, Projects,
Schedule, Tag metadata -- is portable too, and provide a full JSON
backup/restore round-trip so nobody is ever trapped in this app's cache.
Each standard-format export also double-checks that the synced objects
survive an app-independent round-trip (ICS/VCF re-parse cleanly).

2026-08-07: the Grades export (/export/grades.csv) is gone along with the
rest of the Databases/Grades feature -- see features/architecture.md's
removal note.

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
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import db, ical_rows, vcard_rows
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


# Phase 1 (label-space rework, 2026-08-06): the app no longer mirrors
# Schedule's class VEVENTs into a separate "target calendar" to exclude --
# there's just one universal `events` pool now (see db.py's Phase 1
# comments and routers/schedule.py). Every class's mirrored event is a
# real row in that pool, uid-stable, and (until Phase 2 gives labels a way
# to exclude it) is included in exports like any other event.


@router.get("")
def export_index(request: Request, conn=Depends(get_db)):
    """2026-08-08: no longer its own page -- direct feedback ("export and
    backup should be fully with all buttons... in the advanced page") --
    the standard-format/JSON downloads and restore forms this used to
    render (export_index.html, deleted) are now inlined directly into
    Settings > Advanced (routers/settings.py's settings_advanced,
    settings_advanced.html's own "Export & backup" section) instead of
    living behind a link to a separate page. This route stays registered
    as a plain redirect rather than being deleted outright, so an old
    bookmark/link to /export still lands somewhere real."""
    return RedirectResponse(url="/settings/advanced", status_code=303)


def export_context(conn) -> dict:
    """The data Settings > Advanced's "Export & backup" section needs --
    factored out of the old export_index page route (above) so
    routers/settings.py's settings_advanced can call it directly instead
    of importing a page-rendering function. Deliberately takes `conn`
    only, not `request` -- radicale_url is fetched separately by the
    caller (it needs `request.app.state`, which this function has no use
    for otherwise), keeping this a plain data function."""
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
    for row in db.list_tasks(conn, include_habit_tasks=True):
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
    rows = [
        [
            t["uid"], t["title"], t["status"], t["due_at"],
            t["importance"] or "", t["urgency"] or "", ", ".join(t.get("tags") or []),
        ]
        for t in db.list_tasks(conn, include_habit_tasks=True)
    ]
    return _csv_response("tasks.csv", ["UID", "Title", "Status", "Due", "Importance", "Urgency", "Tags"], rows)


@router.get("/contacts.csv")
def export_contacts_csv(conn=Depends(get_db)):
    rows = [
        [c["uid"], c["full_name"], c["org"] or "", c["phone"] or "", c["email"] or "", c["address"] or "", ", ".join(c.get("tags") or [])]
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


@router.get("/schedule.json")
def export_schedule_json(conn=Depends(get_db)):
    return _json_response(
        "schedule.json",
        {
            "settings": db.get_schedule_settings(conn),
            # 1.6: a class is a real recurring event now (tagged with the
            # Schedule system label) -- db.list_schedule_class_events reads
            # exactly those, in place of the old dedicated schedule_classes
            # table this key used to be a straight dump of.
            "classes": db.list_schedule_class_events(conn),
            "holidays": db.list_holidays(conn),
        },
    )


def build_backup_payload(conn) -> dict[str, Any]:
    """The full-backup dict -- every synced object (minus the rebuildable
    Schedule mirror -- schedule.json covers the source) plus all local-only
    data. Factored out of export_data_json (below) so it has exactly one
    definition: the download route wraps it as a JSON response,
    `src/data_health.py`'s create_backup writes the identical dict straight
    to a file on disk -- Data Health's server-side backups and this route's
    on-demand download are the same bytes, never two payload-building code
    paths that could quietly drift apart.

    2026-08-07: no more "grades" key -- the `grades` table (and the rest
    of Databases/Grades) is removed entirely, not just excluded from the
    backup."""
    return {
        "exported_at": _now(),
        "events": db.list_events(conn),
        "tasks": db.list_tasks(conn, include_habit_tasks=True),
        "contacts": db.list_contacts(conn),
        "labels": db.list_labels(conn),
        "object_labels": _export_object_labels(conn),
        # 1.6: no more "schedule_classes" key -- a class is a real
        # event now, already covered by the "events" key above.
        "schedule_holidays": db.list_holidays(conn),
        "schedule_settings": db.get_schedule_settings(conn),
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
# Import / restore
# --------------------------------------------------------------------- #


@router.post("/import/events")
def import_events(file: UploadFile, conn=Depends(get_db)):
    """Re-import an .ics exported by this app or any CalDAV app into the
    universal events pool. Phase 1 (label-space rework) dropped
    `calendars` -- there's no collection to pick anymore, plain SQL write
    straight into `events` (see db.py's Phase 1 comments)."""
    from icalendar import Calendar as ICalCalendar

    text = file.file.read().decode("utf-8")
    added = 0
    try:
        parsed = ICalCalendar.from_ical(text)
    except (ValueError, IndexError):
        return _redirect_with_note("/export", "Imported 0 event(s).")
    for component in parsed.walk():
        if component.name != "VEVENT":
            continue
        row = ical_rows.ical_to_event_row(component)
        db.upsert_event(conn, row)
        added += 1
    return _redirect_with_note("/export", f"Imported {added} event(s).")


@router.post("/import/tasks")
def import_tasks(file: UploadFile, conn=Depends(get_db)):
    from icalendar import Calendar as ICalCalendar

    text = file.file.read().decode("utf-8")
    added = 0
    try:
        parsed = ICalCalendar.from_ical(text)
    except (ValueError, IndexError):
        return _redirect_with_note("/export", "Imported 0 task(s).")
    for component in parsed.walk():
        if component.name != "VTODO":
            continue
        row = ical_rows.ical_to_task_row(component)
        db.upsert_task(conn, row)
        added += 1
    return _redirect_with_note("/export", f"Imported {added} task(s).")


@router.post("/import/contacts")
def import_contacts(file: UploadFile, conn=Depends(get_db)):
    import vobject

    text = file.file.read().decode("utf-8")
    added = 0
    for card in vobject.readComponents(io.StringIO(text)):
        row = vcard_rows.vcard_to_contact_row(card)
        db.upsert_contact(conn, row)
        added += 1
    return _redirect_with_note("/export", f"Imported {added} contact(s).")


@router.post("/import/json")
def import_json(file: UploadFile, conn=Depends(get_db)):
    """Full-backup restore. Every row (tasks/events/contacts included) is
    upserted straight into the cache -- Phase 1 (label-space rework)
    dropped the bridge from this path along with everything else in base
    CRUD (see db.py's Phase 1 comments)."""
    payload = json.loads(file.file.read().decode("utf-8"))
    restore_backup_payload(conn, payload)
    return _redirect_with_note("/export", "Backup restored.")


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
    # (already restored by the "events" loop above), and db.upsert_
    # schedule_class no longer exists. A backup file from before this
    # rework that still carries a "schedule_classes" key simply has that
    # key ignored on restore now, same "old key silently ignored" treatment
    # every other removed feature gets here (see the "grades" note below).
    for row in payload.get("schedule_holidays", []):
        db.upsert_holiday(conn, row)
    settings = payload.get("schedule_settings")
    if settings:
        db.save_schedule_settings(conn, settings)
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
