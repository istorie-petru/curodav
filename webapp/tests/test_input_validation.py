"""A task or event the forms would refuse is also refused when posted directly, with a message the modal shows as a toast."""

from src.validation import TITLE_MAX, event_error, task_error

STATUSES = ["active", "done"]


def test_a_valid_task_has_no_error():
    assert task_error("Pay rent", "2026-10-01", "2026-10-05T09:00", "active", STATUSES) is None


def test_a_blank_title_is_refused_with_the_title_field():
    assert task_error("   ", "", "", "active", STATUSES)["field"] == "title"


def test_a_very_long_title_is_refused():
    assert task_error("a" * (TITLE_MAX + 1), "", "", "active", STATUSES)["field"] == "title"


def test_an_unknown_status_is_refused():
    assert task_error("x", "", "", "bogus", STATUSES)["field"] == "status"


def test_a_garbage_due_date_is_refused():
    assert task_error("x", "", "garbage", "active", STATUSES)["field"] == "due_at"


def test_a_due_date_before_the_start_date_is_refused():
    assert task_error("x", "2026-10-20", "2026-10-10", "active", STATUSES)["field"] == "due_at"


def test_an_event_that_ends_before_it_starts_is_refused():
    assert event_error("Meeting", "2026-10-20T10:00", "2026-10-20T09:00")["field"] == "end_at"


def test_an_event_without_an_end_is_fine():
    assert event_error("Meeting", "2026-10-20T10:00", "") is None
