"""Tests for routers/projects.py (Phase 3 of the projects/tags rework):
manage-page CRUD, groups, archive/unarchive/merge/delete, the cover-image
upload helper, and _project_scope's aggregation of tasks/events/contacts
from every list linked to a project. No bridge/Radicale dependency at all
here -- projects are entirely local (see db.py's `projects` table
comment), so these call the router functions directly with asyncio.run
for the two async (file-upload-capable) endpoints, no TestClient or live
server needed."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src import db
from src.routers import projects as projects_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_project(conn, **kwargs):
    # list_projects sorts by name, so grabbing [0] after creation would
    # silently return the wrong project once more than one exists (e.g.
    # creating "B" after "A" -- "A" still sorts first). Find by name
    # instead of assuming insertion order/position.
    defaults = dict(name="Test", color="blue", icon="", group_uid="")
    defaults.update(kwargs)
    asyncio.run(projects_router.create_project(conn=conn, **defaults))
    name = defaults["name"].strip()
    return next(p for p in db.list_projects(conn) if p["name"] == name)


class FakeUploadFile:
    """Minimal stand-in for fastapi.UploadFile -- just enough surface
    (.filename, .content_type, async .read()) for _read_cover_image."""

    def __init__(self, filename: str, content_type: str, data: bytes):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


class TestCreateProject:
    def test_creates_with_defaults(self, conn):
        p = _create_project(conn, name="University", color="purple", icon="🎓")
        assert p["name"] == "University"
        assert p["color"] == "purple"
        assert p["icon"] == "🎓"
        assert p["archived_at"] is None
        assert p["description"] == ""

    def test_blank_name_is_a_noop(self, conn):
        asyncio.run(projects_router.create_project(name="   ", color="blue", icon="", group_uid="", conn=conn))
        assert db.list_projects(conn) == []


class TestEditProject:
    def test_edit_updates_fields_and_preserves_unset_ones(self, conn):
        p = _create_project(conn, name="Uni", color="blue")
        asyncio.run(
            projects_router.edit_project(
                p["uid"], name="University", description="School stuff", color="purple",
                icon="🎓", group_uid="", cover_image=None, remove_cover_image="", conn=conn,
            )
        )
        updated = db.get_project(conn, p["uid"])
        assert updated["name"] == "University"
        assert updated["description"] == "School stuff"
        assert updated["color"] == "purple"
        assert updated["icon"] == "🎓"

    def test_default_redirect_lands_on_the_project_detail_page(self, conn):
        # Unchanged behavior for project_detail.html's own "Edit project"
        # panel, which never sends return_to.
        p = _create_project(conn, name="Uni")
        resp = asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni", description="", color="blue", icon="",
                group_uid="", cover_image=None, remove_cover_image="", conn=conn,
            )
        )
        assert resp.headers["location"] == f"/projects/{p['uid']}"

    def test_return_to_keeps_you_on_the_manage_page(self, conn):
        # 2026-08-02 regression test -- projects_manage.html's per-row
        # autosubmit color/icon/name/Space pickers post return_to=
        # "/projects" precisely so picking a color doesn't redirect the
        # whole page away to the project's own detail page (previously
        # the *only* possible redirect target, which read as "clicking
        # the color/icon picker just opens the project").
        p = _create_project(conn, name="Uni")
        resp = asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni", description="", color="purple", icon="",
                group_uid="", cover_image=None, remove_cover_image="", return_to="/projects", conn=conn,
            )
        )
        assert resp.headers["location"] == "/projects"
        assert db.get_project(conn, p["uid"])["color"] == "purple"

    def test_return_to_rejects_a_non_internal_path(self, conn):
        # Belt-and-suspenders against return_to being turned into an open
        # redirect via a crafted form post -- only an absolute internal
        # path (starts with "/") is honored, anything else falls back to
        # the safe default.
        p = _create_project(conn, name="Uni")
        resp = asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni", description="", color="blue", icon="",
                group_uid="", cover_image=None, remove_cover_image="",
                return_to="https://evil.example/", conn=conn,
            )
        )
        assert resp.headers["location"] == f"/projects/{p['uid']}"

    def test_edit_with_no_new_cover_image_preserves_existing_one(self, conn):
        p = _create_project(conn, name="Uni")
        asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni", description="", color="blue", icon="",
                group_uid="", cover_image=FakeUploadFile("cover.png", "image/png", b"\x89PNG\r\n"),
                remove_cover_image="", conn=conn,
            )
        )
        with_cover = db.get_project(conn, p["uid"])
        assert with_cover["cover_image_b64"]
        assert with_cover["cover_image_type"] == "image/png"

        # A second edit that doesn't touch the file input must not wipe it.
        asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni Renamed", description="", color="blue", icon="",
                group_uid="", cover_image=None, remove_cover_image="", conn=conn,
            )
        )
        still_has_cover = db.get_project(conn, p["uid"])
        assert still_has_cover["cover_image_b64"] == with_cover["cover_image_b64"]
        assert still_has_cover["name"] == "Uni Renamed"

    def test_remove_cover_image_flag_clears_it(self, conn):
        p = _create_project(conn, name="Uni")
        asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni", description="", color="blue", icon="",
                group_uid="", cover_image=FakeUploadFile("cover.png", "image/png", b"\x89PNG\r\n"),
                remove_cover_image="", conn=conn,
            )
        )
        asyncio.run(
            projects_router.edit_project(
                p["uid"], name="Uni", description="", color="blue", icon="",
                group_uid="", cover_image=None, remove_cover_image="1", conn=conn,
            )
        )
        cleared = db.get_project(conn, p["uid"])
        assert cleared["cover_image_b64"] is None
        assert cleared["cover_image_type"] is None

    def test_unsupported_image_type_rejected(self, conn):
        from fastapi import HTTPException

        p = _create_project(conn, name="Uni")
        with pytest.raises(HTTPException):
            asyncio.run(
                projects_router.edit_project(
                    p["uid"], name="Uni", description="", color="blue", icon="",
                    group_uid="", cover_image=FakeUploadFile("virus.exe", "application/octet-stream", b"x"),
                    remove_cover_image="", conn=conn,
                )
            )

    def test_oversized_image_rejected(self, conn):
        from fastapi import HTTPException

        p = _create_project(conn, name="Uni")
        too_big = b"x" * (projects_router._MAX_COVER_BYTES + 1)
        with pytest.raises(HTTPException):
            asyncio.run(
                projects_router.edit_project(
                    p["uid"], name="Uni", description="", color="blue", icon="",
                    group_uid="", cover_image=FakeUploadFile("big.png", "image/png", too_big),
                    remove_cover_image="", conn=conn,
                )
            )


class TestArchiveUnarchiveMergeDelete:
    def test_archive_hides_from_list_projects_default(self, conn):
        p = _create_project(conn, name="A")
        projects_router.archive_project(p["uid"], conn=conn)
        assert db.list_projects(conn) == []
        assert db.get_project(conn, p["uid"])["archived_at"] is not None

    def test_unarchive_restores(self, conn):
        p = _create_project(conn, name="A")
        projects_router.archive_project(p["uid"], conn=conn)
        projects_router.unarchive_project(p["uid"], conn=conn)
        assert len(db.list_projects(conn)) == 1

    def test_merge_repoints_linked_lists(self, conn):
        a = _create_project(conn, name="A")
        b = _create_project(conn, name="B")
        db.ensure_default_task_list(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, a["uid"])
        projects_router.merge_project(a["uid"], dest_uid=b["uid"], conn=conn)
        assert db.get_project(conn, a["uid"]) is None
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] == b["uid"]

    def test_merge_into_self_is_a_noop(self, conn):
        a = _create_project(conn, name="A")
        projects_router.merge_project(a["uid"], dest_uid=a["uid"], conn=conn)
        assert db.get_project(conn, a["uid"]) is not None

    def test_delete_unassigns_but_keeps_linked_lists(self, conn):
        p = _create_project(conn, name="A")
        db.ensure_default_task_list(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, p["uid"])
        projects_router.delete_project(p["uid"], conn=conn)
        assert db.get_project(conn, p["uid"]) is None
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID) is not None
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] is None


class TestMergeModal:
    """GET /projects/{uid}/merge (2026-08-02 -- "merge into to be a
    button ... that creates a modal window with information of the
    merged and the merger and a merge button there"). Replaces the old
    bare inline dropdown; POST /{uid}/merge itself (tested above) is
    unchanged."""

    def _request(self):
        from starlette.requests import Request

        return Request({"type": "http", "method": "GET", "path": "/projects/x/merge", "headers": []})

    def test_shows_source_project_and_candidate_destinations_with_task_counts(self, conn):
        a = _create_project(conn, name="A")
        b = _create_project(conn, name="B")
        db.upsert_task_list(conn, {"uid": "hw", "name": "HW", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", a["uid"])
        db.upsert_task(conn, {
            "uid": "t1", "href": "/t1", "calendar_path": "tasks", "list_path": "hw",
            "title": "t1", "description": "", "status": "active", "tags": [], "created_at": _now(),
        })

        resp = projects_router.merge_project_modal(a["uid"], self._request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["project"]["uid"] == a["uid"]
        assert resp.context["project_tasks_total"] == 1
        assert [c["uid"] for c in resp.context["candidates"]] == [b["uid"]]
        assert resp.context["candidates"][0]["tasks_total"] == 0

    def test_excludes_the_source_project_itself_from_candidates(self, conn):
        a = _create_project(conn, name="A")
        resp = projects_router.merge_project_modal(a["uid"], self._request(), conn=conn)
        assert resp.context["candidates"] == []

    def test_unknown_uid_redirects_to_projects(self, conn):
        resp = projects_router.merge_project_modal("does-not-exist", self._request(), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"


class TestProjectListsModal:
    """GET /projects/{uid}/lists (2026-08-02 -- "the lists is just a
    button. it opens a modal window"): the actual linked/unclaimed task
    list/calendar/address book markup, moved out of the manage page's own
    per-row disclosure into its own modal, reusing _list_collections_
    by_project the exact same way manage_projects does for its "Lists (N)"
    button count."""

    def _request(self):
        from starlette.requests import Request

        return Request({"type": "http", "method": "GET", "path": "/projects/x/lists", "headers": []})

    def test_renders_with_linked_and_unclaimed_items(self, conn):
        p = _create_project(conn, name="Uni")
        db.upsert_task_list(conn, {"uid": "hw", "name": "HW", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", p["uid"])
        db.upsert_task_list(conn, {"uid": "errands", "name": "Errands", "color": "green", "created_at": _now()})

        resp = projects_router.project_lists_modal(p["uid"], self._request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["project"]["uid"] == p["uid"]
        assert [t["uid"] for t in resp.context["task_lists_by_project"][p["uid"]]] == ["hw"]
        assert [t["uid"] for t in resp.context["unclaimed_task_lists"]] == ["errands"]
        body = resp.body.decode()
        assert "HW" in body
        # 2026-08-02: no <select> anywhere in this modal anymore -- an
        # unclaimed item is its own clickable "pill-linkable" button
        # ("just buttons, not a lot of buttons or dropdown menus").
        assert "<select" not in body
        assert "pill-linkable" in body
        assert "Errands" in body
        assert 'id="modal-target"' in body

    def test_unknown_uid_redirects_to_projects(self, conn):
        resp = projects_router.project_lists_modal("does-not-exist", self._request(), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"


class TestNewProjectModal:
    """GET /projects/new-project (2026-08-02 -- "the new project could
    just be a + icon button that sits for each space"): a name-only modal
    replacing the inline text-input-and-button quick_add_project used to
    render directly on the manage page. Registered as a literal route
    ahead of the catch-all GET /{uid} (project_detail) further down this
    router -- both match exactly one path segment, so "new-project" would
    otherwise resolve as project_detail(uid="new-project") instead of
    this route if the ordering were reversed."""

    def _request(self):
        from starlette.requests import Request

        return Request({"type": "http", "method": "GET", "path": "/projects/new-project", "headers": []})

    def test_renders_with_no_group(self, conn):
        resp = projects_router.new_project_modal(self._request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["group"] is None
        assert resp.context["group_uid"] == ""
        assert 'id="modal-target"' in resp.body.decode()

    def test_renders_with_a_real_group(self, conn):
        projects_router.create_project_group(name="Uni", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        resp = projects_router.new_project_modal(self._request(), group_uid=group["uid"], conn=conn)
        assert resp.status_code == 200
        assert resp.context["group"]["uid"] == group["uid"]
        assert group["name"] in resp.body.decode()

    def test_route_precedes_the_catch_all_project_detail_route(self, conn):
        # Regression guard for the exact ordering hazard the class
        # docstring describes -- confirms the literal "/new-project" path
        # is registered on this router *before* GET /{uid}, not just that
        # calling the function directly works (which would pass even if
        # the decorator order were wrong, since that's a routing-table
        # concern, not a Python-call concern).
        import inspect

        source = inspect.getsource(projects_router)
        assert source.index('@router.get("/new-project")') < source.index('@router.get("/{uid}")')


class TestManageProjectsPage:
    """GET /projects (2026-08-02 manage-page rework -- "the projects
    grouped by spaces ... actually together and subordinated"): renders,
    and nests each Space's own projects under it instead of two separate
    flat sections."""

    def _request(self):
        from starlette.requests import Request

        return Request({"type": "http", "method": "GET", "path": "/projects", "headers": []})

    def test_renders(self, conn):
        resp = projects_router.manage_projects(self._request(), conn=conn)
        assert resp.status_code == 200

    def test_nests_projects_under_their_own_space(self, conn):
        projects_router.create_project_group(name="Uni", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        p_in = _create_project(conn, name="CS101", group_uid=group["uid"])
        p_out = _create_project(conn, name="Personal")

        resp = projects_router.manage_projects(self._request(), conn=conn)
        assert [p["uid"] for p in resp.context["projects_by_group"][group["uid"]]] == [p_in["uid"]]
        assert [p["uid"] for p in resp.context["ungrouped_projects"]] == [p_out["uid"]]
        assert resp.context["project_count"] == 2

    def test_a_space_with_no_projects_yet_still_gets_an_empty_list(self, conn):
        projects_router.create_project_group(name="Empty Space", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        resp = projects_router.manage_projects(self._request(), conn=conn)
        assert resp.context["projects_by_group"][group["uid"]] == []

    def test_passes_curated_icon_list(self, conn):
        resp = projects_router.manage_projects(self._request(), conn=conn)
        assert resp.context["project_icons"] == projects_router.PROJECT_ICONS
        assert len(resp.context["project_icons"]) > 0

    def test_buckets_linked_and_unclaimed_collections_per_project(self, conn):
        # 2026-08-02 -- "link specific webdav lists (calendar, tasks,
        # contacts) as subordinates for a project".
        p1 = _create_project(conn, name="Uni")
        p2 = _create_project(conn, name="Personal")
        db.upsert_task_list(conn, {"uid": "hw", "name": "HW", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", p1["uid"])
        db.upsert_task_list(conn, {"uid": "errands", "name": "Errands", "color": "green", "created_at": _now()})
        # "errands" stays unclaimed -- no set_task_list_project call.
        db.upsert_calendar(conn, {"uid": "classes", "name": "Classes", "color": "orange", "created_at": _now()})
        db.set_calendar_project(conn, "classes", p1["uid"])
        db.upsert_addressbook(conn, {"uid": "profs", "name": "Professors", "color": "purple", "created_at": _now()})
        db.set_addressbook_project(conn, "profs", p2["uid"])

        resp = projects_router.manage_projects(self._request(), conn=conn)
        assert [t["uid"] for t in resp.context["task_lists_by_project"][p1["uid"]]] == ["hw"]
        assert p2["uid"] not in resp.context["task_lists_by_project"]
        assert [t["uid"] for t in resp.context["unclaimed_task_lists"]] == ["errands"]
        assert [c["uid"] for c in resp.context["calendars_by_project"][p1["uid"]]] == ["classes"]
        assert resp.context["unclaimed_calendars"] == []
        assert [a["uid"] for a in resp.context["addressbooks_by_project"][p2["uid"]]] == ["profs"]
        assert resp.context["unclaimed_addressbooks"] == []

    def test_renders_with_a_linked_list_and_shows_the_lists_button_count(self, conn):
        # 2026-08-02: the manage page itself only shows a "Lists (N)"
        # button now (project_lists_modal.html has the actual linked-item
        # markup, tested separately below) -- "the lists is just a
        # button, it opens a modal window."
        p = _create_project(conn, name="Uni")
        db.upsert_task_list(conn, {"uid": "hw", "name": "HW", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", p["uid"])
        db.upsert_task_list(conn, {"uid": "errands", "name": "Errands", "color": "green", "created_at": _now()})

        resp = projects_router.manage_projects(self._request(), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert f'href="/projects/{p["uid"]}/lists"' in body
        assert "Lists (1)" in body
        assert "HW" not in body  # linked item names live in the modal, not here

    def test_curated_icon_list_only_uses_real_sprite_icon_names(self):
        # 2026-08-02: PROJECT_ICONS switched from a one-off emoji set to
        # keys into templates/_icons_sprite.html (the same library
        # {{ icon(name) }} draws from everywhere else) -- a typo'd name
        # here would silently render as a blank icon (an SVG <use> to a
        # symbol id that doesn't exist errors nowhere, it just draws
        # nothing), so check every entry against the sprite file directly
        # rather than relying on eyeballing it.
        import re
        from pathlib import Path

        sprite_path = Path(projects_router.__file__).resolve().parent.parent / "templates" / "_icons_sprite.html"
        sprite_ids = set(re.findall(r'symbol id="icon-([a-z0-9-]+)"', sprite_path.read_text()))
        assert sprite_ids  # sanity: the sprite file actually parsed
        for name in projects_router.PROJECT_ICONS:
            assert name in sprite_ids, f"{name!r} is not a real icon in _icons_sprite.html"


class TestProjectGroups:
    def test_create_edit_delete(self, conn):
        projects_router.create_project_group(name="School", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        assert group["name"] == "School"
        assert group["color"] == "blue"  # default, Step 1
        projects_router.edit_project_group(group["uid"], name="Academics", color="purple", default_range_days="", conn=conn)
        updated = db.list_project_groups(conn)[0]
        assert updated["name"] == "Academics"
        assert updated["color"] == "purple"
        projects_router.delete_project_group(group["uid"], conn=conn)
        assert db.list_project_groups(conn) == []


class TestSpaceDetail:
    """GET /projects/groups/{uid} (spaces-home-pipeline, 2026-08-02; widget
    grid follow-up same day) -- renders, 404s on an unknown uid, and seeds
    the Space's own widget grid (same system as Home, see
    test_dashboard_router.py's TestSpaceWidgets) on first visit."""

    def _request(self):
        from starlette.requests import Request

        return Request({"type": "http", "method": "GET", "path": "/projects/groups/x", "headers": []})

    def test_renders_and_seeds_default_widgets(self, conn):
        projects_router.create_project_group(name="University", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]

        resp = projects_router.space_detail(group["uid"], self._request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["group"]["uid"] == group["uid"]
        # Seeded exactly once, all pre-scoped to this Space via
        # config["group_uid"] -- see dashboard_router._DEFAULT_SPACE_WIDGETS.
        # §2 Spaces v2 (2026-08-03): 4 defaults -- calendar_agenda (third),
        # weekly_overview (two_thirds, 7 days), project_preview, habit_checkin.
        widgets = db.list_dashboard_widgets(conn, space_uid=group["uid"])
        assert [w["type"] for w in widgets] == ["calendar_agenda", "weekly_overview", "project_preview", "habit_checkin"]
        assert all(w["config"]["group_uid"] == group["uid"] for w in widgets)

    def test_seeding_is_a_noop_on_second_visit(self, conn):
        projects_router.create_project_group(name="University", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        projects_router.space_detail(group["uid"], self._request(), conn=conn)
        db.delete_dashboard_widget(conn, db.list_dashboard_widgets(conn, space_uid=group["uid"])[0]["uid"])
        projects_router.space_detail(group["uid"], self._request(), conn=conn)
        assert len(db.list_dashboard_widgets(conn, space_uid=group["uid"])) == 3

    def test_renders_in_edit_mode_with_the_add_widget_form(self, conn):
        # Smoke test for _widget_workspace.html's edit_mode branch, shared
        # verbatim with dashboard.html (2026-08-02) -- only rendered when
        # edit_mode is truthy.
        projects_router.create_project_group(name="University", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        resp = projects_router.space_detail(group["uid"], self._request(), edit=True, conn=conn)
        assert resp.status_code == 200
        assert b"Add widget" in resp.body

    def test_404s_on_unknown_uid(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            projects_router.space_detail("does-not-exist", self._request(), conn=conn)
        assert exc_info.value.status_code == 404

    def test_seeded_weekly_overview_pools_tasks_from_every_project_in_the_space(self, conn):
        from datetime import date

        projects_router.create_project_group(name="University", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        p1 = _create_project(conn, name="CS101", group_uid=group["uid"])
        p2 = _create_project(conn, name="MATH201", group_uid=group["uid"])

        db.upsert_task_list(conn, {"uid": "hw1", "name": "HW1", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw1", p1["uid"])
        db.upsert_task_list(conn, {"uid": "hw2", "name": "HW2", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw2", p2["uid"])
        today = date.today().isoformat()
        db.upsert_task(conn, {
            "uid": "t1", "href": "/t1", "calendar_path": "tasks", "list_path": "hw1",
            "title": "t1", "description": "", "status": "active", "due_at": today,
            "tags": [], "created_at": _now(),
        })
        db.upsert_task(conn, {
            "uid": "t2", "href": "/t2", "calendar_path": "tasks", "list_path": "hw2",
            "title": "t2", "description": "", "status": "active", "due_at": today,
            "tags": [], "created_at": _now(),
        })

        resp = projects_router.space_detail(group["uid"], self._request(), conn=conn)
        weekly = next(wc for wc in resp.context["widget_contexts"] if wc["widget"]["type"] == "weekly_overview")
        today_day = next(d for d in weekly["data"]["days"] if d["date"] == today)
        assert {t["uid"] for t in today_day["tasks"]} == {"t1", "t2"}

    def test_seeded_project_preview_only_shows_this_spaces_projects(self, conn):
        projects_router.create_project_group(name="University", color="blue", conn=conn)
        group = db.list_project_groups(conn)[0]
        p_in = _create_project(conn, name="CS101", group_uid=group["uid"])
        _create_project(conn, name="Personal")  # not in this Space

        resp = projects_router.space_detail(group["uid"], self._request(), conn=conn)
        cards = next(wc for wc in resp.context["widget_contexts"] if wc["widget"]["type"] == "project_preview")
        assert [pv["project"]["uid"] for pv in cards["data"]["previews"]] == [p_in["uid"]]


def _seed_task(conn, uid, list_path, status="active"):
    db.upsert_task(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": "tasks", "list_path": list_path,
        "title": uid, "description": "", "status": status, "tags": [], "created_at": _now(),
    })


def _seed_event(conn, uid, calendar_path):
    db.upsert_event(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": calendar_path, "title": uid,
        "description": "", "status": "active", "all_day": 0, "start_at": "2026-08-05T10:00:00",
        "tags": [], "created_at": _now(),
    })


def _seed_contact(conn, uid, addressbook_path):
    db.upsert_contact(conn, {
        "uid": uid, "href": f"/{uid}", "addressbook_path": addressbook_path,
        "full_name": uid, "tags": [], "created_at": _now(),
    })


class TestProjectScopeAggregation:
    def test_centralizes_tasks_events_contacts_from_linked_lists(self, conn):
        p = _create_project(conn, name="Uni")

        db.upsert_task_list(conn, {"uid": "hw", "name": "Homework", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", p["uid"])
        _seed_task(conn, "t1", "hw", status="active")
        _seed_task(conn, "t2", "hw", status="done")
        # A task in an unlinked list must not show up in this project's scope.
        db.upsert_task_list(conn, {"uid": "other", "name": "Other", "color": "green", "created_at": _now()})
        _seed_task(conn, "t3", "other")

        db.upsert_calendar(conn, {"uid": "sched", "name": "Schedule", "color": "orange", "created_at": _now()})
        db.set_calendar_project(conn, "sched", p["uid"])
        _seed_event(conn, "e1", "sched")
        db.upsert_calendar(conn, {"uid": "personal2", "name": "Other cal", "color": "red", "created_at": _now()})
        _seed_event(conn, "e2", "personal2")

        db.upsert_addressbook(conn, {"uid": "profs", "name": "Professors", "color": "purple", "created_at": _now()})
        db.set_addressbook_project(conn, "profs", p["uid"])
        _seed_contact(conn, "c1", "profs")

        scope = projects_router._project_scope(conn, p["uid"])

        assert {t["uid"] for t in scope["tasks"]} == {"t1", "t2"}
        assert {e["uid"] for e in scope["events"]} == {"e1"}
        assert {c["uid"] for c in scope["contacts"]} == {"c1"}
        assert scope["tasks_total"] == 2
        assert scope["tasks_done"] == 1
        assert scope["progress"] == 50

    def test_empty_scope_has_no_progress(self, conn):
        p = _create_project(conn, name="Empty")
        scope = projects_router._project_scope(conn, p["uid"])
        assert scope["tasks"] == []
        assert scope["progress"] is None

    def test_project_detail_route_handles_missing_project(self, conn):
        from starlette.requests import Request

        scope_request = Request({"type": "http", "method": "GET", "path": "/projects/nope", "headers": []})
        ctx = projects_router.project_detail("nope", scope_request, conn=conn)
        # TemplateResponse renders fine even for a missing project (template
        # has a "Project not found" branch) -- just confirm it doesn't raise.
        assert ctx.status_code == 200

    def test_project_detail_renders_with_a_real_project(self, conn):
        # Smoke test for the "Edit project" panel's color/icon pickers
        # (2026-08-02 -- same components as projects_manage.html) -- the
        # missing-project case above never exercises that markup, since
        # it's all inside `{% if project %}`.
        from starlette.requests import Request

        p = _create_project(conn, name="University", color="purple", icon="activity")
        req = Request({"type": "http", "method": "GET", "path": f"/projects/{p['uid']}", "headers": []})
        resp = projects_router.project_detail(p["uid"], req, conn=conn)
        assert resp.status_code == 200
        assert resp.context["colors"] == projects_router.COLORS
        assert resp.context["project_icons"] == projects_router.PROJECT_ICONS
