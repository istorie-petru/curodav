"""Tests for modal-input-design Phase D: wrapping the remaining bounded
number inputs (habit Daily target, habit log-entry Value, schedule class
Credits, schedule settings Credits needed) in the `.stepper` component
already built in Phase A for the widget builder's Limit field
(_widget_builder_fields.html) and wired generically by static/stepper.js.

This phase is purely a markup wrap -- stepper.js already scans for any
`.stepper` on the page (not hardcoded to the widget builder) and already
reads the input's own `step` attribute (falling back to 1 only when
`step` is absent/"any"), so half-step fields like these four don't need
any JS change. These tests just confirm the wrap happened and that each
input's `name`/`min`/`step`/`value` were preserved exactly."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import habits as habits_router
from src.routers import schedule as schedule_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _assert_stepper_wraps(body: str, input_snippet: str):
    assert 'class="stepper"' in body
    assert 'class="stepper-btn stepper-dec"' in body
    assert 'class="stepper-btn stepper-inc"' in body
    assert input_snippet in body


class TestHabitDailyTargetStepper:
    def test_new_habit_form_wraps_target_per_day_in_a_stepper(self, conn):
        resp = habits_router.new_habit_form(_request(), conn=conn)
        body = resp.body.decode()
        _assert_stepper_wraps(
            body,
            '<input type="number" name="target_per_day" class="stepper-input" min="0" step="0.5" value="1">',
        )

    def test_edit_habit_form_preserves_existing_value(self, conn):
        now = _now()
        db.upsert_habit(
            conn,
            {"uid": "h1", "name": "Water", "target_per_day": 6, "created_at": now, "updated_at": now},
        )
        resp = habits_router.edit_habit_form("h1", _request(), conn=conn)
        body = resp.body.decode()
        _assert_stepper_wraps(
            body,
            '<input type="number" name="target_per_day" class="stepper-input" min="0" step="0.5" value="6.0">',
        )


class TestHabitLogValueStepper:
    def test_habit_detail_wraps_log_value_in_a_stepper(self, conn):
        now = _now()
        db.upsert_habit(
            conn,
            {"uid": "h1", "name": "Water", "target_per_day": 8, "created_at": now, "updated_at": now},
        )
        resp = habits_router.habit_detail("h1", _request(), conn=conn)
        body = resp.body.decode()
        _assert_stepper_wraps(
            body,
            '<input type="number" name="value" class="stepper-input" min="0" step="0.5" value="1">',
        )


class TestScheduleClassCreditsStepper:
    def test_new_class_form_wraps_credits_in_a_stepper(self, conn):
        resp = schedule_router.new_class_form(_request(), conn=conn)
        body = resp.body.decode()
        _assert_stepper_wraps(
            body,
            '<input type="number" name="credits" class="stepper-input" min="0" step="0.5" value="0">',
        )


class TestScheduleSettingsCreditsNeededStepper:
    # 2026-08-08: Settings (semester dates/credits/reminder/event label)
    # moved from its own /schedule/settings page back onto schedule_classes.html
    # as a <details> block (see routers/schedule.py's classes_view/
    # save_settings) -- these now render via classes_view, not the removed
    # settings_view.
    def test_settings_view_wraps_credits_needed_in_a_stepper(self, conn):
        resp = schedule_router.classes_view(_request(), conn=conn)
        body = resp.body.decode()
        _assert_stepper_wraps(
            body,
            '<input type="number" name="credits_needed" class="stepper-input" min="0" step="1" value="">',
        )

    def test_settings_view_preserves_existing_credits_needed_value(self, conn):
        db.save_schedule_settings(
            conn,
            {
                "semester_start": None,
                "semester_end": None,
                "credits_needed": 120,
                "reminder_minutes": 0,
            },
        )
        resp = schedule_router.classes_view(_request(), conn=conn)
        body = resp.body.decode()
        assert 'class="stepper"' in body
        assert 'name="credits_needed"' in body
        assert 'value="120' in body
