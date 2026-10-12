"""Page types: Sections, Widget dashboard and Secretariat for Home, groups and labels."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import clock, db
from src.routers import dashboard as dashboard_router
from src.routers import label_pages
from src.routers import secretariat_page


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


@pytest.fixture(autouse=True)
def pinned_clock(frozen_today):
    from datetime import date

    frozen_today(date(2026, 10, 7))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def _task(conn, uid, tags, due="2026-10-07"):
    db.upsert_task(conn, {"uid": uid, "title": f"Task {uid}", "description": "", "status": "active", "tags": tags,
                          "due_at": due, "created_at": _now()})


class TestStorage:
    def test_old_dashboard_flag_becomes_a_page_type(self, conn):
        db.upsert_label_config(conn, {"name": "Old", "has_dashboard": 1})
        db.upsert_label_config(conn, {"name": "Plain"})
        assert db.effective_label_config(conn, "Old")["page_type"] == "dashboard"
        assert db.effective_label_config(conn, "Plain")["page_type"] == "sections"

    def test_migration_converts_existing_rows_once(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        conn.execute("UPDATE label_config SET has_dashboard = 1, page_type = 'sections' WHERE name = 'Gym'")
        conn.execute("DELETE FROM app_meta WHERE key = ?", (db._LABEL_PAGE_TYPE_MIGRATED_KEY,))
        db.migrate_label_page_type(conn)
        assert db.effective_label_config(conn, "Gym")["page_type"] == "dashboard"
        conn.execute("UPDATE label_config SET page_type = 'sections' WHERE name = 'Gym'")
        db.migrate_label_page_type(conn)
        assert db.effective_label_config(conn, "Gym")["page_type"] == "sections"

    def test_home_defaults_to_the_secretariat_and_remembers_a_choice(self, conn):
        assert db.get_home_page_type(conn) == "secretariat"
        db.set_home_page_type(conn, "sections")
        assert db.get_home_page_type(conn) == "sections"
        db.set_home_page_type(conn, "nonsense")
        assert db.get_home_page_type(conn) == "sections"

    def test_group_defaults_to_the_dashboard_and_follows_a_rename(self, conn):
        db.ensure_group(conn, "Uni")
        assert db.get_group_page_type(conn, "Uni") == "dashboard"
        db.set_group_page_type(conn, "Uni", "secretariat")
        db.rename_group(conn, "Uni", "College")
        assert db.get_group_page_type(conn, "College") == "secretariat"


class TestPages:
    def test_label_secretariat_lists_only_its_own_items(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "page_type": "secretariat"})
        _task(conn, "mine", ["Gym"])
        _task(conn, "other", ["Work"])
        resp = label_pages.label_page("Gym", _request("/labels/Gym"), conn=conn)
        body = resp.body.decode()
        assert resp.template.name == "secretariat.html"
        assert "Task mine" in body and "Task other" not in body

    def test_home_secretariat_lists_everything(self, conn):
        _task(conn, "a", ["Gym"])
        _task(conn, "b", ["Work"])
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert resp.template.name == "secretariat.html"
        assert "Task a" in body and "Task b" in body

    def test_home_can_be_the_widget_dashboard_or_sections(self, conn):
        db.set_home_page_type(conn, "dashboard")
        assert dashboard_router.dashboard_view(_request(), conn=conn).template.name == "dashboard.html"
        db.set_home_page_type(conn, "sections")
        assert dashboard_router.dashboard_view(_request(), conn=conn).template.name == "label_sections.html"

    @pytest.mark.parametrize("page_type, template", [
        ("secretariat", "secretariat.html"), ("sections", "label_sections.html"), ("dashboard", "label_detail.html")])
    def test_group_page_follows_its_page_type(self, conn, page_type, template):
        db.set_group_members(conn, "Uni", [])
        db.upsert_label_config(conn, {"name": "Essay", "label_group": "Uni"})
        db.set_group_page_type(conn, "Uni", page_type)
        assert label_pages.group_page("Uni", _request("/groups/Uni"), conn=conn).template.name == template

    def test_group_sections_cover_the_member_labels_only(self, conn):
        db.upsert_label_config(conn, {"name": "Essay", "label_group": "Uni"})
        db.set_group_page_type(conn, "Uni", "secretariat")
        _task(conn, "in", ["Essay"])
        _task(conn, "out", ["Work"])
        body = label_pages.group_page("Uni", _request("/groups/Uni"), conn=conn).body.decode()
        assert "Task in" in body and "Task out" not in body


class TestChoosingAPageType:
    def test_home_modal_saves_the_choice(self, conn):
        resp = secretariat_page.set_home_page(page_type="sections", conn=conn)
        assert resp.status_code == 303 and db.get_home_page_type(conn) == "sections"
        body = secretariat_page.home_page_modal(_request("/home/page"), conn=conn).body.decode()
        assert 'name="page_type"' in body

    def test_group_edit_saves_the_choice(self, conn):
        db.ensure_group(conn, "Uni")
        label_pages.update_group("Uni", color="gray", icon="", new_name="", members=[], members_submitted="",
                                 page_type="secretariat", request=None, conn=conn)
        assert db.get_group_page_type(conn, "Uni") == "secretariat"


class TestSecretariatLayout:
    def _render(self, conn):
        return dashboard_router.dashboard_view(_request(), conn=conn).body.decode()

    def test_empty_sections_are_left_out_and_a_blank_page_says_so(self, conn):
        body = self._render(conn)
        assert "Events today" not in body and "Other reminders" not in body
        assert "Nothing planned" in body

    def test_only_sections_with_content_appear(self, conn):
        _task(conn, "a", ["Gym"])
        body = self._render(conn)
        assert "Tasks due today" in body
        assert "Tasks due this week" not in body and "Events today" not in body

    def test_a_task_completed_just_now_stays_listed_as_done(self, conn):
        _task(conn, "a", ["Gym"])
        db.upsert_task(conn, {**db.get_task(conn, "a"), "status": "done", "completed_at": clock.now().isoformat()})
        body = self._render(conn)
        assert "Task a" in body and "sec-row is-done" in body

    def test_a_task_completed_long_ago_is_gone(self, conn):
        _task(conn, "a", ["Gym"])
        db.upsert_task(conn, {**db.get_task(conn, "a"), "status": "done"})
        conn.execute("UPDATE tasks SET completed_at = ? WHERE uid = 'a'",
                     ((clock.now() - timedelta(minutes=30)).isoformat(),))
        conn.commit()
        assert "Task a" not in self._render(conn)

    def test_rows_show_the_icon_and_the_date_but_no_label_pill(self, conn):
        _task(conn, "a", ["Gym"])
        body = self._render(conn)
        assert "label-pill-link" not in body and "pill-static" in body and 'data-start="' in body
