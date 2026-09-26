"""Habits H2 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): the
Habits page at /habits -- replaces the Tasks table's Habits group. Rows
come from habit_view.habit_items; "To do" holds habits whose open window
isn't kept yet, "On track" the rest. Every control posts to the task
completion endpoints. Also covers the habit form's "Only on" weekday
chips (routers/tasks.py _apply_habit_days)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db
from src.routers import habits as habits_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid, title, recurrence="FREQ=DAILY", target=1, **extra):
    db.save_task_habit_settings(conn, "Habit")
    row = {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Habit"],
           "recurrence": recurrence, "target_per_day": target, "created_at": _now()}
    row.update(extra)
    db.upsert_task(conn, row)


def _request(path="/habits", db_path=None):
    scope = {"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
             "server": ("testserver", 80), "root_path": "", "headers": []}
    if db_path is not None:
        scope["app"] = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(
            db_path=db_path, radicale_base_url="http://localhost:5232")))
    return Request(scope)


def _page(conn, req=None):
    resp = habits_router.habits_page(req or _request(), conn=conn)
    return resp, resp.body.decode()


TODAY = date.today().isoformat()


class TestPage:
    def test_empty_state(self, conn):
        resp, body = _page(conn)
        assert resp.context["has_habits"] is False
        assert "No habits yet" in body
        assert 'href="/tasks/new?habit=1"' in body

    def test_todo_and_on_track_split(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "h2", "Stretch")
        db.upsert_task_completion(conn, "h2", TODAY, _now())
        resp, body = _page(conn)
        assert [h["uid"] for h in resp.context["todo"]] == ["h1"]
        assert [h["uid"] for h in resp.context["on_track"]] == ["h2"]
        assert body.index(">To do <") < body.index("Read") < body.index(">On track <") < body.index("Stretch")

    def test_only_habits_not_plain_or_done_tasks(self, conn):
        _habit(conn, "h1", "Qwhabit")
        _habit(conn, "h2", "Qwretired", status="done")
        db.upsert_task(conn, {"uid": "t1", "title": "Qwplain", "description": "", "status": "active",
                              "tags": [], "created_at": _now()})
        _, body = _page(conn)
        assert "Qwhabit" in body and "Qwretired" not in body and "Qwplain" not in body

    def test_row_controls_post_to_task_completion_endpoints(self, conn):
        _habit(conn, "h1", "Read")
        _, body = _page(conn)
        assert f'action="/tasks/h1/completion/{TODAY}/toggle" class="form-inline habit-action habit-toggle"' in body
        # 7-day strip, oldest first, ending today
        first = (date.today() - timedelta(days=6)).isoformat()
        assert body.count('class="form-inline habit-action habit-day-form"') == 7
        strip = body[body.index('class="habit-week"'):]
        assert strip.index(f"/tasks/h1/completion/{first}/toggle") < strip.index(f"/tasks/h1/completion/{TODAY}/toggle")
        assert 'href="/tasks/h1" data-modal class="habit-card-title"' in body

    def test_quantity_habit(self, conn):
        _habit(conn, "h1", "Water", target=8)
        db.upsert_task_completion(conn, "h1", TODAY, _now(), value=3)
        _, body = _page(conn)
        assert 'action="/tasks/h1/completions"' in body
        assert 'name="value" value="4"' in body
        assert '<span class="habit-qty-count">3</span><span class="habit-qty-target">/8</span>' in body

    def test_period_habit_shows_progress_and_week_unit(self, conn):
        _habit(conn, "h1", "Gym", recurrence="FREQ=WEEKLY", habits_per_period=3)
        _, body = _page(conn)
        assert "3x a week" in body
        assert "0/3 this week" in body

    def test_streak_text_standard_and_playful(self, conn, tmp_path):
        _habit(conn, "h1", "Read")
        for i in range(8):
            db.upsert_task_completion(conn, "h1", (date.today() - timedelta(days=i)).isoformat(), _now())
        _, body = _page(conn)
        assert "8 days streak" in body
        db.set_app_meta(conn, "habit_streak_terminology", "playful")
        _, body = _page(conn, _request(db_path=tmp_path / "cache.sqlite"))
        assert "This week has been full" in body

    def test_region_fragment_is_just_the_body(self, conn):
        _habit(conn, "h1", "Read")
        html = habits_router.habits_regions(_request("/habits/regions"), conn=conn).body.decode()
        assert html.lstrip().startswith("{#") is False
        assert '<div id="habits-body"' in html
        assert "<html" not in html

    def test_nav_has_habits_link(self, conn):
        _, body = _page(conn)
        assert 'href="/habits" data-tab="habits" class="tab-btn active"' in body


class TestHabitDays:
    @pytest.mark.parametrize(
        "rec,days,present,expected",
        [
            ("FREQ=DAILY", ["WE", "MO", "FR"], "1", "FREQ=WEEKLY;BYDAY=MO,WE,FR"),
            ("FREQ=WEEKLY;BYDAY=MO,WE", [], "1", "FREQ=WEEKLY"),
            ("FREQ=DAILY", [], "1", "FREQ=DAILY"),
            ("FREQ=DAILY", ["MO"], "", "FREQ=DAILY"),  # form without the chips
            ("FREQ=DAILY", ["XX"], "1", "FREQ=DAILY"),
        ],
    )
    def test_apply(self, rec, days, present, expected):
        assert tasks_router._apply_habit_days(rec, days, present) == expected

    def test_create_with_days_and_form_prechecks(self, conn):
        db.save_task_habit_settings(conn, "Habit")
        tasks_router.create_task(title="Swim", description="", due_at="", status="active", tags="",
                                 tags_labels=["Habit"], recurrence="FREQ=DAILY", target_per_day="1",
                                 habit_days=["TU", "TH"], habit_days_present="1", conn=conn)
        task = next(t for t in db.list_habit_tasks(conn) if t["title"] == "Swim")
        assert task["recurrence"] == "FREQ=WEEKLY;BYDAY=TU,TH"
        form = tasks_router.edit_task_form(task["uid"], _request(f"/tasks/{task['uid']}/edit"), conn=conn).body.decode()
        assert 'value="TU" checked' in form and 'value="TH" checked' in form
        assert 'value="MO" checked' not in form
        page = habits_router.habits_page(_request(), conn=conn).body.decode()
        assert "Tue, Thu" in page


class TestHabitRepeat:
    """2026-09-26 (Peter): the habit form's "How often" choice replaces the
    raw Recurrence picker ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" on screen)."""

    @pytest.mark.parametrize(
        "repeat,rec,days,per,expected",
        [
            ("daily", "FREQ=WEEKLY", ["MO"], "3", ("FREQ=DAILY", "")),
            ("days", "FREQ=DAILY", ["FR", "MO"], "3", ("FREQ=WEEKLY;BYDAY=MO,FR", "")),
            ("days", "FREQ=DAILY", [], "3", ("FREQ=DAILY", "")),
            ("week", "FREQ=DAILY", ["MO"], "3", ("FREQ=WEEKLY", "3")),
            ("month", "FREQ=DAILY", [], "2", ("FREQ=MONTHLY", "2")),
            ("keep", "FREQ=WEEKLY;INTERVAL=2", [], "1", ("FREQ=WEEKLY;INTERVAL=2", "1")),
            (None, "FREQ=YEARLY", ["MO"], None, ("FREQ=YEARLY", None)),  # plain task form
        ],
    )
    def test_apply(self, repeat, rec, days, per, expected):
        assert tasks_router._apply_habit_repeat(repeat, rec, days, per) == expected

    @pytest.mark.parametrize(
        "rec,per,mode,days,times",
        [
            ("FREQ=DAILY", None, "daily", [], 1),
            ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", None, "days", ["MO", "TU", "WE", "TH", "FR"], 1),
            ("FREQ=WEEKLY", 3, "week", [], 3),
            ("FREQ=MONTHLY", None, "month", [], 1),
            ("FREQ=WEEKLY;INTERVAL=2", None, "keep", [], 1),
            ("FREQ=DAILY;INTERVAL=2", None, "keep", [], 1),
            ("FREQ=DAILY;UNTIL=2027-01-01", None, "keep", [], 1),
        ],
    )
    def test_choice_for_existing_habit(self, rec, per, mode, days, times):
        from src import habit_view

        choice = habit_view.repeat_choice({"recurrence": rec, "habits_per_period": per})
        assert (choice["mode"], choice["days"], choice["times"]) == (mode, days, times)

    def test_edit_form_never_shows_the_raw_rule(self, conn):
        _habit(conn, "h1", "Walk", recurrence="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")
        form = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert "FREQ=" not in form
        assert 'data-repeat="days"' in form
        assert '<option value="days" selected>' in form
        assert 'value="MO" checked' in form and 'value="SA" checked' not in form
        assert "recurrence-input" not in form

    def test_edit_form_keeps_an_unusual_rule(self, conn):
        _habit(conn, "h1", "Clean", recurrence="FREQ=WEEKLY;INTERVAL=2")
        form = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert '<option value="keep" selected>Once every 2 weeks (current)</option>' in form
        assert '<input type="hidden" name="recurrence" value="FREQ=WEEKLY;INTERVAL=2">' in form

    def test_update_round_trip(self, conn):
        _habit(conn, "h1", "Gym")
        tasks_router.update_task("h1", title="Gym", description="", due_at="", start_at="", status="active", tags="",
                                 tags_labels=["Habit"], project="", project_field="", recurrence="",
                                 target_per_day="1", habit_days_present="", habit_kind="build", habit_unit="",
                                 reminder_time="", holiday_calendar="", exclude_saturday="", exclude_sunday="",
                                 x_requested_with=None,
                                 habits_per_period="3", habit_days=["MO"], habit_repeat="week", conn=conn)
        task = db.get_task(conn, "h1")
        assert (task["recurrence"], task["habits_per_period"]) == ("FREQ=WEEKLY", 3)
        tasks_router.update_task("h1", title="Gym", description="", due_at="", start_at="", status="active", tags="",
                                 tags_labels=["Habit"], project="", project_field="", recurrence="",
                                 target_per_day="1", habit_days_present="", habit_kind="build", habit_unit="",
                                 reminder_time="", holiday_calendar="", exclude_saturday="", exclude_sunday="",
                                 x_requested_with=None,
                                 habits_per_period="3", habit_days=[], habit_repeat="daily", conn=conn)
        task = db.get_task(conn, "h1")
        assert (task["recurrence"], task["habits_per_period"]) == ("FREQ=DAILY", None)


