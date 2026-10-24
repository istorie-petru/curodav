"""Rendering of the contact, groups and labels, habit check-in and weekly schedule widgets."""

from __future__ import annotations

from dashboard_seed import now_iso, seed_event, seed_recurring_event

from src import db
from src.routers import dashboard as dashboard_router


class TestContactListWidget:
    """§2 Spaces v2, 2026-08-03 -- contact_list widget filters contacts by
    tags matching the space's group project names (via group_uid) or
    explicit config['tags']."""

    def _seed_contact(self, conn, uid, full_name, tags=None):
        db.upsert_contact(conn, {
            "uid": uid,
            "full_name": full_name, "tags": tags or [], "created_at": now_iso(),
        })

    def test_returns_contacts_key(self, conn):
        data = dashboard_router._render_contact_list(conn, {})
        assert "contacts" in data

    def test_no_filter_returns_all_contacts(self, conn):
        self._seed_contact(conn, "c1", "Alice")
        self._seed_contact(conn, "c2", "Bob")
        data = dashboard_router._render_contact_list(conn, {})
        assert {c["uid"] for c in data["contacts"]} == {"c1", "c2"}

    def test_explicit_tags_filter(self, conn):
        self._seed_contact(conn, "c1", "Alice", tags=["professor"])
        self._seed_contact(conn, "c2", "Bob", tags=["student"])
        data = dashboard_router._render_contact_list(conn, {"tags": ["professor"]})
        assert {c["uid"] for c in data["contacts"]} == {"c1"}

    def test_label_name_scoping_uses_child_label_names_as_tags(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "created_at": now_iso()})
        self._seed_contact(conn, "c1", "Alice", tags=["CS101"])
        self._seed_contact(conn, "c2", "Bob", tags=["Personal"])
        data = dashboard_router._render_contact_list(conn, {"label_name": "group:Uni"})
        assert {c["uid"] for c in data["contacts"]} == {"c1"}

    def test_limit_caps_results(self, conn):
        for i in range(5):
            self._seed_contact(conn, f"c{i}", f"Contact {i}", tags=["tagged"])
        data = dashboard_router._render_contact_list(conn, {"tags": ["tagged"], "limit": 3})
        assert len(data["contacts"]) == 3

    def test_limit_zero_means_8_items_max(self, conn):
        # 2026-08-31 direct feedback: "add a way to set the limit to 0
        # (0 = unlimited)". 2026-09-13 direct request ("no limit should
        # actually be 20 maximum items") -- 0 no longer means truly
        # unlimited, it now caps at 20; 2026-09-28 direct feedback ("make
        # the default limit smaller, maximum 8") dropped that cap (and the
        # default) to 8 -- seeds 25 (more than the cap) and asserts exactly
        # 8 come back.
        for i in range(25):
            self._seed_contact(conn, f"c{i}", f"Contact {i}", tags=["tagged"])
        data = dashboard_router._render_contact_list(conn, {"tags": ["tagged"], "limit": 0})
        assert len(data["contacts"]) == 8




class TestSpaceScopedRenderers:
    """_render_project_preview and _render_habit_checkin both need to
    resolve config['group_uid'] the same way _filtered_tasks/_filtered_
    events already do, since a Space's default widgets use group_uid, not
    project_uid, to auto-scope (2026-08-02)."""

    def test_project_preview_label_filter(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "widget_pin": 1, "created_at": now_iso()})
        db.upsert_label_config(conn, {"name": "Personal", "widget_pin": 1, "created_at": now_iso()})
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "group:Uni"})
        assert [pv["project"]["uid"] for pv in data["previews"]] == ["CS101"]

    def test_habit_checkin_label_filter(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "created_at": now_iso()})
        for uid, tags in (("h1", ["CS101"]), ("h2", [])):
            db.upsert_task(conn, {"uid": uid, "title": uid, "description": "", "status": "active", "is_habit": 1,
                                  "tags": tags, "recurrence": "FREQ=DAILY", "created_at": now_iso()})
        data = dashboard_router._render_habit_checkin(conn, {"label_name": "group:Uni"})
        assert [r["uid"] for r in data["rows"]] == ["h1"]


