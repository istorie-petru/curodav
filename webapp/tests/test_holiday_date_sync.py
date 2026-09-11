"""Tests for the Holiday Add/Edit modal's Start/End date auto-sync
(documentation/plans/audit-fixes-2.1.md, 2026-09-11 direct request):
"While adding a hollday, in the specific modal window, after setting
either the start and end date, the other one should be automatically set
the same. After the initial set both can be changed without any sync
between them. This is only to make one day hollyday easier to add."

`holiday_edit_modal.html`'s Start/End fields are two independent
`_datetime_picker.html` instances (`date_from`/`date_to`, mode="date"),
each firing a plain `change` event on its own hidden input when a day is
picked (datetime_picker.js's commitChange()) with no built-in awareness of
the other field. The actual sync behavior lives in the new
static/holiday_date_sync.js, which listens for that change and -- only
when the *other* field is still empty -- fills it via a small
`dtpSetDate` hook datetime_picker.js's enhance() now exposes on each
`.dtp` container. Same "check the rendered markup / script wiring
structurally" convention test_event_format_field.py's
TestFormatToggleScript uses for its own client-side-only behavior --
there's no server-side field to assert against, `date_from`/`date_to`
already round-tripped through create_holiday/update_holiday before this
slice."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import settings as settings_router

_STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "static"
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "templates"


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _request(path="/"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


class TestHolidayModalDateFieldMarkup:
    def test_new_holiday_modal_has_both_date_pickers_in_one_form(self, conn):
        resp = settings_router.new_holiday_modal(_request("/settings/holidays/new"), conn=conn)
        body = resp.body.decode()
        assert 'id="holiday-form"' in body
        assert 'name="date_from"' in body
        assert 'name="date_to"' in body
        assert 'data-dtp-mode="date"' in body

    def test_edit_holiday_modal_has_both_date_pickers(self, conn):
        db.upsert_holiday(conn, {
            "uid": "h1", "label": "Test Holiday", "calendar_name": "Default",
            "date_from": "2026-12-25", "date_to": "2026-12-25",
        })
        resp = settings_router.edit_holiday_modal("h1", _request("/settings/holidays/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'id="holiday-form"' in body
        assert 'name="date_from"' in body
        assert 'name="date_to"' in body


class TestHolidayDateSyncScript:
    def test_script_exists_and_defines_the_expected_api(self):
        script = (_STATIC_DIR / "holiday_date_sync.js").read_text()
        assert "CCHolidayDateSync" in script
        assert "holiday-form" in script
        assert 'name="date_from"' in script
        assert 'name="date_to"' in script
        assert "dtpSetDate" in script

    def test_only_fills_the_other_field_when_it_is_empty(self):
        # Structural guard against regressing the "after the initial set
        # both can be changed without any sync between them" half of the
        # request -- both change listeners must gate on the *other*
        # input's value being falsy before calling dtpSetDate.
        script = (_STATIC_DIR / "holiday_date_sync.js").read_text()
        assert "!toInput.value" in script
        assert "!fromInput.value" in script

    def test_base_html_loads_the_script_globally(self):
        html = (_TEMPLATES_DIR / "base.html").read_text()
        assert "holiday_date_sync.js" in html

    def test_modal_js_reinits_the_sync_on_injected_content(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert "CCHolidayDateSync" in script


class TestDatetimePickerDateModeSetHook:
    def test_datetime_picker_js_exposes_a_set_date_hook_for_date_mode(self):
        script = (_STATIC_DIR / "datetime_picker.js").read_text()
        assert "dtpSetDate" in script
        assert 'mode === "date"' in script
