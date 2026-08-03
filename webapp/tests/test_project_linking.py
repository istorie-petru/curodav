"""Tests for Phase 4 of the projects/tags rework: linking an existing
task list / calendar / address book / schedule class to a project via the
manage-page dropdowns. The actual linking mechanism (Phase 1's
set_*_project setters) is already covered in test_projects_tags_db.py --
this file covers the router wiring: that the form field actually reaches
the setter, that create/edit both work, and -- the specific regression
these routers are designed to avoid -- that an unrelated rename/recolor
never silently clobbers an existing project link (upsert_* COALESCEs
project_uid; only the router's explicit set_*_project call should ever
change it)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import addressbooks as addressbooks_router
from src.routers import calendars as calendars_router
from src.routers import schedule as schedule_router
from src.routers import task_lists as task_lists_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_project(conn, name="Uni"):
    now = _now()
    uid = f"proj-{name.lower()}"
    db.upsert_project(conn, {"uid": uid, "name": name, "created_at": now, "updated_at": now})
    return uid


class FakeBridge:
    """No-op stand-in -- these tests care about project_uid wiring, not
    CalDAV I/O. ensure_*/delete_event/save_event_row/save_contact_row all
    just need to exist and not explode; see the module docstring."""

    def ensure_calendar(self, uid): pass
    def ensure_task_list(self, uid): pass
    def ensure_addressbook(self, uid): pass

    def delete_event(self, uid, calendar_path): pass

    def save_event_row(self, row):
        row = dict(row)
        row.setdefault("href", f"/{row['uid']}")
        row.setdefault("etag", None)
        return row

    def save_contact_row(self, row):
        row = dict(row)
        row.setdefault("href", f"/{row['uid']}")
        return row


@pytest.fixture()
def bridge():
    return FakeBridge()


class TestTaskListLinking:
    def test_create_with_project(self, conn, bridge):
        p = _make_project(conn)
        task_lists_router.create_task_list(name="Homework", color="blue", project_uid=p, bridge=bridge, conn=conn)
        tl = next(t for t in db.list_task_lists(conn) if t["name"] == "Homework")
        assert tl["project_uid"] == p

    def test_edit_links_existing_list(self, conn):
        db.ensure_default_task_list(conn)
        p = _make_project(conn)
        task_lists_router.edit_task_list(db.DEFAULT_TASK_LIST_UID, name="Tasks", color="blue", project_uid=p, conn=conn)
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] == p

    def test_edit_unlinks_when_dropdown_reset(self, conn):
        db.ensure_default_task_list(conn)
        p = _make_project(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, p)
        task_lists_router.edit_task_list(db.DEFAULT_TASK_LIST_UID, name="Tasks", color="blue", project_uid="", conn=conn)
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] is None

    def test_rename_via_router_preserves_link(self, conn):
        # Regression guard: this is exactly the bug class flagged in
        # Phase 1 -- an edit that includes project_uid="" because a
        # template with no <select> (no projects exist) still submits the
        # form must not be confused with "explicitly unlink." Here we
        # simulate the real template behavior: project_uid is always
        # submitted as whatever the dropdown's current selection is.
        db.ensure_default_task_list(conn)
        p = _make_project(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, p)
        task_lists_router.edit_task_list(db.DEFAULT_TASK_LIST_UID, name="Renamed", color="green", project_uid=p, conn=conn)
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["name"] == "Renamed"
        assert tl["project_uid"] == p


class TestCalendarLinking:
    def test_create_with_project(self, conn, bridge):
        p = _make_project(conn)
        calendars_router.create_calendar(name="Schedule", color="orange", project_uid=p, bridge=bridge, conn=conn)
        cal = next(c for c in db.list_calendars(conn) if c["name"] == "Schedule")
        assert cal["project_uid"] == p

    def test_edit_links_and_unlinks(self, conn):
        db.ensure_default_calendar(conn)
        p = _make_project(conn)
        calendars_router.edit_calendar(db.DEFAULT_CALENDAR_UID, name="Personal", color="blue", project_uid=p, conn=conn)
        assert db.get_calendar(conn, db.DEFAULT_CALENDAR_UID)["project_uid"] == p
        calendars_router.edit_calendar(db.DEFAULT_CALENDAR_UID, name="Personal", color="blue", project_uid="", conn=conn)
        assert db.get_calendar(conn, db.DEFAULT_CALENDAR_UID)["project_uid"] is None


class TestAddressbookLinking:
    def test_link_addressbook_to_project(self, conn):
        """Post-§4: addressbooks are fixed (Active/Archived), so linking is
        done via set_addressbook_project, not create_addressbook."""
        db.ensure_default_addressbook(conn)
        p = _make_project(conn)
        db.set_addressbook_project(conn, db.DEFAULT_ADDRESSBOOK_UID, p)
        assert db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)["project_uid"] == p

    def test_edit_links_and_unlinks(self, conn):
        db.ensure_default_addressbook(conn)
        p = _make_project(conn)
        addressbooks_router.edit_addressbook(db.DEFAULT_ADDRESSBOOK_UID, project_uid=p, conn=conn)
        assert db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)["project_uid"] == p
        addressbooks_router.edit_addressbook(db.DEFAULT_ADDRESSBOOK_UID, project_uid="", conn=conn)
        assert db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)["project_uid"] is None


class TestReturnToRedirect:
    """2026-08-02 -- create/edit on all three routers now accept an
    optional return_to so the Projects page's per-project quick-add/link
    forms (routers/projects.py's manage_projects) can post here and land
    back on /projects instead of always bouncing to /task-lists,
    /calendars, or /addressbooks. Absent or non-internal return_to must
    still fall back to the original default, unchanged."""

    def test_task_list_create_return_to(self, conn, bridge):
        resp = task_lists_router.create_task_list(name="HW", color="blue", project_uid="", return_to="/projects", bridge=bridge, conn=conn)
        assert resp.headers["location"] == "/projects"

    def test_task_list_create_default_redirect_unchanged(self, conn, bridge):
        resp = task_lists_router.create_task_list(name="HW", color="blue", project_uid="", bridge=bridge, conn=conn)
        assert resp.headers["location"] == "/task-lists"

    def test_calendar_edit_return_to(self, conn):
        db.ensure_default_calendar(conn)
        resp = calendars_router.edit_calendar(db.DEFAULT_CALENDAR_UID, name="Personal", color="blue", project_uid="", return_to="/projects", conn=conn)
        assert resp.headers["location"] == "/projects"

    def test_addressbook_edit_rejects_external_return_to(self, conn):
        """Post-§4: create_addressbook no longer exists; test the edit
        endpoint's return_to handling instead."""
        db.ensure_default_addressbook(conn)
        resp = addressbooks_router.edit_addressbook(
            db.DEFAULT_ADDRESSBOOK_UID, project_uid="", return_to="https://evil.example/", conn=conn,
        )
        assert resp.headers["location"] == "/addressbooks"


class TestLinkEndpoint:
    """2026-08-02 -- the Projects page's per-project "Link existing" /
    "Unlink" controls post here (uid as a plain form field, not a URL
    path segment, since it comes from a <select>) rather than reusing
    the full edit endpoint, which would need name/color resent too."""

    def test_link_task_list_sets_project(self, conn):
        db.ensure_default_task_list(conn)
        p = _make_project(conn)
        resp = task_lists_router.link_task_list(uid=db.DEFAULT_TASK_LIST_UID, project_uid=p, return_to="/projects", conn=conn)
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] == p
        assert resp.headers["location"] == "/projects"

    def test_link_with_blank_project_uid_unlinks(self, conn):
        db.ensure_default_task_list(conn)
        p = _make_project(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, p)
        task_lists_router.link_task_list(uid=db.DEFAULT_TASK_LIST_UID, project_uid="", conn=conn)
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] is None

    def test_link_unknown_uid_is_a_noop(self, conn):
        p = _make_project(conn)
        resp = task_lists_router.link_task_list(uid="does-not-exist", project_uid=p, conn=conn)
        assert resp.status_code == 303  # doesn't raise, just no-ops

    def test_link_calendar(self, conn):
        db.ensure_default_calendar(conn)
        p = _make_project(conn)
        calendars_router.link_calendar(uid=db.DEFAULT_CALENDAR_UID, project_uid=p, conn=conn)
        assert db.get_calendar(conn, db.DEFAULT_CALENDAR_UID)["project_uid"] == p

    def test_link_addressbook(self, conn):
        db.ensure_default_addressbook(conn)
        p = _make_project(conn)
        addressbooks_router.link_addressbook(uid=db.DEFAULT_ADDRESSBOOK_UID, project_uid=p, conn=conn)
        assert db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)["project_uid"] == p

    def test_linking_to_one_project_makes_it_unavailable_to_another(self, conn):
        # "existing lists can not be reused in another project" -- the
        # actual UI-level guarantee is that routers/projects.py's
        # manage_projects only offers unclaimed (project_uid IS NULL)
        # lists in a *different* project's "Link existing" picker; once
        # linked here, this list drops out of that unclaimed set.
        db.ensure_default_task_list(conn)
        p1 = _make_project(conn, "A")
        p2 = _make_project(conn, "B")
        task_lists_router.link_task_list(uid=db.DEFAULT_TASK_LIST_UID, project_uid=p1, conn=conn)

        from src.routers import projects as projects_router
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/projects", "headers": []})
        resp = projects_router.manage_projects(req, conn=conn)
        assert db.DEFAULT_TASK_LIST_UID not in {t["uid"] for t in resp.context["unclaimed_task_lists"]}
        assert [t["uid"] for t in resp.context["task_lists_by_project"].get(p1, [])] == [db.DEFAULT_TASK_LIST_UID]
        assert resp.context["task_lists_by_project"].get(p2, []) == []


