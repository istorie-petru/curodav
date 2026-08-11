"""Tests for routers/habits.py: the heatmap grid builder, streak
computation, and CRUD/toggle/backfill router wiring. No bridge/Radicale
dependency -- habits are entirely local (see db.py's table comments)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src import db
from src.routers import habits as habits_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestHeatmapWeeks:
    def test_grid_ends_on_today_and_starts_on_a_monday(self):
        today = date(2026, 8, 1)  # a Saturday
        weeks = habits_router._heatmap_weeks({}, 1, weeks=4, today=today)
        first_day = weeks[0][0]["date"]
        assert date.fromisoformat(first_day).weekday() == 0  # Monday
        last_real_day = [c for w in weeks for c in w if not c["is_future"]][-1]
        assert last_real_day["date"] == today.isoformat()

    def test_future_days_marked_and_not_leveled(self):
        today = date(2026, 8, 1)
        weeks = habits_router._heatmap_weeks({}, 1, weeks=1, today=today)
        future_cells = [c for w in weeks for c in w if c["is_future"]]
        assert future_cells  # the grid pads out to a full week, so some exist
        assert all(c["level"] == -1 for c in future_cells)

    def test_level_buckets_scale_with_target(self):
        today = date(2026, 8, 1)
        entries = {
            "2026-08-01": 8,  # full target
            "2026-07-31": 6,  # 75%
            "2026-07-30": 3,  # 37.5%
            "2026-07-29": 1,  # 12.5%
            "2026-07-28": 0,
        }
        weeks = habits_router._heatmap_weeks(entries, target=8, weeks=1, today=today)
        by_date = {c["date"]: c for w in weeks for c in w}
        assert by_date["2026-08-01"]["level"] == 4
        assert by_date["2026-07-31"]["level"] == 3
        assert by_date["2026-07-30"]["level"] == 2
        assert by_date["2026-07-29"]["level"] == 1
        assert by_date["2026-07-28"]["level"] == 0

    def test_no_target_any_logged_value_is_full_intensity(self):
        today = date(2026, 8, 1)
        weeks = habits_router._heatmap_weeks({"2026-08-01": 1}, target=0, weeks=1, today=today)
        by_date = {c["date"]: c for w in weeks for c in w}
        assert by_date["2026-08-01"]["level"] == 4

    def test_month_label_only_on_first_monday_of_month(self):
        today = date(2026, 8, 15)
        weeks = habits_router._heatmap_weeks({}, 1, weeks=8, today=today)
        labeled = [c for w in weeks for c in w if c["month_label"]]
        for c in labeled:
            d = date.fromisoformat(c["date"])
            assert d.weekday() == 0
            assert d.day <= 7


class TestStreaks:
    def test_no_entries(self):
        assert habits_router._streaks({}) == (0, 0)

    def test_current_streak_counts_consecutive_days_ending_today(self):
        today = date(2026, 8, 5)
        entries = {
            (today - timedelta(days=0)).isoformat(): 1,
            (today - timedelta(days=1)).isoformat(): 1,
            (today - timedelta(days=2)).isoformat(): 1,
            (today - timedelta(days=5)).isoformat(): 1,  # gap -- not part of the streak
        }
        current, longest = habits_router._streaks(entries, today=today)
        assert current == 3
        assert longest == 3

    def test_current_streak_tolerates_today_not_yet_logged(self):
        today = date(2026, 8, 5)
        entries = {
            (today - timedelta(days=1)).isoformat(): 1,
            (today - timedelta(days=2)).isoformat(): 1,
        }
        current, _ = habits_router._streaks(entries, today=today)
        assert current == 2  # today itself not logged yet doesn't zero the streak

    def test_current_streak_broken_by_a_skipped_day(self):
        today = date(2026, 8, 5)
        entries = {
            (today - timedelta(days=2)).isoformat(): 1,  # gap at day-1
            (today - timedelta(days=3)).isoformat(): 1,
        }
        current, _ = habits_router._streaks(entries, today=today)
        assert current == 0

    def test_longest_streak_can_exceed_current(self):
        today = date(2026, 8, 10)
        entries = {}
        # A 5-day streak two weeks ago, nothing recent.
        for i in range(5):
            entries[(today - timedelta(days=15 + i)).isoformat()] = 1
        current, longest = habits_router._streaks(entries, today=today)
        assert current == 0
        assert longest == 5

    def test_zero_value_entries_do_not_count_as_done(self):
        today = date(2026, 8, 5)
        entries = {today.isoformat(): 0}
        current, longest = habits_router._streaks(entries, today=today)
        assert current == 0
        assert longest == 0


def _make_habit(conn, name="Read", **kwargs):
    now = _now()
    row = {"uid": f"habit-{name.lower()}", "name": name, "created_at": now, "updated_at": now}
    row.update(kwargs)
    db.upsert_habit(conn, row)
    return row["uid"]


class TestCreateEditHabit:
    def test_create_registers_tags(self, conn):
        habits_router.create_habit(
            name="Study", description="", color="purple", icon="📚",
            target_per_day="1", tags="uni, focus", project_uid="", conn=conn,
        )
        h = next(x for x in db.list_habits(conn) if x["name"] == "Study")
        assert set(h["tags"]) == {"uni", "focus"}
        # Phase 2 (label-space rework): there's no separate tag registry
        # to "register" into -- applying a label the first time is enough
        # for it to show up everywhere labels are listed.
        assert "uni" in db.list_all_label_names(conn)
        assert "focus" in db.list_all_label_names(conn)

    def test_blank_name_is_a_noop(self, conn):
        habits_router.create_habit(
            name="   ", description="", color="blue", icon="",
            target_per_day="1", tags="", project_uid="", conn=conn,
        )
        assert db.list_habits(conn) == []

    def test_edit_updates_and_preserves_unset_fields(self, conn):
        uid = _make_habit(conn, "Read", target_per_day=1)
        habits_router.edit_habit(
            uid, name="Read Daily", description="20 pages", color="green", icon="📖",
            target_per_day="20", tags="reading", project_uid="", conn=conn,
        )
        h = db.get_habit(conn, uid)
        assert h["name"] == "Read Daily"
        assert h["target_per_day"] == 20
        assert h["tags"] == ["reading"]


class TestArchiveDelete:
    def test_archive_hides_from_default_list(self, conn):
        uid = _make_habit(conn, "A")
        habits_router.archive_habit(uid, conn=conn)
        assert db.list_habits(conn) == []
        assert db.get_habit(conn, uid)["archived_at"] is not None

    def test_unarchive(self, conn):
        uid = _make_habit(conn, "A")
        habits_router.archive_habit(uid, conn=conn)
        habits_router.unarchive_habit(uid, conn=conn)
        assert len(db.list_habits(conn)) == 1

    def test_delete_cascades_entries(self, conn):
        uid = _make_habit(conn, "A")
        db.upsert_habit_entry(conn, uid, "2026-08-01", 1, None, _now())
        habits_router.delete_habit(uid, conn=conn)
        assert db.get_habit(conn, uid) is None
        assert db.list_habit_entries(conn, uid) == []


class TestEntryEndpoints:
    def test_toggle_via_router(self, conn):
        from starlette.requests import Request

        uid = _make_habit(conn, "A")
        req = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
        habits_router.toggle_entry(uid, "2026-08-01", req, conn=conn)
        assert db.get_habit_entry(conn, uid, "2026-08-01")["value"] == 1
        habits_router.toggle_entry(uid, "2026-08-01", req, conn=conn)
        assert db.get_habit_entry(conn, uid, "2026-08-01") is None

    def test_add_entry_backfill_with_exact_value(self, conn):
        from starlette.requests import Request

        uid = _make_habit(conn, "Water", target_per_day=8)
        past_date = "2026-05-15"
        req = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
        habits_router.add_entry(uid, req, entry_date=past_date, value="6", note="six glasses", conn=conn)
        entry = db.get_habit_entry(conn, uid, past_date)
        assert entry["value"] == 6
        assert entry["note"] == "six glasses"

    def test_add_entry_with_zero_value_clears_it(self, conn):
        from starlette.requests import Request

        uid = _make_habit(conn, "A")
        db.upsert_habit_entry(conn, uid, "2026-08-01", 5, None, _now())
        req = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
        habits_router.add_entry(uid, req, entry_date="2026-08-01", value="0", note="", conn=conn)
        assert db.get_habit_entry(conn, uid, "2026-08-01") is None

    def test_delete_entry_endpoint(self, conn):
        uid = _make_habit(conn, "A")
        db.upsert_habit_entry(conn, uid, "2026-08-01", 1, None, _now())
        habits_router.delete_entry(uid, "2026-08-01", conn=conn)
        assert db.get_habit_entry(conn, uid, "2026-08-01") is None


class TestHabitDetailRoute:
    def test_detail_handles_missing_habit(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/habits/nope", "headers": []})
        resp = habits_router.habit_detail("nope", req, conn=conn)
        assert resp.status_code == 200

    def test_detail_includes_streaks_and_project(self, conn):
        from starlette.requests import Request

        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        uid = _make_habit(conn, "Study", project_uid="Uni")
        db.upsert_habit_entry(conn, uid, date.today().isoformat(), 1, None, _now())
        req = Request({"type": "http", "method": "GET", "path": f"/habits/{uid}", "headers": []})
        resp = habits_router.habit_detail(uid, req, conn=conn)
        assert resp.status_code == 200
        assert resp.context["current_streak"] == 1
        assert resp.context["project"]["name"] == "Uni"
