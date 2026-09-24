"""Tests for deps.py's `relative_date` Jinja filter (`_relative_date`) --
2026-09-24 direct request: the humanized cases must never exceed 5
characters, so "Tomorrow"/"Yesterday" were shortened to "Tmw"/"Yest"
("Today" already fit and is unchanged). Covers the filter directly rather
than through a rendered page, since it's a pure function of the stored
value and today's date."""

from __future__ import annotations

from datetime import date, timedelta

from src.deps import _relative_date


def test_today_is_unchanged():
    assert _relative_date(date.today().isoformat()) == "Today"


def test_tomorrow_is_shortened_to_tmw():
    tomorrow = date.today() + timedelta(days=1)
    assert _relative_date(tomorrow.isoformat()) == "Tmw"


def test_yesterday_is_shortened_to_yest():
    yesterday = date.today() - timedelta(days=1)
    assert _relative_date(yesterday.isoformat()) == "Yest"


def test_every_named_case_fits_a_five_character_budget():
    today = date.today()
    for delta in (0, 1, -1):
        value = _relative_date((today + timedelta(days=delta)).isoformat())
        assert len(value) <= 5, f"{value!r} exceeds the 5-char budget"


def test_other_dates_fall_back_to_day_month_unchanged():
    far_future = date.today() + timedelta(days=10)
    result = _relative_date(far_future.isoformat())
    assert result not in ("Tmw", "Yest", "Today")
    assert result == f"{far_future.day} {far_future.strftime('%b')}"


def test_full_iso_timestamp_and_unparseable_value_still_degrade_correctly():
    tomorrow = date.today() + timedelta(days=1)
    assert _relative_date(tomorrow.isoformat() + "T10:00:00") == "Tmw"
    assert _relative_date("not-a-date") == "not-a-date"
    assert _relative_date(None) is None
