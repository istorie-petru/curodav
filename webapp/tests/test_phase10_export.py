"""Phase 10 (command-center-rework) -- Export / portfolio.

A portable-format export hub (ICS/VCF/CSV per object) plus the app's own
JSON backup/restore round-trip. The phase's acceptance: nothing is ever
trapped in the SQLite cache -- the synced objects re-parse cleanly in
app-independent formats (ICS/VCF), and the local-only data (Spaces,
Projects, Schedule, Tags) has a lossless JSON round-trip.

Phase 1 (label-space rework, 2026-08-06) dropped `calendars`/`task_lists`
and every `href`/`etag`/`calendar_path`/`list_path`/`addressbook_path`/
`raw_ics`/`raw_vcard` column from `events`/`tasks`/`contacts` (see db.py's
Phase 1 comments) -- every seed/import call below drops those fields, and
the calendar/list-picker import tests are gone since there's nothing left
to pick (import now always lands in the one universal pool).

2026-08-07: TestStandardFormats.test_grades_csv is deleted and every
"grades"/database seed dropped from the JSON round-trip tests -- the
Grades export (/export/grades.csv) and the "grades" key in data.json are
gone along with the rest of the Databases/Grades feature. See
routers/export.py's own removal notes."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO, StringIO
from types import SimpleNamespace

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from src import db
from src.routers import export as export_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/export"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _request_with_settings(path="/export"):
    from starlette.applications import Starlette

    app = Starlette()
    app.state.settings = SimpleNamespace(radicale_base_url="http://127.0.0.1:5232/devuser/")
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
        "headers": [],
        "app": app,
    }
    return Request(scope)


def _seed(conn):
    db.upsert_event(
        conn,
        {"uid": "e1", "title": "Standup", "description": "",
         "start_at": "2026-10-05T09:00:00", "end_at": "2026-10-05T09:30:00", "all_day": 0,
         "location": None, "meeting_url": None, "status": "active", "recurrence": None,
         "exdates_json": "[]", "reminders_json": "[]", "tags_json": '["work"]',
         "created_at": _now(), "updated_at": _now()},
    )
    db.upsert_task(
        conn,
        {"uid": "t1",
         "title": "Ship export", "description": "", "start_at": None, "due_at": "2026-10-06",
         "priority": 1, "status": "active", "progress": None, "tags_json": '["work"]',
         "parent_uid": None, "recurrence": None, "exdates_json": "[]",
         "created_at": _now(), "updated_at": _now()},
    )
    db.upsert_contact(
        conn,
        {"uid": "c1", "full_name": "Ada Lovelace",
         "org": "UCL", "phone": "+123", "email": "ada@example.com", "address": None,
         "tags_json": '["colleague"]', "notes": None, "photo_b64": None, "photo_type": None,
         "created_at": _now(), "updated_at": _now()},
    )


class TestIndex:
    def test_index_redirects_to_settings_advanced(self, conn):
        # 2026-08-08: /export is no longer a page of its own -- direct
        # feedback ("export and backup should be fully with all
        # buttons... in the advanced page") moved every download/import
        # button here into Settings > Advanced directly
        # (settings_advanced.html; see routers/settings.py's
        # settings_advanced and export.py's export_context()). This route
        # stays registered as a redirect so an old bookmark/link to
        # /export still lands somewhere real, rather than 404ing.
        resp = export_router.export_index(_request_with_settings(), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/advanced"

    def test_export_context_has_the_counts_settings_advanced_needs(self, conn):
        _seed(conn)
        ctx = export_router.export_context(conn)
        assert ctx == {"contact_count": 1, "event_count": 1, "task_count": 1}


class TestStandardFormats:
    def test_events_ics_round_trips(self, conn):
        _seed(conn)
        resp = export_router.export_events_ics(conn=conn)
        assert resp.headers["Content-Disposition"].startswith("attachment")
        from icalendar import Calendar

        cal = Calendar.from_ical(resp.body)
        names = [c["UID"] for c in cal.walk() if c.name == "VEVENT"]
        assert "e1" in names

    def test_tasks_ics_round_trips(self, conn):
        _seed(conn)
        resp = export_router.export_tasks_ics(conn=conn)
        from icalendar import Calendar

        cal = Calendar.from_ical(resp.body)
        uids = [c["UID"] for c in cal.walk() if c.name == "VTODO"]
        assert "t1" in uids

    def test_contacts_vcf_round_trips(self, conn):
        _seed(conn)
        resp = export_router.export_contacts_vcf(conn=conn)
        import vobject

        cards = list(vobject.readComponents(StringIO(resp.body.decode())))
        assert len(cards) == 1
        assert cards[0].fn.value == "Ada Lovelace"

    def test_tasks_csv(self, conn):
        _seed(conn)
        resp = export_router.export_tasks_csv(conn=conn)
        assert b"Ship export" in resp.body
        assert b"UID" in resp.body

    def test_contacts_csv(self, conn):
        _seed(conn)
        resp = export_router.export_contacts_csv(conn=conn)
        assert b"Ada Lovelace" in resp.body


class TestJson:
    def test_data_json_covers_everything(self, conn):
        # Phase 2 (label-space rework): "spaces"/"projects"/"tags"/
        # "tag_groups" are gone from the export -- everything local-only
        # about organization is now one "labels" list (label_config rows)
        # plus "object_labels" (raw membership).
        _seed(conn)
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "blue", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "University", "color": "blue", "created_at": _now()})
        db.add_object_label(conn, "task", "t1", "work")
        resp = export_router.export_data_json(conn=conn)
        import json

        data = json.loads(resp.body)
        assert data["events"][0]["uid"] == "e1"
        assert data["tasks"][0]["uid"] == "t1"
        assert data["contacts"][0]["uid"] == "c1"
        label_names = {l["name"] for l in data["labels"]}
        assert {"University", "CS101", "work"} <= label_names
        assert {"object_type": "task", "object_id": "t1", "label_name": "work"} in data["object_labels"]

    def test_labels_json(self, conn):
        # 2026-08-07: was test_spaces_projects_json / export_spaces_json --
        # consolidated with the former (duplicate) export_tags_json into
        # one export_labels_json route, see export.py's own comment.
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "blue", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "University", "color": "blue", "created_at": _now()})
        import json

        data = json.loads(export_router.export_labels_json(conn=conn).body)
        names = {l["name"] for l in data["labels"]}
        assert {"University", "CS101"} <= names

    def test_schedule_json(self, conn):
        import json

        data = json.loads(export_router.export_schedule_json(conn=conn).body)
        assert "settings" in data and "classes" in data and "holidays" in data


class TestImportRestore:
    def test_full_json_restore_round_trip(self, conn):
        payload = {
            "events": [{"uid": "e9", "title": "R",
                        "description": "", "start_at": "2026-10-05T09:00:00", "end_at": None, "all_day": 0,
                        "location": None, "meeting_url": None, "status": "active", "recurrence": None,
                        "exdates_json": "[]", "reminders_json": "[]", "tags_json": "[]",
                        "created_at": _now(), "updated_at": _now()}],
            "tasks": [],
            "contacts": [],
            "labels": [{"name": "University", "generate_space": 1, "color": "blue", "created_at": _now()}],
            "object_labels": [{"object_type": "event", "object_id": "e9", "label_name": "University"}],
            "schedule_classes": [], "schedule_holidays": [], "schedule_settings": {},
            "task_completions": [{"task_uid": "x", "due_date": "2026-10-05", "completed_at": _now()}],
        }
        import json

        upload = UploadFile(file=BytesIO(json.dumps(payload).encode("utf-8")))
        export_router.import_json(upload, conn=conn)
        assert db.get_event(conn, "e9")["title"] == "R"
        assert db.get_label_config(conn, "University")["generate_space"] == 1
        assert db.list_labels_for_object(conn, "event", "e9") == ["University"]
        assert db.list_task_completions(conn, "x") != []

    def test_relations_backup_and_restore_round_trip(self, conn, tmp_path):
        # 2026-08-09 Relations: the event_task_relations join table is
        # local-only user data (like task_completions), so it rides in the
        # full data.json backup and restores after both pools are up.
        db.upsert_event(conn, {"uid": "e9", "title": "R", "description": "",
                               "start_at": "2026-10-05T09:00:00", "end_at": None,
                               "all_day": 0, "location": None, "meeting_url": None,
                               "status": "active", "recurrence": None, "tags": ["work"],
                               "created_at": _now(), "updated_at": _now()})
        db.upsert_task(conn, {"uid": "t9", "title": "R", "description": "",
                              "status": "active", "tags": ["work"],
                              "created_at": _now(), "updated_at": _now()})
        db.add_event_task_relation(conn, "e9", "t9")
        import json

        data = json.loads(export_router.export_data_json(conn=conn).body)
        assert data["event_task_relations"] == [{"event_uid": "e9", "task_uid": "t9",
                                                 "created_at": data["event_task_relations"][0]["created_at"]}]

        payload = {
            "events": data["events"], "tasks": data["tasks"], "contacts": [],
            "labels": [], "object_labels": [], "schedule_classes": [],
            "schedule_holidays": [], "schedule_settings": {},
            "task_completions": [], "event_task_relations": data["event_task_relations"],
        }
        upload = UploadFile(file=BytesIO(json.dumps(payload).encode("utf-8")))
        export_router.import_json(upload, conn=conn)  # idempotent re-restore on the same db
        assert [e["uid"] for e in db.related_events_for_task(conn, "t9")] == ["e9"]
        assert [t["uid"] for t in db.related_tasks_for_event(conn, "e9")] == ["t9"]

    def test_import_events_lands_in_the_universal_pool(self, conn):
        # Phase 1 (label-space rework, 2026-08-06) dropped `calendars` --
        # there's no more collection picker, every imported event lands
        # straight in the one events pool (see routers/export.py's
        # import_events).
        body = (
            "BEGIN:VCALENDAR\r\nPRODID:-//test//EN\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:imp1\r\nDTSTART:20261005T090000\r\n"
            "SUMMARY:Imported\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode("utf-8")
        upload = UploadFile(file=BytesIO(body))
        export_router.import_events(upload, conn=conn)
        ev = db.get_event(conn, "imp1")
        assert ev is not None and ev["title"] == "Imported"

    def test_import_contacts(self, conn):
        vcard = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:v1\r\nFN:Bob Brown\r\nN:Brown;Bob;;;\r\n"
            "EMAIL:bob@example.com\r\nEND:VCARD\r\n"
        ).encode("utf-8")
        upload = UploadFile(file=BytesIO(vcard))
        export_router.import_contacts(upload, conn=conn)
        assert db.get_contact(conn, "v1")["full_name"] == "Bob Brown"

    def test_import_empty_file_adds_nothing(self, conn):
        resp = export_router.import_events(UploadFile(file=BytesIO(b"")), conn=conn)
        assert resp.status_code == 303
        assert db.list_events(conn) == []
