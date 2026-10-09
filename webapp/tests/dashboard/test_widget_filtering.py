"""Which tasks, events and contacts a widget shows: tag filters, the no-label option and the page-scope guarantee."""

from __future__ import annotations

from dashboard_seed import now_iso, seed_event, seed_task

from src import db
from src.routers import dashboard as dashboard_router


class TestFiltering:
    def test_tag_filter(self, conn, today):
        seed_task(conn, "t1", due_at=today.isoformat(), tags=["uni"])
        seed_task(conn, "t2", due_at=today.isoformat(), tags=["personal"])
        result = dashboard_router._filtered_tasks(conn, {"tags": ["uni"]})
        assert {t["uid"] for t in result} == {"t1"}

    def test_no_label_sentinel_matches_only_unlabeled_items(self, conn, today):
        # 2026-08-31 direct feedback: "add a way to not select any label
        # to filter by" -- distinct from an empty tags filter (= "All").
        seed_task(conn, "tagged", due_at=today.isoformat(), tags=["uni"])
        seed_task(conn, "untagged", due_at=today.isoformat(), tags=[])
        result = dashboard_router._filtered_tasks(conn, {"tags": [dashboard_router.NO_LABEL_SENTINEL]})
        assert {t["uid"] for t in result} == {"untagged"}

    def test_no_label_sentinel_ors_with_real_labels(self, conn, today):
        seed_task(conn, "uni", due_at=today.isoformat(), tags=["uni"])
        seed_task(conn, "personal", due_at=today.isoformat(), tags=["personal"])
        seed_task(conn, "untagged", due_at=today.isoformat(), tags=[])
        result = dashboard_router._filtered_tasks(conn, {"tags": ["uni", dashboard_router.NO_LABEL_SENTINEL]})
        assert {t["uid"] for t in result} == {"uni", "untagged"}

    def test_project_filter_is_a_noop_since_task_lists_are_gone(self, conn):
        # Phase 1 (label-space rework, 2026-08-06) dropped `task_lists` --
        # there's no more list->project link to resolve a task's project
        # through (see db.py's Phase 1 comments and dashboard.py's
        # _passes_filters comment), so project_uid no longer narrows
        # anything; only the tags filter still applies.
        db.upsert_label_config(conn, {"name": "Uni", "created_at": now_iso()})
        seed_task(conn, "t1")
        seed_task(conn, "t2")
        result = dashboard_router._filtered_tasks(conn, {"project_uid": "p1"}, open_only=False)
        assert {t["uid"] for t in result} == {"t1", "t2"}

    def test_list_uids_filter_is_a_noop_since_task_lists_are_gone(self, conn):
        seed_task(conn, "t1")
        seed_task(conn, "t2")
        result = dashboard_router._filtered_tasks(conn, {"list_uids": ["hw"]}, open_only=False)
        assert {t["uid"] for t in result} == {"t1", "t2"}

    def test_open_only_excludes_done_and_archived(self, conn):
        seed_task(conn, "t1", status="active")
        seed_task(conn, "t2", status="done")
        seed_task(conn, "t3", status="archived")
        result = dashboard_router._filtered_tasks(conn, {})
        assert {t["uid"] for t in result} == {"t1"}

    def test_no_filters_returns_everything_open(self, conn):
        seed_task(conn, "t1")
        seed_task(conn, "t2")
        result = dashboard_router._filtered_tasks(conn, {})
        assert {t["uid"] for t in result} == {"t1", "t2"}


class TestScopeChildNames:
    """_scope_child_names (Spaces -- labels-as-membership rework slice 4,
    2026-09-14) -- the one place a page's `label_name` resolves to its
    hard tag-membership scope now, replacing three near-identical inline
    copies (the old _effective_tags_filter, _child_label_names, and
    _render_habit_checkin's own branch)."""

    def test_none_when_no_label_name(self, conn):
        assert dashboard_router._scope_child_names(conn, None) is None

    def test_space_resolves_to_its_child_label_names(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "created_at": now_iso()})
        db.upsert_label_config(conn, {"name": "MATH201", "label_group": "Uni", "created_at": now_iso()})
        assert dashboard_router._scope_child_names(conn, "group:Uni") == {"CS101", "MATH201"}

    def test_plain_label_resolves_to_just_its_own_name(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "created_at": now_iso()})
        assert dashboard_router._scope_child_names(conn, "CS101") == {"CS101"}

    def test_unconfigured_label_name_resolves_to_just_its_own_name(self, conn):
        # No label_config row at all -- get_label_config returns None,
        # still not a Space, same "treat as a plain label" fallback every
        # other label-scoped query in this app uses.
        assert dashboard_router._scope_child_names(conn, "Adhoc") == {"Adhoc"}


