"""Labels-as-modules slice a (plans/ui-cleanup-2026-09.md item 4,
2026-09-25): the new per-label module fields on label_config, their
one-time backfill from the Space/Project model (db.backfill_label_modules),
and the interim write-path mirror (db._mirror_legacy_module_fields) that
keeps them in step with generate_space/is_project/parent_name/end_date until
the UI moves onto the new fields.
"""

from __future__ import annotations

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _legacy(conn, name, **cols):
    """A label_config row as a pre-migration database would have it: only
    the legacy columns are set, and the new ones are left at their column
    defaults."""
    cols = {"name": name, **cols}
    conn.execute(
        f"INSERT INTO label_config ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        list(cols.values()),
    )


def _rerun_backfill(conn):
    conn.execute("DELETE FROM app_meta WHERE key = ?", (db._LABEL_MODULES_BACKFILLED_KEY,))
    db.backfill_label_modules(conn)


class TestDefaults:
    def test_plain_label_defaults(self, conn):
        cfg = db.effective_label_config(conn, "Nothing")
        assert cfg["sidebar_pin"] is False
        assert cfg["widget_pin"] is False
        assert cfg["has_deadline"] is False
        assert cfg["deadline_date"] is None
        assert cfg["has_dashboard"] is False
        assert cfg["agenda_widget"] is True
        assert cfg["tasks_widget"] is True
        assert cfg["contacts_widget"] is False
        assert cfg["is_archived"] is False

    def test_upsert_round_trips_module_fields(self, conn):
        db.upsert_label_config(conn, {
            "name": "Gym", "sidebar_pin": True, "widget_pin": 1, "has_deadline": 1,
            "deadline_date": "2026-12-01", "has_dashboard": 0, "contacts_widget": "on",
            "agenda_widget": 0,
        })
        row = db.get_label_config(conn, "Gym")
        assert (row["sidebar_pin"], row["widget_pin"], row["has_deadline"]) == (1, 1, 1)
        assert row["contacts_widget"] == 1 and row["agenda_widget"] == 0
        assert row["deadline_date"] == "2026-12-01"
        # Partial upsert leaves the module fields alone.
        db.upsert_label_config(conn, {"name": "Gym", "color": "red"})
        assert db.effective_label_config(conn, "Gym")["sidebar_pin"] is True

    def test_is_archived_follows_archived_at(self, conn):
        db.upsert_label_config(conn, {"name": "Old", "is_project": 1})
        db.archive_project(conn, "Old")
        assert db.effective_label_config(conn, "Old")["is_archived"] is True


class TestBackfill:
    def test_space_children_and_projects(self, conn):
        _legacy(conn, "School", generate_space=1)
        _legacy(conn, "Maths", parent_name="School")
        _legacy(conn, "Thesis", parent_name="School", is_project=1, start_date="2026-09-01", end_date="2027-06-30")
        _legacy(conn, "Trip", is_project=1)
        _legacy(conn, "Misc")
        _rerun_backfill(conn)
        cfg = {n: db.effective_label_config(conn, n) for n in ("School", "Maths", "Thesis", "Trip", "Misc")}

        assert [cfg[n]["label_group"] for n in cfg] == ["School", "School", "School", None, None]
        assert [cfg[n]["sidebar_pin"] for n in cfg] == [True, True, True, True, False]
        assert [cfg[n]["widget_pin"] for n in cfg] == [True, False, True, True, False]
        assert [cfg[n]["has_dashboard"] for n in cfg] == [True, False, True, True, False]
        assert cfg["Thesis"]["has_deadline"] is True
        assert cfg["Thesis"]["deadline_date"] == "2027-06-30"
        # A project with no end date has no deadline.
        assert cfg["Trip"]["has_deadline"] is False
        assert cfg["Trip"]["deadline_date"] is None

    def test_free_text_group_kept_but_space_wins(self, conn):
        _legacy(conn, "School", generate_space=1)
        _legacy(conn, "Old", label_group="Hobbies")
        _legacy(conn, "Both", label_group="Stale", parent_name="School")
        _rerun_backfill(conn)
        assert db.effective_label_config(conn, "Old")["label_group"] == "Hobbies"
        assert db.effective_label_config(conn, "Both")["label_group"] == "School"

    def test_parent_that_is_not_a_space_is_ignored(self, conn):
        _legacy(conn, "Orphan", parent_name="Gone")
        _rerun_backfill(conn)
        cfg = db.effective_label_config(conn, "Orphan")
        assert cfg["label_group"] is None
        assert cfg["sidebar_pin"] is False

    def test_label_with_own_widgets_keeps_its_dashboard(self, conn):
        _legacy(conn, "Reading")
        conn.execute(
            "INSERT INTO dashboard_widgets (uid, type, label_name) VALUES ('w1', 'tasks', 'Reading')"
        )
        _rerun_backfill(conn)
        assert db.effective_label_config(conn, "Reading")["has_dashboard"] is True

    def test_runs_once(self, conn):
        _legacy(conn, "School", generate_space=1)
        _rerun_backfill(conn)
        conn.execute("UPDATE label_config SET sidebar_pin = 0 WHERE name = 'School'")
        db.backfill_label_modules(conn)  # marker set -> no-op
        assert db.effective_label_config(conn, "School")["sidebar_pin"] is False

    def test_init_schema_runs_it_on_an_existing_database(self, tmp_path):
        path = tmp_path / "cache.sqlite"
        with db.connect(path) as c:
            _legacy(c, "School", generate_space=1)
            c.execute("DELETE FROM app_meta WHERE key = ?", (db._LABEL_MODULES_BACKFILLED_KEY,))
            c.commit()
        with db.connect(path) as c:
            assert db.effective_label_config(c, "School")["sidebar_pin"] is True


