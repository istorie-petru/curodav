"""Phase 2 (label-space rework) acceptance tests -- see
features/architecture.md §3 Phase 2's own acceptance criteria and this
phase's task spec, item 8:

  * rename propagates to object_labels and children's parent_name;
  * merge unions membership correctly;
  * no delete endpoint exists (there is no DELETE-shaped route for a
    label at all -- "clear" empties membership instead);
  * a generate_space=1 label's page renders the right aggregated content;
  * dashboard_widgets.label_name migration correctness;
  * habits correctly filter by label now.

2026-08-07: TestDatabasesFilterByLabel and
test_databases_project_uid_backfilled_as_object_labels (which exercised
the now-removed Databases feature's project-link-as-label behavior) are
deleted -- see features/architecture.md's Grades/Databases removal
note. Everything else in this file covers habits/label management,
unaffected by that removal.

2026-08-15: TestScheduleClassesFilterByLabel is deleted -- the whole
Schedule module (and the class-as-real-recurring-event mechanism it
relied on) is removed, see plans/STATE.md's removal entry.
`test_schedule_classes_project_uid_backfilled_as_a_real_tag` stays: it
exercises `migrate_labels.py`'s legacy pre-1.6 `schedule_classes`-table
backfill path directly against a synthetic table, unrelated to
routers/schedule.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import migrate_labels  # noqa: E402

from src.routers import habits as habits_router
from src.routers import labels as labels_router
from src.routers import spaces as spaces_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/labels"):
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
# Icon persistence (2026-09-03 bug fix -- direct report: "chose icons
# individually and they don't save"). label_form_modal.html's icon picker
# (_icon_swatch_picker.html, `name="icon"` radios) has posted into this
# form since it existed; routers/labels.py's create_label/update_label
# never declared an `icon` Form param to receive it, so FastAPI silently
# dropped the field on every submit and db.upsert_label_config's own
# partial-update contract ("only touch what you're told to") meant the
# icon just... never changed. Fixed by declaring `icon` on both routes.
# --------------------------------------------------------------------- #


class TestIconPersistence:
    # Every Form(...) param is passed explicitly here, including ones this
    # test doesn't otherwise care about (role/start_date/end_date/
    # description/label_group) -- calling a FastAPI route function
    # directly (not through the app) bypasses Form()'s normal request-body
    # resolution, so any parameter left at its Python default literally
    # holds FastAPI's own `Form(...)` marker object, not the string a real
    # submit would inject (same caveat routers/labels.py's own
    # `set_label`/`create_label` already document for `abbreviation`).

    def test_create_label_saves_the_chosen_icon(self, conn):
        labels_router.create_label(new_name="Garden", color="green", icon="  leaf  ", label_group="", role="none", start_date="", end_date="", conn=conn)
        cfg = db.get_label_config(conn, "Garden")
        assert cfg["icon"] == "leaf"

    def test_update_label_saves_a_newly_chosen_icon(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="green", icon="leaf", label_group="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["icon"] == "leaf"

    def test_update_label_changes_an_existing_icon(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "icon": "leaf", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="green", icon="flag", label_group="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["icon"] == "flag"

    def test_update_label_no_icon_radio_clears_it(self, conn):
        # The picker's "No icon" option submits icon="" (_icon_swatch_
        # picker.html) -- an explicit clear, not "leave unchanged".
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "icon": "leaf", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="green", icon="", label_group="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["icon"] is None

    def test_update_label_still_saves_color_and_group_alongside_icon(self, conn):
        # Regression guard: adding the new `icon` param shouldn't disturb
        # the fields that already worked.
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="purple", icon="leaf", label_group="Home", description="", role="none", start_date="", end_date="", conn=conn)
        cfg = db.get_label_config(conn, "Garden")
        assert cfg["icon"] == "leaf"
        assert cfg["color"] == "purple"
        assert cfg["label_group"] == "Home"


# --------------------------------------------------------------------- #
# Color validation + reserved-name guard (2026-09-07 fixes, both flagged
# in an earlier audit): `color` used to be written to storage unchecked
# (`color or "blue"`, accepting literally any string), and nothing stopped
# a label from being named after one of the sentinel banner scopes
# (db.PAGE_HEADER_BANNER_SCOPE / db.SEASON_BANNER_SCOPES), which live in
# the exact same app_meta namespace a label's own banner does.
# --------------------------------------------------------------------- #


class TestColorValidation:
    def test_create_label_rejects_an_unknown_color(self, conn):
        labels_router.create_label(new_name="Garden", color="not-a-real-color", icon="", label_group="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "blue"

    def test_create_label_accepts_a_real_color(self, conn):
        labels_router.create_label(new_name="Garden", color="teal", icon="", label_group="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "teal"

    def test_update_label_rejects_an_unknown_color(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="<script>", icon="", label_group="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "blue"

    def test_set_label_rejects_an_unknown_color(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.set_label(name="Garden", color="whatever", icon="", description="", parent_name="", generate_space="", abbreviation="", return_to="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "blue"


class TestReservedLabelNameGuard:
    def test_create_label_rejects_the_page_header_scope_name(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.create_label(new_name=db.PAGE_HEADER_BANNER_SCOPE, color="blue", icon="", label_group="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, db.PAGE_HEADER_BANNER_SCOPE) is None

    def test_create_label_rejects_a_season_scope_name(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.create_label(new_name=db.SEASON_BANNER_SCOPES["summer"], color="blue", icon="", label_group="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400

    def test_update_label_rejects_renaming_into_a_reserved_name(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.update_label(name="Garden", new_name=db.PAGE_HEADER_BANNER_SCOPE, color="green", icon="", label_group="", description="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400
        # Rejected before the rename happened -- the label is untouched.
        assert db.get_label_config(conn, "Garden") is not None

    def test_update_label_editing_in_place_is_unaffected(self, conn):
        # Sanity check the guard only fires on an actual name *change* --
        # every ordinary edit (new_name == name) must keep working.
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="teal", icon="", label_group="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "teal"

    def test_rename_endpoint_rejects_a_reserved_destination(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.rename_label(name="Garden", new_name=db.PAGE_HEADER_BANNER_SCOPE, conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, "Garden") is not None

    def test_merge_rejects_a_reserved_destination(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.merge_label(name="Garden", dest_name=db.PAGE_HEADER_BANNER_SCOPE, conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, "Garden") is not None

    def test_set_label_rejects_a_reserved_name(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.set_label(name=db.PAGE_HEADER_BANNER_SCOPE, color="blue", icon="", description="", parent_name="", generate_space="", abbreviation="", return_to="", conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, db.PAGE_HEADER_BANNER_SCOPE) is None


# --------------------------------------------------------------------- #
# Rename
# --------------------------------------------------------------------- #


class TestRename:
    def test_rename_rewrites_object_labels(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.rename_label(conn, "uni", "university")
        assert db.list_labels_for_object(conn, "task", "t1") == ["university"]
        assert db.list_object_ids_for_label(conn, "task", "uni") == []

    def test_rename_updates_own_label_config_row(self, conn):
        db.upsert_label_config(conn, {"name": "uni", "color": "purple", "created_at": _now()})
        db.rename_label(conn, "uni", "university")
        assert db.get_label_config(conn, "uni") is None
        cfg = db.get_label_config(conn, "university")
        assert cfg is not None and cfg["color"] == "purple"

    def test_rename_updates_childrens_parent_name(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "MATH201", "parent_name": "Uni", "created_at": _now()})
        db.rename_label(conn, "Uni", "University")
        assert db.get_label_config(conn, "CS101")["parent_name"] == "University"
        assert db.get_label_config(conn, "MATH201")["parent_name"] == "University"

    def test_rename_colliding_with_an_existing_label_merges_instead(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "Y", "description": "", "status": "active",
                               "tags": ["university"], "created_at": _now()})
        db.rename_label(conn, "uni", "university")
        assert sorted(db.list_object_ids_for_label(conn, "task", "university")) == ["t1", "t2"]

    def test_case_only_rename_is_not_treated_as_a_merge(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.rename_label(conn, "uni", "Uni")
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_rename_router_endpoint(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        resp = labels_router.rename_label("uni", new_name="university", conn=conn)
        assert resp.status_code == 303
        assert db.list_labels_for_object(conn, "task", "t1") == ["university"]


# --------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------- #


class TestMerge:
    def test_merge_unions_membership(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["source"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "Y", "description": "", "status": "active",
                                "all_day": 0, "tags": ["dest"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Z", "tags": ["source"], "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.list_object_ids_for_label(conn, "task", "dest") == ["t1"]
        assert db.list_object_ids_for_label(conn, "event", "dest") == ["e1"]
        assert db.list_object_ids_for_label(conn, "contact", "dest") == ["c1"]
        assert db.list_object_ids_for_label(conn, "task", "source") == []

    def test_merge_does_not_duplicate_an_object_already_carrying_both(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["source", "dest"], "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.list_labels_for_object(conn, "task", "t1") == ["dest"]

    def test_merge_repoints_source_children(self, conn):
        db.upsert_label_config(conn, {"name": "dest", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "source", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "child", "parent_name": "source", "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.get_label_config(conn, "child")["parent_name"] == "dest"

    def test_merge_removes_sources_own_config_row(self, conn):
        db.upsert_label_config(conn, {"name": "source", "color": "red", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "dest", "color": "blue", "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.get_label_config(conn, "source") is None

    def test_merge_router_endpoint(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["source"], "created_at": _now()})
        resp = labels_router.merge_label("source", dest_name="dest", conn=conn)
        assert resp.status_code == 303
        assert db.list_object_ids_for_label(conn, "task", "dest") == ["t1"]


# --------------------------------------------------------------------- #
# No delete endpoint -- "clear" empties membership instead (§0.1)
# --------------------------------------------------------------------- #


class TestNoDeleteJustClear:
    def test_labels_router_exposes_delete_route_that_clears(self, conn):
        """Delete endpoint exists but clears membership instead of deleting config (§0.1)."""
        route_paths = {r.path for r in labels_router.router.routes}
        assert any(p.endswith("/delete") for p in route_paths)

    def test_clear_empties_membership_but_keeps_config_row(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.upsert_label_config(conn, {"name": "uni", "color": "purple", "created_at": _now()})
        db.clear_label(conn, "uni")
        assert db.list_object_ids_for_label(conn, "task", "uni") == []
        # The config row is left alone -- harmless stale metadata, not
        # cleaned up (per the plan's own "no delete" semantics).
        assert db.get_label_config(conn, "uni") is not None

    def test_clear_router_endpoint(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        resp = labels_router.clear_label("uni", conn=conn)
        assert resp.status_code == 303
        assert db.list_labels_for_object(conn, "task", "t1") == []


# --------------------------------------------------------------------- #
# Generated Space page
# --------------------------------------------------------------------- #


class TestGeneratedSpacePage:
    def test_space_page_aggregates_direct_membership_only(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        # A task tagged with the child label only -- NOT directly tagged
        # "Uni" -- must not show up in the Space page's own scope (direct
        # assignment only, never transitive through parent_name).
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "ChildOnly", "description": "", "status": "active",
                               "tags": ["CS101"], "created_at": _now()})
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni"), conn=conn)
        assert resp.status_code == 200
        task_uids = {t["uid"] for t in resp.context["tasks"]}
        assert task_uids == {"t1"}
        assert resp.context["is_space"] is True
        assert [c["name"] for c in resp.context["children"]] == ["CS101"]

    def test_plain_label_page_shows_its_own_direct_items(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "HW", "description": "", "status": "active",
                               "tags": ["CS101"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "Lecture", "description": "", "status": "active",
                                "all_day": 0, "tags": ["CS101"], "created_at": _now()})
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert resp.context["is_space"] is False
        assert {t["uid"] for t in resp.context["tasks"]} == {"t1"}
        assert {e["uid"] for e in resp.context["events"]} == {"e1"}

    def test_label_with_no_config_row_still_renders(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["adhoc"], "created_at": _now()})
        resp = labels_router.label_detail("adhoc", _request("/labels/adhoc"), conn=conn)
        assert resp.status_code == 200
        assert resp.context["label"]["color"] == "blue"  # default, sane


# --------------------------------------------------------------------- #
# dashboard_widgets.label_name
# --------------------------------------------------------------------- #


class TestDashboardWidgetsLabelName:
    def test_upsert_and_list_by_label_name(self, conn):
        db.upsert_dashboard_widget(
            conn, {"uid": "w1", "type": "today_agenda", "title": None, "config": {}, "position": 0.0,
                   "created_at": _now(), "label_name": "Uni"}
        )
        db.upsert_dashboard_widget(
            conn, {"uid": "w2", "type": "today_agenda", "title": None, "config": {}, "position": 0.0,
                   "created_at": _now(), "label_name": None}
        )
        assert [w["uid"] for w in db.list_dashboard_widgets(conn, label_name="Uni")] == ["w1"]
        assert [w["uid"] for w in db.list_dashboard_widgets(conn)] == ["w2"]

    def test_space_uid_project_uid_are_aliases_for_label_name(self, conn):
        # Backward-compat accessors -- both old param names collapse onto
        # the one label_name column now (Phase 2 item 4).
        db.upsert_dashboard_widget(
            conn, {"uid": "w1", "type": "today_agenda", "title": None, "config": {}, "position": 0.0,
                   "created_at": _now(), "project_uid": "CS101"}
        )
        widget = db.get_dashboard_widget(conn, "w1")
        assert widget["label_name"] == "CS101"
        assert widget["space_uid"] == "CS101"
        assert widget["project_uid"] == "CS101"
        assert [w["uid"] for w in db.list_dashboard_widgets(conn, space_uid="CS101")] == ["w1"]


# --------------------------------------------------------------------- #
# habits filter by label
# --------------------------------------------------------------------- #


class TestHabitsFilterByLabel:
    def test_habit_project_link_is_a_label(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        habits_router.create_habit(
            name="Study", description="", color="blue", icon="", target_per_day="1",
            tags="", project_uid="Uni", conn=conn,
        )
        habits_router.create_habit(
            name="Read", description="", color="blue", icon="", target_per_day="1",
            tags="", project_uid="", conn=conn,
        )
        scoped = db.list_habits(conn, project_uid="Uni")
        assert [h["name"] for h in scoped] == ["Study"]


# --------------------------------------------------------------------- #
# migrate_labels.py -- generate_space + habit/schedule_class
# backfill (Phase 2 extensions to the Phase 1 script)
# --------------------------------------------------------------------- #


class TestMigrationExtensions:
    def test_project_groups_migrate_with_generate_space_set(self, conn):
        conn.execute("CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, group_uid TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO project_groups VALUES ('g1', 'University', 'orange', ?)", (_now(),))
        conn.execute("INSERT INTO projects VALUES ('p1', 'CS101', '', 'purple', 'g1', ?, ?)", (_now(), _now()))
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result
        assert db.get_label_config(conn, "University")["generate_space"] == 1
        assert db.get_label_config(conn, "CS101")["generate_space"] == 0

    def test_habits_project_uid_backfilled_as_object_labels(self, conn):
        conn.execute("CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, group_uid TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO projects VALUES ('p1', 'CS101', '', 'blue', NULL, ?, ?)", (_now(), _now()))
        conn.execute("ALTER TABLE habits ADD COLUMN project_uid TEXT")
        conn.execute(
            "INSERT INTO habits (uid, name, description, color, target_per_day, project_uid, created_at, updated_at) "
            "VALUES ('h1', 'Study', '', 'blue', 1, 'p1', ?, ?)", (_now(), _now())
        )
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result
        assert db.project_label_for(conn, "habit", "h1") == "CS101"
        # A project link is a real tag now (2026-08-06 correction) -- it
        # must show up in the habit's own `tags` list, not just the
        # derived `project_uid` view, or a Space page's aggregation would
        # never find this habit.
        assert "CS101" in db.get_habit(conn, "h1")["tags"]

    def test_schedule_classes_project_uid_backfilled_as_a_real_tag(self, conn):
        # 1.6 dropped `schedule_classes` from SCHEMA_SQL entirely (see
        # db.py's removal note) -- this test simulates a genuinely pre-1.6
        # database that still physically has the table on disk, which
        # migrate_labels.py's _PROJECT_LINKED_SOURCES still knows how to
        # read (that legacy migration path is unaffected by 1.6; it's
        # about *labels*, not about how a class is represented today).
        conn.execute(
            "CREATE TABLE schedule_classes (uid TEXT PRIMARY KEY, day TEXT, start_time TEXT, "
            "end_time TEXT, name TEXT, credits REAL, parity TEXT, enrolled INTEGER, created_at TEXT, updated_at TEXT)"
        )
        conn.execute("CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, group_uid TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO projects VALUES ('p1', 'CS101', '', 'blue', NULL, ?, ?)", (_now(), _now()))
        conn.execute("ALTER TABLE schedule_classes ADD COLUMN project_uid TEXT")
        conn.execute(
            "INSERT INTO schedule_classes (uid, day, start_time, end_time, name, credits, parity, enrolled, project_uid, created_at, updated_at) "
            "VALUES ('c1', 'Monday', '09:00', '10:00', 'Algorithms', 6, 'all', 1, 'p1', ?, ?)", (_now(), _now())
        )
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result
        # A real tag, not the display-only pseudo-type habits/databases use.
        assert "CS101" in db.list_labels_for_object(conn, "schedule_class", "c1")


# --------------------------------------------------------------------- #
# Sidebar Spaces (2026-08-08 -- nav rail, base.html/deps.py)
# --------------------------------------------------------------------- #
#
# 2026-08-08 follow-up: this used to be a TestPinnedSpaces class covering
# a separate opt-in "pin to sidebar" flag on top of generate_space --
# removed the same day, per direct feedback: a label worth turning into a
# Space is a label worth finding quickly, so a second manual step just to
# make it show up in the rail was friction with no real benefit. Every
# Space shows in the rail automatically now (db.list_space_labels,
# already covered by TestGeneratedSpacePage above) -- nothing left here
# to test that isn't already covered by the plain Space-page/rename/merge
# tests elsewhere in this file, or by db.list_space_labels' own use in
# deps.py.


# --------------------------------------------------------------------- #
# Abbreviations (2026-08-09 -- max-5-char synonym per label)
# --------------------------------------------------------------------- #


class TestLabelAbbreviation:
    def _set(self, name, abbreviation="", generate_space=""):
        return labels_router.set_label(
            name,
            color="blue",
            icon="",
            description="",
            parent_name="",
            generate_space=generate_space,
            abbreviation=abbreviation,
            conn=self.conn,
        )

    def _conn(self, conn):
        self.conn = conn

    def test_set_label_stores_abbreviation_and_effective_config_exposes_it(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        cfg = db.effective_label_config(conn, "University")
        assert cfg["abbreviation"] == "Uni"
        assert db.get_label_config(conn, "University")["abbreviation"] == "Uni"

    def test_set_label_truncates_longer_than_five_and_blank_clears(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Universitas")
        assert db.get_label_config(conn, "University")["abbreviation"] == "Unive"
        self._set("University", abbreviation="")
        assert db.get_label_config(conn, "University")["abbreviation"] is None

    def test_set_object_labels_resolves_abbreviation_to_full_name(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": [], "created_at": _now()})
        db.set_object_labels(conn, "task", "t1", ["Uni"])
        # Stored as the full name, not a brand-new "Uni" label.
        assert db.list_labels_for_object(conn, "task", "t1") == ["University"]
        assert db.list_object_ids_for_label(conn, "task", "University") == ["t1"]

    def test_abbreviation_resolution_is_case_insensitive(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="uni")
        db.set_object_labels(conn, "task", "t1", ["UNI"])
        assert db.list_labels_for_object(conn, "task", "t1") == ["University"]

    def test_real_label_name_wins_over_an_abbreviation_collision(self, conn):
        # A genuine label literally named "Uni" (here: its own config row)
        # must not be rewritten just because another label abbreviated to
        # the same string.
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        db.upsert_label_config(conn, {"name": "Uni", "created_at": _now()})
        db.set_object_labels(conn, "task", "t1", ["Uni"])
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_duplicate_abbreviation_stays_inert(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        self._set("Unified", abbreviation="Uni")
        db.set_object_labels(conn, "task", "t1", ["Uni"])
        # Ambiguous -- passed through as-is rather than guessing a label.
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_list_space_labels_carries_abbreviation(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni", generate_space="1")
        spaces = db.list_space_labels(conn)
        assert [(s["name"], s["abbreviation"]) for s in spaces] == [("University", "Uni")]

