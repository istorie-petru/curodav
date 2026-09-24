"""Tests for modal-input-design Phase D: wrapping the remaining bounded
number inputs (habit Daily target, habit log-entry Value) in the
`.stepper` component already built in Phase A for the widget builder's
Limit field (_widget_builder_fields.html) and wired generically by
static/stepper.js.

This phase is purely a markup wrap -- stepper.js already scans for any
`.stepper` on the page (not hardcoded to the widget builder) and already
reads the input's own `step` attribute (falling back to 1 only when
`step` is absent/"any"), so half-step fields like these don't need
any JS change. These tests just confirm the wrap happened and that each
input's `name`/`min`/`step`/`value` were preserved exactly.

2026-08-15: `TestScheduleClassCreditsStepper`/
`TestScheduleSettingsCreditsNeededStepper` removed along with the whole
Schedule module -- see plans/STATE.md's removal entry."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db

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