class TestLegacyWriteMirror:
    def test_making_a_space(self, conn):
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1})
        cfg = db.effective_label_config(conn, "Home")
        assert (cfg["sidebar_pin"], cfg["widget_pin"], cfg["has_dashboard"]) == (True, True, True)
        assert cfg["label_group"] == "Home"

    def test_joining_and_leaving_a_space(self, conn):
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1})
        db.upsert_label_config(conn, {"name": "Garden", "parent_name": "Home"})
        cfg = db.effective_label_config(conn, "Garden")
        assert cfg["label_group"] == "Home" and cfg["sidebar_pin"] is True
        db.upsert_label_config(conn, {"name": "Garden", "parent_name": None})
        assert db.effective_label_config(conn, "Garden")["label_group"] is None

    def test_leaving_a_space_keeps_an_unrelated_group(self, conn):
        _legacy(conn, "Garden", label_group="Outdoors", parent_name="Home")
        db.upsert_label_config(conn, {"name": "Garden", "parent_name": None})
        assert db.effective_label_config(conn, "Garden")["label_group"] == "Outdoors"

    def test_project_dates_set_and_clear_the_deadline(self, conn):
        db.upsert_label_config(conn, {"name": "Move", "is_project": 1, "start_date": "2026-10-01", "end_date": "2026-11-01"})
        cfg = db.effective_label_config(conn, "Move")
        assert cfg["has_deadline"] is True and cfg["deadline_date"] == "2026-11-01"
        assert cfg["has_dashboard"] is True and cfg["widget_pin"] is True
        db.upsert_label_config(conn, {"name": "Move", "start_date": "2026-10-01", "end_date": "2026-12-15"})
        assert db.effective_label_config(conn, "Move")["deadline_date"] == "2026-12-15"
        db.upsert_label_config(conn, {"name": "Move", "is_project": 0, "start_date": None, "end_date": None, "archived_at": None})
        cfg = db.effective_label_config(conn, "Move")
        assert cfg["has_deadline"] is False and cfg["deadline_date"] is None

    def test_end_date_on_a_non_project_is_not_a_deadline(self, conn):
        db.upsert_label_config(conn, {"name": "Plain", "end_date": "2026-11-01"})
        assert db.effective_label_config(conn, "Plain")["has_deadline"] is False

    def test_explicit_new_field_wins(self, conn):
        # e.g. restoring a backup that already carries the new columns.
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1, "sidebar_pin": 0, "label_group": "Family"})
        cfg = db.effective_label_config(conn, "Home")
        assert cfg["sidebar_pin"] is False and cfg["label_group"] == "Family"
        assert cfg["widget_pin"] is True


class TestRenameCarriesTheGroup:
    def _space(self, conn):
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1})
        db.upsert_label_config(conn, {"name": "Garden", "parent_name": "Home"})
        _legacy(conn, "Unrelated", label_group="Home")

    def test_rename(self, conn):
        self._space(conn)
        db.rename_label(conn, "Home", "House")
        assert db.effective_label_config(conn, "House")["label_group"] == "House"
        assert db.effective_label_config(conn, "Garden")["label_group"] == "House"
        assert db.effective_label_config(conn, "Unrelated")["label_group"] == "Home"

    def test_case_only_rename(self, conn):
        self._space(conn)
        db.rename_label(conn, "Home", "HOME")
        assert db.effective_label_config(conn, "Garden")["label_group"] == "HOME"

    def test_merge(self, conn):
        self._space(conn)
        db.upsert_label_config(conn, {"name": "House", "generate_space": 1})
        db.merge_labels(conn, "Home", "House")
        assert db.effective_label_config(conn, "Garden")["label_group"] == "House"
        assert db.effective_label_config(conn, "Unrelated")["label_group"] == "Home"
