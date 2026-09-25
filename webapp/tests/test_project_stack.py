"""1.3 (Project-enabled label stack) acceptance tests -- see
plans/open-priority.md § Project-enabled label stack and
plans/roadmap.md's 1.3 subsection. Covers: label_config's new is_project/
start_date/end_date/archived_at columns, the computed lifecycle
(db.project_status), the overlap rule (db.find_overlapping_project),
project_label_for's 1.3 supersession of the old generate_space=0
heuristic, and routers/projects.py's promote/dates/demote/archive actions.

Work allocations and the project's own Tasks/Week Calendar views were 1.4's
job. Both, plus the original `/projects` listing page itself, were later
retired as redundant, presentation-only pages (2026-08-15 -- see
routers/projects.py's module docstring and plans/open.md's "Retire the
standalone /projects page" decision record). `GET /projects/{name}` itself
was rebuilt 2026-08-30 as a real Kanban + upcoming-events page -- see
test_project_detail.py for that route's own tests. `GET /projects` and
`GET /projects/{name}/calendar` are still redirect-only, covered by
TestProjectPageRedirects below. promote/set_dates/demote/archive are
untouched by any of this and still covered fully here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src import db
from src.routers import label_pages
from src.routers import projects as projects_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class TestProjectStatus:
    def _cfg(self, conn, name="P", end="2026-12-31", is_project=1):
        db.upsert_label_config(conn, {"name": name, "is_project": is_project, "has_deadline": 1, "deadline_date": end, "created_at": _now()})
        return db.effective_label_config(conn, name)

    def test_any_label_with_a_deadline_has_a_status(self, conn):
        # labels-as-modules slice b: the lifecycle isn't project-only.
        cfg = self._cfg(conn, end="2026-01-01", is_project=0)
        _task(conn, "t1", ["P"], status="done")
        assert db.project_status(conn, cfg, today=date(2026, 6, 1)) == "Pending Archiving"

    def test_deadline_switched_off_is_ignored(self, conn):
        db.upsert_label_config(conn, {"name": "P", "is_project": 1, "has_deadline": 0, "deadline_date": "2099-01-01"})
        _task(conn, "t1", ["P"], status="done")
        cfg = db.effective_label_config(conn, "P")
        assert db.project_status(conn, cfg, today=date(2026, 1, 1)) == "Pending Archiving"

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


class TestArchiveAction:
    """labels-as-modules slice b (2026-09-25): archiving moved from
    POST /projects/{name}/archive to the label's own page, and gained an
    undo. promote/set_dates/demote (and the start/end overlap rule) are
    gone -- the label form sets the deadline and the Project role."""

    def test_archive_sets_archived_at_and_status(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1, "has_deadline": 1, "deadline_date": "2020-01-01", "created_at": _now()})
        resp = label_pages.archive_label("Trip", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/labels/Trip"
        cfg = db.effective_label_config(conn, "Trip")
        assert cfg["archived_at"] is not None
        assert db.project_status(conn, cfg) == "Archived"

    def test_unarchive_goes_back_to_the_computed_status(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1, "created_at": _now()})
        label_pages.archive_label("Trip", conn=conn)
        label_pages.unarchive_label("Trip", conn=conn)
        cfg = db.effective_label_config(conn, "Trip")
        assert cfg["archived_at"] is None
        assert db.project_status(conn, cfg) == "Open"

    def test_old_project_endpoints_are_gone(self):
        for name in ("promote", "set_dates", "demote", "archive"):
            assert not hasattr(projects_router, name)
        assert not hasattr(db, "find_overlapping_project")


class TestProjectPageRedirects:
    """The /projects listing page and the Week Calendar child view are
    gone (2026-08-15, presentation-only -- see routers/projects.py's
    module docstring and plans/open.md's "Retire the standalone /projects
    page" decision record). `GET /projects/{name}` itself was rebuilt
    2026-08-30 -- see test_project_detail.py, not here. These two routes
    still just redirect; the actual promote/set_dates/demote/archive
    behavior above is unchanged."""

    # 2026-08-28 "major rework" session update: the Tasks table's grouping
    # is unconditional now (no more `?group_by=project` to opt into) and its
    # label filter is gone entirely (item 3, "filtering reduced to date
    # only") -- the listing redirect below lands on the plain Table view
    # now, where a project already surfaces as its own group.

    def test_list_projects_redirects_to_tasks_table(self, conn):
        resp = projects_router.list_projects_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/tasks"

    def test_project_calendar_redirects_to_the_label_page(self, conn):
        resp = projects_router.project_calendar_redirect("Trip")
        assert resp.status_code == 301
        assert resp.headers["location"] == "/labels/Trip"
