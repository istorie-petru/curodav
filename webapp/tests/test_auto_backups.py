"""Automatic backups: made twice a day and at start, kept a week, compared with now, restored whole or one thing at a time."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

import pytest

from src import api_history, auto_backups, clock, db


@pytest.fixture()
def paths(tmp_path):
    db_path, backups = tmp_path / "cache.sqlite", tmp_path / "backups"
    with db.connect(db_path) as conn:
        _note(conn, "n1", "Kant")
    yield db_path, backups
    clock.set_override(None)


def _at(text: str) -> None:
    clock.set_override(datetime.fromisoformat(text).astimezone().astimezone(timezone.utc))


def _note(conn, uid, title, text="First"):
    db.upsert_notebook_document(conn, {"uid": uid, "title": title, "content_json": json.dumps({"blocks": [
        {"id": "p1", "type": "paragraph", "data": {"text": text}}]}), "document_type": "full", "note_type": "",
        "created_at": "2026-10-01T10:00:00+00:00", "updated_at": clock.now().isoformat()})


def test_a_backup_is_a_complete_compressed_copy(paths):
    db_path, backups = paths
    _at("2026-11-02T10:05")
    path = auto_backups.make(db_path, backups, "morning")
    assert path.name == "curodav-20261102-1005-morning.sqlite.gz"
    with gzip.open(path) as f:
        assert f.read(16) == b"SQLite format 3\x00"


def test_daily_backups_are_due_after_their_time_and_only_once(paths):
    db_path, backups = paths
    _at("2026-11-02T09:59")
    assert auto_backups.due(backups) == []
    _at("2026-11-02T18:30")
    assert auto_backups.due(backups) == ["morning", "evening"]
    auto_backups.run_due(db_path, backups)
    assert auto_backups.due(backups) == []


def test_backups_older_than_a_week_and_extra_start_backups_go(paths):
    db_path, backups = paths
    _at("2026-10-20T10:00")
    auto_backups.make(db_path, backups, "morning")
    for minute in range(7):
        _at(f"2026-11-02T08:0{minute}")
        auto_backups.make(db_path, backups, "start")
    kinds = [e["kind"] for e in auto_backups.list_backups(backups)]
    assert kinds.count("start") == auto_backups.KEEP_START and "morning" not in kinds


def test_the_timeline_shows_the_last_seven_days(paths):
    db_path, backups = paths
    _at("2026-11-02T10:00")
    auto_backups.make(db_path, backups, "morning")
    days = auto_backups.timeline(backups)
    assert len(days) == 7 and days[0]["day"] == "2026-11-02" and days[0]["backups"][0]["kind"] == "morning"


def test_the_comparison_lists_notes_changed_since(paths):
    db_path, backups = paths
    _at("2026-11-02T10:00")
    name = auto_backups.make(db_path, backups, "morning").name
    _at("2026-11-02T11:00")
    with db.connect(db_path) as conn:
        _note(conn, "n1", "Kant renamed")
        _note(conn, "n2", "New one")
        diff = auto_backups.compare(conn, backups, name)
    assert [n["title"] for n in diff["notes"]] == ["Kant"]
    notes = next(a for a in diff["areas"] if a["area"] == "Notes")
    assert (notes["then"], notes["now"]) == (1, 2)


def test_one_note_is_restored_and_that_can_be_undone(paths):
    db_path, backups = paths
    _at("2026-11-02T10:00")
    name = auto_backups.make(db_path, backups, "morning").name
    with db.connect(db_path) as conn:
        _note(conn, "n1", "Kant renamed", "Second")
        _note(conn, "n2", "Kept")
        change = auto_backups.restore_one(conn, backups, name, "note", "n1")
        assert db.get_notebook_document(conn, "n1")["title"] == "Kant"
        assert db.get_notebook_document(conn, "n2") is not None
        api_history.undo(conn, change)
        assert db.get_notebook_document(conn, "n1")["title"] == "Kant renamed"


def test_restoring_everything_keeps_the_state_before(paths):
    db_path, backups = paths
    _at("2026-11-02T10:00")
    name = auto_backups.make(db_path, backups, "morning").name
    with db.connect(db_path) as conn:
        _note(conn, "n2", "Written after")
    _at("2026-11-02T12:00")
    safety = auto_backups.restore_all(db_path, backups, name)
    with db.connect(db_path) as conn:
        assert db.get_notebook_document(conn, "n2") is None
    assert safety.name.endswith("-restore.sqlite.gz")


def test_a_name_that_is_not_a_backup_is_refused(paths):
    _db_path, backups = paths
    with pytest.raises(FileNotFoundError):
        with auto_backups.opened(backups, "../cache.sqlite"):
            pass
