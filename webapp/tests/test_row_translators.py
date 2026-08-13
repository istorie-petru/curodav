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
            "parent_uid": "project-1",
            "recurrence": "FREQ=WEEKLY;BYDAY=MO,WE",
        }
        ics = task_row_to_ical(row)
        todo = Todo.from_ical(ics)
        result = ical_to_task_row(todo)

        assert result["title"] == row["title"]
        assert result["description"] == row["description"]
        assert result["start_at"] == row["start_at"]
        assert result["due_at"] == row["due_at"]
        # 1.1: PRIORITY carries urgency (urgency-dominant export), so the
        # urgency axis round-trips exactly; importance survives only in this
        # app's own DB, not in iCal -- see ical_rows.py's recorded decision.
        assert result["urgency"] == row["urgency"]
        assert result["status"] == row["status"]
        assert result["progress"] == row["progress"]
        assert set(result["tags"]) == set(row["tags"])
        assert result["parent_uid"] == row["parent_uid"]
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
            "org": "Acme",
            "phone": "+15550100",
            "email": "jane@example.com",
            "address": "123 Main St",
            "tags": ["friend", "vip"],
            "notes": "met at a conference",
        }
        text = contact_row_to_vcard(row)
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)

        assert result["full_name"] == row["full_name"]
        assert result["org"] == row["org"]
        assert result["phone"] == row["phone"]
        assert result["email"] == row["email"]
        assert result["address"] == row["address"]
        assert set(result["tags"]) == set(row["tags"])
        assert result["notes"] == row["notes"]
