"""Tests for schedule-class form input rework (Phases E and the 2026-08-08
promotion to the app-wide single-select dropdown): task Priority and
schedule class Day/Parity/Class type. Phase E first converted these from
plain `<select>`s into the `.segmented`/`.seg-btn` radio-styled control
(widget builder View/Range); the 2026-08-08 follow-up replaced the class
form's segmented controls and native `<select>`s with the shared
`_widget_list_multiselect.html` single-select dropdowns.

Class type is the special case (§3 of modal-input-design.md): a dropdown
pre-populated with this user's own already-used class_type values
(db.list_schedule_class_types, queried not hardcoded) plus a "+ Other"
option that reveals a plain text fallback via the same `:has()`
progressive-disclosure trick the Professor field's "+ Add new professor..."
reveal uses in this exact template.

These tests confirm: the markup is a real radio group (no-JS-safe), the
stored int/string values are unchanged from what the old `<select>`s
produced, and an existing class_type value that's since fallen out of the
distinct-values list still round-trips instead of being silently dropped.
"""

from __future__ import annotations

import re

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import schedule as schedule_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    from starlette.requests import Request

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



# --------------------------------------------------------------------- #
# Task Priority
# --------------------------------------------------------------------- #


class TestTaskPrioritySegmented:
    # 2026-08-08 follow-up ("rework Priority/Status/Recurrence to look the
    # same as Range/View/Labels") -- Priority moved again, this time from
    # the plain `<select>` the 2026-08-07 pass above put it in, to the same
    # single-mode _widget_list_multiselect.html panel View/Range/Labels
    # already share (see routers/tasks.py's PRIORITY_ITEMS). These tests
    # now assert on that markup instead of `<option>`.
    def test_new_task_form_renders_priority_multiselect(self, conn):
        resp = tasks_router.new_task_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'data-ms-label="priority"' in body
        assert 'name="priority" value=""' in body
        assert 'name="priority" value="1"' in body
        assert 'name="priority" value="4"' in body

    def test_creating_a_task_with_each_priority_stores_the_right_int(self, conn):
        for value in ["1", "2", "3", "4"]:
            tasks_router.create_task(
                title=f"Task {value}",
                description="",
                due_at="",
                priority=value,
                status="active",
                tags="",
                tags_labels=[],
                recurrence="",
                parent_uid="",
                conn=conn,
            )
        tasks = db.list_tasks(conn)
        stored = {t["title"]: t["priority"] for t in tasks}
        assert stored["Task 1"] == 1
        assert stored["Task 2"] == 2
        assert stored["Task 3"] == 3
        assert stored["Task 4"] == 4

    def test_creating_a_task_with_none_priority_stores_null(self, conn):
        tasks_router.create_task(
            title="No priority",
            description="",
            due_at="",
            priority="",
            status="active",
            tags="",
            tags_labels=[],
            recurrence="",
            parent_uid="",
            conn=conn,
        )
        tasks = db.list_tasks(conn)
        assert tasks[0]["priority"] is None

    def test_editing_a_task_preserves_its_priority_as_checked(self, conn):
        now = _now()
        db.upsert_task(
            conn,
            {
                "uid": "t1", "title": "X", "description": "", "due_at": None, "start_at": None,
                "priority": 2, "status": "active", "progress": 0, "tags": [], "parent_uid": None,
                "recurrence": None, "created_at": now, "updated_at": now,
            },
        )
        resp = tasks_router.edit_task_form("t1", _request(), conn=conn)
        body = resp.body.decode()
        assert 'name="priority" value="2"' in body
        # radio, not <select>/<option> any more -- confirm it's actually
        # checked, not just present in the options list.
        import re

        m = re.search(r'<input type="radio" name="priority" value="2"[^>]*>', body)
        assert m and "checked" in m.group(0)


# --------------------------------------------------------------------- #
# Schedule class Day / Parity
# --------------------------------------------------------------------- #


def _seed_class(conn, uid="c1", **overrides):
    now = _now()
    row = {
        "uid": uid, "day": "Monday", "start_time": "09:00", "end_time": "10:00",
        "name": "Algorithms", "acronym": "ALG", "class_type": "Course", "professor": "",
        "professor_contact_uid": None, "room": "", "credits": 6, "parity": "all",
        "enrolled": True, "event_uid": None, "created_at": now, "updated_at": now,
    }
    row.update(overrides)
    db.upsert_schedule_class(conn, row)
    return row