class TestGroupsAndLabelsWidget:
    """The "spaces_projects" widget type, shown as "Groups & Labels" since
    labels-as-modules slice c (2026-09-25): driven by groups and each
    label's widget_pin flag. 2026-09-30 fix (direct report: a group page
    "always showed empty" for a group whose members were never converted
    to a Project, since widget_pin only ever gets set that way) -- a
    group's page now lists EVERY one of its member labels, pinned or not
    (db.group_member_names), same "every member visible" guarantee
    _render_group_members's sibling widget already gives. widget_pin still
    curates the *unscoped* Home case: every pinned label (List) or every
    group plus every pinned ungrouped label (Cards). scope=="everything"
    still opts a page's instance out of its page scope."""

    def _seed(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "widget_pin": 1, "is_project": 1})
        db.upsert_label_config(conn, {"name": "Art", "label_group": "Uni"})  # not pinned
        db.upsert_label_config(conn, {"name": "Personal", "widget_pin": 1})
        db.upsert_label_config(conn, {"name": "Old", "widget_pin": 1})
        db.archive_project(conn, "Old")

    def test_group_page_lists_every_member_label_not_just_pinned(self, conn):
        self._seed(conn)
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "group:Uni"})
        assert [pv["project"]["name"] for pv in data["previews"]] == ["Art", "CS101"]

    def test_home_list_is_every_pinned_open_label(self, conn):
        self._seed(conn)
        data = dashboard_router._render_spaces_projects(conn, {})
        assert [pv["project"]["name"] for pv in data["previews"]] == ["CS101", "Personal"]

    def test_scope_everything_ignores_the_page(self, conn):
        self._seed(conn)
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "group:Uni", "scope": "everything"})
        assert {pv["project"]["name"] for pv in data["previews"]} == {"CS101", "Personal"}

    def test_label_page_has_no_sub_labels(self, conn):
        self._seed(conn)
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "CS101"})
        assert data["previews"] == []

    def test_home_cards_are_groups_plus_ungrouped_pinned_labels(self, conn):
        self._seed(conn)
        data = dashboard_router._render_spaces_projects(conn, {"style": "cards"})
        cards = {c["name"]: c for c in data["cards"]}
        assert set(cards) == {"Uni", "Personal"}  # CS101 is reached through Uni
        assert cards["Uni"]["href"] == "/groups/Uni" and cards["Uni"]["meta"] == "2 labels"
        assert cards["Personal"]["href"] == "/labels/Personal" and cards["Personal"]["meta"] == "Shelf"

    def test_group_page_cards_are_every_member_label_not_just_pinned(self, conn):
        self._seed(conn)
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "group:Uni", "style": "cards"})
        assert [(c["name"], c["icon"], c["meta"]) for c in data["cards"]] == [
            ("Art", "tag", "Shelf"), ("CS101", "folder", "Project"),
        ]

    def test_add_widget_stores_scope(self, conn):
        dashboard_router.add_widget(
            source="spaces_projects", view="spaces_projects_view", range="", title="", project_uid="",
            tags="", task_list_uids=[], calendar_uids=[], limit="", style="cards", scope="everything",
            show=[], space_uid="group:Uni", conn=conn,
        )
        w = db.list_dashboard_widgets(conn, label_name="group:Uni")[0]
        assert w["type"] == "spaces_projects"
        assert w["config"]["scope"] == "everything"
        assert w["config"]["style"] == "cards"



class TestIsLongLivedRecurrence:
    """2026-08-15, new Weekly Schedule widget -- filters a short recurring
    reminder out while keeping a real standing weekly pattern, purely from
    the event's own recurrence rule (no DB, no "as of" date needed)."""

    def test_open_ended_weekly_qualifies(self):
        event = {"uid": "e1", "start_at": "2026-09-01T10:00:00", "end_at": "2026-09-01T11:00:00", "recurrence": "FREQ=WEEKLY"}
        assert dashboard_router._is_long_lived_recurrence(event) is True

    def test_semester_long_until_qualifies(self):
        event = {
            "uid": "e1", "start_at": "2026-09-01T10:00:00", "end_at": "2026-09-01T11:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-12-15",
        }
        assert dashboard_router._is_long_lived_recurrence(event) is True

    def test_short_count_reminder_does_not_qualify(self):
        event = {
            "uid": "e1", "start_at": "2026-09-01T08:00:00", "end_at": "2026-09-01T08:05:00",
            "recurrence": "FREQ=DAILY;COUNT=3",
        }
        assert dashboard_router._is_long_lived_recurrence(event) is False

    def test_non_recurring_does_not_qualify(self):
        event = {"uid": "e1", "start_at": "2026-09-01T10:00:00", "end_at": "2026-09-01T11:00:00"}
        assert dashboard_router._is_long_lived_recurrence(event) is False

    def test_no_start_at_does_not_qualify(self):
        assert dashboard_router._is_long_lived_recurrence({"uid": "e1", "recurrence": "FREQ=WEEKLY"}) is False


