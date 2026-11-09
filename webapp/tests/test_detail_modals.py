"""Tests for the 2026-08-08 visual rework of the three read-only detail
modals -- event_detail.html / task_detail.html / contact_detail.html -- as
one cohesive design (direct feedback: make the event/task/contact
"view before you edit" modal windows more visually pleasing across all
three contexts in a single stroke):

1. Each now splits its `#modal-target` content into `.modal-header` /
   `.modal-body` / `.modal-footer` like the *_form.html modals already do
   (static/modal.js's `injectModalContent` `hasSections` split), so the
   identity and the footer actions stay anchored instead of scrolling.

2. The header carries the entity's identity at a glance: a large bold
   `.detail-title` plus a colored `.detail-identity-dot` (event's calendar
   color, task's status color) or the contact's `.avatar-large`.
   (2026-09-03: the identity dot/avatar moved into the shared
   `_detail_cover.html` cover banner's floating badge -- see
   `TestIdentityMark` below, updated the same day.)

3. The body holds the 2-column `.detail-meta-grid`, whose values use the
   crisp `.detail-meta-value` typography. (2026-09-03 direct feedback:
   the grid's wrapper is the plain `.detail-meta-panel` -- no elevated
   tonal surface, no colored left accent -- the identity color instead
   stays only on the header's `.detail-identity-dot` and, for events, the
   `.color-dot` next to the Start value.)

4. The old filled-red `.btn.danger` Delete is demoted to a quiet
   `.detail-delete-link` text-link in the footer, letting the primary
   `.btn.primary` Edit action take center stage as the logical next step.

5. contact_detail.html drops its one-off `.detail-kv` <table> for the same
   detail-meta-grid every other detail view uses."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import contacts as contacts_router
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


def _index(body: str, needle: str) -> int:
    idx = body.find(needle)
    assert idx != -1, f"{needle!r} not found in body"
    return idx


class TestDetailModalSections:
    """Every one of the three detail modals must render all three
    sections, in order, like the form modals."""

    def _assert_sections(self, body: str):
        header_pos = _index(body, 'class="modal-header"')
        body_pos = _index(body, 'class="modal-body"')
        footer_pos = _index(body, 'class="modal-footer"')
        assert header_pos < body_pos < footer_pos

    def test_event_detail(self, conn):
        _seed_event(conn, "e1")
        self._assert_sections(calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode())

    def test_task_detail(self, conn):
        _seed_task(conn, "t1")
        self._assert_sections(tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode())

    def test_contact_detail(self, conn):
        _seed_contact(conn, "c1")
        self._assert_sections(contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn).body.decode())


class TestIdentityMark:
    """The header leads with a cover banner whose floating badge carries a
    color-coded icon (or the contact's avatar), so the entity is identified
    at a glance. 2026-09-03: rewritten for the Variant B cover-banner
    baseline ("I like variant B so much I want it to be the baseline for
    all view modal windows") -- the old .detail-identity-dot beside the
    title is gone; the same color now drives .detail-cover-icon's `color`
    (an icon's stroke is `currentColor`, see style.css's `.icon` rule) when
    no real banner image is resolved."""

    def test_event_identity_badge_uses_calendar_color(self, conn):
        _seed_event(conn, "e1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-cover-icon" data-style="color:var(--cal-accent-blue)"' in body
        assert '#icon-calendar' in body
        assert 'class="detail-title"' in body

    def test_event_identity_badge_follows_a_label_color(self, conn):
        # An event's calendar_color is its first label's color -- a red
        # label must drive both the cover badge's color and the Start
        # value's own color-dot (2026-09-03: the meta panel itself no
        # longer carries a colored accent, so these two are the only
        # remaining color tells).
        _seed_event(conn, "e1")
        db.upsert_label_config(conn, {"name": "Work", "color": "red"})
        db.set_object_labels(conn, "event", "e1", ["Work"])
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-cover-icon" data-style="color:var(--cal-accent-red)"' in body
        assert 'class="color-dot cal-red"' in body

    def test_task_identity_badge_uses_status_color(self, conn):
        _seed_task(conn, "t1", status="in_progress")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert 'class="detail-cover-icon" data-style="color:var(--cal-accent-orange)"' in body
        assert '#icon-check-square' in body
        assert 'class="detail-title"' in body

    def test_task_detail_has_no_subtask_identity(self, conn):
        # 1.2: tasks are flat -- the old "Subtask of" heading (which pointed
        # back at tasks.parent_uid) is gone entirely, even for rows that
        # still carry a parent_uid on disk from before the removal.
        _seed_task(conn, "t1")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert "Subtask of" not in body
        assert 'class="detail-heading-sub"' not in body

    def test_contact_header_shows_avatar_and_org(self, conn):
        _seed_contact(conn, "c1", full_name="Ada Lovelace", org="Analytical Engines")
        body = contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn).body.decode()
        # 2026-09-13: no-photo initials fallback now also carries
        # avatar-colored (deps.py's avatar(), see test_banners.py's own
        # comment on the same change) -- substring match, not the old
        # exact-two-class string.
        assert 'class="avatar-circle avatar-large avatar-colored"' in body
        assert "Ada Lovelace" in body
        assert "Analytical Engines" in body
        assert 'class="detail-heading-sub"' in body


class TestDetailCardAndMetaGrid:
    """2026-09-03: the meta grid's wrapper is the plain .detail-meta-panel
    (no elevated tonal surface, no colored left accent -- direct feedback
    that the colored bg card read wrong for showing plain metadata), just
    the 2-column grid and crisp value typography."""

    def test_event_card_has_calendar_accent(self, conn):
        _seed_event(conn, "e1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-section"' in body
        assert 'class="vi-row"' in body

    def test_task_card_has_status_accent(self, conn):
        _seed_task(conn, "t1", status="in_progress")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert 'class="detail-section"' in body
        assert 'class="vi-row"' in body  # the task window is a table of label and value rows

    def test_contact_uses_the_shared_meta_grid_not_the_old_table(self, conn):
        # Contacts field parity slices 2/5: phone and address are multi-
        # value now (contact_phones/contact_addresses) -- the legacy flat
        # `phone`/`address` columns this test used to seed are dead and no
        # longer rendered, so this seeds the real child-row shape instead
        # to still get a populated meta grid.
        _seed_contact(
            conn, "c1",
            phones=[{"type": "Other", "value": "+123"}],
            emails=[{"type": "Other", "value": "a@example.com"}],
            addresses=[{"type": "Other", "street": "1 St"}],
        )
        body = contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn).body.decode()
        assert 'class="detail-section"' in body
        assert 'class="vi-rows"' in body
        assert "+123" in body and "a@example.com" in body and "1 St" in body
        assert '<table class="detail-kv">' not in body

    def test_task_page_is_header_and_body_sections_only(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert 'class="detail-section-head"' in body
        assert 'class="detail-section-body"' in body
        assert 'class="detail-card' not in body

    def test_task_view_work_sessions_are_read_only(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        modal = body[body.index('class="modal-body"'):body.index('class="modal-footer"')]
        assert "Work sessions" in modal
        # The editors of the in-place rows sit in inert <template> tags; the sessions themselves hold no controls.
        live = re.sub(r"<template\b.*?</template>", "", modal, flags=re.S)
        assert "<input" not in live and "<form" not in live and "<button" not in live


class TestFooterActions:
    """Delete is demoted from the old filled-red .btn.danger to a quiet
    .detail-delete-link text-link; Edit becomes the primary button. Both
    live in the footer, after the footer div opens, not in the body."""

    def _footer_pos(self, body: str) -> int:
        return _index(body, 'class="modal-footer"')

    def test_event_delete_demoted_and_edit_primary(self, conn):
        _seed_event(conn, "e1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        footer_pos = self._footer_pos(body)
        assert 'class="btn danger"' not in body
        delete_pos = _index(body, 'aria-label="Delete"')
        edit_pos = _index(body, 'class="btn primary btn-split-main"')
        assert delete_pos > footer_pos
        assert edit_pos > footer_pos and "Edit fields" in body  # Done is the primary and Edit fields is in its menu
        # Done (the primary action) comes after the demoted Delete button.
        assert edit_pos > delete_pos

    def test_task_delete_demoted_and_edit_primary(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        footer_pos = self._footer_pos(body)
        assert 'class="btn danger"' not in body
        assert _index(body, 'aria-label="Delete"') > footer_pos
        assert _index(body, 'class="btn primary btn-split-main"') > footer_pos  # Done is the primary, Edit fields sits in its menu
        assert "Edit fields" in body and "Mark done" in body
        assert 'data-delete-undo-redirect="/tasks"' in body

    def test_task_delete_is_always_the_undo_path(self, conn):
        # 1.2: no more subtask cascade, so a task delete never needs the
        # confirm sheet -- every task delete is a single, independent task
        # on the undo path.
        _seed_task(conn, "t1")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        footer_pos = self._footer_pos(body)
        assert 'class="btn danger"' not in body
        assert "data-confirm-sheet" not in body
        assert _index(body, 'aria-label="Delete"') > footer_pos

    def test_contact_delete_demoted_and_edit_primary(self, conn):
        _seed_contact(conn, "c1")
        body = contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn).body.decode()
        footer_pos = self._footer_pos(body)
        assert 'class="btn danger"' not in body
        assert _index(body, 'aria-label="Delete"') > footer_pos
        assert _index(body, 'class="btn primary btn-split-main"') > footer_pos
        assert 'data-delete-undo-redirect="/contacts"' in body


class TestMissingObject:
    """The not-found branches still render a usable empty state."""

    def test_event_missing(self, conn):
        body = calendar_router.event_detail("nope", _request("/events/nope"), conn=conn).body.decode()
        assert "Event not found" in body

    def test_task_missing(self, conn):
        body = tasks_router.task_detail("nope", _request("/tasks/nope"), conn=conn).body.decode()
        assert "Task not found" in body

    def test_contact_missing(self, conn):
        body = contacts_router.contact_detail("nope", _request("/contacts/nope"), conn=conn).body.decode()
        assert "Contact not found" in body


class TestInlineFieldRoutes:
    """The view windows of an event and a contact save a field in place."""

    def _call(self, route, uid, field, value, conn):
        import asyncio, json
        request = _request("/x")

        async def receive():
            return {"type": "http.request", "body": json.dumps({"field": field, "value": value}).encode(), "more_body": False}

        request._receive = receive
        return asyncio.run(route(uid, request, conn=conn))

    def test_an_event_location_and_description_are_saved(self, conn):
        _seed_event(conn, "e1")
        assert self._call(calendar_router.update_event_field, "e1", "location", "  Room A2 ", conn).status_code == 200
        assert self._call(calendar_router.update_event_field, "e1", "description", " Bring notes ", conn).status_code == 200
        event = db.get_event(conn, "e1")
        assert event["location"] == "Room A2" and event["description"] == "Bring notes"

    def test_an_event_title_is_not_inline_editable(self, conn):
        _seed_event(conn, "e1")
        assert self._call(calendar_router.update_event_field, "e1", "title", "x", conn).status_code == 400

    def test_a_repeating_event_is_changed_in_its_form(self, conn):
        _seed_event(conn, "e1", recurrence="FREQ=WEEKLY")
        assert self._call(calendar_router.update_event_field, "e1", "location", "x", conn).status_code == 400

    def test_contact_notes_are_saved_without_touching_the_rest(self, conn):
        from src.routers import contacts as contacts_router
        _seed_contact(conn, "c1", org="Acme")
        assert self._call(contacts_router.update_contact_field, "c1", "notes", "  Office hours  ", conn).status_code == 200
        contact = db.get_contact(conn, "c1")
        assert contact["notes"] == "Office hours" and contact["org"] == "Acme"


class TestMarkHabitToday:
    """The habit window's Done menu marks today done; asking twice never un-marks it, and a plain task is refused."""

    def test_today_is_marked_and_stays_marked(self, conn):
        from src import clock
        _seed_task(conn, "h1", is_habit=1, recurrence="FREQ=DAILY")
        for _ in range(2):
            resp = tasks_router.mark_habit_today_done("h1", _request("/tasks/h1"), conn=conn)
            assert resp.status_code in (200, 303)
        assert db.get_task_completion(conn, "h1", clock.today().isoformat()) is not None

    def test_a_plain_task_is_refused(self, conn):
        _seed_task(conn, "t1")
        assert tasks_router.mark_habit_today_done("t1", _request("/tasks/t1"), conn=conn).status_code == 404