class TestHardTopLevelScopeFilter:
    """2026-09-14 (Spaces -- labels-as-membership rework slice 4): before
    this slice, a widget's own optional `config["tags"]` filter was
    UNION'd with the page's label_name-derived scope into one OR-matched
    list (_effective_tags_filter's old behavior) -- so a widget on a
    Space/Project page with its own tag filter selected could still show
    items from OUTSIDE that page's scope, as long as they matched the
    widget's own filter. `_passes_scope` is now a separate, unconditional
    AND-check every item must clear regardless of the widget's own
    filter -- these tests seed exactly that leak scenario for each item
    type and assert it's closed."""

    def test_task_widget_filter_no_longer_escapes_page_scope(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "created_at": now_iso()})
        # In scope (CS101) and matches the widget's own "Urgent" filter.
        seed_task(conn, "in_scope_and_matches", tags=["CS101", "Urgent"])
        # Matches the widget's own filter but is OUTSIDE the Space --
        # pre-slice-4 this leaked in via the OR union.
        seed_task(conn, "matches_but_out_of_scope", tags=["Urgent"])
        # In scope but doesn't match the widget's own filter.
        seed_task(conn, "in_scope_no_match", tags=["CS101"])
        result = dashboard_router._filtered_tasks(conn, {"label_name": "group:Uni", "tags": ["Urgent"]}, open_only=False)
        assert {t["uid"] for t in result} == {"in_scope_and_matches"}

    def test_event_widget_filter_no_longer_escapes_page_scope(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "created_at": now_iso()})
        seed_event(conn, "in_scope_and_matches", tags=["CS101", "Urgent"])
        seed_event(conn, "matches_but_out_of_scope", tags=["Urgent"])
        result = dashboard_router._filtered_events(conn, {"label_name": "group:Uni", "tags": ["Urgent"]})
        assert {e["uid"] for e in result} == {"in_scope_and_matches"}

    def test_contact_widget_filter_no_longer_escapes_page_scope(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "created_at": now_iso()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "In scope", "tags": ["CS101", "Professor"], "created_at": now_iso()})
        db.upsert_contact(conn, {"uid": "c2", "full_name": "Out of scope", "tags": ["Professor"], "created_at": now_iso()})
        data = dashboard_router._render_contact_list(conn, {"label_name": "group:Uni", "tags": ["Professor"]})
        assert {c["uid"] for c in data["contacts"]} == {"c1"}

    def test_plain_label_page_widget_filter_no_longer_escapes_its_own_scope(self, conn):
        # Same leak, a plain/project label page rather than a Space.
        db.upsert_label_config(conn, {"name": "CS101", "created_at": now_iso()})
        seed_task(conn, "in_scope_and_matches", tags=["CS101", "Urgent"])
        seed_task(conn, "matches_but_out_of_scope", tags=["Urgent"])
        result = dashboard_router._filtered_tasks(conn, {"label_name": "CS101", "tags": ["Urgent"]}, open_only=False)
        assert {t["uid"] for t in result} == {"in_scope_and_matches"}

    def test_home_unscoped_widget_filter_is_unaffected(self, conn):
        # No label_name at all (Home) -- scope_names is None, only the
        # widget's own filter applies, exactly as before this slice.
        seed_task(conn, "matches", tags=["Urgent"])
        seed_task(conn, "no_match", tags=["Other"])
        result = dashboard_router._filtered_tasks(conn, {"tags": ["Urgent"]}, open_only=False)
        assert {t["uid"] for t in result} == {"matches"}
