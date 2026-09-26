"""Labels-as-modules slice b (plans/ui-cleanup-2026-09.md item 4,
2026-09-25): one label page at /labels/{name} (routers/label_pages.py)
whose layout follows the label's module fields, the old per-kind URLs
redirecting there, the label form's Deadline/Page fields, and the generic
archive flow.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import re

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db
from src.routers import label_pages
from src.routers import labels as labels_router
from src.routers import spaces as spaces_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/labels/X"):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
    })


def _page(conn, name):
    return label_pages.label_page(name, _request(f"/labels/{name}"), conn=conn)


class TestWhichPage:
    def test_label_with_a_dashboard_gets_the_widget_grid(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_dashboard": 1})
        resp = _page(conn, "Gym")
        assert resp.template.name == "label_detail.html"
        assert resp.context["active_tab"] == "label"
        assert resp.context["group_labels"] == []
        # Seeded with the Home-style default layout on first visit.
        assert db.list_dashboard_widgets(conn, label_name="Gym")

    def test_label_without_a_dashboard_gets_the_sections_page(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        assert _page(conn, "Gym").template.name == "label_sections.html"

    def test_a_project_defaults_to_a_dashboard(self, conn):
        # Backfilled/mirrored in slice a: a project's page was a real page.
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        assert _page(conn, "Trip").template.name == "label_detail.html"


class TestSections:
    def _seed(self, conn, **flags):
        db.upsert_label_config(conn, {"name": "Gym", **flags})
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        db.upsert_task(conn, {"uid": "t1", "title": "Squats", "description": "", "status": "active",
                              "tags": ["Gym"], "created_at": _now(), "due_at": f"{tomorrow}T09:00:00"})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Coach", "tags": ["Gym"], "created_at": _now()})

    def test_all_three_on_by_default(self, conn):
        self._seed(conn)
        resp = _page(conn, "Gym")
        body = resp.body.decode()
        assert [i["uid"] for i in resp.context["agenda_items"]] == ["t1"]
        assert [c["uid"] for c in resp.context["contacts"]] == ["c1"]
        assert [t["uid"] for t in resp.context["columns"]["active"]] == ["t1"]
        assert "kanban-board" in body and 'src="/static/tasks_board.js' in body
        assert "> Contacts</h2>" in body and "> Agenda</h2>" in body

    def test_switched_off_sections_are_not_rendered(self, conn):
        self._seed(conn, agenda_widget=0, contacts_widget=0)
        resp = _page(conn, "Gym")
        body = resp.body.decode()
        assert resp.context["agenda_items"] == [] and resp.context["contacts"] == []
        assert "> Agenda</h2>" not in body and "> Contacts</h2>" not in body
        assert "kanban-board" in body

    def test_no_kanban_means_no_board_script(self, conn):
        self._seed(conn, tasks_widget=0)
        body = _page(conn, "Gym").body.decode()
        assert "kanban-board" not in body
        assert 'src="/static/tasks_board.js' not in body

    def test_everything_off_says_so(self, conn):
        self._seed(conn, agenda_widget=0, contacts_widget=0, tasks_widget=0)
        assert "Nothing is switched on for this page" in _page(conn, "Gym").body.decode()

    def test_deadline_shows_in_the_agenda_for_any_label(self, conn):
        soon = (date.today() + timedelta(days=3)).isoformat()
        db.upsert_label_config(conn, {"name": "Essay", "has_deadline": 1, "deadline_date": soon})
        items = _page(conn, "Essay").context["agenda_items"]
        assert [(i["title"], i.get("is_deadline")) for i in items] == [("Deadline", True)]

    def test_archived_label_has_no_upcoming_deadline_row(self, conn):
        soon = (date.today() + timedelta(days=3)).isoformat()
        db.upsert_label_config(conn, {"name": "Essay", "has_deadline": 1, "deadline_date": soon})
        db.archive_project(conn, "Essay")
        assert _page(conn, "Essay").context["agenda_items"] == []


class TestGroupPage:
    """Slice c (2026-09-25): /groups/<name> -- a widget dashboard scoped to
    every label in the group, stored under the "group:<name>" page key."""

    def _group(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni", "color": "red"})
        db.upsert_label_config(conn, {"name": "Art", "label_group": "Uni"})

    def test_renders_a_dashboard_with_its_members(self, conn):
        self._group(conn)
        resp = label_pages.group_page("Uni", _request("/groups/Uni"), conn=conn)
        assert resp.template.name == "label_detail.html"
        assert resp.context["label"]["uid"] == "group:Uni"
        assert [l["name"] for l in resp.context["group_labels"]] == ["Art", "Maths"]
        assert resp.context["page_label_scope"] == "group:Uni"
        body = resp.body.decode()
        assert 'href="/labels/Maths"' in body and 'class="toolbar group-labels"' in body
        # Seeded with the default layout under the group key.
        assert db.list_dashboard_widgets(conn, label_name="group:Uni")

    def test_widgets_are_scoped_to_the_members(self, conn):
        from src.routers import dashboard as dashboard_router
        self._group(conn)
        assert dashboard_router._scope_child_names(conn, "group:Uni") == {"Art", "Maths"}
        assert dashboard_router._return_url("group:Uni") == "/groups/Uni"
        assert dashboard_router._page_scope(conn, "group:Uni") == "space"

    def test_unknown_group_redirects_to_the_labels_list(self, conn):
        resp = label_pages.group_page("Nope", _request("/groups/Nope"), conn=conn)
        # 2026-09-26: groups have their own settings page.
        assert resp.status_code == 303 and resp.headers["location"] == "/settings/groups"

    def test_group_prefix_is_reserved_for_label_names(self, conn):
        with pytest.raises(HTTPException):
            labels_router.create_label(new_name="group:Uni", color="blue", icon="", label_group="", role="none", conn=conn)


class TestStatusRow:
    def test_plain_label_has_no_status_row(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        resp = _page(conn, "Gym")
        assert resp.context["label_status"] is None
        assert "label-status" not in resp.body.decode()

    def test_label_with_a_deadline_shows_status_and_archive(self, conn):
        db.upsert_label_config(conn, {"name": "Essay", "has_deadline": 1, "deadline_date": "2020-01-01"})
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "done",
                              "tags": ["Essay"], "created_at": _now()})
        resp = _page(conn, "Essay")
        body = resp.body.decode()
        assert resp.context["label_status"] == "Pending Archiving"
        assert 'action="/labels/Essay/archive"' in body
        # Ready to archive: no "are you sure" sheet.
        assert "It still has open tasks" not in body

    def test_archiving_early_asks_first(self, conn):
        db.upsert_label_config(conn, {"name": "Essay", "has_deadline": 1, "deadline_date": "2099-01-01"})
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Essay"], "created_at": _now()})
        body = _page(conn, "Essay").body.decode()
        assert "It still has open tasks" in body

    def test_archived_label_offers_unarchive(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        db.archive_project(conn, "Trip")
        body = _page(conn, "Trip").body.decode()
        assert 'action="/labels/Trip/unarchive"' in body
        assert 'action="/labels/Trip/archive"' not in body

    def test_status_row_is_on_the_dashboard_page_too(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        resp = _page(conn, "Trip")
        assert resp.template.name == "label_detail.html"
        assert "label-status" in resp.body.decode()


class TestOldUrls:
    def test_settings_label_url_redirects(self):
        resp = labels_router.label_detail_redirect("Gym")
        assert resp.status_code == 301 and resp.headers["location"] == "/labels/Gym"

    def test_space_url_redirects(self):
        resp = spaces_router.space_detail_redirect("Uni")
        assert resp.status_code == 301 and resp.headers["location"] == "/labels/Uni"

    def test_literal_settings_routes_still_win(self):
        paths = [r.path for r in labels_router.router.routes]
        assert paths.index("/settings/labels/new") < paths.index("/settings/labels/{name}")
        assert paths.index("/settings/labels/regions") < paths.index("/settings/labels/{name}")


class TestFormFields:
    def _update(self, conn, **kw):
        base = dict(name="Gym", new_name="Gym", color="blue", icon="", label_group="", description="", role="none")
        base.update(kw)
        return labels_router.update_label(**base, conn=conn)

    def test_update_writes_deadline_and_page_fields(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        self._update(conn, page_fields="1", deadline_date="2026-12-01", has_dashboard="1",
                     agenda_widget="1", tasks_widget="", contacts_widget="1")
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["has_deadline"] is True and cfg["deadline_date"] == "2026-12-01"
        assert cfg["has_dashboard"] is True
        assert (cfg["agenda_widget"], cfg["tasks_widget"], cfg["contacts_widget"]) == (True, False, True)

    def test_empty_deadline_clears_it(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_deadline": 1, "deadline_date": "2026-12-01"})
        self._update(conn, page_fields="1", deadline_date="")
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["has_deadline"] is False and cfg["deadline_date"] is None

    def test_without_the_marker_page_fields_are_left_alone(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_dashboard": 1, "has_deadline": 1, "deadline_date": "2026-12-01"})
        self._update(conn)
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["has_dashboard"] is True and cfg["deadline_date"] == "2026-12-01"
        assert cfg["agenda_widget"] is True and cfg["tasks_widget"] is True

    def test_bad_deadline_is_rejected(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        with pytest.raises(HTTPException) as exc:
            self._update(conn, page_fields="1", deadline_date="soon")
        assert exc.value.status_code == 400

    def test_project_role_no_longer_needs_dates(self, conn):
        self._update(conn, role="project", page_fields="1")
        assert db.effective_label_config(conn, "Gym")["is_project"] is True

    def test_role_change_does_not_touch_archiving(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "is_project": 1})
        db.archive_project(conn, "Gym")
        self._update(conn, role="none", page_fields="1")
        assert db.effective_label_config(conn, "Gym")["is_archived"] is True

    def test_create_writes_page_fields(self, conn):
        labels_router.create_label(new_name="Essay", color="blue", icon="", label_group="", role="none",
                                   page_fields="1", deadline_date="2026-11-30", agenda_widget="1", conn=conn)
        cfg = db.effective_label_config(conn, "Essay")
        assert cfg["deadline_date"] == "2026-11-30" and cfg["has_dashboard"] is False
        assert (cfg["agenda_widget"], cfg["tasks_widget"], cfg["contacts_widget"]) == (True, False, False)

    def test_edit_modal_renders_the_new_fields(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_deadline": 1, "deadline_date": "2026-12-01", "has_dashboard": 1})
        body = labels_router.edit_label_modal("Gym", _request("/settings/labels/Gym/edit"), conn=conn).body.decode()
        assert 'name="page_fields" value="1"' in body
        assert 'name="deadline_date"' in body and "2026-12-01" in body
        # 2026-09-26: Page is a dropdown; Sections hide (CSS) with a dashboard.
        assert _checked(body, "has_dashboard", "1")
        assert 'data-page="dashboard"' in body
        assert 'name="start_date"' not in body and 'name="end_date"' not in body

    def test_update_writes_group_and_pins(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        self._update(conn, label_group="  Health ", page_fields="1", sidebar_pin="1", widget_pin="")
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["label_group"] == "Health"
        assert cfg["sidebar_pin"] is True and cfg["widget_pin"] is False

    def test_new_label_modal_defaults_all_sections_on(self, conn):
        body = labels_router.new_label_modal(_request("/settings/labels/new"), conn=conn).body.decode()
        for name in ("agenda_widget", "tasks_widget", "contacts_widget"):
            assert _checked(body, name, "1")
        assert not _checked(body, "has_dashboard", "1") and _checked(body, "has_dashboard", "")
        assert '<span class="ms-summary">Agenda, Tasks, Contacts</span>' in body


class TestSettingsLabelsTable:
    """Settings > Labels groups its rows by the text label_group since slice
    c (2026-09-25): one header row per group (links to the group's page, no
    checkbox or edit/delete, since a group isn't a label), then its labels;
    ungrouped labels after. Within a group, projects sort before plain
    labels, then by name."""

    def test_context_groups_and_sorts(self, conn):
        db.upsert_label_config(conn, {"name": "Zeta", "label_group": "Uni"})
        db.upsert_label_config(conn, {"name": "Alpha", "label_group": "Uni"})
        db.upsert_label_config(conn, {"name": "Thesis", "label_group": "Uni", "is_project": 1})
        db.upsert_label_config(conn, {"name": "Run", "label_group": "Health"})
        db.upsert_label_config(conn, {"name": "Loose"})
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        # 2026-09-26: projects are listed on Settings > Projects, not here.
        assert [(g["name"], [l["name"] for l in g["labels"]]) for g in ctx["label_groups"]] == [
            ("Health", ["Run"]), ("Uni", ["Alpha", "Zeta"]),
        ]
        assert [l["name"] for l in ctx["ungrouped_labels"]] == ["Loose"]
        pctx = labels_router._labels_context(conn, _request("/settings/projects"), "projects")
        assert [(g["name"], [l["name"] for l in g["labels"]]) for g in pctx["label_groups"]] == [("Uni", ["Thesis"])]

    def test_rendered_group_row_links_to_the_group_page(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni"})
        body = labels_router.manage_labels(_request("/settings/labels"), conn=conn).body.decode()
        assert 'class="entity-section-row" data-label-group="Uni"' in body
        assert 'href="/groups/Uni" class="icon-btn" title="Open group page"' in body
        assert 'data-uid="Uni"' not in body  # no bulk-select checkbox for a group
        assert 'data-label-name="Maths" data-label-group="Uni"' in body

    def test_edit_modal_has_a_group_dropdown(self, conn):
        # 2026-09-26: groups are standalone; the label picks one from a
        # dropdown (or No group) instead of typing free text.
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni"})
        db.upsert_label_config(conn, {"name": "Run", "label_group": "Health"})
        body = labels_router.edit_label_modal("Maths", _request("/settings/labels/Maths/edit"), conn=conn).body.decode()
        assert _checked(body, "label_group", "Uni")
        assert 'name="label_group" value="Health"' in body and 'name="label_group" value=""' in body
        assert 'name="role"' not in body  # 2026-09-26: no Role field
        assert 'name="parent_name"' not in body
        assert 'value="space"' not in body  # no Space role any more
        assert 'name="sidebar_pin"' in body and 'name="widget_pin"' in body


class TestLabelPillLinks:
    """Slice d (2026-09-25): label pills link to the label -- a preview
    modal from inside detail modals and cards, never from inside another
    control (a picker option, the Tasks table's dropdown trigger, a whole-
    row link)."""

    def test_preview_modal(self, conn):
        db.upsert_label_config(conn, {"name": "Essay", "label_group": "Uni", "has_deadline": 1,
                                      "deadline_date": (date.today() + timedelta(days=3)).isoformat()})
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Essay"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Tutor", "tags": ["Essay"], "created_at": _now()})
        resp = label_pages.label_preview("Essay", _request("/labels/Essay/preview"), conn=conn)
        body = resp.body.decode()
        assert resp.template.name == "label_preview_modal.html"
        assert 'id="modal-target"' in body
        assert resp.context["open_task_count"] == 1 and resp.context["contact_count"] == 1
        assert [i["title"] for i in resp.context["agenda_items"]] == ["Deadline"]
        assert 'href="/groups/Uni"' in body
        # Open page leaves the modal; Edit swaps the form in.
        assert '<a class="btn ghost" href="/labels/Essay">' in body
        assert 'href="/settings/labels/Essay/edit" data-modal' in body

    def test_detail_modal_pills_open_the_preview(self, conn):
        from src.routers import tasks as tasks_router
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Road trip"], "created_at": _now()})
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        # 2026-09-25 (UI audit L11): the task modal's own URL rides along
        # as `from`, so the preview can offer "Back" to it.
        assert 'href="/labels/Road%20trip/preview?from=/tasks/t1" data-modal' in body

    def test_kanban_card_pills_open_the_preview(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        db.upsert_task(conn, {"uid": "t1", "title": "Squats", "description": "", "status": "active",
                              "tags": ["Gym", "Legs"], "created_at": _now()})
        body = _page(conn, "Gym").body.decode()
        assert 'href="/labels/Legs/preview" data-modal' in body
        assert 'href="/labels/Gym/preview"' not in body  # the page's own label isn't repeated

    def test_pills_inside_other_controls_stay_plain(self, conn):
        from src.routers import tasks as tasks_router
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Gym"], "created_at": _now()})
        body = tasks_router.list_tasks(_request("/tasks"), conn=conn).body.decode()
        assert "/labels/Gym/preview" not in body


def _checked(body: str, name: str, value: str) -> bool:
    """A multiselect-partial input (attributes split over lines) is checked."""
    return bool(re.search(r'name="%s" value="%s"[^>]*\bchecked\b' % (re.escape(name), re.escape(value)), body))
