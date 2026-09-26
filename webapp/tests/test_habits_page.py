"""Habits H2 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): the
Habits page at /habits -- replaces the Tasks table's Habits group. Rows
come from habit_view.habit_items; "To do" holds habits whose open window
isn't kept yet, "On track" the rest. Every control posts to the task
completion endpoints. Also covers the habit form's "Only on" weekday
chips (routers/tasks.py _apply_habit_days)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import re

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
        # 2026-09-26: this calendar week from Monday (the default first
        # day); days after today are inert spans.
        first = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        assert body.count('class="form-inline habit-action habit-day-form"') == date.today().weekday() + 1
        strip = body[body.index('class="habit-week"'):]
        assert strip.index(f"/tasks/h1/completion/{first}") <= strip.index(f"/tasks/h1/completion/{TODAY}/toggle")
        assert body.count('class="habit-day is-future"') == 6 - date.today().weekday()
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
        assert re.search(r'value="TU" form="habit-task-form" data-short="Tue" checked', form)
        assert re.search(r'value="TH" form="habit-task-form" data-short="Thu" checked', form)
        assert 'data-short="Mon" checked' not in form
        assert '<span class="ms-summary">Tue, Thu</span>' in form
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
        assert re.search(r'name="habit_repeat" value="days"\s+form="habit-task-form"\s+checked', form)
        assert '<span class="ms-summary">Weekdays</span>' in form
        assert 'data-short="Sat" checked' not in form
        assert "recurrence-input" not in form

    def test_edit_form_keeps_an_unusual_rule(self, conn):
        _habit(conn, "h1", "Clean", recurrence="FREQ=WEEKLY;INTERVAL=2")
        form = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert re.search(r'name="habit_repeat" value="keep"\s+form="habit-task-form"\s+checked', form)
        assert "Once every 2 weeks (current)" in form
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


class TestSecondPass20260926:
    """2026-09-26 (Peter, second pass): week start, compact widget row,
    expandable history, habit colour + icon, edit form without pills."""

    def test_strip_follows_sunday_week_start(self, conn):
        from src import habit_view

        _habit(conn, "h1", "Read")
        db.set_app_meta(conn, habit_view.WEEK_START_KEY, "sunday")
        today = date(2026, 9, 23)  # a Wednesday
        week = habit_view.habit_items(conn, today)[0]["week"]
        assert [d["iso"] for d in week][0] == "2026-09-20"  # the Sunday before
        assert [d["initial"] for d in week] == ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
        assert [d["is_future"] for d in week] == [False] * 4 + [True] * 3

    def test_page_row_has_chevron_and_history_panel(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "h2", "Gym", recurrence="FREQ=WEEKLY", habits_per_period=3)
        _, body = _page(conn)
        assert 'class="icon-btn habit-expand" aria-expanded="false" aria-controls="habit-panel-h1"' in body
        panel_h1 = body[body.index('id="habit-panel-h1"'):]
        assert 'class="heatmap heatmap-wide' in panel_h1[:600]
        panel_h2 = body[body.index('id="habit-panel-h2"'):]
        assert 'habit-periods habit-periods-week' in panel_h2[:600]

    def test_widget_row_is_compact(self, conn):
        from src.deps import templates

        _habit(conn, "h1", "Read")
        from src import habit_view

        tpl = templates.env.from_string(
            '{% from "_habit_page_row.html" import habit_page_row with context %}{{ habit_page_row(h, compact=true) }}'
        )
        html = tpl.render(h=habit_view.habit_items(conn)[0], request=_request())
        assert "is-compact" in html
        assert "habit-card-meta" not in html and "habit-expand" not in html and "habit-panel" not in html

    def test_colour_and_icon_round_trip(self, conn):
        _habit(conn, "h1", "Read")
        tasks_router.update_task("h1", title="Read", description="", due_at="", start_at="", status="active", tags="",
                                 tags_labels=["Habit"], project="", project_field="", recurrence="",
                                 target_per_day="1", habit_days_present="", habit_kind="build", habit_unit="",
                                 reminder_time="", holiday_calendar="", exclude_saturday="", exclude_sunday="",
                                 x_requested_with=None, habits_per_period="", habit_days=[], habit_repeat="daily",
                                 habit_icon="moon", habit_color="purple", conn=conn)
        task = db.get_task(conn, "h1")
        assert (task["habit_icon"], task["habit_color"]) == ("moon", "purple")
        _, body = _page(conn)
        assert "habit-card habit-c-purple" in body and 'href="#icon-moon"' in body
        # unknown names store the default
        tasks_router._save_habit_look(conn, "h1", "rocket-ship", "neon")
        task = db.get_task(conn, "h1")
        assert (task["habit_icon"], task["habit_color"]) == (None, None)

    def test_edit_form_has_dropdowns_and_no_hint_text(self, conn):
        _habit(conn, "h1", "Read")
        form = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert "habit-choice-row" not in form and "habit-days-hint" not in form and "field-hint" not in form
        assert 'data-ms-label="kind"' in form and "habit-look-select" in form
        assert 'name="habit_color" value="purple"' in form and 'name="habit_icon" value="moon"' in form

    def test_backup_restore_keeps_look_and_reminder(self, conn):
        from src.routers import export as export_router

        _habit(conn, "h1", "Read")
        db.set_task_habit_look(conn, "h1", "moon", "purple")
        db.set_task_reminder_time(conn, "h1", "07:30")
        payload = {"tasks": [db.get_task(conn, "h1")]}
        db.set_task_habit_look(conn, "h1", None, None)
        db.set_task_reminder_time(conn, "h1", "")
        export_router.restore_backup_payload(conn, payload)
        task = db.get_task(conn, "h1")
        assert (task["habit_icon"], task["habit_color"], task["reminder_time"]) == ("moon", "purple", "07:30")


class TestEditFormMockup20260926:
    """2026-09-26: Peter's approved edit-modal mockup -- dropdown follow-ups
    half width next to their parent; Daily goal as check-off vs amount."""

    def test_times_dropdowns_and_goal(self):
        f = tasks_router._apply_habit_repeat
        assert f("week", "", [], "9", "4", "2") == ("FREQ=WEEKLY", "4")
        assert f("month", "", [], "9", "4", "2") == ("FREQ=MONTHLY", "2")
        assert tasks_router._apply_habit_goal("once", "8") == "1"
        assert tasks_router._apply_habit_goal("amount", "8") == "8"
        assert tasks_router._apply_habit_goal(None, "8") == "8"  # plain task form

    @pytest.mark.parametrize(
        "codes,week_start,expected",
        [
            ([], "monday", "Pick days"),
            (["MO", "TU", "WE", "TH", "FR", "SA", "SU"], "monday", "Every day"),
            (["FR", "MO", "TU", "WE", "TH"], "monday", "Weekdays"),
            (["SU", "SA"], "monday", "Weekends"),
            (["FR", "MO", "WE"], "monday", "Mon, Wed, Fri"),
            (["SU", "MO"], "sunday", "Sun, Mon"),
            (["SU", "MO"], "monday", "Mon, Sun"),
        ],
    )
    def test_days_label(self, codes, week_start, expected):
        from src import habit_view

        assert habit_view.days_label(codes, week_start) == expected

    def test_day_options_follow_week_start(self):
        from src import habit_view

        opts = habit_view.repeat_choice({"recurrence": "FREQ=DAILY"}, "sunday")["day_options"]
        assert [o["code"] for o in opts] == ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]

    def test_amount_habit_round_trip_and_back_to_once(self, conn):
        _habit(conn, "h1", "Water")
        base = dict(title="Water", description="", due_at="", start_at="", status="active", tags="",
                    tags_labels=["Habit"], project="", project_field="", recurrence="",
                    habit_days_present="", habit_kind="build", reminder_time="", holiday_calendar="",
                    exclude_saturday="", exclude_sunday="", x_requested_with=None, habits_per_period="",
                    habit_days=[], habit_repeat="daily", conn=conn)
        tasks_router.update_task("h1", target_per_day="8", habit_unit="glasses", habit_goal="amount", **base)
        task = db.get_task(conn, "h1")
        assert (task["target_per_day"], task["habit_unit"]) == (8, "glasses")
        tasks_router.update_task("h1", target_per_day="8", habit_unit="glasses", habit_goal="once", **base)
        assert db.get_task(conn, "h1")["target_per_day"] == 1

    def test_form_order_and_half_width_hooks(self, conn):
        _habit(conn, "h1", "Read")
        form = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        order = [form.index(x) for x in ('name="title"', "habit-look-select", 'data-ms-label="kind"',
                                         'data-ms-label="how often"', 'data-ms-label="daily goal"',
                                         'data-ms-label="reminder"', 'name="description"')]
        assert order == sorted(order)
        assert "habit-sub habit-sub-days" in form and "habit-sub habit-sub-week" in form
        assert "habit-sub habit-sub-amount" in form and "stepper-btn" not in form

    def test_view_modal_has_no_log_form(self, conn):
        _habit(conn, "h1", "Read")
        body = tasks_router.task_detail("h1", _request("/tasks/h1"), conn=conn).body.decode()
        assert "habit-log-form" not in body and "Log a day" not in body
