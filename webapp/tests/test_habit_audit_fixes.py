"""UI audit 2026-09-25 (documentation/plans/ui-audit-2026-09-25.md), Habits
area: amount habits are done only at their target (H-01/H-02/C-5), the
strip's off days and two-letter initials (H-16), "Log a day" with an
empty amount keeps the day's value (H-13), the Habit check-in widget's
count (H-08) and empty state (H-22), avoid habits never paused (H-12),
the single Notifications form (H-19), and the CSS/template hooks behind
the other P2s."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db, habit_schedule, habit_view, push, reminders
from src.routers import dashboard as dashboard_router
from src.routers import settings as settings_router
from src.routers import tasks as tasks_router

SRC = Path(__file__).resolve().parent.parent / "src"
TODAY = date.today()


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid, title="Water", target=1, rrule="FREQ=DAILY", kind="build", created=None):
    db.save_task_habit_settings(conn, "Habit")
    db.upsert_task(
        conn,
        {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Habit"],
         "recurrence": rrule, "target_per_day": target, "habit_kind": kind,
         "created_at": created or _now()},
    )


def _req(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})


class TestAmountHabitDoneAtTarget:
    def test_stats_only_count_days_at_target(self):
        today = date(2026, 9, 25)
        entries = {"2026-09-22": 8, "2026-09-23": 8, "2026-09-24": 1, "2026-09-25": 3}
        s = habit_schedule.habit_stats(entries, "FREQ=DAILY", today=today, target_per_day=8)
        # 24th is partial -> breaks the run; today (3/8) is still open.
        assert (s["current"], s["longest"], s["due_today"]) == (0, 2, True)
        # Without a target any value counts (the old rule, still used for
        # a plain habit).
        plain = habit_schedule.habit_stats(entries, "FREQ=DAILY", today=today)
        assert plain["current"] == 4 and plain["due_today"] is False

    def test_one_plus_one_leaves_the_habit_to_do(self, conn):
        _habit(conn, "h1", target=8)
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=1)
        item = habit_view.habit_items(conn)[0]
        assert item["due_today"] is True
        assert (item["done_today"], item["partial_today"], item["remaining_today"]) == (False, True, 7)
        # ...so the widget isn't "all done" and the Agenda keeps the row.
        data = dashboard_router._render_habit_checkin(conn, {})
        assert data["all_done"] is False
        assert [h["uid"] for h in dashboard_router._agenda_habits(conn, {}, {"habits"})] == ["h1"]
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=8)
        item = habit_view.habit_items(conn)[0]
        assert (item["due_today"], item["done_today"], item["partial_today"]) == (False, True, False)

    def test_detail_stats_use_real_values(self, conn):
        _habit(conn, "h1", target=8)
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=2)
        resp = tasks_router.task_detail("h1", _req("/tasks/h1"), conn=conn)
        stats = resp.context["habit_stats"]
        assert stats["due_today"] is True and stats["current"] == 0

    def test_strip_and_month_mark_partial_days(self, conn):
        _habit(conn, "h1", target=8)
        y = (TODAY - timedelta(days=1)).isoformat()
        db.upsert_task_completion(conn, "h1", y, _now(), value=4)
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=8)
        week = habit_view.habit_items(conn)[0]["week"]
        assert (week[-2]["done"], week[-2]["partial"]) == (False, True)
        assert (week[-1]["done"], week[-1]["partial"]) == (True, False)
        month = habit_view.month_calendar("h1", db.list_task_completions(conn, "h1"), None, target=8)
        days = {d["iso"]: d for w in month["weeks"] for d in w}
        assert days[TODAY.isoformat()]["done"] is True
        if y in days:
            assert (days[y]["done"], days[y]["partial"]) == (False, True)

    def test_plain_habit_any_value_is_done(self, conn):
        _habit(conn, "h1")
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=1)
        item = habit_view.habit_items(conn)[0]
        assert (item["is_quantity"], item["done_today"], item["partial_today"]) == (False, True, False)


class TestDayViewQuantityHabit:
    def test_day_row_carries_target_and_plus(self, conn):
        _habit(conn, "h1", target=8)
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=1)
        row = habit_view.habits_for_day(conn, TODAY)[0]
        assert row["is_quantity"] is True
        assert (row["value"], row["target"], row["next_value"]) == (1, 8, 2)
        assert (row["done"], row["partial"]) == (False, True)
        assert row["plus_url"] == "/tasks/h1/completions" and row["date"] == TODAY.isoformat()

    def test_day_grid_template_renders_plus_form(self):
        text = (SRC / "templates" / "_calendar_day_grid.html").read_text()
        assert 'action="{{ h.plus_url }}"' in text
        assert "{{ h.value|int }}/{{ h.target|int }}" in text


class TestStripOffDays:
    def test_off_days_and_two_letter_initials(self, conn):
        _habit(conn, "h1", rrule="FREQ=WEEKLY;BYDAY=MO,WE,FR")
        week = habit_view.habit_items(conn)[0]["week"]
        for d in week:
            wd = date.fromisoformat(d["iso"]).weekday()
            assert d["off_day"] is (wd not in (0, 2, 4))
            assert len(d["initial"]) == 2
        assert len({d["initial"] for d in week}) == 7

    def test_avoid_habit_has_no_off_days_and_no_pause(self, conn):
        _habit(conn, "h1", kind="avoid")
        db.add_habit_pause(conn, "p1", None, TODAY.isoformat(), TODAY.isoformat(), _now())
        item = habit_view.habit_items(conn)[0]
        assert not any(d["off_day"] for d in item["week"])
        assert item["paused_today"] is False


class TestLogADayEmptyAmount:
    def test_empty_value_keeps_existing_amount(self, conn):
        _habit(conn, "h1", target=8)
        d = TODAY.isoformat()
        db.upsert_task_completion(conn, "h1", d, _now(), value=1)
        tasks_router.set_task_completion("h1", _req(), completion_date=d, value="", note="just a note",
                                         x_requested_with="fetch", conn=conn)
        row = db.get_task_completion(conn, "h1", d)
        assert (row["value"], row["note"]) == (1, "just a note")

    def test_empty_value_on_new_day_logs_target(self, conn):
        _habit(conn, "h1", target=8)
        d = (TODAY - timedelta(days=1)).isoformat()
        tasks_router.set_task_completion("h1", _req(), completion_date=d, value="", note=None,
                                         x_requested_with="fetch", conn=conn)
        assert db.get_task_completion(conn, "h1", d)["value"] == 8

    def test_detail_template_amount_is_placeholder(self):
        text = (SRC / "templates" / "habit_task_detail.html").read_text()
        assert 'placeholder="{{ task.target_per_day|int }}"' in text
        assert 'value="{{ task.target_per_day|int }}"' not in text


class TestWidget:
    def _render(self, conn):
        tpl = dashboard_router.templates.env.get_template("_widget_habit_checkin.html")
        return tpl.render(request=_req(), data=dashboard_router._render_habit_checkin(conn, {}))

    def test_count_skips_avoid_habits_and_keeps_link(self, conn):
        _habit(conn, "h1", title="Read")
        _habit(conn, "h2", title="No sugar", kind="avoid")
        html = self._render(conn)
        assert "<strong>0</strong> of 1 done" in html
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), value=1)
        html = self._render(conn)
        assert "All done for now" in html and 'href="/habits" class="habit-widget-link"' in html

    def test_empty_state_links_to_new_habit(self, conn):
        html = self._render(conn)
        assert "No habits yet" in html and 'href="/tasks/new?habit=1"' in html


class TestNotificationsForm:
    def test_one_form_saves_email_via_fetch(self, conn):
        resp = settings_router.set_notifications(types=["tasks"], digest_time="07:30", email="me@example.org",
                                                 x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200 and json.loads(resp.body) == {"ok": True}
        assert push.contact_email(conn) == "me@example.org"
        assert reminders.digest_time_str(conn) == "07:30"

    def test_invalid_email_saves_nothing(self, conn):
        resp = settings_router.set_notifications(types=[], digest_time="06:00", email="nope",
                                                 x_requested_with="fetch", conn=conn)
        assert resp.status_code == 400 and "email" in json.loads(resp.body)["error"]
        assert reminders.digest_time_str(conn) == "08:00"

    def test_plain_post_returns_to_the_card(self, conn):
        resp = settings_router.set_notifications(types=[], digest_time="08:00", email=None,
                                                 x_requested_with=None, conn=conn)
        assert resp.headers["location"].endswith("#push-settings")

    def test_time_uses_app_format(self, conn):
        from src.deps import TIME_FORMAT_KEY

        db.set_app_meta(conn, TIME_FORMAT_KEY, "24h")
        body = settings_router.settings_general(_req("/settings/general"), conn=conn).body.decode()
        card = body.split('id="push-settings"', 1)[1]
        assert 'type="time"' not in card
        assert "PM" not in card


class TestStylingHooks:
    css = (SRC / "static" / "style.css").read_text()

    def test_partial_and_off_day_rules(self):
        for sel in (".habit-day.is-partial", ".habit-month-day.is-partial", ".habit-check-btn.is-partial",
                    ".habit-day.is-off", ".allday-habit.is-partial"):
            assert sel in self.css, sel

    def test_heatmap_view_only_on_touch(self):
        assert "@media (pointer: coarse)" in self.css and ".habit-year-heatmap .heatmap-cell{pointer-events:none;}" in self.css
        text = (SRC / "templates" / "habit_task_detail.html").read_text()
        assert "detail-plain-section habit-year-heatmap" in text

    def test_habit_actions_reads_error_body_and_offers_undo(self):
        js = (SRC / "static" / "habit_actions.js").read_text()
        assert "data.error" in js and 'label: "Undo"' in js


class TestCheckinSummaryCountsOnlyDoableHabits:
    """H-08 remainder (2026-09-25): the renderer, not just the template,
    leaves avoid habits out of done/total/all_done."""

    def test_avoid_habit_is_not_counted_as_done(self, conn):
        _habit(conn, "b1", title="Meditate")
        _habit(conn, "a1", title="No sugar", kind="avoid")
        data = dashboard_router._render_habit_checkin(conn, {})
        assert (data["done_count"], data["total"], data["all_done"]) == (0, 1, False)
        db.upsert_task_completion(conn, "b1", TODAY.isoformat(), _now(), value=1)
        data = dashboard_router._render_habit_checkin(conn, {})
        assert (data["done_count"], data["total"], data["all_done"]) == (1, 1, True)

    def test_only_avoid_habits_is_never_all_done(self, conn):
        _habit(conn, "a1", title="No sugar", kind="avoid")
        data = dashboard_router._render_habit_checkin(conn, {})
        assert (data["total"], data["all_done"]) == (0, False)
        assert len(data["rows"]) == 1  # the row itself still renders


def test_stack_bar_is_named_and_dissolve_has_its_own_icon():
    # H-18 (2026-09-25): "Dissolve stack" no longer shares Remove widget's x.
    tpl = (SRC / "templates" / "_widget_workspace.html").read_text()
    assert '<span class="widget-stack-label">Stack</span>' in tpl
    assert 'aria-label="Dissolve stack">{{ icon(\'scissors\', \'icon-sm\') }}' in tpl
