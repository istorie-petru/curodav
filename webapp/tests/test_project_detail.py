"""1.4 slice 2 (project pages & views' Tasks view) acceptance tests -- see
plans/open-priority.md § Project pages & views. Covers `GET /projects/{name}`
(`routers/projects.py::project_detail`): a project's own page, currently just
its Tasks view (tasks carrying the project's label, open/completed split,
reusing the same row markup + inline pill-select/delete-undo behavior the
global Tasks page uses). The Week Calendar view is a later slice, not
covered here.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import projects as projects_router
from src.routers import tasks as tasks_router


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


def _project(conn, name, start_date="2026-08-01", end_date="2026-09-01"):
    db.upsert_label_config(
        conn,
        {"name": name, "is_project": 1, "start_date": start_date, "end_date": end_date, "created_at": _now()},
    )


def _task(conn, uid, tags, status="active", due_at=None):
    db.upsert_task(
        conn,
        {
            "uid": uid, "title": uid, "description": "", "status": status,
            "tags": tags, "created_at": _now(), "due_at": due_at,
        },
    )


class TestProjectDetailRoute:
    def test_unknown_or_non_project_label_redirects_to_projects_list(self, conn):
        resp = projects_router.project_detail("Nope", _request("/projects/Nope"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"

    def test_plain_label_not_promoted_redirects(self, conn):
        db.upsert_label_config(conn, {"name": "Plain", "created_at": _now()})
        resp = projects_router.project_detail("Plain", _request("/projects/Plain"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"

    def test_renders_project_header_and_dates(self, conn):
        _project(conn, "Conference XYZ", start_date="2026-08-11", end_date="2026-10-13")
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert "Conference XYZ" in body
        assert "2026-08-11" in body
        assert "2026-10-13" in body

    def test_only_tasks_carrying_the_project_label_show_up(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"])
        _task(conn, "t2", tags=["Other Label"])
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert "/tasks/t1" in body
        assert "/tasks/t2" not in body

    def test_open_and_completed_tasks_both_render_split(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], status="active")
        _task(conn, "t2", tags=["Conference XYZ"], status="done")
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert "/tasks/t1" in body
        assert "/tasks/t2" in body
        assert "Completed (1)" in body

    def test_new_task_link_prefills_the_project_label(self, conn):
        _project(conn, "Conference XYZ")
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert "/tasks/new?project=Conference%20XYZ" in body

    def test_empty_project_shows_empty_state_with_new_task_link(self, conn):
        _project(conn, "Conference XYZ")
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert "No tasks yet" in body
        assert "/tasks/new?project=Conference%20XYZ" in body

    def test_task_rows_carry_pill_selects_and_delete_undo(self, conn):
        """The row must be the same interactive markup the global Tasks page
        uses (static/tasks_table.js's pill-select fields, delete-with-undo)
        -- not a read-only list -- since editing status/importance/urgency
        or deleting a task from the project page must work without any new
        JS or backend route (see _task_row.html's own comment)."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"])
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert 'data-field="status"' in body
        assert 'data-field="importance"' in body
        assert 'data-field="urgency"' in body
        assert 'data-delete-undo="t1"' in body
        assert 'action="/tasks/t1/delete"' in body
        # No row-select checkboxes -- the project page has no scoped bulk
        # action surface yet (show_select=false).
        assert "row-select" not in body

    def test_progress_bar_and_percentage_render(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], status="done")
        _task(conn, "t2", tags=["Conference XYZ"], status="active")
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert "50% complete" in body
        assert "project-progress-fill" in body


class TestNewTaskFormPrefill:
    def test_project_query_param_pre_checks_the_label_even_when_unused(self, conn):
        """A freshly-promoted project label has zero object_labels rows
        (list_tag_names_in_use won't return it) until its first task exists
        -- exactly the state a brand-new, empty project's "+ New task" link
        hits. The chip must still be offered and pre-checked, not silently
        dropped because the label "isn't in use yet"."""
        _project(conn, "Conference XYZ")
        body = tasks_router.new_task_form(
            _request("/tasks/new", query_string=b"project=Conference+XYZ"), project="Conference XYZ", conn=conn
        ).body.decode()
        assert 'value="Conference XYZ"' in body
        # The option's `checked` attribute sits within the same <input> tag
        # as its value= -- assert it appears in that immediate slice, not
        # merely somewhere later in the page.
        after_value = body.split('value="Conference XYZ"', 1)[1][:150]
        assert "checked" in after_value

    def test_no_project_param_leaves_nothing_pre_checked(self, conn):
        body = tasks_router.new_task_form(_request("/tasks/new"), conn=conn).body.decode()
        assert "multiselect-option" in body


class TestProjectsPageLinksToDetail:
    def test_project_card_open_link_points_to_project_detail(self, conn):
        _project(conn, "Conference XYZ")
        body = projects_router.list_projects(_request("/projects"), conn=conn).body.decode()
        assert '/projects/Conference XYZ' in body
        assert '/labels/Conference XYZ' not in body
