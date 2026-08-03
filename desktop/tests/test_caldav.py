"""Round-trip tests for core/caldav -- the CalDAV/CardDAV translation layer
(task/event/person <-> VTODO/VEVENT/VCARD). See core/caldav/ical.py and
vcard.py for the design rationale: standard fields sync with any compliant
client, CommandCenter-only fields ride as X-COMMANDCENTER-* properties and
must survive a full app-to-app round trip, but must NOT be required for
(or clobbered by) an edit made by a client that doesn't know about them.
"""

from __future__ import annotations

from icalendar import Event, Todo

from src.core.caldav import (
    merge_standard_fields_into,
    to_vcard,
    to_vevent,
    to_vtodo,
    vcard_to_fields,
    vevent_to_fields,
    vtodo_to_fields,
)
from src.core.models import (
    EventDetails,
    Object,
    ObjectStatus,
    ObjectType,
    PersonDetails,
    Priority,
    TaskDetails,
)


def _task_object(**overrides) -> Object:
    defaults = dict(
        id="task-1",
        type=ObjectType.task,
        title="Write handoff doc",
        description="Cover the sync bridge design",
        status=ObjectStatus.waiting,
        priority=Priority.high,
        start_at="2026-08-01",
        due_at="2026-08-05",
        pinned=True,
        parent_id="project-1",
        sort_key="aa",
        tags=["work", "urgent"],
        created_at="2026-07-01T10:00:00",
        updated_at="2026-07-31T10:00:00",
    )
    defaults.update(overrides)
    return Object(**defaults)


def _task_details(**overrides) -> TaskDetails:
    defaults = dict(
        checklist=[{"id": "1", "text": "Draft outline", "done": True}],
        estimate_min=60,
        time_spent_min=15,
        recurrence="FREQ=WEEKLY;BYDAY=MO,WE",
        waiting_on="review",
    )
    defaults.update(overrides)
    return TaskDetails(**defaults)


class TestTaskRoundTrip:
    def test_full_round_trip_preserves_everything(self):
        obj = _task_object()
        details = _task_details()

        todo = to_vtodo(obj, details)
        # Simulate actually going over the wire: serialize, reparse.
        todo2 = Todo.from_ical(todo.to_ical())
        fields = vtodo_to_fields(todo2)

        assert fields["title"] == obj.title
        assert fields["description"] == obj.description
        assert fields["start_at"] == obj.start_at
        assert fields["due_at"] == obj.due_at
        assert fields["priority"] == obj.priority
        assert fields["status"] == obj.status  # from X-COMMANDCENTER-STATUS
        assert fields["pinned"] is True
        assert fields["parent_id"] == obj.parent_id
        assert fields["sort_key"] == obj.sort_key
        assert set(fields["tags"]) == set(obj.tags)
        assert fields["details"]["checklist"] == details.checklist
        assert fields["details"]["estimate_min"] == details.estimate_min
        assert fields["details"]["time_spent_min"] == details.time_spent_min
        assert fields["details"]["waiting_on"] == details.waiting_on
        assert fields["details"]["recurrence"] == details.recurrence

    def test_priority_mapping_is_stable_both_directions(self):
        for p in (Priority.urgent, Priority.high, Priority.medium, Priority.low):
            obj = _task_object(priority=p)
            todo = Todo.from_ical(to_vtodo(obj, TaskDetails()).to_ical())
            fields = vtodo_to_fields(todo)
            assert fields["priority"] == p

    def test_foreign_edit_has_no_extras_but_maps_standard_status(self):
        """A phone's native Reminders app marks the task done: it writes a
        plain VTODO with no X-COMMANDCENTER-* properties at all. The parsed
        update dict must still carry `status` (recovered from the standard
        STATUS property), but none of our extras."""
        foreign = Todo()
        foreign.add("UID", "task-1")
        foreign.add("SUMMARY", "Write handoff doc")
        foreign.add("STATUS", "COMPLETED")

        fields = vtodo_to_fields(foreign)

        assert fields["status"] == ObjectStatus.done
        assert "details" not in fields or "checklist" not in fields.get("details", {})

    def test_merge_of_foreign_edit_preserves_local_only_fields(self):
        local = _task_object()
        local.details = {
            "checklist": [{"id": "1", "text": "Draft outline", "done": True}],
            "estimate_min": 60,
        }

        foreign = Todo()
        foreign.add("UID", "task-1")
        foreign.add("SUMMARY", "Write handoff doc")
        foreign.add("STATUS", "COMPLETED")
        updates = vtodo_to_fields(foreign)

        merge_standard_fields_into(local, updates)

        assert local.status == ObjectStatus.done  # the actual edit applied
        assert local.details["checklist"] == [
            {"id": "1", "text": "Draft outline", "done": True}
        ]  # untouched, since the foreign resource never mentioned it
        assert local.details["estimate_min"] == 60
        assert local.pinned is True  # untouched top-level field
        assert local.parent_id == "project-1"  # untouched top-level field

    def test_merge_only_touches_keys_present_in_updates(self):
        local = _task_object()
        original_due = local.due_at
        merge_standard_fields_into(local, {"title": "Renamed"})
        assert local.title == "Renamed"
        assert local.due_at == original_due
        assert local.status == ObjectStatus.waiting


