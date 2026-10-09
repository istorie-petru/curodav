"""Fixtures for the dashboard tests: a fresh database and a pinned clock."""

from datetime import date, datetime, time, timezone

import pytest

from src import clock, db

PINNED_DAY = date(2026, 10, 9)  # a Friday


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


@pytest.fixture(autouse=True)
def pinned_clock(frozen_today):
    """Every dashboard test runs on PINNED_DAY, never on the real date."""
    frozen_today(PINNED_DAY)


@pytest.fixture()
def today(pinned_clock):
    """Today's date, pinned to PINNED_DAY for the whole test."""
    return PINNED_DAY


@pytest.fixture()
def now(today):
    """The pinned clock's current moment (PINNED_DAY at 12:00 UTC)."""
    return clock.now()
