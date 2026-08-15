"""Release 1.1 (virtual & derived states, plans/open-priority.md § Virtual &
derived states) -- slices 1-5: the Importance/Urgency data model, label rules,
the pure effective-value module, and the two-axis UI that replaced the old
single priority.

Side work (post-1.1, direct feedback: "just calculated automatically, no
manual input") later removed the *explicit* per-task axes entirely -- see
src/derived_state.py's module docstring. This file now covers the model as
it stands after that rework:
  1. Schema: tasks.importance / tasks.urgency do NOT exist as columns
     anymore (dropped outright, including via migration on an existing
     database); label_config's importance / urgency_threshold_days rules
     still do (label rules are configured once per label, not per task).
  2. label_config: the `importance` / `urgency_threshold_days` behavior keys
     upsert and read back through effective_label_config with defaults.
  3. src/derived_state.py: deterministic effective-importance / effective-
     urgency derivation purely from label rules + temporal state, with max
     precedence across whichever labels a task carries and no stored
     derived state.
  4. Slice 5 (as reworked): the two axes are read-only in the UI --
     independent filters/sort over the *computed* value, and read-only
     table/board/detail rendering. No inline edit, no create/edit form
     field, exists for either axis anymore.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from icalendar import Todo

from src import db, derived_state, ical_rows
from src.ical_rows import ical_to_task_row, task_row_to_ical
from src.routers import tasks as tasks_router
from src.routers import timeline as timeline_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, due_at=None, tags=None, status="active"):
    db.upsert_task(
        conn,
        {
            "uid": uid,
            "title": uid,
            "description": "",
            "status": status,
            "due_at": due_at,
            "tags": tags or [],
            "created_at": _now(),
        },
    )


def _rules(conn, *labels):
    return {name: db.effective_label_config_ci(conn, name) for name in labels}


class TestSchema:
    def test_fresh_database_has_no_importance_or_urgency_columns(self, conn):
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        assert "importance" not in cols
        assert "urgency" not in cols
        # The old WebDAV priority column stays physically present (never
        # force-dropped, same convention as every other removal in db.py --
        # importance/urgency are the deliberate exception, see db.py's
        # `_drop_column` docstring).
        assert "priority" in cols

    def test_existing_database_loses_the_columns_via_migration(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            # Simulate a pre-rework database that still physically carries
            # the 1.1 explicit columns.
            c.execute("ALTER TABLE tasks ADD COLUMN importance INTEGER")
            c.execute("ALTER TABLE tasks ADD COLUMN urgency INTEGER")
        with db.connect(db_path) as c:  # reconnect -> init_schema runs migrations
            cols = {row[1] for row in c.execute("PRAGMA table_info(tasks)").fetchall()}
            assert "importance" not in cols
            assert "urgency" not in cols

    def test_label_config_still_has_the_rule_columns(self, conn):
        # Label rules are configured once per label, not per task -- these
        # are the one persistent exception derived_state.py's docstring
        # calls out, and were never part of this rework.
        lcols = {row[1] for row in conn.execute("PRAGMA table_info(label_config)").fetchall()}
        assert "importance" in lcols
        assert "urgency_threshold_days" in lcols

    def test_upsert_ignores_importance_and_urgency_keys(self, conn):
        # A caller that still passes these keys (e.g. an old direct
        # db.upsert_task call site) doesn't crash -- upsert_task's column
        # list simply doesn't include them anymore, so they're silently
        # dropped rather than raising.
        db.upsert_task(
            conn,
            {
                "uid": "t1", "title": "t1", "description": "", "status": "active",
                "due_at": None, "importance": 3, "urgency": 2, "tags": [],
                "created_at": _now(),
            },
        )
        t = db.get_task(conn, "t1")
        assert "importance" not in t
        assert "urgency" not in t


class TestLabelConfigRules:
    def test_rules_upsert_and_read_back(self, conn):
        db.upsert_label_config(
            conn,
            {
                "name": "Exam",
                "importance": 3,
                "urgency_threshold_days": 7,
                "created_at": _now(),
            },
        )
        cfg = db.effective_label_config(conn, "Exam")
        assert cfg["importance"] == 3
        assert cfg["urgency_threshold_days"] == 7

    def test_rule_defaults_when_unset(self, conn):
        cfg = db.effective_label_config(conn, "Exam")
        assert cfg["importance"] is None
        assert cfg["urgency_threshold_days"] is None

    def test_partial_upsert_keeps_other_fields(self, conn):
        db.upsert_label_config(
            conn,
            {
                "name": "Exam",
                "color": "red",
                "importance": 2,
                "created_at": _now(),
            },
        )
        db.upsert_label_config(conn, {"name": "Exam", "urgency_threshold_days": 14, "created_at": _now()})
        cfg = db.effective_label_config(conn, "Exam")
        assert cfg["color"] == "red"  # untouched by the second upsert
        assert cfg["importance"] == 2
        assert cfg["urgency_threshold_days"] == 14


class TestEffectiveImportance:
    """Pure derived_state.effective_importance -- label-derived only (no
    manual per-task value exists), so these construct plain task/label_rules
    dicts directly rather than going through the DB."""

    def test_none_when_nothing_says_importance(self):
        assert derived_state.effective_importance({"tags": []}, {}) == 0

    def test_label_rule_sets_importance(self):
        task = {"tags": ["Exam"]}
        rules = {"Exam": {"importance": 3}}
        assert derived_state.effective_importance(task, rules) == 3

    def test_max_across_multiple_labels(self):
        task = {"tags": ["A", "B"]}
        rules = {"A": {"importance": 1}, "B": {"importance": 3}}
        assert derived_state.effective_importance(task, rules) == 3

    def test_label_without_rule_contributes_nothing(self):
        task = {"tags": ["Exam"]}  # no rule for this label at all
        assert derived_state.effective_importance(task, {}) == 0


class TestEffectiveUrgency:
    """Pure derived_state.effective_urgency -- max(label-derived, temporal),
    no manual per-task value."""

    def test_label_threshold_implies_urgency_within_window(self):
        today = date(2026, 1, 10)
        rules = {"Conference": {"urgency_threshold_days": 7}}
        inside = {"tags": ["Conference"], "due_at": (today + timedelta(days=3)).isoformat()}
        outside = {"tags": ["Conference"], "due_at": (today + timedelta(days=30)).isoformat()}
        nodate = {"tags": ["Conference"]}
        assert derived_state.effective_urgency(inside, rules, today) == 3
        assert derived_state.effective_urgency(outside, rules, today) == 0
        assert derived_state.effective_urgency(nodate, rules, today) == 0

    def test_temporal_urgency_overdue_and_today(self):
        today = date(2026, 1, 10)
        overdue = {"due_at": (today - timedelta(days=1)).isoformat()}
        due_today = {"due_at": today.isoformat()}
        tomorrow = {"due_at": (today + timedelta(days=1)).isoformat()}
        later = {"due_at": (today + timedelta(days=10)).isoformat()}
        assert derived_state.effective_urgency(overdue, {}, today) == 3
        assert derived_state.effective_urgency(due_today, {}, today) == 3
        assert derived_state.effective_urgency(tomorrow, {}, today) == 2
        assert derived_state.effective_urgency(later, {}, today) == 0

    def test_max_precedence_between_label_and_temporal(self):
        today = date(2026, 1, 10)
        rules = {"Conference": {"urgency_threshold_days": 7}}
        # Due tomorrow (temporal -> 2) but also inside the label's window
        # (label -> 3) -- max wins.
        task = {"tags": ["Conference"], "due_at": (today + timedelta(days=3)).isoformat()}
        assert derived_state.effective_urgency(task, rules, today) == 3


class TestDerivedStates:
    def test_important_at_high_importance(self):
        task = {"tags": ["Exam"]}
        rules = {"Exam": {"importance": 3}}
        assert derived_state.is_important(task, rules)
        assert not derived_state.is_urgent(task, rules, date(2026, 1, 10))

    def test_urgent_at_high_urgency(self):
        task = {"due_at": "2026-01-10"}
        assert derived_state.is_urgent(task, {}, date(2026, 1, 10))
        assert not derived_state.is_important(task, {})

    def test_medium_is_neither_state(self):
        task = {"tags": ["Exam"], "due_at": "2026-01-20"}
        rules = {"Exam": {"importance": 2}}
        assert not derived_state.is_important(task, rules)
        assert not derived_state.is_urgent(task, rules, date(2026, 1, 10))


def _request(path="/tasks"):
    from starlette.requests import Request

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


def _request_with_app(path, db_path):
    """Same helper as test_display_prefs_settings.py's own -- a Request
    whose `.app.state.settings.db_path` actually resolves, so deps.py's
    `effective_importance`/`effective_urgency` template globals (which
    need a real DB connection to resolve label rules) exercise their real
    path instead of the bare-Request try/except fallback (empty rules,
    i.e. every computed value reads as 0/unset)."""
    from types import SimpleNamespace

    from starlette.requests import Request

    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path, radicale_base_url="http://localhost:5232")))
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [], "app": fake_app,
        }
    )


class TestVirtualStateFilters:
    """Slice 2: the temporal/derived virtual states surface as query-driven
    projections in the Tasks Table/Board/Timeline filters -- tomorrow,
    this_month, important, urgent -- computed from derived values, never
    stored, never labels."""

    def test_table_tomorrow_filter(self, conn):
        today = date.today()
        tomorrow_iso = (today + timedelta(days=1)).isoformat()
        _seed_task(conn, "due_tomorrow", due_at=tomorrow_iso)
        _seed_task(conn, "due_today", due_at=today.isoformat())
        resp = tasks_router.list_tasks(_request(), date_filter="tomorrow", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"due_tomorrow"}

    def test_table_this_month_filter(self, conn):
        today = date.today()
        first = today.replace(day=1)
        month_end = (first + timedelta(days=35)).replace(day=1) - timedelta(days=1)
        _seed_task(conn, "in_month", due_at=first.isoformat())
        _seed_task(conn, "end_month", due_at=month_end.isoformat())
        _seed_task(conn, "next_month", due_at=(month_end + timedelta(days=1)).isoformat())
        resp = tasks_router.list_tasks(_request(), date_filter="this_month", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"in_month", "end_month"}

    def test_important_filter_is_purely_label_derived(self, conn):
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        _seed_task(conn, "important_exam", tags=["Exam"])
        _seed_task(conn, "untagged", tags=[])
        resp = tasks_router.list_tasks(_request(), date_filter="important", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"important_exam"}

    def test_urgent_filter_uses_temporal_urgency(self, conn):
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "far_out", due_at=(today + timedelta(days=30)).isoformat())
        resp = tasks_router.list_tasks(_request(), date_filter="urgent", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"overdue"}

    def test_urgent_filter_uses_label_threshold_and_time(self, conn):
        db.upsert_label_config(conn, {"name": "Conference", "urgency_threshold_days": 7, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "conf_soon", due_at=(today + timedelta(days=2)).isoformat(), tags=["Conference"])
        _seed_task(conn, "conf_later", due_at=(today + timedelta(days=30)).isoformat(), tags=["Conference"])
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        resp = tasks_router.list_tasks(_request(), date_filter="urgent", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"conf_soon", "overdue"}

    def test_important_and_urgent_are_not_labels_in_data(self, conn):
        # The virtual states never create object_labels rows or label_config
        # entries -- filtering by them is a pure projection.
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        _seed_task(conn, "t1", tags=["Exam"])
        tasks_router.list_tasks(_request(), date_filter="important", conn=conn)
        tasks_router.list_tasks(_request(), date_filter="urgent", conn=conn)
        labels = db.list_all_label_names(conn)
        assert "important" not in {l.lower() for l in labels}
        assert "urgent" not in {l.lower() for l in labels}
        assert "tomorrow" not in {l.lower() for l in labels}
        assert "this month" not in {l.lower() for l in labels}

    def test_board_and_timeline_respect_virtual_filters(self, conn):
        today = date.today()
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        _seed_task(conn, "imp", status="active", tags=["Exam"])
        _seed_task(conn, "not_imp", status="active")
        board = tasks_router.board_view(_request("/tasks/board"), date_filter="important", conn=conn)
        board_uids = {t["uid"] for col in board.context["columns"].values() for t in col}
        assert board_uids == {"imp"}
        _seed_task(conn, "imp2", status="active", tags=["Exam"], due_at=today.isoformat())
        tl = timeline_router.timeline_view(_request("/tasks/timeline"), date_filter="important", conn=conn)
        tl_uids = {b["task"]["uid"] for b in tl.context["bars"]}
        assert "imp2" in tl_uids

    def test_tomorrow_and_this_month_are_in_the_toolbar_dropdown(self, conn):
        resp = tasks_router.list_tasks(_request(), conn=conn)
        body = resp.body.decode()
        assert 'value="tomorrow"' in body
        assert 'value="this_month"' in body
        assert 'value="important"' in body
        assert 'value="urgent"' in body


class TestAggregationService:
    """Slice 3: src/derived_state.py's count_by_state -- the one shared
    aggregation service every surface reads instead of re-implementing the
    math. Counts must agree with the Tasks page's virtual-state filters by
    construction (same predicate), which the cross-check below asserts."""

    def _open_tasks(self, conn):
        return db.list_tasks(conn)

    def test_counts_every_state_in_one_pass(self, conn):
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_task(conn, "tomorrow", due_at=(today + timedelta(days=1)).isoformat())
        _seed_task(conn, "in_week", due_at=(today + timedelta(days=3)).isoformat())
        _seed_task(conn, "next_month", due_at=(today.replace(day=28) + timedelta(days=15)).isoformat())
        _seed_task(conn, "imp", tags=["Exam"])
        counts = derived_state.count_by_state(self._open_tasks(conn), db.list_label_rules(conn))
        assert counts["overdue"] == 1
        assert counts["today"] == 1
        assert counts["tomorrow"] == 1
        assert counts["this_week"] == 3  # today + tomorrow + in_week
        assert counts["important"] == 1
        # Urgent = the overdue one + the due-today one (temporal urgency);
        # a task counts toward every state it belongs to.
        assert counts["urgent"] == 2

    def test_counts_match_filters_exactly(self, conn):
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "a", due_at=today.isoformat(), tags=["Exam"])
        _seed_task(conn, "b", due_at=(today + timedelta(days=3)).isoformat())
        _seed_task(conn, "c", due_at=(today - timedelta(days=2)).isoformat())
        tasks = db.list_tasks(conn)
        rules = db.list_label_rules(conn)
        counts = derived_state.count_by_state(tasks, rules)
        # For every state, the aggregation count equals the filter result set
        # size -- the single source of truth guarantees the agreement.
        for state, n in counts.items():
            resp = tasks_router.list_tasks(_request(), date_filter=state, conn=conn)
            filtered = resp.context["open_tasks"]
            assert len(filtered) == n, f"state {state}: filter {len(filtered)} != aggregate {n}"

    def test_label_rule_fed_counts(self, conn):
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "exam", due_at=(today + timedelta(days=2)).isoformat(), tags=["Exam"])
        counts = derived_state.count_by_state(self._open_tasks(conn), db.list_label_rules(conn))
        assert counts["important"] == 1
        assert counts["this_week"] == 1


class TestAtAGlanceWidget:
    def test_renderer_uses_aggregation_service(self, conn):
        from src.routers import dashboard as dashboard_router

        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_task(conn, "imp", tags=["Exam"])
        data = dashboard_router._render_at_a_glance(conn, {})
        assert data["overdue_count"] == 1
        assert data["today_count"] == 1
        assert data["week_count"] == 1
        assert data["important_count"] == 1
        # The overdue and due-today tasks are both urgent (temporal urgency).
        assert data["urgent_count"] == 2
        assert data["overdue_link"].startswith("/tasks?date_filter=overdue")

    def test_at_a_glance_widget_renders_five_stats(self, conn):
        from src.routers import dashboard as dashboard_router

        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "imp", tags=["Exam"])
        data = dashboard_router._render_at_a_glance(conn, {})
        ctx = {"request": _request(), "data": data}
        body = dashboard_router.templates.get_template("_widget_at_a_glance.html").render(ctx)
        assert "Overdue" in body
        assert "Due today" in body
        assert "Due this week" in body
        assert "Important" in body
        assert "Urgent" in body


class TestWebDAVRepresentation:
    """Slice 4 (as reworked, post-1.1): Importance/Urgency -> iCal PRIORITY
    in ical_rows.py, export direction only. The recorded decision: PRIORITY
    carries the combined *effective* axes via an urgency-dominant
    precedence table; import no longer maps PRIORITY back to anything --
    there is no explicit field left to write it to (this app is the
    write-source for its own tasks)."""

    def test_urgency_dominant_export(self):
        # Urgency maps to the low/red iCal PRIORITY numbers.
        assert ical_rows._priority_to_ical(None, 3) == 1
        assert ical_rows._priority_to_ical(1, 2) == 3
        assert ical_rows._priority_to_ical(None, 1) == 5

    def test_importance_fills_between_values_when_urgency_unset(self):
        assert ical_rows._priority_to_ical(3, None) == 2
        assert ical_rows._priority_to_ical(2, None) == 4
        assert ical_rows._priority_to_ical(1, None) == 6

    def test_both_unset_is_zero(self):
        assert ical_rows._priority_to_ical(None, None) == 0
        assert ical_rows._priority_to_ical(0, 0) == 0

    def test_import_does_not_map_priority_to_anything(self):
        # No _priority_from_ical anymore -- ical_to_task_row simply never
        # sets an urgency/importance key on the parsed row.
        assert not hasattr(ical_rows, "_priority_from_ical")
        row = {"uid": "t1", "title": "T", "due_at": "2026-08-10", "status": "active"}
        todo = Todo.from_ical(task_row_to_ical(row))
        todo["PRIORITY"] = 1  # simulate a foreign client setting a high priority
        result = ical_to_task_row(todo)
        assert "urgency" not in result
        assert "importance" not in result

    def test_export_writes_the_effective_value_passed_in(self):
        # Callers (routers/export.py, published_lists.py) attach the
        # *effective* computed value onto the row dict before calling
        # task_row_to_ical -- this module itself stays pure/DB-free, it
        # just reads whatever importance/urgency keys are on the row.
        row = {"uid": "t1", "title": "T", "due_at": "2026-08-10", "status": "active",
               "importance": 3, "urgency": 2}
        todo = Todo.from_ical(task_row_to_ical(row))
        assert int(todo["PRIORITY"]) == ical_rows._priority_to_ical(3, 2)

    def test_tasks_csv_exports_the_effective_importance_and_urgency(self, conn):
        from src.routers import export as export_router

        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "t1", tags=["Exam"], due_at=(today + timedelta(days=1)).isoformat())
        resp = export_router.export_tasks_csv(conn=conn)
        body = resp.body.decode()
        assert "Importance" in body
        assert "Urgency" in body
        assert "Priority" not in body
        row = [c for c in body.splitlines()[1].split(",")]
        assert row[4] == "3"  # importance column: the Exam label's rule
        assert row[5] == "2"  # urgency column: temporal (due tomorrow)


class TestSlice5AxesInUI:
    """Slice 5 (as reworked, post-1.1): the two axes are read-only in the
    UI -- independent filters/sort over the *computed* value, and
    read-only table/board/detail rendering. No create/edit form field, no
    inline pill-select, exists for either axis anymore."""

    def _json_request(self, payload):
        import json as _json
        from starlette.requests import Request

        req = Request({"type": "http", "method": "POST", "path": "/x",
                       "headers": [(b"content-type", b"application/json")]})

        async def receive():
            return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

        req._receive = receive
        return req

    def test_active_filter_count_counts_both_axes(self):
        assert tasks_router._active_filter_count("all", "all", "all", "all", None) == 0
        assert tasks_router._active_filter_count("all", "all", "3", "all", None) == 1
        assert tasks_router._active_filter_count("all", "all", "all", "2", None) == 1
        assert tasks_router._active_filter_count("all", "all", "3", "2", None) == 2

    def test_sort_keys_have_importance_and_urgency(self):
        # _SORT_KEYS is a factory now (needs label_rules to compute the
        # effective value) rather than a plain module-level dict.
        keys = tasks_router._sort_keys({})
        assert "importance" in keys
        assert "urgency" in keys
        assert "priority" not in keys
        # Higher = first; unset sorts as 0.
        assert keys["importance"]({"tags": ["Exam"]}) == 0  # no rule for Exam here
        rules = {"Exam": {"importance": 3}}
        keys = tasks_router._sort_keys(rules)
        assert keys["importance"]({"tags": ["Exam"]}) > keys["importance"]({"tags": []})

    def test_updatable_fields_no_longer_include_either_axis(self):
        # Side work, post-1.1: neither axis is inline-editable anymore --
        # both are purely computed, see src/derived_state.py.
        assert "importance" not in tasks_router._UPDATABLE_FIELDS
        assert "urgency" not in tasks_router._UPDATABLE_FIELDS
        assert "priority" not in tasks_router._UPDATABLE_FIELDS

    def test_update_field_rejects_importance_and_urgency(self, conn):
        import asyncio

        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.update_field("t1", self._json_request({"field": "importance", "value": "3"}), conn=conn))
        assert resp.status_code == 400
        resp = asyncio.run(tasks_router.update_field("t1", self._json_request({"field": "urgency", "value": "2"}), conn=conn))
        assert resp.status_code == 400

    def test_update_field_rejects_priority(self, conn):
        import asyncio

        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.update_field("t1", self._json_request({"field": "priority", "value": "1"}), conn=conn))
        assert resp.status_code == 400

    def test_list_filters_by_effective_importance_and_urgency_independently(self, conn):
        db.upsert_label_config(conn, {"name": "Imp3", "importance": 3, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Imp1", "importance": 1, "created_at": _now()})
        today = date.today()
        overdue = (today - timedelta(days=1)).isoformat()  # temporal urgency 3
        far_out = (today + timedelta(days=30)).isoformat()  # temporal urgency 0
        _seed_task(conn, "a", tags=["Imp3"], due_at=far_out)  # importance 3, urgency 0
        _seed_task(conn, "b", tags=["Imp1"], due_at=overdue)  # importance 1, urgency 3
        _seed_task(conn, "c", tags=["Imp3"], due_at=overdue)  # importance 3, urgency 3
        resp = tasks_router.list_tasks(_request(), importance_filter="3", conn=conn)
        assert {t["uid"] for t in resp.context["open_tasks"]} == {"a", "c"}
        resp = tasks_router.list_tasks(_request(), urgency_filter="3", conn=conn)
        assert {t["uid"] for t in resp.context["open_tasks"]} == {"b", "c"}
        resp = tasks_router.list_tasks(_request(), importance_filter="3", urgency_filter="3", conn=conn)
        assert {t["uid"] for t in resp.context["open_tasks"]} == {"c"}

    def test_table_does_not_render_either_axis(self, conn):
        # Further follow-up feedback ("I don't want importance and urgency
        # to show in the tasks table view"): the Table view dropped the
        # two columns entirely (first made read-only, then removed
        # outright) -- both axes are still fully computed and still shown
        # on Board/Detail (see test_board_renders_both_pills/
        # test_detail_renders_both_meta_items below), this is a Table-view-
        # only removal.
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "t1", tags=["Exam"], due_at=(today + timedelta(days=1)).isoformat())
        resp = tasks_router.list_tasks(_request(), conn=conn)
        ctx = {"request": _request(), **resp.context}
        body = tasks_router.templates.get_template("tasks_list.html").render(ctx)
        assert 'data-field="importance"' not in body
        assert 'data-field="urgency"' not in body
        assert "pill-static" not in body
        # The toolbar's Importance/Urgency filter dropdowns are untouched
        # (this feedback was about the table's own columns, not the
        # filters) -- so "Importance"/"Urgency" text legitimately still
        # appears there; what's gone is the sortable column header link.
        assert "&urgency_filter=" in body  # toolbar filter still present
        assert "sort=importance" not in body  # no column header link to it
        assert "sort=urgency" not in body

    def test_board_renders_both_pills(self, conn, tmp_path):
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "t1", tags=["Exam"], due_at=(today + timedelta(days=1)).isoformat(), status="active")
        req = _request_with_app("/tasks/board", tmp_path / "cache.sqlite")
        resp = tasks_router.board_view(req, conn=conn)
        ctx = {"request": req, **resp.context}
        body = tasks_router.templates.get_template("tasks_board.html").render(ctx)
        assert 'title="Importance"' in body
        assert 'title="Urgency"' in body
        # Task is importance 3 (Exam) and urgency 2 (due tomorrow) -- both
        # pills render.
        assert "High" in body
        assert "Medium" in body

    def test_detail_renders_both_meta_items(self, conn, tmp_path):
        db.upsert_label_config(conn, {"name": "Exam", "importance": 3, "created_at": _now()})
        today = date.today()
        _seed_task(conn, "t1", tags=["Exam"], due_at=(today + timedelta(days=1)).isoformat(), status="active")
        req = _request_with_app("/tasks/t1", tmp_path / "cache.sqlite")
        resp = tasks_router.task_detail("t1", req, conn=conn)
        ctx = {"request": req, **resp.context}
        body = tasks_router.templates.get_template("task_detail.html").render(ctx)
        assert "<span class=\"detail-meta-label\">Importance</span>" in body
        assert "<span class=\"detail-meta-label\">Urgency</span>" in body
        assert "High" in body
        assert "Medium" in body

    def test_quick_add_offers_neither_axis(self, conn):
        from src.routers import dashboard as dashboard_router

        resp = dashboard_router.quick_add_form(_request(), conn=conn)
        body = resp.body.decode()
        assert 'name="importance"' not in body
        assert 'name="urgency"' not in body
