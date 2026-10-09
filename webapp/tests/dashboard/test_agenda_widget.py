"""The Agenda widget: what each range shows for tasks, events and overdue items, with the clock pinned."""

from __future__ import annotations

from datetime import timedelta

from dashboard_seed import seed_event, seed_recurring_event, seed_task, set_completed_at

from src.routers import dashboard as dashboard_router


class TestAgendaWidgetToday:
    """range="today" reproduces today_agenda's old content: overdue + due-
    today tasks (as separate Overdue/Tasks sections now) and today's
    events."""

    def test_includes_overdue_and_today_excludes_future(self, conn, today):
        seed_task(conn, "overdue", due_at=(today - timedelta(days=2)).isoformat())
        seed_task(conn, "today", due_at=today.isoformat())
        seed_task(conn, "future", due_at=(today + timedelta(days=3)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "today"})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue"}
        assert {t["uid"] for t in data["tasks"]} == {"today"}

    def test_events_only_today(self, conn, today):
        seed_event(conn, "e_today", start_at=f"{today.isoformat()}T09:00:00")
        seed_event(conn, "e_tomorrow", start_at=f"{(today + timedelta(days=1)).isoformat()}T09:00:00")
        data = dashboard_router._render_agenda(conn, {"range": "today"})
        assert {e["uid"] for e in data["events"]} == {"e_today"}

    def test_show_toggles_narrow_the_sections_rendered(self, conn, today):
        seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        seed_task(conn, "today", due_at=today.isoformat())
        seed_event(conn, "e_today", start_at=f"{today.isoformat()}T09:00:00")
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["overdue"]})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue"}
        assert data["tasks"] == []
        assert data["events"] == []


class TestAgendaWidgetDays:
    def test_groups_by_day_across_next_seven_days(self, conn, today):
        seed_task(conn, "t1", due_at=today.isoformat())
        seed_task(conn, "t2", due_at=(today + timedelta(days=3)).isoformat())
        seed_task(conn, "t_out_of_range", due_at=(today + timedelta(days=10)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "next_7_days"})
        assert data["mode"] == "days"
        assert len(data["days"]) == 7
        assert data["days"][0]["is_today"] is True
        all_task_uids = {t["uid"] for day in data["days"] for t in day["tasks"]}
        assert all_task_uids == {"t1", "t2"}

    def test_next_30_days_range_is_flat_like_all_upcoming(self, conn, today):
        # 2026-08-31 direct feedback: "next 30 days range css should look
        # like all upcoming" -- it's flat/limit-capped/chronological now,
        # not a 30-cell day grid.
        seed_task(conn, "t_in", due_at=(today + timedelta(days=3)).isoformat())
        seed_task(conn, "t_out", due_at=(today + timedelta(days=40)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "next_30_days"})
        assert data["mode"] == "flat"
        assert "days" not in data
        assert {t["uid"] for t in data["tasks"]} == {"t_in"}

    def test_next_30_days_windows_events_for_recurrence(self, conn, today):
        seed_recurring_event(conn, "recur", start_at=f"{(today - timedelta(days=30)).isoformat()}T09:00", recurrence="FREQ=WEEKLY")
        data = dashboard_router._render_agenda(conn, {"range": "next_30_days", "show": ["events"]})
        assert data["mode"] == "flat"
        assert any(e["uid"] == "recur" for e in data["events"])


class TestAgendaWidgetAllUpcoming:
    def test_only_future_events_chronological(self, conn, now):
        seed_event(conn, "past", start_at=(now - timedelta(days=1)).isoformat())
        seed_event(conn, "soon", start_at=(now + timedelta(days=1)).isoformat())
        seed_event(conn, "later", start_at=(now + timedelta(days=5)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"]})
        assert [e["uid"] for e in data["events"]] == ["soon", "later"]

    def test_todays_earlier_events_still_count_as_upcoming(self, conn, now):
        # 2026-09-03 direct bug report ("the data is not put in the...
        # Upcoming correctly") -- this branch used to compare the full
        # start_at timestamp against datetime.now().isoformat(), so an
        # event whose clock time on *today's own date* was earlier than
        # the moment this renders got silently dropped, even though it's
        # still today, not "past." Only a fully past *date* should be
        # excluded -- an event a minute from now, and one already an hour
        # ago earlier today, must both still show.
        today_str = now.date().isoformat()
        seed_event(conn, "earlier_today", start_at=f"{today_str}T00:00:00")
        seed_event(conn, "yesterday", start_at=(now - timedelta(days=1)).isoformat())
        seed_event(conn, "soon", start_at=(now + timedelta(hours=1)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"]})
        assert {e["uid"] for e in data["events"]} == {"earlier_today", "soon"}

    def test_respects_limit(self, conn, now):
        for i in range(5):
            seed_event(conn, f"e{i}", start_at=(now + timedelta(days=i + 1)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"], "limit": 2})
        assert len(data["events"]) == 2

    def test_limit_zero_means_8_items_max(self, conn, now):
        # 2026-08-31 direct feedback: "add a way to set the limit to 0
        # (0 = unlimited)" -- `config.get("limit") or 10` used to collapse
        # a stored 0 back into the 10-item default; must not fall back to
        # the default once explicitly set to 0.
        # 2026-09-13 direct request ("no limit should actually be 20
        # maximum items") -- 0 is no longer truly unlimited, it now caps at
        # 20; 2026-09-28 direct feedback ("make the default limit smaller,
        # maximum 8") dropped that cap (and the default) to 8 -- seeds 25
        # (more than the cap) and asserts exactly 8 come back.
        for i in range(25):
            seed_event(conn, f"e{i}", start_at=(now + timedelta(days=i + 1)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"], "limit": 0})
        assert len(data["events"]) == 8

    def test_all_upcoming_range_bounds_to_364_days_out(self, conn, now):
        # 2026-09-13 direct request: "widgets that don't have a time limit
        # -- the time limit shouldn't actually be infinite, it should
        # always be 364 days into the future." Previously all_upcoming left
        # Tasks with no upper bound at all and windowed Events to 730 days
        # (recurrence-expansion cap, not a real display bound); both now
        # share a 364-day horizon. limit=0 (see above) would otherwise cap
        # this at 20, well below the 25 seeded, so a generous per-item
        # limit here isolates the date-bound behavior specifically.
        seed_event(conn, "within_horizon", start_at=(now + timedelta(days=360)).isoformat())
        seed_event(conn, "past_horizon", start_at=(now + timedelta(days=400)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"], "limit": 30})
        assert [e["uid"] for e in data["events"]] == ["within_horizon"]


class TestAgendaWidgetOverdueOnly:
    def test_only_overdue_open_tasks(self, conn, today, now):
        seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        seed_task(conn, "today", due_at=today.isoformat())
        seed_task(conn, "done_overdue", due_at=(today - timedelta(days=2)).isoformat(), status="done")
        set_completed_at(conn, "done_overdue", now - timedelta(hours=1))
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["overdue"]})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue"}

    def test_just_completed_overdue_task_stays_visible_during_grace_window(self, conn, today, now):
        seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        seed_task(conn, "just_done", due_at=(today - timedelta(days=2)).isoformat(), status="done")
        set_completed_at(conn, "just_done", now - timedelta(minutes=5))
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["overdue"]})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue", "just_done"}
