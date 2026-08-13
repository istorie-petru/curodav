"""1.3 (Project-enabled label stack) acceptance tests -- see
plans/open-priority.md § Project-enabled label stack and
plans/roadmap.md's 1.3 subsection. Covers: label_config's new is_project/
start_date/end_date/archived_at columns, the computed lifecycle
(db.project_status), the overlap rule (db.find_overlapping_project),
project_label_for's 1.3 supersession of the old generate_space=0
heuristic, and routers/projects.py's promote/dates/demote/archive actions
plus the Projects page's card data.

Work allocations and the project's own Tasks/Week Calendar views are 1.4's
job (not covered here) -- card progress is completed/total task count, the
interim proxy STATE.md's 1.3 breadcrumb calls for.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import projects as projects_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/projects", query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _task(conn, uid, tags, status="active", due_at=None):
    db.upsert_task(
        conn,
        {
            "uid": uid, "title": uid, "description": "", "status": status,
            "tags": tags, "created_at": _now(), "due_at": due_at,
        },
    )


# --------------------------------------------------------------------- #
# Schema / effective config
# --------------------------------------------------------------------- #


class TestLabelConfigProjectColumns:
    def test_defaults_are_not_a_project(self, conn):
        db.upsert_label_config(conn, {"name": "Plain", "created_at": _now()})
        cfg = db.effective_label_config(conn, "Plain")
        assert cfg["is_project"] is False
        assert cfg["start_date"] is None
        assert cfg["end_date"] is None
        assert cfg["archived_at"] is None

    def test_upsert_sets_project_fields(self, conn):
        db.upsert_label_config(
            conn,
            {"name": "Conf", "is_project": 1, "start_date": "2026-08-11", "end_date": "2026-10-13", "created_at": _now()},
        )
        cfg = db.effective_label_config(conn, "Conf")
        assert cfg["is_project"] is True
        assert cfg["start_date"] == "2026-08-11"
        assert cfg["end_date"] == "2026-10-13"

    def test_list_project_labels_only_returns_is_project(self, conn):
        db.upsert_label_config(conn, {"name": "Proj", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Space", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Plain", "created_at": _now()})
        assert [p["name"] for p in db.list_project_labels(conn)] == ["Proj"]


# --------------------------------------------------------------------- #
# Overlap rule
# --------------------------------------------------------------------- #


class TestOverlap:
    def test_no_conflict_when_no_other_projects(self, conn):
        assert db.find_overlapping_project(conn, "A", "2026-01-01", "2026-02-01") is None

    def test_overlapping_period_conflicts(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        conflict = db.find_overlapping_project(conn, "B", "2026-01-15", "2026-03-01")
        assert conflict is not None and conflict["name"] == "A"

    def test_adjacent_non_overlapping_period_is_fine(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        assert db.find_overlapping_project(conn, "B", "2026-02-02", "2026-03-01") is None

    def test_a_project_never_conflicts_with_itself(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        assert db.find_overlapping_project(conn, "A", "2026-01-10", "2026-02-10") is None

    def test_archived_projects_are_excluded_from_the_check(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        db.archive_project(conn, "A")
        assert db.find_overlapping_project(conn, "B", "2026-01-15", "2026-02-10") is None

    def test_missing_dates_never_conflict(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "created_at": _now()})
        assert db.find_overlapping_project(conn, "B", "2026-01-01", "2026-02-01") is None


# --------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------- #


class TestProjectStatus:
    def _cfg(self, conn, name="P", start="2026-01-01", end="2026-12-31"):
        db.upsert_label_config(conn, {"name": name, "is_project": 1, "start_date": start, "end_date": end, "created_at": _now()})
        return db.effective_label_config(conn, name)

    def test_no_tasks_is_open(self, conn):
        cfg = self._cfg(conn)
        assert db.project_status(conn, cfg) == "Open"

    def test_incomplete_task_is_open(self, conn):
        cfg = self._cfg(conn)
        _task(conn, "t1", ["P"], status="active")
        assert db.project_status(conn, cfg) == "Open"

    def test_all_completed_before_end_date_is_pending(self, conn):
        cfg = self._cfg(conn, end="2099-01-01")
        _task(conn, "t1", ["P"], status="done")
        assert db.project_status(conn, cfg, today=date(2026, 1, 1)) == "Pending"

    def test_all_completed_past_end_date_is_pending_archiving(self, conn):
        cfg = self._cfg(conn, end="2026-01-01")
        _task(conn, "t1", ["P"], status="done")
        assert db.project_status(conn, cfg, today=date(2026, 6, 1)) == "Pending Archiving"

    def test_archived_status_set_stays_archived_regardless_of_tasks(self, conn):
        cfg = self._cfg(conn)
        _task(conn, "t1", ["P"], status="active")
        db.archive_project(conn, "P")
        cfg = db.effective_label_config(conn, "P")
        assert db.project_status(conn, cfg) == "Archived"

    def test_end_date_passing_alone_does_not_archive(self, conn):
        # "The end date does not automatically archive a project."
        cfg = self._cfg(conn, end="2020-01-01")
        _task(conn, "t1", ["P"], status="active")
        assert db.project_status(conn, cfg, today=date(2026, 6, 1)) == "Open"

    def test_completing_all_tasks_does_not_silently_archive(self, conn):
        cfg = self._cfg(conn, end="2099-01-01")
        _task(conn, "t1", ["P"], status="done")
        assert db.project_status(conn, cfg, today=date(2026, 1, 1)) != "Archived"


# --------------------------------------------------------------------- #
# project_label_for supersession
# --------------------------------------------------------------------- #


class TestProjectLabelForSupersession:
    def test_is_project_label_wins_over_old_heuristic(self, conn):
        # Old heuristic: the first non-Space label wins alphabetically.
        # "Course" would win alphabetically over "Zeta" -- but Zeta is
        # explicitly is_project=1, so it must win now.
        db.upsert_label_config(conn, {"name": "Course", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Zeta", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        db.add_object_label(conn, "habit", "h1", "Course")
        db.add_object_label(conn, "habit", "h1", "Zeta")
        assert db.project_label_for(conn, "habit", "h1") == "Zeta"

    def test_falls_back_to_old_heuristic_when_nothing_is_project_enabled(self, conn):
        db.upsert_label_config(conn, {"name": "Space", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Course", "created_at": _now()})
        db.add_object_label(conn, "habit", "h1", "Space")
        db.add_object_label(conn, "habit", "h1", "Course")
        assert db.project_label_for(conn, "habit", "h1") == "Course"


# --------------------------------------------------------------------- #
# routers/projects.py
# --------------------------------------------------------------------- #


class TestPromoteDemoteArchive:
    def test_promote_sets_is_project_and_dates(self, conn):
        resp = projects_router.promote(name="Trip", start_date="2026-08-11", end_date="2026-10-13", confirm_overlap="", conn=conn)
        assert resp.status_code == 303
        cfg = db.effective_label_config(conn, "Trip")
        assert cfg["is_project"] is True
        assert cfg["start_date"] == "2026-08-11"

    def test_promote_with_overlap_redirects_without_saving(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        resp = projects_router.promote(name="B", start_date="2026-01-15", end_date="2026-03-01", confirm_overlap="", conn=conn)
        assert resp.status_code == 303
        assert "overlap=A" in resp.headers["location"]
        assert db.get_label_config(conn, "B") is None

    def test_promote_with_confirm_overlap_saves_anyway(self, conn):
        db.upsert_label_config(conn, {"name": "A", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        resp = projects_router.promote(name="B", start_date="2026-01-15", end_date="2026-03-01", confirm_overlap="1", conn=conn)
        assert resp.status_code == 303
        assert db.effective_label_config(conn, "B")["is_project"] is True

    def test_demote_clears_project_fields_but_keeps_label(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1, "start_date": "2026-08-11", "end_date": "2026-10-13", "created_at": _now()})
        db.add_object_label(conn, "task", "t1", "Trip")
        resp = projects_router.demote("Trip", conn=conn)
        assert resp.status_code == 303
        cfg = db.effective_label_config(conn, "Trip")
        assert cfg["is_project"] is False
        assert cfg["start_date"] is None
        # The label itself and its membership survive demotion.
        assert db.list_labels_for_object(conn, "task", "t1") == ["Trip"]

    def test_archive_sets_archived_at_and_status(self, conn):
        cfg_kwargs = {"name": "Trip", "is_project": 1, "start_date": "2026-01-01", "end_date": "2020-01-01", "created_at": _now()}
        db.upsert_label_config(conn, cfg_kwargs)
        resp = projects_router.archive("Trip", conn=conn)
        assert resp.status_code == 303
        cfg = db.effective_label_config(conn, "Trip")
        assert cfg["archived_at"] is not None
        assert db.project_status(conn, cfg) == "Archived"

    def test_set_dates_updates_period(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-02-01", "created_at": _now()})
        resp = projects_router.set_dates("Trip", start_date="2026-03-01", end_date="2026-04-01", confirm_overlap="", conn=conn)
        assert resp.status_code == 303
        cfg = db.effective_label_config(conn, "Trip")
        assert cfg["start_date"] == "2026-03-01" and cfg["end_date"] == "2026-04-01"


class TestProjectsPage:
    def test_lists_project_cards_with_progress(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-12-31", "created_at": _now()})
        _task(conn, "t1", ["Trip"], status="done")
        _task(conn, "t2", ["Trip"], status="active", due_at="2026-06-01T00:00:00")
        resp = projects_router.list_projects(_request(), conn=conn)
        assert resp.status_code == 200
        cards = resp.context["projects"]
        assert len(cards) == 1
        card = cards[0]
        assert card["task_count"] == 2
        assert card["completed_count"] == 1
        assert card["remaining_count"] == 1
        assert card["progress"] == 50
        assert card["upcoming_deadline"] == "2026-06-01T00:00:00"
        assert card["status"] == "Open"

    def test_non_project_labels_are_not_listed(self, conn):
        db.upsert_label_config(conn, {"name": "Plain", "created_at": _now()})
        resp = projects_router.list_projects(_request(), conn=conn)
        assert resp.context["projects"] == []
