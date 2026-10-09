"""Shared pytest setup: orders core tests first and provides the clock fixture."""

from datetime import date, datetime, time, timezone

import pytest

from src import clock


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
