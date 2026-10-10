"""Shared pytest setup: orders core tests first and provides the clock fixture."""

from datetime import date, datetime, time, timezone

import pytest

from src import clock, db


def pytest_collection_modifyitems(items):
    """Core tests (the rules) run before everything else."""
    items.sort(key=lambda item: 0 if item.get_closest_marker("core") else 1)


@pytest.fixture
def frozen_today():
    """Pin src.clock to a given date for one test: `frozen_today(date(2026, 10, 9))`."""

    def freeze(day: date) -> None:
        clock.set_override(datetime.combine(day, time(12, 0), tzinfo=timezone.utc))

    yield freeze
    clock.set_override(None)


@pytest.fixture
def home_is_dashboard(monkeypatch):
    """Home defaults to the Secretariat; tests of the widget dashboard ask for it explicitly."""
    monkeypatch.setattr(db, "get_home_page_type", lambda conn: "dashboard")


@pytest.fixture
def local_today():
    """Pin src.clock to the machine's own calendar day, for tests that seed data with date.today()."""
    clock.set_override(datetime.combine(date.today(), time(12, 0), tzinfo=timezone.utc))
    yield
    clock.set_override(None)