class TestWeeklyScheduleWidget:
    """2026-08-15, new type -- a compact, static weekly-pattern view of a
    label's long-lived recurring events; no revival of the removed
    Schedule module, purely a presentation over ordinary recurring
    Calendar events."""

    def test_short_lived_recurrence_is_excluded(self, conn):
        seed_recurring_event(conn, "e1", "2026-09-01T10:00:00", "2026-09-01T10:30:00", recurrence="FREQ=DAILY;COUNT=3")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"] == []
        assert data["agenda_rows"] == []

    def test_non_recurring_event_is_excluded(self, conn):
        seed_event(conn, "e1", start_at="2026-09-01T10:00:00")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"] == []

    def test_semester_long_weekly_event_produces_one_day_column(self, conn):
        # 2026-09-01 is a Tuesday.
        seed_recurring_event(conn, "lecture", "2026-09-01T10:00:00", "2026-09-01T11:30:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert len(data["days"]) == 1
        assert data["days"][0]["weekday"] == 1  # Tuesday, Monday=0
        assert data["days"][0]["label"] == "Tue"
        assert len(data["days"][0]["blocks"]) == 1
        assert data["days"][0]["blocks"][0]["event"]["uid"] == "lecture"
        assert data["agenda_rows"][0]["event"]["uid"] == "lecture"

    def test_grid_is_only_as_tall_as_the_events_own_time_span(self, conn):
        # Two lectures 10:00-11:00 and 14:00-15:00 -- the grid should be
        # tightened to roughly 9:30-15:30, not the full 24h day, so a
        # 10:00 block doesn't start near the very top of a mostly-empty
        # column.
        seed_recurring_event(conn, "morning", "2026-09-01T10:00:00", "2026-09-01T11:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15")
        seed_recurring_event(conn, "afternoon", "2026-09-03T14:00:00", "2026-09-03T15:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15")
        data = dashboard_router._render_weekly_schedule(conn, {})
        blocks = {b["event"]["uid"]: b for day in data["days"] for b in day["blocks"]}
        assert blocks["morning"]["top_pct"] < blocks["afternoon"]["top_pct"]
        # Neither block should be flush against the very top of its column
        # (a 30-minute pad was added before the earliest start).
        assert blocks["morning"]["top_pct"] > 0

    def test_biweekly_event_is_flagged(self, conn):
        seed_recurring_event(conn, "lecture", "2026-09-01T10:00:00", "2026-09-01T11:00:00", recurrence="FREQ=WEEKLY;INTERVAL=2")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"][0]["blocks"][0]["biweekly"] is True
        assert data["agenda_rows"][0]["biweekly"] is True

    def test_label_scoping(self, conn):
        seed_recurring_event(conn, "cs101", "2026-09-01T10:00:00", "2026-09-01T11:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15", tags=["CS101"])
        seed_recurring_event(conn, "other", "2026-09-02T10:00:00", "2026-09-02T11:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15", tags=["Other"])
        data = dashboard_router._render_weekly_schedule(conn, {"tags": ["CS101"]})
        agenda_uids = {row["event"]["uid"] for row in data["agenda_rows"]}
        assert agenda_uids == {"cs101"}


    def test_all_day_recurring_event_is_excluded_not_crashed(self, conn):
        # 2026-08-30 bug fix: db.sync_contact_birthday_event writes an
        # all_day=True, FREQ=YEARLY event with a bare "1900-MM-DD"
        # start_at (no "THH:MM" time portion) for every contact with a
        # birthday -- automatic, not something a user has to construct by
        # hand. Before the fix, this crashed _minutes_of_day's fixed-
        # offset slice (ValueError: invalid literal for int() with base
        # 10: '') for any dashboard with a Weekly Schedule widget whose
        # label matched a birthday'd contact, taking down GET / entirely.
        # An all-day event has no time-of-day to place on this grid
        # anyway (same exclusion grid_layout.layout_day already applies),
        # so it should just be skipped, not crash the widget.
        db.upsert_event(conn, {
            "uid": "birthday-1", "title": "Jordan's Birthday",
            "description": "", "status": "active", "all_day": 1,
            "start_at": "1900-06-15", "end_at": None, "recurrence": "FREQ=YEARLY",
            "tags": [], "created_at": now_iso(),
        })
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"] == []
        assert data["agenda_rows"] == []
