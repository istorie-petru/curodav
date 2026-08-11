"""Tests for the 2026-08-08 view<->edit merge -- the event/task/contact
modals' detail views and edit forms are now one continuous dialog:

1. Both states share the same footer, `_modal_footer.html` (a ghost
   back/cancel link on the left, the demoted Delete text-link, and the
   primary action -- "Edit" on the view, "Save" on the form -- on the
   right), instead of each state hand-rolling its own action bar. The
   edit forms give up their old standalone footer markup (including the
   loud filled-red `.btn.danger` Delete) for this one partial.

2. Every one of the six modal templates (event/task/contact detail +
   form) marks its `#modal-target` with `modal-stable-height`, and
   static/modal.js turns that marker into an `is-stable-height` class on
   the dialog -- the CSS locks the dialog to one fixed size for the pair,
   and toggling `.is-swapped` plays a subtle cross-fade instead of a hard
   content swap when navigating between the two states."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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


class TestSharedFooterPartial:
    """All six modal templates render through the one `_modal_footer.html`
    partial, and each rendered page has exactly ONE `.modal-footer` div
    (the partial's own -- the templates no longer wrap it in their own)."""

    VIEWS = {
        "event": lambda c, u: calendar_router.event_detail(u, _request(f"/events/{u}"), conn=c),
        "task": lambda c, u: tasks_router.task_detail(u, _request(f"/tasks/{u}"), conn=c),
        "contact": lambda c, u: contacts_router.contact_detail(u, _request(f"/contacts/{u}"), conn=c),
    }
    FORMS = {
        "event": lambda c, u: calendar_router.edit_event_form(u, _request(f"/events/{u}/edit"), conn=c),
        "task": lambda c, u: tasks_router.edit_task_form(u, _request(f"/tasks/{u}/edit"), conn=c),
        "contact": lambda c, u: contacts_router.edit_contact_form(u, _request(f"/contacts/{u}/edit"), conn=c),
    }

    def test_every_view_and_form_renders_exactly_one_footer(self, conn):
        for name, seed, views, forms in (
            ("event", _seed_event, self.VIEWS["event"], self.FORMS["event"]),
            ("task", _seed_task, self.VIEWS["task"], self.FORMS["task"]),
            ("contact", _seed_contact, self.VIEWS["contact"], self.FORMS["contact"]),
        ):
            seed(conn, f"{name}1")
            for label, fn in (("view", views), ("form", forms)):
                body = fn(conn, f"{name}1").body.decode()
                # The base.html modal shell (its own empty footer div, plus
                # the overlay) comes after the content block, so scope the
                # count to the fragment itself, from #modal-target up to
                # where the shell begins.
                fragment = body[body.index('id="modal-target"'):body.index('id="modal-overlay"')]
                assert fragment.count('class="modal-footer"') == 1, (name, label)

    def test_shared_footer_ghost_back_link_and_primary_action(self, conn):
        _seed_event(conn, "e1")
        view = self.VIEWS["event"](conn, "e1").body.decode()
        form = self.FORMS["event"](conn, "e1").body.decode()
        # Both states carry the ghost back link and a primary action.
        for body in (view, form):
            assert 'class="btn ghost"' in body
        # View's primary is an Edit *link* into the edit form (data-modal),
        # the form's primary is a Save *button* tied back to its <form>.
        assert 'href="/events/e1/edit"' in view
        assert 'form="event-form"' in form
        assert "> Save</a>" not in view  # the view's primary is Edit, not Save

    def test_edit_cancel_returns_to_the_view_modal_not_close(self, conn):
        """2026-08-08 direct feedback: on an edit form, the footer Cancel
        goes BACK to the detail view modal (a data-modal link into the
        view URL), while the modal's X is the only way to fully close."""
        _seed_event(conn, "e1")
        _seed_task(conn, "t1")
        _seed_contact(conn, "c1")
        cases = [
            (self.FORMS["event"](conn, "e1").body.decode(), "/events/e1"),
            (self.FORMS["task"](conn, "t1").body.decode(), "/tasks/t1"),
            (self.FORMS["contact"](conn, "c1").body.decode(), "/contacts/c1"),
        ]
        for body, view_url in cases:
            # The back link is a data-modal link to the detail view, not a
            # data-modal-cancel that closes the window.
            ghost = body.index('class="btn ghost"')
            back = body[body.rfind("<a ", 0, ghost):body.index("</a>", ghost)]
            assert 'data-modal-cancel' not in back
            assert f'href="{view_url}"' in back
            assert "> Cancel</a>" in body

    def test_new_form_cancel_still_closes_via_data_modal_cancel(self, conn):
        # A brand-new object has no detail view to return to, so its Cancel
        # stays a plain data-modal-cancel close.
        for body in (
            calendar_router.new_event_form(_request("/events/new"), conn=conn).body.decode(),
            tasks_router.new_task_form(_request("/tasks/new"), conn=conn).body.decode(),
            contacts_router.new_contact_form(_request("/contacts/new"), conn=conn).body.decode(),
        ):
            ghost = body.index('class="btn ghost"')
            back = body[body.rfind("<a ", 0, ghost):body.index("</a>", ghost)]
            assert "data-modal-cancel" in back
            assert "data-modal>" not in back

    def test_delete_only_appears_in_footer_presence(self, conn):
        # The edit forms no longer render their own filled-red delete; the
        # shared partial's demoted text-link is the only delete affordance,
        # and it exists only where the template opted in (event/task, not
        # contact).
        _seed_task(conn, "t1")
        body = self.FORMS["task"](conn, "t1").body.decode()
        assert 'class="detail-delete-link"' in body
        assert 'class="btn danger"' not in body
        _seed_contact(conn, "c1")
        body = self.FORMS["contact"](conn, "c1").body.decode()
        assert "/delete" not in body


class TestStableHeightMarker:
    """The view/edit pair marks `#modal-target` with `modal-stable-height`
    so static/modal.js can lock the dialog to one size across both."""

    def test_all_six_templates_mark_their_modal_target(self, conn):
        for name, seed, views, forms in (
            ("event", _seed_event, TestSharedFooterPartial.VIEWS["event"], TestSharedFooterPartial.FORMS["event"]),
            ("task", _seed_task, TestSharedFooterPartial.VIEWS["task"], TestSharedFooterPartial.FORMS["task"]),
            ("contact", _seed_contact, TestSharedFooterPartial.VIEWS["contact"], TestSharedFooterPartial.FORMS["contact"]),
        ):
            seed(conn, f"{name}1")
            for label, fn in (("view", views), ("form", forms)):
                body = fn(conn, f"{name}1").body.decode()
                assert 'id="modal-target" class="modal-stable-height"' in body, (name, label)

    def test_modal_js_toggles_stable_height_and_swap_animation(self):
        js_path = Path(__file__).resolve().parents[1] / "src" / "static" / "modal.js"
        js = js_path.read_text(encoding="utf-8")
        for expected in [
            "function stabilizeHeight(fragment)",
            "modal-stable-height",
            'is-stable-height',
            "function animateContentSwap()",
            "animateContentSwap()",
            "is-swapped",
            "const wasOpen = overlay.classList.contains(\"is-open\")",
        ]:
            assert expected in js, expected

    def test_css_locks_stable_height_and_defines_swap_keyframes(self):
        css_path = Path(__file__).resolve().parents[1] / "src" / "static" / "style.css"
        css = css_path.read_text(encoding="utf-8")
        assert ".modal.is-stable-height{" in css
        assert "@keyframes cc-modal-swap-in" in css
        assert ".modal.is-swapped{" in css