class TestScheduleClassLinking:
    """The specific ask: 'make university courses to be projects and have
    a dropdown there.' A course links to a project via the same
    project_uid mechanism as any other list -- see schedule_class_form.html."""

    def test_create_class_with_project(self, conn, bridge):
        p = _make_project(conn, "University")
        schedule_router.create_class(
            day="Monday", start_time="10:00", end_time="12:00", name="Databases",
            acronym="DB", class_type="Course", professor_select="", professor_new="",
            room="", credits="5", parity="all", enrolled="1", project_uid=p,
            bridge=bridge, conn=conn,
        )
        cls = next(c for c in db.list_schedule_classes(conn) if c["name"] == "Databases")
        assert cls["project_uid"] == p

    def test_update_class_links_and_unlinks(self, conn, bridge):
        p = _make_project(conn, "University")
        schedule_router.create_class(
            day="Monday", start_time="10:00", end_time="12:00", name="Databases",
            acronym="", class_type="", professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="1", project_uid="",
            bridge=bridge, conn=conn,
        )
        cls = next(c for c in db.list_schedule_classes(conn) if c["name"] == "Databases")
        # §5: creating a class with no explicit project_uid auto-provisions one
        # (see _auto_provision_university_project in routers/schedule.py).
        assert cls["project_uid"] is not None
        auto_project_uid = cls["project_uid"]
        # The auto-provisioned project should exist and carry the class name.
        auto_project = db.get_project(conn, auto_project_uid)
        assert auto_project is not None
        assert auto_project["name"] == "Databases"
        # A Grades database should have been auto-provisioned too.
        grades_dbs = db.list_databases(conn, project_uid=auto_project_uid)
        assert len(grades_dbs) == 1
        assert "Grades" in grades_dbs[0]["name"]

        schedule_router.update_class(
            cls["uid"], day="Monday", start_time="10:00", end_time="12:00", name="Databases",
            acronym="", class_type="", professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="1", project_uid=p,
            bridge=bridge, conn=conn,
        )
        assert db.get_schedule_class(conn, cls["uid"])["project_uid"] == p

        schedule_router.update_class(
            cls["uid"], day="Monday", start_time="10:00", end_time="12:00", name="Databases",
            acronym="", class_type="", professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="1", project_uid="",
            bridge=bridge, conn=conn,
        )
        assert db.get_schedule_class(conn, cls["uid"])["project_uid"] is None

    def test_class_appears_in_project_scope_once_linked(self, conn, bridge):
        from src.routers.projects import _project_scope

        p = _make_project(conn, "University")
        schedule_router.create_class(
            day="Tuesday", start_time="09:00", end_time="11:00", name="Algorithms",
            acronym="ALG", class_type="", professor_select="", professor_new="",
            room="", credits="6", parity="all", enrolled="1", project_uid=p,
            bridge=bridge, conn=conn,
        )
        scope = _project_scope(conn, p)
        assert len(scope["classes"]) == 1
        assert scope["classes"][0]["name"] == "Algorithms"
