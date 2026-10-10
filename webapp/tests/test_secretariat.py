"""What the Secretariat page lists, and under which heading."""

from datetime import date

import pytest

from src import secretariat

TODAY = date(2026, 10, 7)  # a Wednesday


def _task(uid, due=None, status="active"):
    return {"uid": uid, "title": uid, "due_at": due, "status": status}


def _event(uid, start):
    return {"uid": uid, "title": uid, "start_at": start}


def test_events_today_are_in_time_order():
    page = secretariat.build(TODAY, [], [_event("late", "2026-10-07T15:00"), _event("early", "2026-10-07T08:00"),
                                          _event("tomorrow", "2026-10-08T09:00")], [])
    assert [e["uid"] for e in page["events_today"]] == ["early", "late"]


def test_overdue_tasks_lead_the_due_today_list_and_are_flagged():
    tasks = [_task("today", "2026-10-07"), _task("old", "2026-10-02"), _task("gone", "2026-10-07", "archived")]
    page = secretariat.build(TODAY, tasks, [], [])
    assert [(r["task"]["uid"], r["overdue"]) for r in page["tasks_today"]] == [("old", True), ("today", False)]


def test_week_list_runs_to_sunday():
    tasks = [_task("fri", "2026-10-09"), _task("sun", "2026-10-11"), _task("next-mon", "2026-10-12")]
    page = secretariat.build(TODAY, tasks, [], [])
    assert [t["uid"] for t in page["tasks_week"]] == ["fri", "sun"]


def test_reminders_hold_two_habits_near_events_and_in_progress_tasks_not_listed_above():
    tasks = [_task("working", status="in_progress"), _task("working-due", "2026-10-08", "in_progress"),
             _task("waiting", status="waiting")]
    events = [_event("soon", "2026-10-09T10:00"), _event("far", "2026-10-20T10:00")]
    habits = [{"uid": f"h{n}"} for n in range(3)]
    page = secretariat.build(TODAY, tasks, events, habits)
    assert [(r["kind"], r["item"]["uid"]) for r in page["reminders"]] == [
        ("habit", "h0"), ("habit", "h1"), ("event", "soon"), ("task", "working")]


@pytest.mark.parametrize("hour, expected", [(6, "Good morning, Ada"), (13, "Good afternoon, Ada"), (21, "Good evening, Ada")])
def test_greeting_follows_the_hour(hour, expected):
    assert secretariat.greeting(hour, "Ada") == expected


def test_greeting_without_a_name():
    assert secretariat.greeting(9) == "Good morning"


def test_a_task_just_completed_stays_in_its_list_after_open_ones_and_is_not_overdue():
    tasks = [_task("done-now", "2026-10-02", "done"), _task("open", "2026-10-07")]
    page = secretariat.build(TODAY, tasks, [], [])
    assert [(r["task"]["uid"], r["overdue"]) for r in page["tasks_today"]] == [("open", False), ("done-now", False)]


def test_a_completed_task_is_not_an_in_progress_reminder():
    page = secretariat.build(TODAY, [_task("t", status="done")], [], [])
    assert page["reminders"] == []