class TestScheduleClassDayParitySegmented:
    def test_new_class_form_renders_single_select_day_and_parity_dropdowns(self, conn):
        # 2026-08-08: Day/Week were promoted from the Phase E segmented
        # controls to the app-wide single-select dropdown
        # (_widget_list_multiselect.html) -- same radio form fields, so the
        # submit values are unchanged; the markup is now the shared
        # .multiselect trigger+panel contract.
        resp = schedule_router.new_class_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'multiselect widget-list-multiselect' in body
        assert 'data-ms-mode="single"' in body
        assert 'name="day" value="Monday"' in body
        assert 'name="day" value="Sunday"' in body
        assert 'name="parity" value="all"' in body
        assert 'name="parity" value="odd"' in body
        assert 'name="parity" value="even"' in body

    def test_creating_a_class_with_each_day_and_parity_stores_the_right_value(self, conn):
        schedule_router.create_class(
            day="Wednesday", start_time="10:00", end_time="11:30", name="Algorithms",
            acronym="ALG", class_type_select="Course", class_type_other="",
            professor_select="", professor_new="",
            room="", credits="6", parity="odd", enrolled="on", project_uid="", conn=conn,
        )
        classes = db.list_schedule_classes(conn)
        assert classes[0]["day"] == "Wednesday"
        assert classes[0]["parity"] == "odd"


# --------------------------------------------------------------------- #
# Schedule class Class type -- segmented + "+ Other" text fallback
# --------------------------------------------------------------------- #


class TestScheduleClassTypeSegmentedWithOther:
    def test_new_class_form_lists_distinct_class_types_already_in_use(self, conn):
        _seed_class(conn, "c1", class_type="Seminar")
        _seed_class(conn, "c2", class_type="Lab")
        _seed_class(conn, "c3", class_type="Seminar")  # duplicate, should collapse
        resp = schedule_router.new_class_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'class-type-field' in body
        assert 'name="class_type_select" value="Seminar"' in body
        assert 'name="class_type_select" value="Lab"' in body
        assert body.count('name="class_type_select" value="Seminar"') == 1
        assert 'name="class_type_select" value="__other__"' in body
        assert '+ Other' in body

    def test_picking_an_existing_class_type_stores_that_string(self, conn):
        _seed_class(conn, "c1", class_type="Seminar")
        schedule_router.create_class(
            day="Tuesday", start_time="08:00", end_time="09:30", name="New course",
            acronym="", class_type_select="Seminar", class_type_other="",
            professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="", project_uid="", conn=conn,
        )
        classes = {c["name"]: c for c in db.list_schedule_classes(conn)}
        assert classes["New course"]["class_type"] == "Seminar"

    def test_picking_other_and_typing_a_new_class_type_stores_the_new_string(self, conn):
        _seed_class(conn, "c1", class_type="Seminar")
        schedule_router.create_class(
            day="Tuesday", start_time="08:00", end_time="09:30", name="Brand new type course",
            acronym="", class_type_select="__other__", class_type_other="Workshop",
            professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="", project_uid="", conn=conn,
        )
        classes = {c["name"]: c for c in db.list_schedule_classes(conn)}
        assert classes["Brand new type course"]["class_type"] == "Workshop"
        # The newly-typed value now shows up as an existing option next time.
        resp = schedule_router.new_class_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'name="class_type_select" value="Workshop"' in body

    def test_none_option_clears_class_type(self, conn):
        _seed_class(conn, "c1", class_type="Seminar")
        schedule_router.create_class(
            day="Tuesday", start_time="08:00", end_time="09:30", name="Untyped course",
            acronym="", class_type_select="", class_type_other="",
            professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="", project_uid="", conn=conn,
        )
        classes = {c["name"]: c for c in db.list_schedule_classes(conn)}
        assert classes["Untyped course"]["class_type"] is None

    def test_editing_a_class_whose_class_type_is_not_in_the_distinct_list_still_shows_it(self, conn, monkeypatch):
        # Simulates stale/edge-case data: a class with a class_type that
        # (for whatever reason) is no longer among the distinct values
        # queried across the user's classes -- since that query naturally
        # includes the class's own current value in the common case,
        # monkeypatch it here to force the edge case the template's
        # defensive `class_type_is_other` check exists to handle.
        _seed_class(conn, "c1", class_type="Colloquium")
        monkeypatch.setattr(db, "list_schedule_class_types", lambda conn: ["Lab", "Seminar"])
        resp = schedule_router.edit_class_form("c1", _request(), conn=conn)
        body = resp.body.decode()
        # "+ Other" should be pre-selected and pre-filled with the existing
        # value, not silently dropped -- mirrors how "+ Add new professor..."
        # pre-fills professor_new for a professor without a linked contact.
        assert re.search(r'name="class_type_select"\s+value="__other__"[^>]*\bchecked\b', body)
        assert 'name="class_type_other" class="class-type-other-input"' in body
        assert 'value="Colloquium"' in body
        # And the stale value must NOT also be rendered as a regular
        # (non-checked) segmented option -- it only shows up via "+ Other".
        assert 'name="class_type_select" value="Colloquium"' not in body

    def test_editing_that_stale_class_round_trips_unchanged_if_resubmitted_as_is(self, conn):
        _seed_class(conn, "c1", class_type="Colloquium")
        schedule_router.update_class(
            uid="c1", day="Monday", start_time="09:00", end_time="10:00", name="Algorithms",
            acronym="ALG", class_type_select="__other__", class_type_other="Colloquium",
            professor_select="", professor_new="",
            room="", credits="6", parity="all", enrolled="on", project_uid="", conn=conn,
        )
        updated = db.get_schedule_class(conn, "c1")
        assert updated["class_type"] == "Colloquium"
