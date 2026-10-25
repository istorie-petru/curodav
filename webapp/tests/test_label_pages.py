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


def _request(path="/labels/X", query=b""):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": query,
        "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
    })


def _page(conn, name, view=""):
    return label_pages.label_page(name, _request(f"/labels/{name}", f"view={view}".encode() if view else b""), conn=conn)


class TestWhichPage:
    def test_a_label_page_is_always_the_overview(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "page_type": "dashboard"})
        resp = _page(conn, "Gym")
        assert resp.template.name == "label_sections.html"
        assert resp.context["active_tab"] == "label"

    def test_the_views_are_overview_agenda_and_board(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        assert _page(conn, "Gym", "agenda").template.name == "secretariat.html"
        assert _page(conn, "Gym", "board").template.name == "scope_board.html"
        assert _page(conn, "Gym", "nonsense").template.name == "label_sections.html"

    def test_label_without_a_dashboard_gets_the_sections_page(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        assert _page(conn, "Gym").template.name == "label_sections.html"

    def test_a_project_page_is_the_overview_too(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        assert _page(conn, "Trip").template.name == "label_sections.html"


class TestSections:
    def _seed(self, conn, **flags):
        db.upsert_label_config(conn, {"name": "Gym", **flags})
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        db.upsert_task(conn, {"uid": "t1", "title": "Squats", "description": "", "status": "active",
                              "tags": ["Gym"], "created_at": _now(), "due_at": f"{tomorrow}T09:00:00"})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Coach", "tags": ["Gym"], "created_at": _now()})
        db.upsert_notebook_document(conn, {"uid": "n1", "title": "Plan", "content_json": "{}",
                                           "document_type": "full", "note_type": "notes",
                                           "created_at": _now(), "updated_at": _now(), "tags": ["Gym"]})

    def test_all_four_on_by_default(self, conn):
        self._seed(conn)
        resp = _page(conn, "Gym")
        body = resp.body.decode()
        assert [i["uid"] for i in resp.context["agenda_items"]] == ["t1"]
        assert [c["uid"] for c in resp.context["contacts"]] == ["c1"]
        assert [d["uid"] for d in resp.context["notebook_documents"]["documents"]] == ["n1"]
        assert [t["uid"] for t in resp.context["columns"]["active"]] == ["t1"]
        assert "kanban-board" not in body
        board = _page(conn, "Gym", "board")
        assert "kanban-board" in board.body.decode() and 'src="/static/tasks_board.js' in board.body.decode()
        assert "Contacts</h2>" in body and "Next</h2>" in body and "Notebook</h2>" in body

    def test_switched_off_sections_are_not_rendered(self, conn):
        self._seed(conn, agenda_widget=0, contacts_widget=0, notebook_widget=0)
        resp = _page(conn, "Gym")
        body = resp.body.decode()
        assert resp.context["agenda_items"] == [] and resp.context["contacts"] == []
        assert resp.context["notebook_documents"] == {}
        assert "Next</h2>" not in body and "Contacts</h2>" not in body and "Notebook</h2>" not in body

    def test_no_kanban_means_no_board_script(self, conn):
        self._seed(conn, tasks_widget=0)
        body = _page(conn, "Gym").body.decode()
        assert "kanban-board" not in body
        assert 'src="/static/tasks_board.js' not in body

    def test_everything_off_says_so(self, conn):
        self._seed(conn, agenda_widget=0, contacts_widget=0, notebook_widget=0, tasks_widget=0)
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
        assert resp.template.name == "label_sections.html"
        assert resp.context["label"]["name"] == "Uni"
        assert sorted(r["label"]["name"] for r in resp.context["group_members"]["rows"]) == ["Art", "Maths"]
        body = resp.body.decode()
        # 2026-09-26 (item 20): the old always-visible plain toolbar
        # (`class="toolbar group-labels"`) is gone -- replaced by a
        # `group_members` widget (2026-09-28: seeded as the quarter-width
        # third column of the page's 25/50/25 row, not a second pinned
        # full-width widget -- see test_group_members_widget.py for that
        # widget's own coverage); `href="/labels/Maths"` still holds, just
        # from the widget's own row link now.
        assert 'href="/labels/Maths"' in body
        assert 'class="toolbar group-labels"' not in body
        # 2026-09-28 (direct request, "always use card grid"): the widget
        # renders every row as a `filled_card` tile now, not a list.
        assert 'class="sec-row"' in body and " open" in body

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
            labels_router.create_label(new_name="group:Uni", color="blue", icon="", label_group="", conn=conn)


class TestStatusRow:
    def test_plain_label_has_no_status_row(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        resp = _page(conn, "Gym")
        assert resp.context["label_status"] is None
        assert "label-status" not in resp.body.decode()

    def test_label_with_a_deadline_is_active_until_archived(self, conn):
        db.upsert_label_config(conn, {"name": "Essay", "has_deadline": 1, "deadline_date": "2020-01-01"})
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "done",
                              "tags": ["Essay"], "created_at": _now()})
        resp = _page(conn, "Essay")
        body = resp.body.decode()
        assert resp.context["label_status"] == "Active" and "label-deadline" in body
        assert 'action="/labels/Essay/archive"' not in body

    def test_archived_label_offers_unarchive(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        db.archive_project(conn, "Trip")
        body = _page(conn, "Trip").body.decode()
        assert "Archived on" in body
        assert "/archive" not in body

    def test_status_row_is_on_the_dashboard_page_too(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1, "agenda_widget": 0, "has_deadline": 1, "deadline_date": "2099-01-01"})
        resp = _page(conn, "Trip")
        assert resp.template.name == "label_sections.html"
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


class TestFormFields:
    def _update(self, conn, **kw):
        base = dict(name="Gym", new_name="Gym", color="blue", icon="", label_group="", description="")
        base.update(kw)
        return labels_router.update_label(**base, conn=conn)

    def test_update_writes_deadline_and_page_fields(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        self._update(conn, page_fields="1", deadline_date="2026-12-01", page_type="dashboard",
                     agenda_widget="1", tasks_widget="", contacts_widget="1", notebook_widget="1")
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["has_deadline"] is True and cfg["deadline_date"] == "2026-12-01"
        assert cfg["page_type"] == "dashboard"
        assert (cfg["agenda_widget"], cfg["tasks_widget"], cfg["contacts_widget"], cfg["notebook_widget"]) == (True, False, True, True)

    def test_empty_deadline_clears_it(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_deadline": 1, "deadline_date": "2026-12-01"})
        self._update(conn, page_fields="1", deadline_date="")
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["has_deadline"] is False and cfg["deadline_date"] is None

    def test_without_the_marker_page_fields_are_left_alone(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "page_type": "dashboard", "has_deadline": 1, "deadline_date": "2026-12-01"})
        self._update(conn)
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["page_type"] == "dashboard" and cfg["deadline_date"] == "2026-12-01"
        assert cfg["agenda_widget"] is True and cfg["tasks_widget"] is True

    def test_bad_deadline_is_rejected(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        with pytest.raises(HTTPException) as exc:
            self._update(conn, page_fields="1", deadline_date="soon")
        assert exc.value.status_code == 400

    def test_create_writes_page_fields(self, conn):
        labels_router.create_label(new_name="Essay", color="blue", icon="", label_group="", page_fields="1", deadline_date="2026-11-30", agenda_widget="1", conn=conn)
        cfg = db.effective_label_config(conn, "Essay")
        assert cfg["deadline_date"] == "2026-11-30" and cfg["page_type"] == "sections"
        assert (cfg["agenda_widget"], cfg["tasks_widget"], cfg["contacts_widget"], cfg["notebook_widget"]) == (True, False, False, False)

    def test_edit_modal_renders_the_new_fields(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_deadline": 1, "deadline_date": "2026-12-01", "page_type": "dashboard"})
        body = labels_router.edit_label_modal("Gym", _request("/settings/labels/Gym/edit"), conn=conn).body.decode()
        assert 'name="page_fields" value="1"' in body
        assert 'name="deadline_date"' in body and "2026-12-01" in body
        assert 'name="page_type"' not in body
        assert 'name="start_date"' not in body and 'name="end_date"' not in body

    def test_update_writes_group_and_pins(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        self._update(conn, label_group="  Health ", page_fields="1", sidebar_pin="1", widget_pin="")
        cfg = db.effective_label_config(conn, "Gym")
        assert cfg["label_group"] == "Health"
        assert cfg["sidebar_pin"] is True and cfg["widget_pin"] is False

    def test_new_label_modal_defaults_all_sections_on(self, conn):
        body = labels_router.new_label_modal(_request("/settings/labels/new"), conn=conn).body.decode()
        for name in ("agenda_widget", "tasks_widget", "contacts_widget", "notebook_widget"):
            assert _checked(body, name, "1")
        assert 'name="page_type"' not in body
        assert '<span class="ms-summary">Agenda, Tasks, Contacts, Notebook</span>' in body


class TestSettingsLabelsTable:
    """Settings > Labels (2026-09-26, second pass -- row-hover on this page
    was broken by the group section rows/hidden columns): flat, no section
    rows -- `labels` sorts by group name (ungrouped last), then by name;
    each carries `group_style` for its row's Group pill.

    2026-09-29 (direct request, "redo the projects table from settings to
    be without grouping and be like the labels one"): Settings > Projects
    is flat now too -- no more per-group header row/"No group" divider,
    same sort as Labels. Its own Due column (project-specific) is
    unchanged; it just doesn't get a Group pill in that slot the way a
    plain label does, since Due already occupies it."""

    def test_context_sorts_flat_grouped_then_ungrouped(self, conn):
        db.upsert_label_config(conn, {"name": "Zeta", "label_group": "Uni"})
        db.upsert_label_config(conn, {"name": "Alpha", "label_group": "Uni"})
        db.upsert_label_config(conn, {"name": "Run", "label_group": "Health"})
        db.upsert_label_config(conn, {"name": "Loose"})
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        assert [l["name"] for l in ctx["labels"]] == ["Run", "Alpha", "Zeta", "Loose"]
        assert ctx["labels"][0]["group_style"]["color"] == "gray"  # Run: Health, default style
        assert "group_style" not in ctx["labels"][-1]  # Loose: no group
    def test_rendered_labels_table_has_no_group_section_rows(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni"})
        db.upsert_label_config(conn, {"name": "Loose"})
        body = labels_router.manage_labels(_request("/settings/labels"), conn=conn).body.decode()
        assert "entity-section-row" not in body
        assert 'data-label-name="Maths" data-label-group="Uni"' in body
        assert 'href="/groups/Uni/view"' in body and "Uni</a>" in body  # the row's Group pill
        assert ">No group<" in body  # Loose's Group cell

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

    def test_preview_agenda_leads_with_at_most_two_habits(self, conn):
        for n in range(3):
            db.upsert_task(conn, {"uid": f"h{n}", "title": f"Habit {n}", "description": "", "status": "active",
                                  "is_habit": 1, "tags": ["Essay"], "recurrence": "FREQ=DAILY", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Essay"], "due_at": "2099-01-01T00:00:00", "created_at": _now()})
        resp = label_pages.label_preview("Essay", _request("/labels/Essay/preview"), conn=conn)
        items = resp.context["agenda_items"]
        assert [i["kind"] for i in items] == ["habit", "habit", "task"]
        assert "Habit 0" in resp.body.decode()

    def test_preview_agenda_is_capped_at_eight(self, conn):
        for n in range(10):
            db.upsert_task(conn, {"uid": f"t{n}", "title": f"Task {n}", "description": "", "status": "active",
                                  "tags": ["Essay"], "due_at": f"2099-01-{n + 1:02d}T00:00:00", "created_at": _now()})
        resp = label_pages.label_preview("Essay", _request("/labels/Essay/preview"), conn=conn)
        assert len(resp.context["agenda_items"]) == 8

    def test_edit_modal_footer_archives_and_unarchives(self, conn):
        from src.routers import labels as labels_router
        db.upsert_label_config(conn, {"name": "Essay"})
        preview = label_pages.label_preview("Essay", _request("/labels/Essay/preview"), conn=conn).body.decode()
        assert "/archive" not in preview
        body = labels_router.edit_label_modal("Essay", _request("/settings/labels/Essay/edit"), conn=conn).body.decode()
        footer = body[body.index('class="modal-footer"'):]
        assert 'action="/labels/Essay/archive"' in footer and "modal-retire" in footer
        label_pages.archive_label("Essay", conn=conn)
        body = labels_router.edit_label_modal("Essay", _request("/settings/labels/Essay/edit"), conn=conn).body.decode()
        assert 'action="/labels/Essay/unarchive"' in body

    def test_detail_modal_tag_pills_are_plain_because_tags_have_no_pages(self, conn):
        from src.routers import tasks as tasks_router
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Road trip"], "created_at": _now()})
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        # 2026-09-25 (UI audit L11): the task modal's own URL rides along
        # as `from`, so the preview can offer "Back" to it.
        assert "Road trip" in body and "/labels/Road%20trip/preview" not in body

    def test_kanban_card_shows_each_tag_as_an_icon_pill(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        db.upsert_label_config(conn, {"name": "Legs", "is_project": 1})
        db.upsert_task(conn, {"uid": "t1", "title": "Squats", "description": "", "status": "active",
                              "tags": ["Gym", "Legs"], "created_at": _now()})
        body = _page(conn, "Gym", "board").body.decode()
        assert 'title="Gym"' in body and 'title="Legs"' in body
        assert "/labels/Gym/preview" not in body  # tags have no pages

    def test_tasks_table_shelf_headers_and_tag_pills_link_to_the_shelf_page(self, conn):
        """The shelf header is a plain link to the shelf page; a tag pill links to that page filtered by the tag."""
        from src.routers import tasks as tasks_router
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Gym", "Home"], "created_at": _now()})
        body = tasks_router.list_tasks(_request("/tasks"), conn=conn).body.decode()
        assert '<a class="shelf-link" href="/labels/Gym">Gym</a>' in body
        assert 'href="/labels/Gym?tag=Gym"' in body

    def test_pills_inside_other_controls_stay_plain(self, conn):
        """The still-live case the class docstring describes: a label
        picker's own option pill (_widget_list_multiselect.html's
        `ms_pill`, e.g. the task edit form's Labels field) sits inside a
        `<label class="multiselect-option">` whose click must toggle its
        checkbox, so it stays a plain (linkless) `label_pill`."""
        from src.routers import tasks as tasks_router
        db.upsert_task(conn, {"uid": "t1", "title": "Draft", "description": "", "status": "active",
                              "tags": ["Gym"], "created_at": _now()})
        body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
        assert "/labels/Gym/preview" not in body


def _checked(body: str, name: str, value: str) -> bool:
    """A multiselect-partial input (attributes split over lines) is checked."""
    return bool(re.search(r'name="%s" value="%s"[^>]*\bchecked\b' % (re.escape(name), re.escape(value)), body))


class TestAgendaView:
    def test_agenda_view_lists_overdue_tasks_and_the_deadline(self, conn):
        soon = (date.today() + timedelta(days=5)).isoformat()
        old = (date.today() - timedelta(days=2)).isoformat()
        db.upsert_label_config(conn, {"name": "Essay", "has_deadline": 1, "deadline_date": soon})
        db.upsert_task(conn, {"uid": "t9", "title": "Late draft", "description": "", "status": "active",
                              "tags": ["Essay"], "created_at": _now(), "due_at": old})
        resp = _page(conn, "Essay", "agenda")
        names = {s["title"]: [x["item"]["title"] for x in s["entries"]] for s in resp.context["agenda_sections"]}
        assert names["Overdue"] == ["Late draft"]
        assert any("Essay deadline" in v for v in sum(names.values(), []))