class TestEventRoundTrip:
    def _event_object(self, **overrides) -> Object:
        defaults = dict(
            id="event-1",
            type=ObjectType.event,
            title="Team standup",
            description="Daily sync",
            status=ObjectStatus.active,
            start_at="2026-08-03T09:00:00",
            tags=["work"],
            created_at="2026-07-01T10:00:00",
            updated_at="2026-07-31T10:00:00",
        )
        defaults.update(overrides)
        return Object(**defaults)

    def test_full_round_trip_preserves_everything(self):
        obj = self._event_object()
        details = EventDetails(
            end_at="2026-08-03T09:30:00",
            all_day=False,
            location="Conference Room A",
            meeting_url="https://meet.example.com/standup",
            recurrence="FREQ=DAILY",
            calendar_id="work-cal",
            reminders=[10, 30],
        )

        event = to_vevent(obj, details)
        event2 = Event.from_ical(event.to_ical())
        fields = vevent_to_fields(event2)

        assert fields["title"] == obj.title
        assert fields["start_at"] == obj.start_at
        assert fields["details"]["end_at"] == details.end_at
        assert fields["details"]["all_day"] is False
        assert fields["details"]["location"] == details.location
        assert fields["details"]["meeting_url"] == details.meeting_url
        assert fields["details"]["recurrence"] == details.recurrence
        assert fields["details"]["calendar_id"] == details.calendar_id
        assert sorted(fields["details"]["reminders"]) == [10, 30]

    def test_all_day_event_uses_date_not_datetime(self):
        obj = self._event_object(start_at="2026-08-03T00:00:00")
        details = EventDetails(all_day=True, end_at="2026-08-03T00:00:00")

        event = to_vevent(obj, details)
        raw = event.to_ical()
        assert b"DTSTART;VALUE=DATE:" in raw

        event2 = Event.from_ical(raw)
        fields = vevent_to_fields(event2)
        assert fields["details"]["all_day"] is True

    def test_foreign_edit_maps_coarse_status(self):
        foreign = Event()
        foreign.add("UID", "event-1")
        foreign.add("SUMMARY", "Team standup (moved)")
        foreign.add("STATUS", "CANCELLED")

        fields = vevent_to_fields(foreign)
        assert fields["status"] == ObjectStatus.archived
        assert fields["title"] == "Team standup (moved)"
        assert "details" not in fields


class TestPersonRoundTrip:
    def _person_object(self, **overrides) -> Object:
        defaults = dict(
            id="person-1",
            type=ObjectType.person,
            title="Jane Doe",
            description="Met at a conference",
            status=ObjectStatus.active,
            tags=["friend", "vip"],
            created_at="2026-07-01T10:00:00",
            updated_at="2026-07-31T10:00:00",
        )
        defaults.update(overrides)
        return Object(**defaults)

    def test_full_round_trip_preserves_everything(self):
        obj = self._person_object()
        details = PersonDetails(
            org="Acme Inc",
            phone="+1 555 0100",
            email="jane@example.com",
            address="123 Main St",
            photo_path="/home/peter/CommandCenter/attachments/abc/photo.jpg",
            category="friend",
        )

        card = to_vcard(obj, details)
        import vobject

        card2 = vobject.readOne(card.serialize())
        fields = vcard_to_fields(card2)

        assert fields["title"] == obj.title
        assert fields["description"] == obj.description
        assert set(fields["tags"]) == set(obj.tags)
        assert fields["details"]["org"] == details.org
        assert fields["details"]["phone"] == details.phone
        assert fields["details"]["email"] == details.email
        assert fields["details"]["address"] == details.address
        assert fields["details"]["photo_path"] == details.photo_path
        assert fields["details"]["category"] == details.category

    def test_foreign_edit_from_native_contacts_app_has_no_extras(self):
        import vobject

        foreign = vobject.vCard()
        foreign.add("version").value = "3.0"
        foreign.add("uid").value = "person-1"
        foreign.add("fn").value = "Jane A. Doe"
        foreign.add("tel").value = "+1 555 9999"

        fields = vcard_to_fields(foreign)

        assert fields["title"] == "Jane A. Doe"
        assert fields["details"]["phone"] == "+1 555 9999"
        assert "org" not in fields.get("details", {})
        assert "photo_path" not in fields.get("details", {})

    def test_merge_of_foreign_contact_edit_preserves_local_only_fields(self):
        local = self._person_object()
        local.details = {
            "org": "Acme Inc",
            "photo_path": "/some/path.jpg",
            "category": "friend",
        }

        import vobject

        foreign = vobject.vCard()
        foreign.add("version").value = "3.0"
        foreign.add("uid").value = "person-1"
        foreign.add("fn").value = "Jane A. Doe"
        foreign.add("tel").value = "+1 555 9999"
        updates = vcard_to_fields(foreign)

        merge_standard_fields_into(local, updates)

        assert local.title == "Jane A. Doe"
        assert local.details["phone"] == "+1 555 9999"
        assert local.details["org"] == "Acme Inc"  # untouched
        assert local.details["photo_path"] == "/some/path.jpg"  # untouched
