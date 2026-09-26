"""UI audit 2026-09-25, labels area (documentation/plans/ui-audit-2026-09-25.md,
the L- table + F18, and flesh-out items 5-7): deadline states, the label
page's header actions / archived line / combined empty state, quick-add
prefill, group identity, the Description field, icon fallback, the task
modal's Project row, and the CSS behind the contrast/indent fixes.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import re

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db, deps
from src.routers import dashboard as dashboard_router
from src.routers import label_pages
from src.routers import labels as labels_router

CSS = (Path(__file__).resolve().parents[1] / "src" / "static" / "style.css").read_text()


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "cache.sqlite"


@pytest.fixture()
def conn(db_path):
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/labels/X", query=b""):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": query,
        "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
    })


def _page(conn, name):
    return label_pages.label_page(name, _request(f"/labels/{name}"), conn=conn)


def _task(conn, uid, tags, status="active"):
    db.upsert_task(conn, {"uid": uid, "title": uid, "description": "", "status": status,
                          "tags": tags, "created_at": _now()})


class TestDeadlineInfo:
    """L6: red only when overdue, orange within 7 days, neutral later."""

    TODAY = date(2026, 9, 25)

    def _info(self, deadline, **extra):
        return label_pages.deadline_info({"has_deadline": 1, "deadline_date": deadline, **extra}, today=self.TODAY)

    def test_no_deadline(self):
        assert label_pages.deadline_info({"has_deadline": 0}, today=self.TODAY) is None

    def test_overdue_is_red(self):
        info = self._info("2026-09-10")
        assert info["state"] == "overdue" and info["color"] == "red"
        assert info["text"] == "Overdue · 10 Sep"
        assert info["short"] == "overdue since 10 Sep"

    def test_within_a_week_is_orange(self):
        assert self._info("2026-09-25")["text"] == "Due today"
        assert self._info("2026-09-26")["text"] == "Due tomorrow"
        info = self._info("2026-09-30")
        assert info["state"] == "soon" and info["color"] == "orange"
        assert info["text"] == "Due in 5 days · 30 Sep"

    def test_later_is_neutral(self):
        info = self._info("2026-10-15")
        assert info["state"] == "later" and info["color"] == "gray" and info["text"] == "Due 15 Oct"

    def test_year_shown_when_different(self):
        assert self._info("2027-01-05")["text"] == "Due 5 Jan 2027"

    def test_archived_is_neutral_history(self):
        info = self._info("2026-09-10", archived_at=_now())
        assert info["state"] == "archived" and info["color"] == "gray"

    def test_overdue_project_page_says_overdue(self, conn):
        db.upsert_label_config(conn, {"name": "Old", "is_project": 1, "has_dashboard": 0,
                                      "has_deadline": 1, "deadline_date": "2020-01-01"})
        _task(conn, "t1", ["Old"])
        body = _page(conn, "Old").body.decode()
        assert "Overdue · 1 Jan 2020" in body
        assert "tag-red label-deadline is-overdue" in body

    def test_preview_modal_uses_the_state(self, conn):
        db.upsert_label_config(conn, {"name": "Old", "is_project": 1, "has_deadline": 1, "deadline_date": "2020-01-01"})
        body = label_pages.label_preview("Old", _request("/labels/Old/preview"), conn=conn).body.decode()
        assert "overdue since 1 Jan 2020" in body


class TestLabelPageActions:
    def test_header_has_edit_and_archive(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        _task(conn, "t1", ["Gym"])
        body = _page(conn, "Gym").body.decode()
        assert 'href="/settings/labels/Gym/edit" data-modal' in body and "Edit label" in body
        assert 'action="/labels/Gym/archive"' in body

    def test_dashboard_page_header_has_them_too(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "has_dashboard": 1})
        body = _page(conn, "Gym").body.decode()
        assert "Edit label" in body and 'action="/labels/Gym/archive"' in body

    def test_archived_plain_label_shows_archived_on_line(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        _task(conn, "t1", ["Gym"])
        label_pages.archive_label("Gym", conn=conn)
        body = _page(conn, "Gym").body.decode()
        today = date.today()
        assert f"Archived on {today.day} {today.strftime('%b')} {today.year}" in body
        assert 'action="/labels/Gym/unarchive"' in body
        assert 'action="/labels/Gym/archive"' not in body

    def test_archiving_a_usage_only_label_creates_its_config(self, conn):
        _task(conn, "t1", ["Loose"])
        label_pages.archive_label("Loose", conn=conn)
        assert db.get_label_config(conn, "Loose")["archived_at"]

    def test_group_page_offers_edit_group_not_edit_label(self, conn):
        db.upsert_label_config(conn, {"name": "Art", "label_group": "Uni"})
        body = label_pages.group_page("Uni", _request("/groups/Uni"), conn=conn).body.decode()
        assert 'href="/groups/Uni/edit" data-modal' in body
        assert "Edit label" not in body


class TestEmptyState:
    def test_nothing_tagged_shows_one_empty_state(self, conn):
        db.upsert_label_config(conn, {"name": "New One"})
        body = _page(conn, "New One").body.decode()
        assert "Nothing tagged New One yet" in body
        for tab in ("task", "event", "contact"):
            assert f'/quick/add?label=New%20One&amp;default_tab={tab}' in body
        # ...instead of the three separate empties.
        assert "kanban-board" not in body
        assert "No contacts" not in body

    def test_tagged_label_has_no_empty_state(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        _task(conn, "t1", ["Gym"])
        body = _page(conn, "Gym").body.decode()
        assert "Nothing tagged" not in body
        assert "kanban-board" in body
        # L12: the board has a heading, and Contacts' empty text names the label.
        assert "label-section-heading" in body
        assert "No contacts tagged Gym yet." in body
        assert "No contacts match this filter." not in body


class TestQuickAddPrefill:
    def test_label_prefills_task_event_and_contact(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        resp = dashboard_router.quick_add_form(_request("/quick/add"), default_tab="task", scope="", label="Gym", conn=conn)
        assert resp.context["prefill_tags"] == ["Gym"]
        body = resp.body.decode()
        # Selected in each of the three Labels pickers (task, event, contact).
        import re

        checked = re.findall(r'<input[^>]*value="Gym"[^>]*form="(\w+)-form"[^>]*checked', body)
        assert checked == ["task", "event", "contact"]

    def test_project_label_lands_in_the_project_dropdown(self, conn):
        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        resp = dashboard_router.quick_add_form(_request("/quick/add"), default_tab="task", scope="", label="Trip", conn=conn)
        assert resp.context["prefill_tags"] == ["Trip"]
        assert "project-field" in resp.body.decode()


class TestUnknownLabel:
    def test_page_redirects(self, conn):
        resp = _page(conn, "Nope")
        assert resp.status_code == 303 and resp.headers["location"] == "/settings/labels"

    def test_preview_404s(self, conn):
        with pytest.raises(HTTPException) as exc:
            label_pages.label_preview("Nope", _request("/labels/Nope/preview"), conn=conn)
        assert exc.value.status_code == 404


class TestPreviewBack:
    def test_from_a_task_modal_offers_back(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        resp = label_pages.label_preview("Gym", _request("/labels/Gym/preview", b"from=/tasks/t1"), conn=conn)
        body = resp.body.decode()
        assert resp.context["back_to"] == "/tasks/t1"
        assert 'href="/tasks/t1" class="btn ghost" data-modal' in body

    def test_offsite_from_is_ignored(self, conn):
        db.upsert_label_config(conn, {"name": "Gym"})
        resp = label_pages.label_preview("Gym", _request("/labels/Gym/preview", b"from=//evil.example"), conn=conn)
        assert resp.context["back_to"] == ""


class TestGroupIdentity:
    def test_style_round_trip_and_default(self, conn):
        db.upsert_label_config(conn, {"name": "Art", "label_group": "Uni"})
        assert db.get_group_style(conn, "Uni") == {"icon": None, "color": "gray"}
        label_pages.update_group("Uni", color="red", icon="school", conn=conn)
        assert db.get_group_style(conn, "Uni") == {"icon": "school", "color": "red"}
        assert db.list_groups(conn)[0]["icon"] == "school"

    def test_bad_color_falls_back_and_unknown_group_404s(self, conn):
        db.upsert_label_config(conn, {"name": "Art", "label_group": "Uni"})
        label_pages.update_group("Uni", color="neon", icon="", conn=conn)
        assert db.get_group_style(conn, "Uni") == {"icon": None, "color": "gray"}
        with pytest.raises(HTTPException):
            label_pages.update_group("Nope", color="red", icon="", conn=conn)

    def test_edit_modal_renders(self, conn):
        db.upsert_label_config(conn, {"name": "Art", "label_group": "Uni"})
        body = label_pages.edit_group_modal("Uni", _request("/groups/Uni/edit"), conn=conn).body.decode()
        assert 'action="/groups/Uni/update"' in body

    def test_rail_uses_group_icon_or_default_glyph(self):
        # 2026-09-26 (Peter): no first-letter chip -- the default glyph.
        base = (Path(__file__).resolve().parents[1] / "src" / "templates" / "base.html").read_text()
        assert "sidebar-group-monogram" not in base and "icon(g.icon or 'layers')" in base
        assert "{{ icon('layers') }}<span>{{ g.name }}" not in base

    def test_nav_icons_reserved_in_the_label_picker(self):
        offered = {n for names in labels_router.LABEL_ICON_GROUPS.values() for n in names}
        assert not offered & {"home", "calendar", "check-square", "address-book", "settings"}
        # Habits keep the full list.
        assert "home" in labels_router.LABEL_ICONS
        # A label that already has one keeps it as an option.
        assert labels_router.icon_groups_for("home")["Current"] == ["home"]


class TestDescriptionField:
    def test_form_has_the_field(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "description": "Lift things"})
        body = labels_router.edit_label_modal("Gym", _request("/settings/labels/Gym/edit"), conn=conn).body.decode()
        assert 'name="description"' in body and "Lift things</textarea>" in body

    def test_create_and_update_save_it(self, conn):
        labels_router.create_label(new_name="Gym", color="blue", icon="", label_group="", description="  Lift  ",
                                   role="none", conn=conn)
        assert db.get_label_config(conn, "Gym")["description"] == "Lift"
        labels_router.update_label("Gym", new_name="Gym", color="blue", icon="", label_group="", description="",
                                   role="none", conn=conn)
        assert db.get_label_config(conn, "Gym")["description"] is None


class TestIconFallback:
    def test_unknown_name_falls_back_to_tag(self):
        assert '#icon-tag"' in deps._icon("no-such-icon")
        assert '#icon-book"' in deps._icon("book")

    def test_markup_injection_is_not_possible(self):
        assert '"><script>' not in deps._icon('x"><script>')


class TestProjectRow:
    def test_task_modal_splits_project_from_labels(self, conn, db_path):
        from src.routers import tasks as tasks_router

        db.upsert_label_config(conn, {"name": "Trip", "is_project": 1})
        _task(conn, "t1", ["Trip", "Gym"])
        req = _request("/tasks/t1")
        req.scope["app"] = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path)))
        body = tasks_router.task_detail("t1", req, conn=conn).body.decode()
        proj = body.index(">Project</span>")
        labels = body.index(">Labels</span>")
        assert body.index("Trip", proj) < labels
        assert "Gym" in body[labels:]


class TestCss:
    def test_dark_theme_has_text_safe_label_colors(self):
        dark = CSS[CSS.index('[data-theme="dark"]{'):]
        assert "--cal-text-blue:#84aedb" in dark[:3000]
        assert "--cal-text-blue:#3675b9" in CSS

    def test_mobile_child_indent_beats_tab_btn_padding(self):
        assert ".tab-btn.tab-btn-child{padding-left:34px;}" in CSS

    def test_mobile_chevron_is_44px(self):
        assert ".sidebar-tree-toggle{display:flex; width:44px; height:44px;" in CSS

    def test_banner_icon_gets_a_white_chip(self):
        assert ".page-header-narrow.has-banner .page-header-narrow-icon.has-color{" in CSS

    def test_label_form_toggles_are_not_uppercase(self):
        rule = CSS[CSS.index(".label-page-fields label.field-toggle{"):][:200]
        assert "text-transform:none" in rule

    def test_member_rows_are_indented(self):
        # 2026-09-26: the shared .entity-table rules.
        assert ".entity-table .entity-row.is-member .label-cell{padding-left:24px;}" in CSS


def _grouped(conn, name, group):
    db.upsert_label_config(conn, {"name": name, "label_group": group, "created_at": _now()})


def _post_req(referer: str = ""):
    headers = [(b"referer", referer.encode())] if referer else []
    return Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                    "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": headers})


class TestGroupRenameAndMembers:
    """2026-09-25 flesh-out item 7: the Edit group modal renames a group
    and picks its members (used to mean editing each label's Group field)."""

    def test_rename_moves_members_dashboard_banner_and_look(self, conn):
        _grouped(conn, "Family", "People")
        _grouped(conn, "Friends", "People")
        old_key, new_key = db.group_page_key("People"), db.group_page_key("Crew")
        db.upsert_dashboard_widget(conn, {"uid": "w1", "type": "agenda", "label_name": old_key,
                                          "config": {"label_name": old_key}, "position": 1})
        # a Home widget scoped to the group follows the rename too
        db.upsert_dashboard_widget(conn, {"uid": "w2", "type": "agenda", "label_name": None,
                                          "config": {"label_name": old_key}, "position": 2})
        db.set_app_meta(conn, f"dashboard_label_{old_key}_seeded_v1", "1")
        db.set_group_style(conn, "People", "users", "orange")
        assert db.rename_group(conn, "People", "Crew") == "Crew"
        assert db.group_member_names(conn, "Crew") == ["Family", "Friends"]
        assert db.group_member_names(conn, "People") == []
        rows = {r["uid"]: dict(r) for r in conn.execute("SELECT uid, label_name, config_json FROM dashboard_widgets")}
        assert rows["w1"]["label_name"] == new_key and new_key in rows["w1"]["config_json"]
        assert rows["w2"]["label_name"] is None and new_key in rows["w2"]["config_json"]
        assert db.get_app_meta(conn, f"dashboard_label_{new_key}_seeded_v1") == "1"
        assert db.get_group_style(conn, "Crew") == {"icon": "users", "color": "orange"}

    def test_rename_onto_an_existing_group_merges_into_it(self, conn):
        _grouped(conn, "Family", "People")
        _grouped(conn, "Reading", "Hobbies")
        db.set_group_style(conn, "Hobbies", "book", "slate")
        assert db.rename_group(conn, "People", "hobbies") == "Hobbies"
        assert db.group_member_names(conn, "Hobbies") == ["Family", "Reading"]
        assert db.get_group_style(conn, "Hobbies")["icon"] == "book"  # the target keeps its look

    def test_set_members_moves_labels_and_rejects_empty(self, conn):
        _grouped(conn, "Family", "People")
        _grouped(conn, "Reading", "Hobbies")
        db.set_group_members(conn, "People", ["Reading", "Work"])  # Work has no config row yet
        assert db.group_member_names(conn, "People") == ["Reading", "Work"]
        assert db.group_member_names(conn, "Hobbies") == []
        assert (db.get_label_config(conn, "Family") or {}).get("label_group") is None
        # 2026-09-26: groups are standalone -- emptying one keeps it.
        db.set_group_members(conn, "People", [])
        assert db.group_member_names(conn, "People") == [] and db.get_group(conn, "People")

    def test_update_route_renames_sets_members_and_redirects_to_new_page(self, conn):
        _grouped(conn, "Family", "People")
        _grouped(conn, "Work", None)
        resp = label_pages.update_group("People", color="green", icon="", new_name="Crew",
                                        members=["Family", "Work"], members_submitted="1", conn=conn)
        assert resp.headers["location"] == "/groups/Crew"
        assert db.group_member_names(conn, "Crew") == ["Family", "Work"]
        assert db.get_group_style(conn, "Crew")["color"] == "green"

    def test_update_route_ignores_posts_without_the_checklist_and_may_empty(self, conn):
        _grouped(conn, "Family", "People")
        label_pages.update_group("People", color="gray", icon="", new_name="", members=[],
                                 members_submitted="", conn=conn)
        assert db.group_member_names(conn, "People") == ["Family"]
        # 2026-09-26: an empty member list empties the group; it stays.
        label_pages.update_group("People", color="gray", icon="", new_name="", members=[],
                                 members_submitted="1", conn=conn)
        assert db.group_member_names(conn, "People") == [] and db.get_group(conn, "People")

    def test_edit_modal_lists_candidates_with_their_current_group(self, conn):
        _grouped(conn, "Family", "People")
        _grouped(conn, "Reading", "Hobbies")
        body = label_pages.edit_group_modal("People", _request("/groups/People/edit"), conn=conn).body.decode()
        assert 'name="new_name" value="People"' in body
        # 2026-09-26: the Labels checkbox dropdown.
        assert re.search(r'name="members" value="Family"[^>]*\bchecked', body)
        assert "Reading (in Hobbies)" in body
        assert "data-follow-redirect" in body


class TestLabelRenameFromItsOwnPage:
    def test_rename_from_label_page_redirects_to_the_new_page(self, conn):
        db.upsert_label_config(conn, {"name": "Reading", "created_at": _now()})
        resp = labels_router.update_label("Reading", new_name="Books", color="blue", icon="", label_group="",
                                          description="", role="none", request=_post_req(
            "http://testserver/labels/Reading"), conn=conn)
        assert resp.headers["location"] == "/labels/Books"

    def test_rename_from_elsewhere_still_lands_on_the_labels_list(self, conn):
        db.upsert_label_config(conn, {"name": "Reading", "created_at": _now()})
        resp = labels_router.update_label("Reading", new_name="Books", color="blue", icon="", label_group="",
                                          description="", role="none", request=_post_req(
            "http://testserver/settings/labels"), conn=conn)
        assert resp.headers["location"] == "/settings/labels"

    def test_modal_js_follows_a_redirect_to_a_different_page_when_asked(self):
        script = (Path(__file__).resolve().parent.parent / "src" / "static" / "modal.js").read_text()
        assert 'form.hasAttribute("data-follow-redirect") && resp.redirected' in script


class TestGroupsAndLabelsWidget:
    """2026-09-25 (audit flesh-out item 5): the Groups & Labels widget shows
    each pinned label's deadline state; group cards use the group's look."""

    def test_list_rows_carry_deadline_state(self, conn):
        soon = (date.today().toordinal() + 3)
        db.upsert_label_config(conn, {"name": "Health", "widget_pin": 1, "has_deadline": 1,
                                      "deadline_date": date.fromordinal(soon).isoformat(), "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Work", "widget_pin": 1, "created_at": _now()})
        data = dashboard_router._render_spaces_projects(conn, {"style": "list"})
        by_name = {p["project"]["name"]: p["deadline"] for p in data["previews"]}
        assert by_name["Health"]["state"] == "soon" and by_name["Health"]["color"] == "orange"
        assert by_name["Work"] is None

    def test_group_cards_use_the_group_style_and_label_cards_the_deadline(self, conn):
        _grouped(conn, "Family", "People")
        db.set_group_style(conn, "People", "users", "orange")
        db.upsert_label_config(conn, {"name": "Launch", "widget_pin": 1, "is_project": 1, "has_deadline": 1,
                                      "deadline_date": "2020-01-01", "created_at": _now()})
        cards = {c["name"]: c for c in dashboard_router._render_spaces_projects(conn, {"style": "cards"})["cards"]}
        assert (cards["People"]["icon"], cards["People"]["color"]) == ("users", "orange")
        assert cards["Launch"]["deadline"]["state"] == "overdue"
