"""Recurrence rules read as plain phrases, so task and event details never show a raw RRULE."""

import pytest

from src.recurrence_text import describe


@pytest.mark.parametrize("rule, phrase", [
    ("FREQ=DAILY", "Daily"),
    ("FREQ=WEEKLY", "Weekly"),
    ("FREQ=WEEKLY;INTERVAL=2", "Every 2 weeks"),
    ("FREQ=WEEKLY;BYDAY=MO,WE,FR", "Weekly on Monday, Wednesday and Friday"),
    ("FREQ=MONTHLY;BYDAY=2TU", "Monthly on the second Tuesday"),
    ("FREQ=MONTHLY;BYDAY=-1FR", "Monthly on the last Friday"),
    ("FREQ=MONTHLY;BYMONTHDAY=15", "Monthly on day 15"),
    ("FREQ=YEARLY;UNTIL=2026-12-12", "Yearly, until 12 Dec 2026"),
    ("FREQ=DAILY;COUNT=5", "Daily, 5 times"),
    ("FREQ=DAILY;COUNT=1", "Daily, 1 time"),
])
def test_known_rules_read_as_phrases(rule, phrase):
    assert describe(rule) == phrase


@pytest.mark.parametrize("rule", [None, "", "None", "Nothing"])
def test_no_rule_is_empty(rule):
    assert describe(rule) == ""


@pytest.mark.parametrize("rule", ["garbage", "FREQ=HOURLY", "FREQ=WEEKLY;BYDAY=XX"])
def test_unreadable_rule_is_custom(rule):
    assert describe(rule) == "Custom"


def test_task_and_event_details_show_the_phrase_not_the_rule(tmp_path):
    from datetime import datetime, timezone
    from starlette.requests import Request
    from src import db
    from src.routers import calendar as calendar_router
    from src.routers import tasks as tasks_router

    now = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()
    request = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "scheme": "http",
                       "server": ("testserver", 80), "root_path": "", "headers": []})
    with db.connect(tmp_path / "cache.sqlite") as conn:
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active",
                              "created_at": now, "recurrence": "FREQ=WEEKLY;INTERVAL=2"})
        db.upsert_event(conn, {"uid": "e1", "title": "e1", "description": "", "start_at": "2026-10-10T09:00:00",
                               "status": "active", "all_day": False, "created_at": now, "updated_at": now,
                               "recurrence": "FREQ=MONTHLY;BYDAY=2TU"})
        task_page = tasks_router.task_detail("t1", request, conn=conn).body.decode()
        event_page = calendar_router.event_detail("e1", request, conn=conn).body.decode()
    assert "Every 2 weeks" in task_page and "FREQ=" not in task_page
    assert "Monthly on the second Tuesday" in event_page and "FREQ=MONTHLY" not in event_page
