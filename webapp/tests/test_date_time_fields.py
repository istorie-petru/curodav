"""2026-09-26 (Peter's mockup): date and time fields -- a typed text box
with a small button that opens a calendar (date) or a time list (time);
a date field holds only a date, a time field only a time; the event form's
"Date & time" block has All day in its header, which only hides the time
boxes. Replaces _datetime_picker.html / datetime_picker.js everywhere."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db, deps
from src.routers import habits as habits_router
from src.routers import settings as settings_router
from src.routers import tasks as tasks_router

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _req(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b"",
                    "scheme": "http", "server": ("testserver", 80), "root_path": ""})


def _now():
    return datetime.now(timezone.utc).isoformat()


class TestFilter:
    @pytest.mark.parametrize("value,expected", [
        ("2026-09-26", "Sat, Sep 26, 2026"), ("2026-09-26T15:30", "Sat, Sep 26, 2026"),
        ("", ""), (None, ""), ("nope", ""),
    ])
    def test_dtf_date(self, value, expected):
        assert deps._dtf_date(value) == expected


class TestRendering:
    def test_event_form_has_the_mockup_block(self, conn):
        from src.routers import calendar as calendar_router

        body = calendar_router.new_event_form(_req("/events/new"), conn=conn).body.decode()
        assert 'class="dtr-title">Date &amp; time</span>' in body
        assert 'id="all_day" name="all_day"' in body
        assert body.count('data-dtf="date"') == 2 and body.count('data-dtf="time"') == 2
        assert 'type="date"' not in body and "data-dtp" not in body

    def test_task_form_dates_are_date_only(self, conn):
        body = tasks_router.new_task_form(_req("/tasks/new"), conn=conn).body.decode()
        assert body.count('data-dtf="date"') == 2 and 'data-dtf="time"' not in body
        assert 'name="start_at"' in body and 'name="due_at"' in body

    def test_tasks_table_inline_due_keeps_its_contract(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "Call", "description": "", "status": "active",
                              "due_at": "2026-10-02", "tags": [], "created_at": _now()})
        tpl = (SRC / "templates" / "_task_row.html").read_text()
        assert "input_class='inline-date'" in tpl and 'data-field="due_at"' in tpl

    def test_time_block_modal_has_two_time_fields(self, conn):
        body = settings_router.new_time_block_modal(_req("/settings/time-blocks/new"), kind="sleep", conn=conn).body.decode()
        assert body.count('data-dtf="time"') == 2
        assert 'name="start_time"' in body and 'name="end_time"' in body

    def test_habit_pauses_use_date_fields(self, conn):
        body = habits_router.pauses_modal(_req("/habits/pauses"), conn=conn).body.decode()
        assert 'type="date"' not in body and body.count('data-dtf="date"') == 2

    def test_old_picker_is_gone(self):
        assert not (SRC / "templates" / "_datetime_picker.html").exists()
        assert not (SRC / "static" / "datetime_picker.js").exists()
        base = (SRC / "templates" / "base.html").read_text()
        assert "date_time_fields.js" in base and "datetime_picker.js" not in base


_NODE = r"""
global.window = { addEventListener() {} };
global.document = { addEventListener() {}, body: {} };
global.HTMLFormElement = function () {};
global.Event = function () {};
eval(require("fs").readFileSync(process.argv[2], "utf8"));
const F = window.CCDateField;
const today = new Date();
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
const out = {
  dmY: F.parseDate("29/09/2023"), dots: F.parseDate("29.09.2023"), short: F.parseDate("1/2/24"),
  isoIn: F.parseDate("2023-09-29"), compact: F.parseDate("29092023"), noYear: F.parseDate("29/09"),
  bad: F.parseDate("31/02/2026"), junk: F.parseDate("banana"), empty: F.parseDate(""),
  display: F.parseDate("Sat, Sep 26, 2026"), today: F.parseDate("today") === iso(today),
  t1: F.parseTime("15:30"), t2: F.parseTime("1530"), t3: F.parseTime("3pm"), t4: F.parseTime("3:30 PM"),
  t5: F.parseTime("12am"), t6: F.parseTime("9"), t7: F.parseTime("25:00"), t8: F.parseTime("15.30"),
  fmt: F.fmtDate("2026-09-26"), year: today.getFullYear(),
};
console.log(JSON.stringify(out));
"""


def test_parsing_in_node(tmp_path):
    script = tmp_path / "run.js"
    script.write_text(_NODE)
    res = subprocess.run(["node", str(script), str(SRC / "static" / "date_time_fields.js")],
                         capture_output=True, text=True, check=True)
    r = json.loads(res.stdout)
    assert r["dmY"] == "2023-09-29" and r["dots"] == "2023-09-29" and r["short"] == "2024-02-01"
    assert r["isoIn"] == "2023-09-29" and r["compact"] == "2023-09-29"
    assert r["noYear"] == f"{r['year']}-09-29"
    assert r["bad"] is None and r["junk"] is None and r["empty"] == ""
    assert r["display"] == "2026-09-26" and r["today"] is True
    assert (r["t1"], r["t2"], r["t3"], r["t4"], r["t5"], r["t6"], r["t7"], r["t8"]) == (
        "15:30", "15:30", "15:00", "15:30", "00:00", "09:00", None, "15:30")
    assert r["fmt"] == "Sat, Sep 26, 2026"
