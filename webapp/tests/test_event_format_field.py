"""Tests for "Event format for simple events" (plans/open.md, small,
2026-08-15): `_event_form_fields.html` gained a Format field (In person /
Online) that reveals only Location or only Meeting URL, instead of always
showing both. Format has no backing column -- it's derived from which of
`events.location`/`events.meeting_url` already has a value, so these tests
check the rendered markup (which radio is `checked`, which field carries
the hidden-by-default class) rather than any new DB field. The actual
show/hide is plain CSS (style.css's `#event-form:has(...)` rules); the
value-clearing-on-switch behavior lives in static/event_format_toggle.js
and is covered structurally alongside sw.js's precache list in
test_pwa_shell.py's convention, plus a source-shape check here.

2026-09-03 direct feedback (Format toggle read as "cramped between icons
and text... no clear 'not one of these' state"): the control is now built
on the app's existing tile/card picker pattern (.tile-select/.tile-option)
instead of the cramped .segmented/.seg-btn pill row, and "neither picked"
is now a real, explicitly-selectable third radio (`event_format_none`)
rather than just both other radios sitting unchecked. The original two
ids/wrapper class are unchanged so the pre-existing tests below (written
against `.segmented`/`.seg-btn`-era markup, but only ever asserting id
strings and `checked`/not-`checked`, never the class names) still hold.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router

_STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "static"
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "templates"


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


class TestFormatFieldMarkup:
    def test_new_event_form_has_format_field_with_neither_radio_checked(self, conn):
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        body = resp.body.decode()
        assert 'id="event_format_in_person"' in body
        assert 'id="event_format_online"' in body
        # Brand-new event: nothing set yet, so neither radio is checked --
        # both Location and Meeting URL stay hidden until a Format is
        # actually picked.
        in_person_tag = body.split('id="event_format_in_person"')[1].split(">")[0]
        online_tag = body.split('id="event_format_online"')[1].split(">")[0]
        assert "checked" not in in_person_tag
        assert "checked" not in online_tag

    def test_location_and_meeting_fields_carry_the_hidden_by_default_classes(self, conn):
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        body = resp.body.decode()
        assert "field-format-location" in body
        assert "field-format-meeting" in body

    def test_edit_form_with_only_location_set_checks_in_person(self, conn):
        _seed_event(conn, "e1", location="Room 204")
        resp = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn)
        body = resp.body.decode()
        in_person_tag = body.split('id="event_format_in_person"')[1].split(">")[0]
        online_tag = body.split('id="event_format_online"')[1].split(">")[0]
        assert "checked" in in_person_tag
        assert "checked" not in online_tag

    def test_edit_form_with_only_meeting_url_set_checks_online(self, conn):
        _seed_event(conn, "e2", meeting_url="https://meet.example.com/abc123")
        resp = calendar_router.edit_event_form("e2", _request("/events/e2/edit"), conn=conn)
        body = resp.body.decode()
        in_person_tag = body.split('id="event_format_in_person"')[1].split(">")[0]
        online_tag = body.split('id="event_format_online"')[1].split(">")[0]
        assert "checked" not in in_person_tag
        assert "checked" in online_tag

    def test_edit_form_with_neither_set_checks_neither(self, conn):
        _seed_event(conn, "e3")
        resp = calendar_router.edit_event_form("e3", _request("/events/e3/edit"), conn=conn)
        body = resp.body.decode()
        in_person_tag = body.split('id="event_format_in_person"')[1].split(">")[0]
        online_tag = body.split('id="event_format_online"')[1].split(">")[0]
        assert "checked" not in in_person_tag
        assert "checked" not in online_tag

    def test_edit_form_with_both_set_prefers_in_person(self, conn):
        # Legacy data predating this field (both columns non-empty) -- no
        # real "both" state in the new model, so Location/In person wins
        # the tie, documented in _event_form_fields.html's own comment.
        _seed_event(
            conn, "e4", location="Room 204", meeting_url="https://meet.example.com/abc123"
        )
        resp = calendar_router.edit_event_form("e4", _request("/events/e4/edit"), conn=conn)
        body = resp.body.decode()
        in_person_tag = body.split('id="event_format_in_person"')[1].split(">")[0]
        online_tag = body.split('id="event_format_online"')[1].split(">")[0]
        assert "checked" in in_person_tag
        assert "checked" not in online_tag

    def test_quick_add_event_tab_also_gets_the_format_field(self, conn):
        from src.routers import dashboard as dashboard_router

        resp = dashboard_router.quick_add_form(_request("/quick/add"), conn=conn)
        body = resp.body.decode()
        assert 'id="event_format_in_person"' in body
        assert 'id="event_format_online"' in body


class TestFormatFieldNoneOption:
    """2026-09-03: "neither picked" is now a real third radio,
    `event_format_none`, rather than an implicit state -- checked whenever
    neither Location nor Meeting URL has a value."""

    def _none_tag(self, body: str) -> str:
        return body.split('id="event_format_none"')[1].split(">")[0]

    def test_new_event_form_checks_none(self, conn):
        resp = calendar_router.new_event_form(_request("/events/new"), conn=conn)
        body = resp.body.decode()
        assert 'id="event_format_none"' in body
        assert "checked" in self._none_tag(body)

    def test_edit_form_with_neither_set_checks_none(self, conn):
        _seed_event(conn, "e3")
        resp = calendar_router.edit_event_form("e3", _request("/events/e3/edit"), conn=conn)
        body = resp.body.decode()
        assert "checked" in self._none_tag(body)

    def test_edit_form_with_location_set_does_not_check_none(self, conn):
        _seed_event(conn, "e1", location="Room 204")
        resp = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn)
        body = resp.body.decode()
        assert "checked" not in self._none_tag(body)

    def test_edit_form_with_meeting_set_does_not_check_none(self, conn):
        _seed_event(conn, "e2", meeting_url="https://meet.example.com/abc123")
        resp = calendar_router.edit_event_form("e2", _request("/events/e2/edit"), conn=conn)
        body = resp.body.decode()
        assert "checked" not in self._none_tag(body)


class TestFormatFieldDoesNotChangeSavePath:
    def test_create_and_update_event_still_only_take_location_and_meeting_url(self, conn):
        # event_format is a pure client-side/derived field -- create_event/
        # update_event never gained a matching parameter, and an unknown
        # posted field is silently ignored by FastAPI's Form(...) params.
        import inspect

        create_params = inspect.signature(calendar_router.create_event).parameters
        update_params = inspect.signature(calendar_router.update_event).parameters
        assert "event_format" not in create_params
        assert "event_format" not in update_params
        assert "location" in create_params and "meeting_url" in create_params
        assert "location" in update_params and "meeting_url" in update_params


class TestFormatToggleScript:
    def test_event_format_toggle_js_exists_and_defines_the_expected_api(self):
        script = (_STATIC_DIR / "event_format_toggle.js").read_text()
        assert "CCEventFormatToggle" in script
        assert "event-format-segmented" in script

    def test_base_html_loads_the_script_globally(self):
        html = (_TEMPLATES_DIR / "base.html").read_text()
        assert "event_format_toggle.js" in html

    def test_modal_js_reinits_the_toggle_on_injected_content(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert "CCEventFormatToggle" in script

    def test_precache_list_includes_the_format_toggle_script(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert "/static/event_format_toggle.js" in script


class TestFormatFieldCss:
    def test_style_css_hides_both_fields_by_default_and_reveals_on_check(self):
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".field.field-format-location,\n.field.field-format-meeting{display:none;}" in css
        assert "#event-form:has(#event_format_in_person:checked) .field-format-location{display:flex;}" in css
        assert "#event-form:has(#event_format_online:checked) .field-format-meeting{display:flex;}" in css
