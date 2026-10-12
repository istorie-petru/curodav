"""Repeating events as real rows: one event per occurrence, scoped edit and delete, the horizon, and the migration
of legacy repeating events."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, event_series, migrations
from src.routers import calendar as calendar_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path="/calendar"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def _now():
    return datetime.now(timezone.utc).isoformat()


def _create(conn, rule="FREQ=WEEKLY;BYDAY=MO;COUNT=6", start="2026-10-05T09:00", end="2026-10-05T10:00", **extra):
    calendar_router.create_event(
        title="Standup", description="", start_at=start, end_at=end, all_day="", location="", meeting_url="", tags="",
        recurrence=rule, reminders="", holiday_calendar=extra.get("holiday", ""), exclude_saturday="", exclude_sunday="", conn=conn)
    return event_series.members(conn, db.list_events(conn)[0]["series_uid"])


def _starts(rows):
    return [r["start_at"][:16] for r in rows]


def test_a_repeating_event_is_created_as_one_real_row_per_occurrence(conn):
    rows = _create(conn)
    assert _starts(rows) == ["2026-10-05T09:00", "2026-10-12T09:00", "2026-10-19T09:00", "2026-10-26T09:00", "2026-11-02T09:00", "2026-11-09T09:00"]
    assert all(r["recurrence"] is None and r["end_at"][11:16] == "10:00" for r in rows)
    assert event_series.get_series(conn, rows[0]["series_uid"])["rule"] == "FREQ=WEEKLY;BYDAY=MO;COUNT=6"


def test_an_open_ended_rule_is_created_to_the_horizon_and_topped_up_later(conn):
    rows = _create(conn, rule="FREQ=WEEKLY;BYDAY=MO", start="2026-10-05T09:00")
    assert 100 <= len(rows) <= 110
    later = date.today() + timedelta(days=400)
    assert event_series.ensure_horizon(conn, later) > 0
    assert len(event_series.members(conn, rows[0]["series_uid"])) > len(rows)
    assert event_series.ensure_horizon(conn, later) == 0


def test_the_weekend_policy_skips_occurrences(conn):
    rows = _create(conn, rule="FREQ=DAILY;COUNT=7", start="2026-10-05T09:00", end="")
    assert len(rows) == 7
    calendar_router.delete_series(rows[0]["uid"], x_requested_with=None, conn=conn)
    calendar_router.create_event(title="W", description="", start_at="2026-10-05T09:00", end_at="", all_day="", location="",
                                 meeting_url="", tags="", recurrence="FREQ=DAILY;UNTIL=2026-10-11", reminders="",
                                 holiday_calendar="", exclude_saturday="1", exclude_sunday="1", conn=conn)
    assert len(db.list_events(conn)) == 5


def test_each_occurrence_is_editable_on_its_own(conn):
    rows = _create(conn)
    calendar_router.update_event(uid=rows[2]["uid"], title="Retro", description="", start_at="2026-10-19T14:00", end_at="2026-10-19T15:00",
                                 all_day="", location="Room 4", meeting_url="", tags="", recurrence="FREQ=WEEKLY;BYDAY=MO;COUNT=6",
                                 reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", series_scope="this", conn=conn)
    rows = event_series.members(conn, rows[0]["series_uid"])
    assert [r["title"] for r in rows] == ["Standup", "Standup", "Retro", "Standup", "Standup", "Standup"]
    assert rows[2]["start_at"].startswith("2026-10-19T14:00") and rows[2]["location"] == "Room 4"


def test_editing_this_and_following_changes_later_rows_and_leaves_earlier_ones(conn):
    rows = _create(conn)
    calendar_router.update_event(uid=rows[3]["uid"], title="Sync", description="", start_at="2026-10-27T11:00", end_at="2026-10-27T12:00",
                                 all_day="", location="", meeting_url="", tags="", recurrence="FREQ=WEEKLY;BYDAY=MO;COUNT=6",
                                 reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", series_scope="following", conn=conn)
    got = db.list_events(conn)
    assert [(r["title"], r["start_at"][:16]) for r in got] == [
        ("Standup", "2026-10-05T09:00"), ("Standup", "2026-10-12T09:00"), ("Standup", "2026-10-19T09:00"),
        ("Sync", "2026-10-27T11:00"), ("Sync", "2026-11-03T11:00"), ("Sync", "2026-11-10T11:00")]
    first, last = got[0], got[-1]
    assert first["series_uid"] != last["series_uid"]
    assert "BYDAY=TU" in event_series.get_series(conn, last["series_uid"])["rule"]
    assert "COUNT=3" in event_series.get_series(conn, first["series_uid"])["rule"]


def test_editing_all_events_changes_every_row(conn):
    rows = _create(conn)
    calendar_router.update_event(uid=rows[1]["uid"], title="Weekly", description="", start_at="2026-10-12T08:30", end_at="2026-10-12T09:30",
                                 all_day="", location="", meeting_url="", tags="", recurrence="FREQ=WEEKLY;BYDAY=MO;COUNT=6",
                                 reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", series_scope="all", conn=conn)
    got = db.list_events(conn)
    assert {r["title"] for r in got} == {"Weekly"} and {r["start_at"][11:16] for r in got} == {"08:30"}


def test_changing_the_rule_from_here_rebuilds_the_later_rows(conn):
    rows = _create(conn)
    calendar_router.update_event(uid=rows[2]["uid"], title="Standup", description="", start_at="2026-10-19T09:00", end_at="2026-10-19T10:00",
                                 all_day="", location="", meeting_url="", tags="", recurrence="FREQ=DAILY;COUNT=3",
                                 reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", series_scope="following", conn=conn)
    assert [r["start_at"][:10] for r in db.list_events(conn)] == ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-20", "2026-10-21"]


def test_delete_scopes_use_relative_before_and_after(conn):
    rows = _create(conn)
    calendar_router.delete_event(rows[1]["uid"], x_requested_with=None, conn=conn)
    assert len(db.list_events(conn)) == 5
    calendar_router.delete_following(rows[3]["uid"], x_requested_with=None, conn=conn)
    assert _starts(db.list_events(conn)) == ["2026-10-05T09:00", "2026-10-19T09:00"]
    calendar_router.delete_series(rows[0]["uid"], x_requested_with=None, conn=conn)
    assert db.list_events(conn) == [] and conn.execute("SELECT COUNT(*) FROM event_series").fetchone()[0] == 0


def test_moving_one_occurrence_and_then_all_future_ones(conn):
    rows = _create(conn)
    one = rows[2]
    db.upsert_event(conn, dict(one, start_at="2026-10-21T09:00", end_at="2026-10-21T10:00"))
    event_series.shift_following(conn, one["uid"], timedelta(days=2))
    got = db.list_events(conn)
    assert _starts(got) == ["2026-10-05T09:00", "2026-10-12T09:00", "2026-10-21T09:00", "2026-10-28T09:00", "2026-11-04T09:00", "2026-11-11T09:00"]
    assert "BYDAY=WE" in event_series.get_series(conn, got[-1]["series_uid"])["rule"]


def test_a_rule_that_cannot_change_day_is_refused(conn):
    with pytest.raises(event_series.CannotShift):
        event_series.shift_rule("FREQ=MONTHLY;BYDAY=2MO", 1)
    assert event_series.shift_rule("FREQ=MONTHLY;BYDAY=2MO", 0) == "FREQ=MONTHLY;BYDAY=2MO"


def test_the_delete_question_has_three_choices_for_a_series(conn):
    rows = _create(conn)
    body = calendar_router.delete_scope_modal(rows[1]["uid"], _request(), conn=conn).body.decode()
    for path in ("/delete\"", "/delete-following", "/delete-series"):
        assert path in body
    detail = calendar_router.event_detail(rows[1]["uid"], _request(), conn=conn).body.decode()
    assert "/delete-scope" in detail and "Every week" in detail or "Weekly" in detail


def test_the_edit_form_asks_which_events_to_change(conn):
    rows = _create(conn)
    body = calendar_router.edit_event_form(rows[1]["uid"], _request(), conn=conn).body.decode()
    assert 'name="series_scope"' in body and "This and following events" in body


# ---- the migration of legacy repeating events

def _legacy(conn, uid="old", start="2026-10-05T09:00:00", end="2026-10-05T10:00:00", rule="FREQ=WEEKLY;BYDAY=MO;COUNT=6", **extra):
    db.upsert_event(conn, {"uid": uid, "title": "Old", "description": "d", "start_at": start, "end_at": end, "all_day": False,
                           "status": "active", "recurrence": rule, "tags": ["Work"], "reminders": [10], "created_at": _now(),
                           "updated_at": _now(), **extra})


def test_the_migration_turns_a_legacy_repeating_event_into_rows(conn):
    _legacy(conn)
    db.upsert_event_occurrence_override(conn, {"master_uid": "old", "occurrence_date": "2026-10-12T09:00:00", "cancelled": True,
                                               "created_at": _now(), "updated_at": _now()})
    db.upsert_event_occurrence_override(conn, {"master_uid": "old", "occurrence_date": "2026-10-19T09:00:00", "cancelled": False,
                                               "start_at": "2026-10-20T15:00:00", "end_at": "2026-10-20T16:00:00", "title": "Moved",
                                               "created_at": _now(), "updated_at": _now()})
    migrations._repeating_events_become_rows(conn)
    got = db.list_events(conn)
    assert [(r["title"], r["start_at"][:16]) for r in got] == [
        ("Old", "2026-10-05T09:00"), ("Moved", "2026-10-20T15:00"), ("Old", "2026-10-26T09:00"), ("Old", "2026-11-02T09:00"), ("Old", "2026-11-09T09:00")]
    assert got[0]["uid"] == "old" and all(r["recurrence"] is None and r["tags"] == ["Work"] and r["reminders"] == [10] for r in got)
    assert db.list_event_occurrence_overrides(conn, "old") == []


def test_the_migration_is_safe_to_run_twice(conn):
    _legacy(conn)
    migrations._repeating_events_become_rows(conn)
    count = len(db.list_events(conn))
    migrations._repeating_events_become_rows(conn)
    assert len(db.list_events(conn)) == count


def test_the_migration_respects_exceptions_dates_and_leaves_unreadable_rules_alone(conn):
    _legacy(conn, uid="a", rule="FREQ=DAILY;COUNT=4", exdates=["2026-10-06"])
    _legacy(conn, uid="b", rule="NOT A RULE")
    migrations._repeating_events_become_rows(conn)
    mine = [r for r in db.list_events(conn) if r["series_uid"]]
    assert [r["start_at"][:10] for r in mine] == ["2026-10-05", "2026-10-07", "2026-10-08"]
    assert db.get_event(conn, "b")["recurrence"] == "NOT A RULE" and db.get_event(conn, "b")["series_uid"] is None


def test_the_migration_is_registered_and_backs_up_first(conn):
    numbers = {m.number: m for m in migrations.MIGRATIONS}
    assert numbers[9].destructive and "real event" in numbers[9].name
    assert conn.execute("SELECT 1 FROM schema_migrations WHERE number = 9").fetchone()


def test_the_drag_toast_is_only_offered_for_rules_that_can_follow_a_day_shift(conn):
    assert event_series.shiftable("FREQ=WEEKLY;BYDAY=MO") and event_series.shiftable("FREQ=DAILY")
    assert not event_series.shiftable("FREQ=MONTHLY;BYDAY=2MO")
    rows = _create(conn, rule="FREQ=MONTHLY;BYDAY=2MO;COUNT=3", start="2026-10-12T09:00", end="")
    body = calendar_router.week_view(_request("/calendar/week"), date_="2026-10-12", conn=conn).body.decode()
    assert 'data-uid="' + rows[0]["uid"] in body and 'data-series="1"' not in body


def test_an_unshiftable_rule_never_raises_and_later_events_keep_their_days(conn):
    rows = _create(conn, rule="FREQ=MONTHLY;BYDAY=2MO;COUNT=3", start="2026-10-12T09:00", end="2026-10-12T10:00")
    assert event_series.shift_following(conn, rows[0]["uid"], timedelta(days=1)) == 0
    calendar_router.update_event(uid=rows[1]["uid"], title="Review", description="", start_at="2026-11-10T11:00", end_at="2026-11-10T12:00",
                                 all_day="", location="", meeting_url="", tags="", recurrence="FREQ=MONTHLY;BYDAY=2MO;COUNT=3",
                                 reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", series_scope="following", conn=conn)
    got = db.list_events(conn)
    assert [(r["title"], r["start_at"][:16]) for r in got] == [
        ("Standup", "2026-10-12T09:00"), ("Review", "2026-11-10T11:00"), ("Review", "2026-12-14T11:00")]


def test_synced_events_with_a_rule_arrive_as_one_time_events():
    from icalendar import Calendar
    from src import ical_rows

    ics = ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:x1\nSUMMARY:Gym\nDTSTART:20261005T180000\nDTEND:20261005T190000\n"
           "RRULE:FREQ=WEEKLY\nEXDATE:20261012T180000\nEND:VEVENT\nBEGIN:VEVENT\nUID:x1\nRECURRENCE-ID:20261019T180000\nSUMMARY:Gym moved\n"
           "DTSTART:20261019T200000\nDTEND:20261019T210000\nEND:VEVENT\nEND:VCALENDAR\n")
    rows = [ical_rows.ical_to_event_row(c, one_time=True) for c in Calendar.from_ical(ics).walk("VEVENT")]
    assert rows[0]["recurrence"] is None and rows[0]["exdates"] == [] and rows[0]["uid"] == "x1"
    assert rows[1]["uid"].startswith("x1-") and rows[1]["uid"] != "x1" and rows[1]["recurrence"] is None