class TestPausesModal:
    """2026-09-26 (Peter): vacation lives in a modal behind a header button,
    not in a section on the page."""

    def test_page_has_button_not_section(self, conn):
        _habit(conn, "h1", "Read")
        _, body = _page(conn)
        assert 'href="/habits/pauses" data-modal' in body
        assert "habits-vacation" not in body and "Pause all habits" not in body

    def test_modal_lists_all_and_single_habit_pauses(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "a1", "No soda", habit_kind="avoid")
        db.add_habit_pause(conn, "p1", None, TODAY, TODAY, _now())
        db.add_habit_pause(conn, "p2", "h1", TODAY, TODAY, _now())
        db.add_habit_pause(conn, "old", "h1", "2020-01-01", "2020-01-02", _now())
        body = habits_router.pauses_modal(_request("/habits/pauses"), conn=conn).body.decode()
        assert "<strong>All habits</strong>" in body and "<strong>Read</strong>" in body
        assert "/habits/pauses/old/delete" not in body  # ended pauses aren't listed
        assert '<option value="h1">Read</option>' in body
        assert "No soda" not in body  # avoid habits can't be paused (UI audit H-12)


class TestCompactRow:
    """2026-09-26 (Peter): one short row per habit -- title and
    "schedule · streak" on one line; reminder time only in the tooltip."""

    def test_row_meta_is_one_line(self, conn):
        _habit(conn, "h1", "Read")
        db.set_task_reminder_time(conn, "h1", "07:30")
        _, body = _page(conn)
        assert '<span class="habit-card-meta" title="' in body
        assert "reminder at" in body  # in the tooltip
        assert "habit-card-main" in body
