"""Tests for two related UI fixes to the Edit-event-style modal forms
(direct user feedback with screenshots of the Edit Event modal):

1. `event_form.html`/`task_form.html`/`contact_form.html`/`habit_form.html`
   (and `schedule_class_form.html`, found sharing the exact same shape)
   now split their `#modal-target` content into `.modal-header`/
   `.modal-body`/`.modal-footer` sections instead of dumping every field
   plus the Save/Cancel/Delete buttons flat into the body -- so the action
   buttons stay anchored (style.css's existing `.modal`
   flex-column/`.modal-body{flex:1; overflow-y:auto}` rules) instead of
   scrolling away with a long field list (static/modal.js's
   `injectModalContent` `hasSections` split already supported this, it's
   just that none of these templates opted in before).

2. Recurrence (event_form.html/task_form.html) and Reminders
   (event_form.html only) are no longer raw-RRULE/raw-CSV text inputs --
   static/recurrence_picker.js and static/reminders_picker.js
   progressively enhance them into a preset dropdown / preset checkboxes,
   entirely client-side (routers/calendar.py's create_event/update_event
   and routers/tasks.py's create_task/update_task do zero server-side
   parsing beyond straight pass-through or `int(m) for m in ... .split(",")`
   -- the final POST still sends the same plain `recurrence`/`reminders`
   fields the backend has always received, unaffected by the picker)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import contacts as contacts_router
from src.routers import habits as habits_router
from src.routers import schedule as schedule_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
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


def _seed_event(conn, uid, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "start_at": "2026-08-10T09:00:00",
        "status": "active",
        "all_day": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return db.get_event(conn, uid)


def _seed_task(conn, uid, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "status": "active",
        "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _seed_contact(conn, uid, **overrides):
    row = {
        "uid": uid,
        "full_name": uid,
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_contact(conn, row)
    return db.get_contact(conn, uid)


def _seed_habit(conn, uid, **overrides):
    row = {
        "uid": uid,
        "name": uid,
        "color": "blue",
        "target_per_day": 1,
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_habit(conn, row)
    return db.get_habit(conn, uid)


def _seed_class(conn, uid, **overrides):
    """1.6: a class is a real recurring event now (see schedule_router's
    module docstring) -- goes through the actual create_class router
    function (day/parity default to Monday/all) rather than a removed
    db.upsert_schedule_class call, then the resulting event's uid is
    looked up by title (create_class always mints its own uuid, it
    doesn't take a caller-supplied uid)."""
    fields = {
        "day": "Monday", "start_time": "09:00", "end_time": "10:00",
        "name": uid, "acronym": "", "class_type_select": "", "class_type_other": "",
        "professor_select": "", "professor_new": "", "room": "", "credits": "0",
        "parity": "all", "enrolled": "on", "project_uid": "",
    }
    fields.update(overrides)
    schedule_router.create_class(conn=conn, **fields)
    event = next(e for e in db.list_schedule_class_events(conn) if e["title"] == uid)
    return schedule_router._class_row(conn, event)


def _index(body: str, needle: str) -> int:
    idx = body.find(needle)
    assert idx != -1, f"{needle!r} not found in body"
    return idx


class TestModalHeaderBodyFooterSections:
    """Every one of these forms must render all three sections, exactly
    once each, for both the New (create) and Edit (existing-object) case."""

    def _assert_sections(self, body: str):
        assert 'class="modal-header"' in body
        assert 'class="modal-body"' in body
        assert 'class="modal-footer"' in body
        header_pos = _index(body, 'class="modal-header"')
        body_pos = _index(body, 'class="modal-body"')
        footer_pos = _index(body, 'class="modal-footer"')
        assert header_pos < body_pos < footer_pos

    def test_event_form_new(self, conn):
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_event_form_edit(self, conn):
        _seed_event(conn, "e1")
        resp = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_task_form_new(self, conn):
        resp = tasks_router.new_task_form(_request("/tasks/new"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_task_form_edit(self, conn):
        _seed_task(conn, "t1")
        resp = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_contact_form_new(self, conn):
        resp = contacts_router.new_contact_form(_request("/contacts/new"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_contact_form_edit(self, conn):
        _seed_contact(conn, "c1")
        resp = contacts_router.edit_contact_form("c1", _request("/contacts/c1/edit"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_habit_form_new(self, conn):
        resp = habits_router.new_habit_form(_request("/habits/new"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_habit_form_edit(self, conn):
        _seed_habit(conn, "h1")
        resp = habits_router.edit_habit_form("h1", _request("/habits/h1/edit"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_schedule_class_form_new(self, conn):
        resp = schedule_router.new_class_form(_request("/schedule/classes/new"), conn=conn)
        self._assert_sections(resp.body.decode())

    def test_schedule_class_form_edit(self, conn):
        cls = _seed_class(conn, "cl1")
        resp = schedule_router.edit_class_form(cls["uid"], _request(f"/schedule/classes/{cls['uid']}/edit"), conn=conn)
        self._assert_sections(resp.body.decode())


class TestFooterButtonPlacement:
    """Save/Cancel(/Delete) must actually sit inside the footer markup,
    not just somewhere after the header -- i.e. after the `.modal-footer`
    div opens, not inside `.modal-body`."""

    def test_event_edit_save_cancel_delete_all_in_footer(self, conn):
        _seed_event(conn, "e1", title="My Event")
        resp = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn)
        body = resp.body.decode()
        header_pos = _index(body, 'class="modal-header"')
        body_pos = _index(body, 'class="modal-body"')
        footer_pos = _index(body, 'class="modal-footer"')
        save_pos = _index(body, '<button type="submit" form="event-form"')
        # 2026-08-08: Cancel on an edit is now a data-modal link that
        # returns to the detail view, not a data-modal-cancel close -- the
        # modal's X is the way to fully close. It still lives in the footer.
        cancel_pos = _index(body, 'class="btn ghost"')
        delete_pos = _index(body, "/events/e1/delete")
        assert header_pos < body_pos < footer_pos
        # Save/Cancel/Delete all sit after the footer div opens, i.e.
        # inside .modal-footer, not somewhere inside .modal-body.
        assert save_pos > footer_pos
        assert cancel_pos > footer_pos
        assert delete_pos > footer_pos

    def test_event_new_has_no_delete_button(self, conn):
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        body = resp.body.decode()
        assert "/delete" not in body

    def test_task_edit_delete_in_footer(self, conn):
        _seed_task(conn, "t1", title="My Task")
        resp = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn)
        body = resp.body.decode()
        footer_pos = _index(body, 'class="modal-footer"')
        delete_pos = _index(body, "/tasks/t1/delete")
        save_pos = _index(body, '<button type="submit" form="task-form"')
        assert delete_pos > footer_pos
        assert save_pos > footer_pos

    def test_contact_form_has_no_delete_button_at_all(self, conn):
        _seed_contact(conn, "c1")
        resp = contacts_router.edit_contact_form("c1", _request("/contacts/c1/edit"), conn=conn)
        body = resp.body.decode()
        assert "/delete" not in body


class TestFullPageRenderingStillWorks:
    """The same templates, rendered as an ordinary full page (not through
    modal.js), must still contain a real, complete, submittable form --
    the header/body/footer split is just plain divs with CSS classes, not
    modal-shell-specific markup."""

    def test_event_edit_full_page_has_complete_form(self, conn):
        event = _seed_event(conn, "e1", title="My Event")
        resp = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn)
        body = resp.body.decode()
        assert f'id="event-form"' in body
        assert f'action="/events/{event["uid"]}"' in body
        assert 'name="title"' in body
        assert 'value="My Event"' in body
        # The Save button references the form by id (works regardless of
        # DOM nesting per the HTML `form` attribute), so it still submits
        # the exact same single POST as before.
        assert 'form="event-form"' in body

    def test_task_edit_full_page_has_complete_form(self, conn):
        task = _seed_task(conn, "t1", title="My Task")
        resp = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'id="task-form"' in body
        assert f'action="/tasks/{task["uid"]}"' in body
        assert 'form="task-form"' in body


class TestRecurrencePresetInputs:
    def test_event_form_recurrence_is_still_a_plain_input_server_side(self, conn):
        # The picker is pure client-side JS enhancement -- server-rendered
        # HTML still has to be a plain <input name="recurrence"> for
        # recurrence_picker.js to progressively enhance at all.
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="recurrence" class="recurrence-input"' in body

    # test_task_form_recurrence_is_still_a_plain_input_server_side removed
    # 2026-08-08 -- task_form.html no longer has a Recurrence field at all
    # ("remove recurrence-input recurrence-raw-input, and add a way to add
    # subtasks in place of it"; the dedicated habit_task_form.html is the
    # only task-creation form with Recurrence now, and it's required
    # there, not this optional/enhanced-picker shape). Its whole subject
    # no longer exists, per this suite's standing rule for a superseded
    # feature.

    def test_event_form_reminders_is_still_a_plain_input_server_side(self, conn):
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="reminders" class="reminders-input"' in body


class TestContactFormAvatarUploadAndFieldOrder:
    """contact_form.html (2026-08-07, direct feedback): the native file
    input no longer renders its own visible "Choose File"/"Browse" button
    -- it's an invisible full-circle overlay on the avatar itself, revealed
    via a hover/focus CSS affordance (`.avatar-upload-overlay`) that this
    no-JS-test-infra repo can't exercise directly, but the underlying
    markup shape (file input still present with the same `name="photo"`,
    both siblings inside one `.avatar-upload` wrapper) is what makes that
    CSS behavior possible and is exactly what these tests assert on.
    Avatar + Full name are also now siblings inside one `.photo-field-row`
    instead of Full name being its own separate field below."""

    def test_file_input_still_present_with_name_photo(self, conn):
        resp = contacts_router.new_contact_form(_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="file" name="photo"' in body

    def test_file_input_has_no_visible_browse_button_markup(self, conn):
        # The old layout had a `.photo-field-controls` wrapper holding a
        # bare, always-visible file input beside the avatar. That wrapper
        # (and the old separate full-name-field-below layout) is gone.
        resp = contacts_router.new_contact_form(_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert "photo-field-controls" not in body
        assert 'class="avatar-upload-input"' in body

    def test_avatar_and_file_input_share_one_wrapper(self, conn):
        resp = contacts_router.new_contact_form(_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        wrapper_pos = _index(body, 'class="avatar-upload"')
        # Scope the avatar search to inside the wrapper: the page's first
        # `avatar-circle` could belong to some earlier avatar (the nav rail
        # used to render the user's own profile avatar here, and other
        # chrome may add avatars later), so search only after the wrapper.
        # The overlay + file input class names are unique to the form, so
        # they need no scoping.
        avatar_pos = wrapper_pos + _index(body[wrapper_pos:], 'class="avatar-circle')
        overlay_pos = _index(body, 'class="avatar-upload-overlay"')
        input_pos = _index(body, 'class="avatar-upload-input"')
        # All three (avatar image/initials, hover overlay, real file input)
        # sit after the wrapper div opens, i.e. inside `.avatar-upload`.
        assert wrapper_pos < avatar_pos
        assert wrapper_pos < overlay_pos
        assert wrapper_pos < input_pos

    def test_avatar_and_full_name_are_siblings_in_one_row(self, conn):
        resp = contacts_router.new_contact_form(_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        row_pos = _index(body, 'class="photo-field-row"')
        avatar_pos = _index(body, 'class="avatar-upload"')
        name_label_pos = _index(body, "<label>Full name</label>")
        footer_pos = _index(body, 'class="modal-footer"')
        # Both the avatar wrapper and the Full name field sit inside the
        # same photo-field-row, well before the footer -- i.e. Full name is
        # no longer its own separate field below the photo row.
        assert row_pos < avatar_pos < name_label_pos < footer_pos

    def test_remove_photo_checkbox_still_present_when_photo_exists(self, conn):
        _seed_contact(conn, "c1", photo_b64="abc123", photo_type="jpeg")
        resp = contacts_router.edit_contact_form("c1", _request("/contacts/c1/edit"), conn=conn)
        body = resp.body.decode()
        assert "Remove current photo" in body
        assert 'name="remove_photo"' in body

    def test_email_and_phone_come_right_after_the_photo_name_row(self, conn):
        resp = contacts_router.new_contact_form(_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        row_pos = _index(body, 'class="photo-field-row"')
        email_pos = _index(body, "<label>Email</label>")
        phone_pos = _index(body, "<label>Phone</label>")
        org_pos = _index(body, "<label>Organization</label>")
        # Email/Phone sit directly after the photo+name row, before
        # Organization and everything else.
        assert row_pos < email_pos < org_pos
        assert row_pos < phone_pos < org_pos

    def test_recurrence_picker_js_defines_the_expected_presets(self):
        js_path = Path(__file__).resolve().parents[1] / "src" / "static" / "recurrence_picker.js"
        js = js_path.read_text(encoding="utf-8")
        for expected in ['label: "Does not repeat"', '"FREQ=DAILY"', '"FREQ=WEEKLY"', '"FREQ=MONTHLY"', '"FREQ=YEARLY"']:
            assert expected in js

    def test_recurrence_picker_js_defines_ends_controls(self):
        """"Ends" -- Never/On date (UNTIL=)/After N occurrences (COUNT=) --
        the recurrence-end-condition feature, wired entirely client-side
        into the same picker (routers/calendar.py still does zero
        server-side parsing of `recurrence`)."""
        js_path = Path(__file__).resolve().parents[1] / "src" / "static" / "recurrence_picker.js"
        js = js_path.read_text(encoding="utf-8")
        for expected in [
            '"never"', '"until"', '"count"',
            '";UNTIL="', '";COUNT="',
            "recurrence-ends-until", "recurrence-ends-count",
        ]:
            assert expected in js

    def test_reminders_picker_js_defines_the_expected_presets(self):
        js_path = Path(__file__).resolve().parents[1] / "src" / "static" / "reminders_picker.js"
        js = js_path.read_text(encoding="utf-8")
        for expected in ["minutes: 0", "minutes: 5", "minutes: 10", "minutes: 30", "minutes: 60", "minutes: 1440"]:
            assert expected in js


class TestSubmissionUnaffectedByPickerUI:
    """The picker only changes what populates the `recurrence`/`reminders`
    form fields client-side -- the value the backend receives is exactly
    the same plain string it always was. Verified here by calling the
    POST route functions directly (this suite's existing convention),
    bypassing any JS entirely."""

    def test_create_event_recurrence_and_reminders_reach_db_unchanged(self, conn):
        calendar_router.create_event(
            title="Standup", description="", start_at="2026-08-10T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="",
            recurrence="FREQ=WEEKLY",
            reminders="0, 10, 1440",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        events = db.list_events(conn, start="2026-01-01", end="2026-12-31")
        assert len(events) == 1
        assert events[0]["recurrence"] == "FREQ=WEEKLY"
        assert events[0]["reminders"] == [0, 10, 1440]

    def test_update_event_recurrence_and_reminders_reach_db_unchanged(self, conn):
        _seed_event(conn, "e1")
        calendar_router.update_event(
            uid="e1",
            title="Standup", description="", start_at="2026-08-10T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="",
            recurrence="FREQ=MONTHLY;BYMONTHDAY=1",
            reminders="5, 60",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        updated = db.get_event(conn, "e1")
        assert updated["recurrence"] == "FREQ=MONTHLY;BYMONTHDAY=1"
        assert updated["reminders"] == [5, 60]

    def test_create_task_recurrence_reaches_db_unchanged(self, conn):
        tasks_router.create_task(
            title="Water plants", description="", due_at="", importance="", urgency="", status="active",
            tags="", recurrence="FREQ=DAILY", conn=conn,
        )
        tasks = [t for t in db.list_tasks(conn) if t["title"] == "Water plants"]
        assert len(tasks) == 1
        assert tasks[0]["recurrence"] == "FREQ=DAILY"

    def test_update_task_recurrence_reaches_db_unchanged(self, conn):
        _seed_task(conn, "t1")
        tasks_router.update_task(
            uid="t1", title="Water plants", description="", due_at="", start_at="",
            importance="", urgency="", status="active", tags="", recurrence="FREQ=YEARLY", conn=conn,
        )
        updated = db.get_task(conn, "t1")
        assert updated["recurrence"] == "FREQ=YEARLY"

    def test_empty_recurrence_still_stores_none(self, conn):
        calendar_router.create_event(
            title="One-off", description="", start_at="2026-08-10T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="", recurrence="", reminders="",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        events = [e for e in db.list_events(conn, start="2026-01-01", end="2026-12-31") if e["title"] == "One-off"]
        assert events[0]["recurrence"] is None
