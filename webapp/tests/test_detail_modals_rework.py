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

3. The body is one elevated tonal `.detail-card` -- with a colored left
   accent following the entity's identity color via `--detail-accent` --
   holding the 2-column `.detail-meta-grid`, whose values use the crisp
   `.detail-meta-value` typography.

4. The old filled-red `.btn.danger` Delete is demoted to a quiet
   `.detail-delete-link` text-link in the footer, letting the primary
   `.btn.primary` Edit action take center stage as the logical next step.

5. contact_detail.html drops its one-off `.detail-kv` <table> for the same
   detail-meta-grid every other detail view uses."""

from __future__ import annotations

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
    """The header leads with a big bold title plus a color-coded dot (or
    the contact's avatar), so the entity is identified at a glance."""

    def test_event_identity_dot_uses_calendar_color(self, conn):
        _seed_event(conn, "e1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-identity-dot cal-blue"' in body
        assert 'class="detail-title"' in body

    def test_event_identity_dot_follows_a_label_color(self, conn):
        # An event's calendar_color is its first label's color -- a red
        # label must drive both the identity dot and the card accent red.
        _seed_event(conn, "e1")
        db.upsert_label_config(conn, {"name": "Work", "color": "red"})
        db.set_object_labels(conn, "event", "e1", ["Work"])
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-identity-dot cal-red"' in body
        assert "--detail-accent: var(--cal-accent-red)" in body

    def test_task_identity_dot_uses_status_color(self, conn):
        _seed_task(conn, "t1", status="in_progress")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert 'class="detail-identity-dot cal-orange"' in body
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
        assert 'class="avatar-circle avatar-large"' in body
        assert "Ada Lovelace" in body
        assert "Analytical Engines" in body
        assert 'class="detail-heading-sub"' in body


class TestDetailCardAndMetaGrid:
    """The body is an elevated tonal .detail-card with a colored left
    accent, a 2-column meta grid, and crisp value typography."""

    def test_event_card_has_calendar_accent(self, conn):
        _seed_event(conn, "e1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-card"' in body
        assert "--detail-accent: var(--cal-accent-blue)" in body
        assert 'class="detail-meta-value"' in body

    def test_task_card_has_status_accent(self, conn):
        _seed_task(conn, "t1", status="in_progress")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert "--detail-accent: var(--cal-accent-orange)" in body
        assert 'class="detail-meta-value"' in body

    def test_contact_uses_the_shared_meta_grid_not_the_old_table(self, conn):
        _seed_contact(conn, "c1", phone="+123", email="a@example.com", address="1 St")
        body = contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn).body.decode()
        assert 'class="detail-card"' in body
        assert 'class="detail-meta-grid"' in body
        assert 'class="detail-meta-value"' in body
        assert '<table class="detail-kv">' not in body

    def test_task_relations_card_is_a_second_detail_card(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert body.count('class="detail-card') == 2
        # The relations picker trigger + its hidden submit form (1.2 side
        # work: replaces the old inline <select> add-row) are still wired
        # for in-place refresh (data-modal-keep-open) inside the modal.
        assert "data-relations-picker" in body
        assert 'class="relations-hidden-form"' in body
        assert "data-modal-keep-open" in body


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
        delete_pos = _index(body, 'class="detail-delete-link"')
        edit_pos = _index(body, 'class="btn primary"')
        done_pos = _index(body, "> Done</a>")
        assert delete_pos > footer_pos
        assert edit_pos > footer_pos
        assert done_pos > footer_pos
        # Edit (the primary action) comes after the demoted Delete link.
        assert edit_pos > delete_pos

    def test_task_delete_demoted_and_edit_primary(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        footer_pos = self._footer_pos(body)
        assert 'class="btn danger"' not in body
        assert _index(body, 'class="detail-delete-link"') > footer_pos
        assert _index(body, 'class="btn primary"') > footer_pos
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
        assert _index(body, 'class="detail-delete-link"') > footer_pos

    def test_contact_delete_demoted_and_edit_primary(self, conn):
        _seed_contact(conn, "c1")
        body = contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn).body.decode()
        footer_pos = self._footer_pos(body)
        assert 'class="btn danger"' not in body
        assert _index(body, 'class="detail-delete-link"') > footer_pos
        assert _index(body, 'class="btn primary"') > footer_pos
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
