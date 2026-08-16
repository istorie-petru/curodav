"""src/quick_capture.py -- pure-function tests, no database at all (the
parser itself never touches `conn`; label resolution and entity creation
are routers/quick_capture.py's job, covered separately in
test_quick_capture.py). Covers every example in plans/quick-capture.md
verbatim, plus the edge cases the doc doesn't spell out (multiple bare
dates, no marker, malformed tokens, short-date year inference)."""

from __future__ import annotations

from datetime import date

import pytest

from src import quick_capture as qc

TODAY = date(2026, 7, 1)


class TestMarkerDetection:
    def test_no_marker_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("just some text", TODAY)

    def test_marker_must_be_a_standalone_token(self):
        # "!together" is not a recognized marker -- no space around it.
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!together nope", TODAY)

    def test_marker_may_appear_anywhere(self):
        r = qc.parse("Write bibliography !t 15/09/2026", TODAY)
        assert r.type == "task"
        assert r.title == "Write bibliography"
        assert r.due_date_iso == "2026-09-15"

    def test_first_marker_wins_when_more_than_one_present(self):
        r = qc.parse("!t buy milk !e later", TODAY)
        assert r.type == "task"

    def test_empty_text_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("", TODAY)
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("   ", TODAY)


class TestTasks:
    def test_spec_example_due_date_and_three_timeblocks(self):
        r = qc.parse(
            "!t Write bibliography 15/09/2026 2/08 14:00-16:00 5/09 14:00-16:00 8/09 14:00-16:00 #history",
            TODAY,
        )
        assert r.type == "task"
        assert r.title == "Write bibliography"
        assert r.due_date_iso == "2026-09-15"
        assert r.labels == ["history"]
        assert [(tb.date_iso, tb.start, tb.end) for tb in r.timeblocks] == [
            ("2026-08-02", "14:00", "16:00"),
            ("2026-09-05", "14:00", "16:00"),
            ("2026-09-08", "14:00", "16:00"),
        ]

    def test_due_date_only(self):
        r = qc.parse("!t Buy textbooks 15/09/2026", TODAY)
        assert r.due_date_iso == "2026-09-15"
        assert r.timeblocks == []
        assert r.title == "Buy textbooks"

    def test_timeblock_only_no_due_date(self):
        r = qc.parse("!t Read article 2/08 14:00-15:00", TODAY)
        assert r.due_date_iso is None
        assert len(r.timeblocks) == 1
        assert r.title == "Read article"

    def test_neither_date_nor_timeblock(self):
        r = qc.parse("!t Just a plain task", TODAY)
        assert r.due_date_iso is None
        assert r.timeblocks == []
        assert r.title == "Just a plain task"

    def test_no_title_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!t 15/09/2026", TODAY)

    def test_labels_only_no_dates(self):
        r = qc.parse("!t Clean the house #chores #home", TODAY)
        assert r.title == "Clean the house"
        assert r.labels == ["chores", "home"]

    def test_extra_bare_date_beyond_the_first_is_stripped_but_not_stored(self):
        # Undocumented edge case (the spec only ever shows one standalone
        # date) -- both dates disappear from the title, only the first
        # becomes due_date_iso.
        r = qc.parse("!t Weird task 15/09/2026 20/09/2026", TODAY)
        assert r.due_date_iso == "2026-09-15"
        assert r.title == "Weird task"


class TestEvents:
    def test_spec_example_timed_event(self):
        r = qc.parse("!e Medieval History lecture 15/09/2026 10:00-12:00 #university", TODAY)
        assert r.type == "event"
        assert r.title == "Medieval History lecture"
        assert r.start_iso == "2026-09-15T10:00:00"
        assert r.end_iso == "2026-09-15T12:00:00"
        assert r.all_day is False
        assert r.labels == ["university"]

    def test_date_only_is_all_day(self):
        r = qc.parse("!e Debate tournament 20/09/2026 #debate", TODAY)
        assert r.all_day is True
        assert r.start_iso == "2026-09-20T00:00:00"
        assert r.end_iso == "2026-09-20T23:59:00"
        assert r.labels == ["debate"]

    def test_no_date_at_all_is_allowed(self):
        r = qc.parse("!e Just a title, no date", TODAY)
        assert r.start_iso is None
        assert r.end_iso is None
        assert r.all_day is False

    def test_no_title_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!e 15/09/2026 10:00-12:00", TODAY)


class TestContacts:
    def test_spec_example_phone_only(self):
        r = qc.parse("!c Maria Popescu +40712345678", TODAY)
        assert r.type == "contact"
        assert r.title == "Maria Popescu"
        assert r.phone == "+40712345678"
        assert r.email is None

    def test_spec_example_phone_email_and_label(self):
        r = qc.parse("!c Maria Popescu +40712345678 maria.popescu@example.com #university", TODAY)
        assert r.title == "Maria Popescu"
        assert r.phone == "+40712345678"
        assert r.email == "maria.popescu@example.com"
        assert r.labels == ["university"]

    def test_dotted_hyphenated_email_form(self):
        r = qc.parse("!c Someone name.whatever-name@domain.xyz", TODAY)
        assert r.email == "name.whatever-name@domain.xyz"

    def test_no_name_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!c +40712345678", TODAY)


class TestNotes:
    def test_spec_example(self):
        r = qc.parse("!n Important points from the medieval history lecture #university", TODAY)
        assert r.type == "note"
        assert r.content == "Important points from the medieval history lecture"
        assert r.labels == ["university"]

    def test_dates_are_left_in_the_content_not_extracted(self):
        r = qc.parse("!n Reading list for 15/09/2026 #history", TODAY)
        assert r.type == "note"
        assert "15/09/2026" in r.content
        assert r.labels == ["history"]

    def test_empty_content_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!n #onlyalabel", TODAY)


class TestApproximateDateHandling:
    def test_short_date_before_today_rolls_to_next_year(self):
        # today = 2026-07-01; 2/06 has already passed this year.
        r = qc.parse("!t Old date task 2/06", TODAY)
        assert r.due_date_iso == "2027-06-02"

    def test_short_date_after_today_stays_this_year(self):
        r = qc.parse("!t Future date task 2/08", TODAY)
        assert r.due_date_iso == "2026-08-02"

    def test_invalid_calendar_date_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!t Bad date 32/13/2026", TODAY)

    def test_invalid_time_range_raises(self):
        with pytest.raises(qc.QuickCaptureError):
            qc.parse("!t Bad time 2/08 25:00-26:00", TODAY)
