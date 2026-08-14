"""Tests for schedule-class form input rework (Phases E and the 2026-08-08
promotion to the app-wide single-select dropdown): task Importance/Urgency
(1.1, the two axes replacing the old WebDAV priority) and schedule class
Day/Parity/Class type. Phase E first converted these from
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
# Task Importance / Urgency
# --------------------------------------------------------------------- #


class TestTaskImportanceUrgencySegmented:
    # 2026-08-08 follow-up ("rework Priority/Status/Recurrence to look the
    # same as Range/View/Labels") -- the field moved again, this time from
    # the plain `<select>` the 2026-08-07 pass above put it in, to the same
    # single-mode _widget_list_multiselect.html panel View/Range/Labels
    # already share (see routers/tasks.py's IMPORTANCE_ITEMS/URGENCY_ITEMS).
    # 1.1 (virtual & derived states): the single Priority axis became two
    # independent 1-3 axes -- Importance and Urgency. These tests assert on
    # that markup instead of `<option>`.
    def test_new_task_form_renders_importance_and_urgency_multiselects(self, conn):
        resp = tasks_router.new_task_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'data-ms-label="importance"' in body
        assert 'name="importance" value=""' in body
        assert 'name="importance" value="1"' in body
        assert 'name="importance" value="3"' in body
        assert 'data-ms-label="urgency"' in body
        assert 'name="urgency" value=""' in body
        assert 'name="urgency" value="1"' in body
        assert 'name="urgency" value="3"' in body
        # No trace of the old single priority axis.
        assert 'name="priority"' not in body

    def test_creating_a_task_with_each_importance_and_urgency_stores_the_right_int(self, conn):
        for value in ["1", "2", "3"]:
            tasks_router.create_task(
                title=f"Task {value}",
                description="",
                due_at="",
                importance=value,
                urgency=value,
                status="active",
                tags="",
                tags_labels=[],
                recurrence="",
                conn=conn,
            )
        tasks = db.list_tasks(conn)
        stored = {t["title"]: (t["importance"], t["urgency"]) for t in tasks}
        assert stored["Task 1"] == (1, 1)
        assert stored["Task 2"] == (2, 2)
        assert stored["Task 3"] == (3, 3)

    def test_creating_a_task_with_none_importance_or_urgency_stores_null(self, conn):
        tasks_router.create_task(
            title="No axes",
            description="",
            due_at="",
            importance="",
            urgency="",
            status="active",
            tags="",
            tags_labels=[],
            recurrence="",
            conn=conn,
        )
        tasks = db.list_tasks(conn)
        assert tasks[0]["importance"] is None
        assert tasks[0]["urgency"] is None

    def test_axes_are_stored_independently(self, conn):
        tasks_router.create_task(
            title="Mixed",
            description="",
            due_at="",
            importance="3",
            urgency="1",
            status="active",
            tags="",
            tags_labels=[],
            recurrence="",
            conn=conn,
        )
        tasks = db.list_tasks(conn)
        assert tasks[0]["importance"] == 3
        assert tasks[0]["urgency"] == 1

    def test_editing_a_task_preserves_its_importance_and_urgency_as_checked(self, conn):
        now = _now()
        db.upsert_task(
            conn,
            {
                "uid": "t1", "title": "X", "description": "", "due_at": None, "start_at": None,
                "importance": 3, "urgency": 2, "status": "active", "progress": 0, "tags": [],
                "recurrence": None, "created_at": now, "updated_at": now,
            },
        )
        resp = tasks_router.edit_task_form("t1", _request(), conn=conn)
        body = resp.body.decode()
        assert 'name="importance" value="3"' in body
        assert 'name="urgency" value="2"' in body
        # radio, not <select>/<option> any more -- confirm they're actually
        # checked, not just present in the options list.
        m = re.search(r'<input type="radio" name="importance" value="3"[^>]*>', body)
        assert m and "checked" in m.group(0)
        m = re.search(r'<input type="radio" name="urgency" value="2"[^>]*>', body)
        assert m and "checked" in m.group(0)


# --------------------------------------------------------------------- #
# Schedule class Day / Parity
# --------------------------------------------------------------------- #


def _seed_class(conn, name="Algorithms", class_type="", **overrides):
    """1.6: a class is a real recurring event tagged with its course label
    now (see schedule_router's module docstring) -- goes through the real
    create_class router path (which auto-provisions a course label named
    after `name` when no project_uid is given, and writes acronym/type/
    credits/professor onto THAT label's label_config row, not the event)
    rather than a removed db.upsert_schedule_class call. Returns the
    enriched class dict (schedule_router._class_row shape, includes the
    real uid create_class minted)."""
    fields = {
        "day": "Monday", "start_time": "09:00", "end_time": "10:00",
        "name": name, "acronym": "ALG", "class_type_select": class_type, "class_type_other": "",
        "professor_select": "", "professor_new": "", "room": "", "credits": "6",
        "parity": "all", "enrolled": "on", "project_uid": "",
    }
    fields.update(overrides)
    schedule_router.create_class(conn=conn, **fields)
    event = next(e for e in db.list_schedule_class_events(conn) if e["title"] == name)
    return schedule_router._class_row(conn, event)


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
        events = db.list_schedule_class_events(conn)
        cls = schedule_router._class_row(conn, events[0])
        assert cls["day"] == "Wednesday"
        assert cls["parity"] == "odd"


# --------------------------------------------------------------------- #
# Schedule class Class type -- segmented + "+ Other" text fallback
# --------------------------------------------------------------------- #


class TestScheduleClassTypeSegmentedWithOther:
    def test_new_class_form_lists_distinct_class_types_already_in_use(self, conn):
        # Each class needs its own course (name) -- class_type is a
        # course-level fact now (label_config.course_type), so three
        # meetings of the *same* course would collapse onto one label/one
        # type, not exercise the dedup list this test is about.
        _seed_class(conn, name="Algorithms", class_type="Seminar")
        _seed_class(conn, name="Databases", class_type="Lab")
        _seed_class(conn, name="Compilers", class_type="Seminar")  # duplicate, should collapse
        resp = schedule_router.new_class_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'class-type-field' in body
        assert 'name="class_type_select" value="Seminar"' in body
        assert 'name="class_type_select" value="Lab"' in body
        assert body.count('name="class_type_select" value="Seminar"') == 1
        assert 'name="class_type_select" value="__other__"' in body
        assert '+ Other' in body

    def test_picking_an_existing_class_type_stores_that_string(self, conn):
        _seed_class(conn, name="Algorithms", class_type="Seminar")
        schedule_router.create_class(
            day="Tuesday", start_time="08:00", end_time="09:30", name="New course",
            acronym="", class_type_select="Seminar", class_type_other="",
            professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="", project_uid="", conn=conn,
        )
        assert db.get_label_config(conn, "New course")["course_type"] == "Seminar"

    def test_picking_other_and_typing_a_new_class_type_stores_the_new_string(self, conn):
        _seed_class(conn, name="Algorithms", class_type="Seminar")
        schedule_router.create_class(
            day="Tuesday", start_time="08:00", end_time="09:30", name="Brand new type course",
            acronym="", class_type_select="__other__", class_type_other="Workshop",
            professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="", project_uid="", conn=conn,
        )
        assert db.get_label_config(conn, "Brand new type course")["course_type"] == "Workshop"
        # The newly-typed value now shows up as an existing option next time.
        resp = schedule_router.new_class_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'name="class_type_select" value="Workshop"' in body

    def test_none_option_clears_class_type(self, conn):
        _seed_class(conn, name="Algorithms", class_type="Seminar")
        schedule_router.create_class(
            day="Tuesday", start_time="08:00", end_time="09:30", name="Untyped course",
            acronym="", class_type_select="", class_type_other="",
            professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="", project_uid="", conn=conn,
        )
        assert db.get_label_config(conn, "Untyped course")["course_type"] is None

    def test_editing_a_class_whose_class_type_is_not_in_the_distinct_list_still_shows_it(self, conn, monkeypatch):
        # Simulates stale/edge-case data: a class whose course_type (for
        # whatever reason) is no longer among the distinct values queried
        # across the user's own courses -- since that query naturally
        # includes the course's own current value in the common case,
        # monkeypatch it here to force the edge case the template's
        # defensive `class_type_is_other` check exists to handle.
        cls = _seed_class(conn, name="Algorithms", class_type="Colloquium")
        monkeypatch.setattr(db, "list_course_types", lambda conn: ["Lab", "Seminar"])
        resp = schedule_router.edit_class_form(cls["uid"], _request(), conn=conn)
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
        cls = _seed_class(conn, name="Algorithms", class_type="Colloquium")
        schedule_router.update_class(
            uid=cls["uid"], day="Monday", start_time="09:00", end_time="10:00", name="Algorithms",
            acronym="ALG", class_type_select="__other__", class_type_other="Colloquium",
            professor_select="", professor_new="",
            room="", credits="6", parity="all", enrolled="on", project_uid="Algorithms", conn=conn,
        )
        assert db.get_label_config(conn, "Algorithms")["course_type"] == "Colloquium"
