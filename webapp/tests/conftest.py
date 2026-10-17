"""Shared pytest setup: orders core tests first and provides the clock fixture."""

import shutil
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


def pytest_sessionfinish(session, exitstatus):
    """A green run leaves nothing in the temp folder (each test's database is megabytes); a red one keeps the failed tests' folders."""
    if exitstatus == 0:
        base = session.config._tmp_path_factory.getbasetemp() if hasattr(session.config, "_tmp_path_factory") else None
        if base is not None:
            shutil.rmtree(base, ignore_errors=True)
