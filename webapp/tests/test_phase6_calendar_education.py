"""Phase 6 (command-center-rework) -- education calendar + per-project
"next occurrence". The calendar, when filtered to an education
(schedule-module) Space, renders a next-lecture badge strip computed off
the structured schedule data (parity + holiday-aware, via
schedule.next_occurrence); the project page's Course-info card shows a
per-class "Next: today / tomorrow / in N days" badge. Homework-deadline
overlays and project events already render on the calendar + project page
(respectively) from Phase 5/earlier work -- this file covers the new
badges only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, schedule
from src.routers import calendar as calendar_router
from src.routers import labels as labels_router
from src.routers import schedule as schedule_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/calendar"):
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


def _seed_education(conn, space_uid="edu"):
    """A Space label (generate_space=1) + one course label under it +
    schedule settings spanning today + one enrolled class carrying both
    labels directly. Returns the class event's uid. 1.6: a class is a real
    recurring event now (see schedule_router's module docstring) -- goes
    through the real create_class router path, tagged with the course
    label CS101 (already existing, so create_class doesn't auto-provision
    a second one) and then the Space label directly (auto-provision-only
    behavior, so added by hand here to match the old direct-tagging
    setup)."""
    db.upsert_label_config(conn, {"name": space_uid, "generate_space": 1, "color": "blue", "created_at": _now()})
    db.upsert_label_config(conn, {"name": "CS101", "parent_name": space_uid, "color": "blue", "created_at": _now()})
    db.save_schedule_settings(
        conn,
        {
            "semester_start": (date.today() - timedelta(days=40)).isoformat(),
            "semester_end": (date.today() + timedelta(days=200)).isoformat(),
            "credits_needed": 120,
            "reminder_minutes": 15,
        },
    )
    schedule_router.create_class(
        day="Wednesday", start_time="10:00", end_time="12:00", name="Algorithms",
        acronym="ALG", class_type_select="Course", class_type_other="",
        professor_select="__new__", professor_new="Dr. X",
        room="204", credits="6", parity="all", enrolled="on", project_uid="CS101", conn=conn,
    )
    cls_uid = db.list_schedule_class_events(conn)[0]["uid"]
    db.add_object_label(conn, "event", cls_uid, space_uid)
    return cls_uid


def _expected_next(cls_uid, conn):
    event = db.get_event(conn, cls_uid)
    return schedule.next_occurrence_for_event(event, date.today())


class TestEducationCalendarBadges:
    def test_month_view_with_education_space_lists_next_lectures(self, conn):
        cls_uid = _seed_education(conn)
        resp = calendar_router.month_view(_request(), label="edu", conn=conn)
        badges = resp.context["schedule_next_lectures"]
        assert len(badges) == 1
        badge = badges[0]
        assert badge["class"]["acronym"] == "ALG"
        assert badge["date"] == _expected_next(cls_uid, conn)
        assert badge["label"] in ("today", "tomorrow") or badge["label"].startswith("in ")
        body = resp.body.decode()
        assert "ALG" in body
        assert "Next lectures" in body

    def test_all_views_carry_the_badges(self, conn):
        # 2026-08-08: Agenda merged into Day and was then removed again
        # (routers/calendar.py's day_view) rather than having its own page
        # -- agenda_view is a redirect now, nothing to assert context on,
        # so Day (which already carries the same badges Month/Week do)
        # covers what this used to check for both.
        _seed_education(conn)
        views = [
            lambda: calendar_router.month_view(_request(), label="edu", conn=conn),
            lambda: calendar_router.week_view(_request(), label="edu", conn=conn),
            lambda: calendar_router.day_view(date.today().isoformat(), _request(), label="edu", conn=conn),
        ]
        for view in views:
            resp = view()
            assert len(resp.context["schedule_next_lectures"]) == 1

    def test_non_education_space_gets_no_badges(self, conn):
        # A plain (non-Space, generate_space=0) label with the same class
        # setup -- no education-module flag means no badges.
        db.upsert_label_config(conn, {"name": "Side", "generate_space": 0, "color": "blue", "created_at": _now()})
        schedule_router.create_class(
            day="Wednesday", start_time="10:00", end_time="12:00", name="Algorithms",
            acronym="ALG", class_type_select="Course", class_type_other="", professor_select="", professor_new="",
            room="", credits="6", parity="all", enrolled="on", project_uid="Side", conn=conn,
        )
        resp = calendar_router.month_view(_request(), label="Side", conn=conn)
        assert resp.context["schedule_next_lectures"] == []

    def test_no_space_filter_gets_no_badges(self, conn):
        _seed_education(conn)
        resp = calendar_router.month_view(_request(), conn=conn)
        assert resp.context["schedule_next_lectures"] == []


class TestProjectNextLecture:
    def test_project_detail_exposes_next_lecture_per_class(self, conn):
        cls_uid = _seed_education(conn)
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert resp.context["label"]["uid"] == "CS101"
        nxt = resp.context["class_next_lecture"][cls_uid]
        assert nxt["date"] == _expected_next(cls_uid, conn)
        assert nxt["label"] in ("today", "tomorrow") or nxt["label"].startswith("in ")
        body = resp.body.decode()
        assert "Next:" in body
        assert "ALG" in body

    def test_project_with_no_classes_has_no_badges(self, conn):
        db.upsert_label_config(conn, {"name": "Boring", "color": "blue", "created_at": _now()})
        resp = labels_router.label_detail("Boring", _request("/labels/Boring"), conn=conn)
        assert resp.context["class_next_lecture"] == {}