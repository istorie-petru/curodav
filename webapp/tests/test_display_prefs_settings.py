"""Three new Settings > General/Advanced preferences (2026-08-08), added
per direct feedback after a brainstorm of "settings that would help and
level up the app":

  1. Week starts on (Sunday/Monday) -- Calendar's Month/Week views.
  2. 24-hour time -- every server-rendered time in the app.
  3. Auto-archive completed tasks -- the automatic, age-based sibling of
     the existing manual "Purge completed" action.

Covers: deps.py's week_start()/time_format()/fmt_time/fmt_hour (the
shared plumbing every consumer reads), routers/calendar.py's _week_bounds/
_month_grid actually respecting the preference, db.py's
delete_old_completed_tasks, routers/tasks.py's lazy trigger, and the
Settings UI/routes themselves."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db, deps
from src.routers import calendar as calendar_router
from src.routers import settings as settings_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bare_request(path="/"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _request_with_app(path, db_path):
    """Same helper as test_pinned_spaces_sidebar.py's own -- a Request
    whose `.app.state.settings.db_path` actually resolves, so deps.py's
    app_meta-backed globals exercise their real (non-fallback) path
    without needing a full TestClient (a pattern this suite doesn't use
    anywhere else)."""
    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path, radicale_base_url="http://localhost:5232")))
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [], "app": fake_app,
        }
    )


def _make_task(conn, uid, status="active", completed_at=None, **overrides):
    row = {
        "uid": uid, "title": f"Task {uid}", "description": "", "status": status,
        "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    if status in ("done", "archived") and completed_at is not None:
        # upsert_task auto-stamps completed_at to "now" -- overwrite
        # directly for tests that need a specific (usually old) date.
        conn.execute("UPDATE tasks SET completed_at = ? WHERE uid = ?", (completed_at, uid))
        conn.commit()
    return uid


# --------------------------------------------------------------------- #
# 1. Week starts on
# --------------------------------------------------------------------- #


class TestWeekStartDefault:
    def test_defaults_to_monday_without_app_scope(self):
        assert deps._week_start(_bare_request()) == "monday"

    def test_defaults_to_monday_with_real_app_scope_and_nothing_set(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path):
            pass
        assert deps._week_start(_request_with_app("/", db_path)) == "monday"

    def test_respects_stored_sunday(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.WEEK_START_KEY, "sunday")
        assert deps._week_start(_request_with_app("/", db_path)) == "sunday"


class TestWeekBounds:
    def test_monday_start_matches_original_behavior(self):
        # A Wednesday -- original (pre-preference) behavior: week starts
        # the preceding Monday.
        wed = date(2026, 8, 12)
        start, end = calendar_router._week_bounds(wed, "monday")
        assert start == date(2026, 8, 10)  # Monday
        assert end == date(2026, 8, 16)  # Sunday

    def test_sunday_start(self):
        wed = date(2026, 8, 12)
        start, end = calendar_router._week_bounds(wed, "sunday")
        assert start == date(2026, 8, 9)  # Sunday
        assert end == date(2026, 8, 15)  # Saturday

    def test_sunday_itself_is_the_start_of_its_own_week_when_sunday_start(self):
        sun = date(2026, 8, 9)
        start, _ = calendar_router._week_bounds(sun, "sunday")
        assert start == sun

    def test_default_param_is_monday(self):
        wed = date(2026, 8, 12)
        assert calendar_router._week_bounds(wed) == calendar_router._week_bounds(wed, "monday")


class TestMonthViewWeekStart:
    def test_month_view_weekday_header_defaults_monday_first(self, conn):
        resp = calendar_router.month_view(_bare_request("/calendar"), year=2026, month=8, conn=conn)
        assert resp.context["weekday_names"] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def test_month_view_weekday_header_rotates_for_sunday(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.WEEK_START_KEY, "sunday")
            resp = calendar_router.month_view(_request_with_app("/calendar", db_path), year=2026, month=8, conn=c)
        assert resp.context["weekday_names"] == ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        body = resp.body.decode()
        assert "<span>Sun</span><span>Mon</span>" in body

    def test_month_grid_first_column_is_sunday_when_configured(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.WEEK_START_KEY, "sunday")
            resp = calendar_router.month_view(_request_with_app("/calendar", db_path), year=2026, month=8, conn=c)
        first_week = resp.context["weeks"][0]["days"]
        assert first_week[0]["date"].strftime("%A") == "Sunday"


# --------------------------------------------------------------------- #
# 2. 24-hour time
# --------------------------------------------------------------------- #


class TestTimeFormatDefault:
    def test_defaults_to_24h(self):
        assert deps._time_format(_bare_request()) == "24h"

    def test_respects_stored_12h(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.TIME_FORMAT_KEY, "12h")
        assert deps._time_format(_request_with_app("/", db_path)) == "12h"


class TestFormatTimeValue:
    def test_24h_passthrough(self):
        assert deps._format_time_value("2026-08-08T14:30:00", "24h") == "14:30"

    def test_12h_afternoon(self):
        assert deps._format_time_value("2026-08-08T14:30:00", "12h") == "2:30 PM"

    def test_12h_midnight_is_12_am(self):
        assert deps._format_time_value("2026-08-08T00:05:00", "12h") == "12:05 AM"

    def test_12h_noon_is_12_pm(self):
        assert deps._format_time_value("2026-08-08T12:00:00", "12h") == "12:00 PM"

    def test_bare_hhmm_supported_not_just_full_iso(self):
        # schedule_classes.html's start_time/end_time are bare "HH:MM",
        # not full ISO datetimes.
        assert deps._format_time_value("09:05", "24h") == "09:05"
        assert deps._format_time_value("09:05", "12h") == "9:05 AM"

    def test_empty_value_returns_empty(self):
        assert deps._format_time_value("", "24h") == ""

    def test_garbage_value_returned_unchanged(self):
        assert deps._format_time_value("not-a-time", "24h") == "not-a-time"


class TestFmtHourFilter:
    def test_24h(self, conn):
        resp = calendar_router.week_view(_bare_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert ">00:00<" in body
        assert ">23:00<" in body

    def test_12h(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.TIME_FORMAT_KEY, "12h")
            resp = calendar_router.week_view(_request_with_app("/calendar/week", db_path), conn=c)
        body = resp.body.decode()
        assert ">12 AM<" in body
        assert ">11 PM<" in body


class TestFmtTimeFilterInCalendarPages:
    def test_event_time_respects_24h_default(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.upsert_event(c, {
                "uid": "e1", "title": "Standup", "description": "", "status": "active",
                "all_day": 0, "start_at": "2026-08-12T14:30:00", "end_at": "2026-08-12T15:00:00",
                "created_at": _now(),
            })
            resp = calendar_router.day_view("2026-08-12", _request_with_app("/calendar/day/2026-08-12", db_path), conn=c)
        body = resp.body.decode()
        assert "14:30" in body

    def test_event_time_respects_12h_when_set(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.TIME_FORMAT_KEY, "12h")
            db.upsert_event(c, {
                "uid": "e1", "title": "Standup", "description": "", "status": "active",
                "all_day": 0, "start_at": "2026-08-12T14:30:00", "end_at": "2026-08-12T15:00:00",
                "created_at": _now(),
            })
            resp = calendar_router.day_view("2026-08-12", _request_with_app("/calendar/day/2026-08-12", db_path), conn=c)
        body = resp.body.decode()
        assert "2:30 PM" in body
        # The raw ISO value legitimately still appears in data-start
        # (a machine-readable attribute static/calendar.js reads, not a
        # display string) -- only the visible .te-time label should have
        # switched format.
        assert '<span class="te-time">2:30 PM' in body
        assert '<span class="te-time">14:30' not in body


# --------------------------------------------------------------------- #
# 3. Auto-archive completed tasks
# --------------------------------------------------------------------- #


class TestDeleteOldCompletedTasks:
    def test_deletes_only_old_completed_tasks(self, conn):
        old_cutoff = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        _make_task(conn, "old_done", status="done", completed_at=old_cutoff)
        _make_task(conn, "recent_done", status="done", completed_at=recent)
        _make_task(conn, "active", status="active")

        deleted = db.delete_old_completed_tasks(conn, 30)

        assert deleted == 1
        remaining = {t["uid"] for t in db.list_tasks(conn)}
        assert remaining == {"recent_done", "active"}

    def test_zero_or_negative_days_is_a_no_op(self, conn):
        old_cutoff = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        _make_task(conn, "ancient_done", status="done", completed_at=old_cutoff)
        assert db.delete_old_completed_tasks(conn, 0) == 0
        assert db.delete_old_completed_tasks(conn, -5) == 0
        assert db.list_tasks(conn) != []

    def test_null_completed_at_is_never_swept(self, conn):
        # A done task with no completed_at (set directly, not via the
        # normal status-transition path) is left alone rather than
        # treated as "infinitely old."
        _make_task(conn, "t1", status="done")
        conn.execute("UPDATE tasks SET completed_at = NULL WHERE uid = 't1'")
        conn.commit()
        assert db.delete_old_completed_tasks(conn, 1) == 0
        assert db.list_tasks(conn) != []

    def test_cascades_object_labels_same_as_manual_purge(self, conn):
        old_cutoff = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        _make_task(conn, "t1", status="done", tags=["Work"], completed_at=old_cutoff)
        db.delete_old_completed_tasks(conn, 30)
        assert db.list_labels_for_object(conn, "task", "t1") == []


class TestAutoArchiveLazyTrigger:
    def test_disabled_by_default_leaves_old_completed_tasks_alone(self, conn):
        old_cutoff = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        _make_task(conn, "ancient_done", status="done", completed_at=old_cutoff)
        tasks_router.list_tasks(_bare_request("/tasks"), conn=conn)
        assert db.list_tasks(conn) != []

    def test_visiting_tasks_list_sweeps_old_completed_tasks_when_configured(self, conn):
        old_cutoff = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        _make_task(conn, "old_done", status="done", completed_at=old_cutoff)
        db.set_app_meta(conn, tasks_router.TASK_AUTO_ARCHIVE_DAYS_KEY, "30")
        tasks_router.list_tasks(_bare_request("/tasks"), conn=conn)
        assert db.list_tasks(conn) == []

    def test_unparseable_setting_value_does_not_crash_or_delete(self, conn):
        old_cutoff = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        _make_task(conn, "old_done", status="done", completed_at=old_cutoff)
        db.set_app_meta(conn, tasks_router.TASK_AUTO_ARCHIVE_DAYS_KEY, "not-a-number")
        tasks_router.list_tasks(_bare_request("/tasks"), conn=conn)
        assert db.list_tasks(conn) != []


# --------------------------------------------------------------------- #
# 4. Settings UI (General + Advanced)
# --------------------------------------------------------------------- #


def _settings_request(path):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


class TestSettingsGeneralNewFields:
    def test_renders_week_start_and_time_format_controls(self, conn):
        resp = settings_router.settings_general(_settings_request("/settings/general"), conn=conn)
        body = resp.body.decode()
        assert 'action="/settings/week-start"' in body
        assert 'action="/settings/time-format"' in body
        assert resp.context["current_week_start"] == "monday"
        assert resp.context["current_time_format"] == "24h"

    def test_set_week_start_route(self, conn):
        resp = settings_router.set_week_start(week_start="sunday", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/general"
        assert db.get_app_meta(conn, deps.WEEK_START_KEY) == "sunday"

    def test_set_week_start_rejects_unrecognized_values(self, conn):
        settings_router.set_week_start(week_start="tuesday", conn=conn)
        assert db.get_app_meta(conn, deps.WEEK_START_KEY) == "monday"

    def test_set_time_format_route(self, conn):
        resp = settings_router.set_time_format(time_format="12h", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/general"
        assert db.get_app_meta(conn, deps.TIME_FORMAT_KEY) == "12h"

    def test_set_time_format_rejects_unrecognized_values(self, conn):
        settings_router.set_time_format(time_format="banana", conn=conn)
        assert db.get_app_meta(conn, deps.TIME_FORMAT_KEY) == "24h"

    def test_general_page_renders_base_html_without_shadowing_crash(self, conn):
        # Regression test for the actual bug hit while building this:
        # passing "time_format"/"week_start" as context keys shadowed
        # deps.py's same-named Jinja globals, breaking base.html's own
        # `{{ time_format(request) }}` call with "'str' object is not
        # callable". Context keys are current_week_start/
        # current_time_format specifically to avoid this.
        resp = settings_router.settings_general(_settings_request("/settings/general"), conn=conn)
        assert resp.status_code == 200
        assert "current_week_start" in resp.context
        assert "current_time_format" in resp.context
        assert "week_start" not in resp.context
        assert "time_format" not in resp.context


class TestSettingsAdvancedAutoArchive:
    def test_renders_auto_archive_select_with_all_choices(self, conn, tmp_path):
        # settings_advanced now also reads request.app.state.settings
        # .radicale_base_url (2026-08-08, Export & backup inlined into
        # this page) -- needs the fuller fake request, not the bare one.
        resp = settings_router.settings_advanced(_request_with_app("/settings/advanced", tmp_path / "cache.sqlite"), conn=conn)
        body = resp.body.decode()
        assert 'action="/settings/task-auto-archive"' in body
        for value, label in settings_router.DAYS_CHOICES:
            assert f'value="{value}"' in body
            assert label in body
        assert resp.context["task_auto_archive_days"] == "0"

    def test_set_task_auto_archive_route(self, conn):
        resp = settings_router.set_task_auto_archive(days="30", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/advanced"
        assert db.get_app_meta(conn, tasks_router.TASK_AUTO_ARCHIVE_DAYS_KEY) == "30"

    def test_set_task_auto_archive_rejects_unrecognized_values(self, conn):
        settings_router.set_task_auto_archive(days="999", conn=conn)
        assert db.get_app_meta(conn, tasks_router.TASK_AUTO_ARCHIVE_DAYS_KEY) == "0"


# --------------------------------------------------------------------- #
# 5. Show icons next to labels (Settings > Appearance, 2026-08-09)
# --------------------------------------------------------------------- #


class TestShowLabelIcons:
    def test_defaults_off(self):
        assert deps._show_label_icons(_bare_request()) is False

    def test_on_when_stored_1(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
        assert deps._show_label_icons(_request_with_app("/", db_path)) is True

    def test_off_when_stored_non_one(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "banana")
        assert deps._show_label_icons(_request_with_app("/", db_path)) is False


class TestLabelIcon:
    def _seed(self, db_path, label="University", icon="book", color="green"):
        with db.connect(db_path) as c:
            db.upsert_label_config(c, {"name": label, "color": color, "icon": icon})

    def test_hidden_when_toggle_off_even_if_label_has_an_icon(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._seed(db_path)
        assert deps._label_icon(_request_with_app("/", db_path), "University") == ""

    def test_returns_assigned_icon_when_on(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._seed(db_path)
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
        assert deps._label_icon(_request_with_app("/", db_path), "University") == "book"

    def test_empty_for_label_without_config_when_on(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
        assert deps._label_icon(_request_with_app("/", db_path), "NoSuchLabel") == ""

    def test_case_insensitive_match_same_as_labels(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._seed(db_path)
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
        assert deps._label_icon(_request_with_app("/", db_path), "university") == "book"

    def test_empty_when_no_icon_assigned(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._seed(db_path, icon="")
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
        assert deps._label_icon(_request_with_app("/", db_path), "University") == ""

    def test_memoized_within_one_request(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._seed(db_path)
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
        req = _request_with_app("/", db_path)
        assert deps._label_icon(req, "University") == "book"
        # Second call hits the per-request memo, not a fresh DB read.
        assert deps._label_icon(req, "University") == "book"


class TestLabelIconInRenderedPages:
    def test_task_tag_pill_shows_icon_when_on(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.SHOW_LABEL_ICONS_KEY, "1")
            db.upsert_label_config(c, {"name": "University", "color": "green", "icon": "book"})
            db.upsert_task(c, {
                "uid": "t1", "title": "Essay", "description": "", "status": "active",
                "tags": ["University"], "created_at": _now(),
            })
            resp = tasks_router.list_tasks(_request_with_app("/tasks", db_path), conn=c)
        body = resp.body.decode()
        assert '#icon-book"' in body
        assert "University" in body

    def test_task_tag_pill_has_no_icon_when_off(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.upsert_label_config(c, {"name": "University", "color": "green", "icon": "book"})
            db.upsert_task(c, {
                "uid": "t1", "title": "Essay", "description": "", "status": "active",
                "tags": ["University"], "created_at": _now(),
            })
            resp = tasks_router.list_tasks(_request_with_app("/tasks", db_path), conn=c)
        body = resp.body.decode()
        # The sprite defines every icon (<symbol id="icon-book">), so check
        # the *use* reference (<use href="#icon-book">), which only renders
        # when the toggle is on.
        assert '#icon-book' not in body
        assert "University" in body


class TestSettingsAppearanceLabelIcons:
    def test_renders_toggle_defaulting_to_off(self, conn):
        resp = settings_router.settings_appearance(_settings_request("/settings/appearance"), conn=conn)
        body = resp.body.decode()
        assert 'action="/settings/label-icons"' in body
        assert resp.context["current_show_label_icons"] is False

    def test_renders_toggle_on_when_set(self, conn):
        db.set_app_meta(conn, deps.SHOW_LABEL_ICONS_KEY, "1")
        resp = settings_router.settings_appearance(_settings_request("/settings/appearance"), conn=conn)
        assert resp.context["current_show_label_icons"] is True

    def test_page_does_not_shadow_the_deps_global(self, conn):
        # Same regression guard as General's current_week_start/
        # current_time_format: passing "show_label_icons" as a context key
        # would shadow deps.py's same-named Jinja global on base.html.
        resp = settings_router.settings_appearance(_settings_request("/settings/appearance"), conn=conn)
        assert "current_show_label_icons" in resp.context
        assert "show_label_icons" not in resp.context

    def test_set_label_icons_route_stores_1(self, conn):
        resp = settings_router.set_label_icons(show="1", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/appearance"
        assert db.get_app_meta(conn, deps.SHOW_LABEL_ICONS_KEY) == "1"

    def test_set_label_icons_route_clears_on_off(self, conn):
        db.set_app_meta(conn, deps.SHOW_LABEL_ICONS_KEY, "1")
        settings_router.set_label_icons(show="", conn=conn)
        assert db.get_app_meta(conn, deps.SHOW_LABEL_ICONS_KEY) == ""
