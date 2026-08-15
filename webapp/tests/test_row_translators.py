"""Pure round-trip tests for ical_rows.py / vcard_rows.py -- no network,
no Radicale needed. See tests/test_caldav_bridge_live.py for the
integration test that exercises these against a real server."""

from __future__ import annotations

from icalendar import Event, Todo

from src.ical_rows import (
    event_row_to_ical,
    ical_to_event_row,
    ical_to_task_row,
    task_row_to_ical,
)
from src.vcard_rows import contact_row_to_vcard, vcard_to_contact_row


class TestTaskRow:
    def test_round_trip(self):
        row = {
            "uid": "task-1",
            "title": "Write report",
            "description": "quarterly",
            "start_at": "2026-08-01",
            "due_at": "2026-08-10",
            "importance": 3,
            "urgency": 2,
            "status": "in_progress",
            "progress": 0.5,
            "tags": ["work", "urgent"],
            "recurrence": "FREQ=WEEKLY;BYDAY=MO,WE",
        }
        ics = task_row_to_ical(row)
        todo = Todo.from_ical(ics)
        result = ical_to_task_row(todo)

        assert result["title"] == row["title"]
        assert result["description"] == row["description"]
        assert result["start_at"] == row["start_at"]
        assert result["due_at"] == row["due_at"]
        # Side work (post-1.1): PRIORITY export still carries the effective
        # urgency-dominant value (callers attach it before calling
        # task_row_to_ical), but import no longer maps PRIORITY back to
        # anything -- there's no explicit field left to write it to, see
        # ical_rows.py's recorded decision.
        assert "urgency" not in result
        assert "importance" not in result
        assert result["status"] == row["status"]
        assert result["progress"] == row["progress"]
        assert set(result["tags"]) == set(row["tags"])
        # 1.2: parent_uid no longer round-trips -- subtasks were removed,
        # so there's no RELATED-TO export/import (tasks are flat). The row
        # built for translation never carries parent_uid at all now.
        assert "parent_uid" not in result
        assert result["recurrence"] == row["recurrence"]

    def test_minimal_row(self):
        row = {"uid": "task-2", "title": "Bare task"}
        ics = task_row_to_ical(row)
        todo = Todo.from_ical(ics)
        result = ical_to_task_row(todo)
        assert result["title"] == "Bare task"
        assert result["status"] == "active"


class TestEventRow:
    def test_round_trip(self):
        row = {
            "uid": "event-1",
            "title": "Standup",
            "description": "daily",
            "start_at": "2026-08-05T09:00:00",
            "end_at": "2026-08-05T09:30:00",
            "all_day": False,
            "location": "Room A",
            "meeting_url": "https://meet.example.com/x",
            "status": "active",
            "tags": ["work"],
            "recurrence": "FREQ=DAILY",
            "reminders": [10, 30],
        }
        ics = event_row_to_ical(row)
        event = Event.from_ical(ics)
        result = ical_to_event_row(event)

        assert result["title"] == row["title"]
        assert result["start_at"] == row["start_at"]
        assert result["end_at"] == row["end_at"]
        assert result["all_day"] is False
        assert result["location"] == row["location"]
        assert result["meeting_url"] == row["meeting_url"]
        assert set(result["tags"]) == set(row["tags"])
        assert result["recurrence"] == row["recurrence"]
        assert sorted(result["reminders"]) == [10, 30]

    def test_all_day(self):
        row = {
            "uid": "event-2",
            "title": "Holiday",
            "start_at": "2026-08-05T00:00:00",
            "all_day": True,
        }
        ics = event_row_to_ical(row)
        assert b"DTSTART;VALUE=DATE:" in ics
        event = Event.from_ical(ics)
        result = ical_to_event_row(event)
        assert result["all_day"] is True


class TestContactRow:
    def test_round_trip(self):
        import vobject

        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "title": "Product Manager",
            "org": "Acme",
            # Contacts field parity slice 2 of 6: phone/email are multi-
            # value now (contact_row_to_vcard no longer reads the old flat
            # "phone"/"email" keys at all -- see vcard_rows.py's module
            # docstring).
            "phones": [{"type": "Cell", "value": "+15550100"}],
            "emails": [{"type": "Work", "value": "jane@example.com"}],
            "address": "123 Main St",
            "tags": ["friend", "vip"],
            "notes": "met at a conference",
        }
        text = contact_row_to_vcard(row)
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)

        assert result["full_name"] == row["full_name"]
        assert result["title"] == row["title"]
        assert result["org"] == row["org"]
        assert result["phones"] == row["phones"]
        assert result["emails"] == row["emails"]
        assert result["address"] == row["address"]
        assert set(result["tags"]) == set(row["tags"])
        assert result["notes"] == row["notes"]
