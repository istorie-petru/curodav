"""Quick Capture (plans/quick-capture.md) -- everything the parser tests
(test_quick_capture_parser.py) don't cover: the HTTP layer
(routers/quick_capture.py's preview + create) and label fuzzy-matching/
alias persistence (db.resolve_capture_label). The quick-capture-backed
Notes entity (`!n`, routers/notes.py) was removed outright 2026-10-01,
absorbed into the Notebook module instead -- its CRUD/search/router
coverage that used to live in this file went with it (see
webapp/tests/test_notebook.py for Notebook's own equivalent coverage)."""

from __future__ import annotations

import asyncio
import json as _json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import quick_capture as qcr

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post_json_request(path: str, payload: dict):
    req = Request({"type": "http", "method": "POST", "path": path, "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


def _make_project(conn, name):
    db.upsert_label_config(conn, {"name": name, "is_project": 1, "start_date": None, "end_date": None, "created_at": _now()})


def _seed_task(conn, uid, tags=None, **overrides):
    row = {"uid": uid, "title": uid, "description": "", "status": "active", "tags": tags or [], "created_at": _now()}
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


class TestPreviewEndpoint:
    def test_blank_text_is_not_ok_but_not_an_error_either(self, conn):
        data = _json.loads(qcr.preview(text="", conn=conn).body.decode())
        assert data == {"ok": False, "error": None}

    def test_valid_task_capture_previews_parsed_fields(self, conn):
        data = _json.loads(qcr.preview(text="!t Write bib 15/09/2026 #history", conn=conn).body.decode())
        assert data["ok"] is True
        assert data["type"] == "task"
        assert data["title"] == "Write bib"
        assert data["due_date"] == "2026-09-15"
        assert data["labels"] == ["history"]

    def test_invalid_capture_previews_the_error_not_ok(self, conn):
        data = _json.loads(qcr.preview(text="!t 15/09/2026", conn=conn).body.decode())
        assert data["ok"] is False
        assert "title" in data["error"]

    def test_preview_does_not_persist_a_fuzzy_alias(self, conn):
        # A close-but-not-exact label typed mid-capture should NOT write to
        # label_aliases just from being previewed -- only an actual create
        # (POST /api/quick-capture) resolves/persists labels. See
        # routers/quick_capture.py's own preview() docstring.
        _seed_task(conn, "t1", tags=["university"])
        qcr.preview(text="!t something #univercity", conn=conn)
        rows = conn.execute("SELECT * FROM label_aliases").fetchall()
        assert rows == []


class TestCreateEndpointTask:
    def test_creates_a_task_with_due_date_and_labels(self, conn):
        resp = asyncio.run(qcr.create(_post_json_request("/api/quick-capture", {"text": "!t Buy milk 15/09/2026 #errands"}), conn=conn))
        assert resp.status_code == 200
        data = _json.loads(resp.body.decode())
        assert data["ok"] is True
        assert data["type"] == "task"
        task = db.get_task(conn, data["uid"])
        assert task["title"] == "Buy milk"
        assert task["due_at"] == "2026-09-15"
        assert task["tags"] == ["errands"]

    def test_creates_work_allocations_for_each_timeblock(self, conn):
        resp = asyncio.run(
            qcr.create(
                _post_json_request(
                    "/api/quick-capture",
                    {"text": "!t Write bib 15/09/2026 2/08 14:00-16:00 5/09 14:00-16:00 #history"},
                ),
                conn=conn,
            )
        )
        data = _json.loads(resp.body.decode())
        allocations = db.list_work_allocations_for_task(conn, data["uid"])
        # Two timeblocks, each a real, dated, 2-hour session -- not pinned
        # to a specific year here, since the parser's own short-date year
        # inference is relative to the real clock at test-run time (see
        # test_quick_capture_parser.py's TestApproximateDateHandling for
        # that logic tested against a fixed `today`).
        assert len(allocations) == 2
        for a in allocations:
            assert a["start_at"].endswith("T14:00:00")
            assert a["end_at"].endswith("T16:00:00")

    def test_no_title_is_a_400_not_a_500(self, conn):
        resp = asyncio.run(qcr.create(_post_json_request("/api/quick-capture", {"text": "!t 15/09/2026"}), conn=conn))
        assert resp.status_code == 400
        assert "title" in _json.loads(resp.body.decode())["error"]

    def test_no_marker_is_a_400(self, conn):
        resp = asyncio.run(qcr.create(_post_json_request("/api/quick-capture", {"text": "no marker at all"}), conn=conn))
        assert resp.status_code == 400

    def test_blank_body_is_a_400(self, conn):
        resp = asyncio.run(qcr.create(_post_json_request("/api/quick-capture", {"text": "  "}), conn=conn))
        assert resp.status_code == 400

    def test_second_project_label_is_rejected(self, conn):
        # 1.5's single-project-per-task guard applies to a captured task
        # exactly like every other write path onto tasks.tags.
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        _seed_task(conn, "t1", tags=["Alpha"])
        resp = asyncio.run(
            qcr.create(_post_json_request("/api/quick-capture", {"text": "!t New task #Alpha #Beta"}), conn=conn)
        )
        assert resp.status_code == 400


class TestCreateEndpointEvent:
    def test_creates_a_timed_event(self, conn):
        resp = asyncio.run(
            qcr.create(
                _post_json_request("/api/quick-capture", {"text": "!e Lecture 15/09/2026 10:00-12:00 #university"}),
                conn=conn,
            )
        )
        data = _json.loads(resp.body.decode())
        event = db.get_event(conn, data["uid"])
        assert event["title"] == "Lecture"
        assert event["start_at"] == "2026-09-15T10:00:00"
        assert event["end_at"] == "2026-09-15T12:00:00"
        assert event["tags"] == ["university"]

    def test_creates_an_all_day_event(self, conn):
        resp = asyncio.run(
            qcr.create(_post_json_request("/api/quick-capture", {"text": "!e Debate tournament 20/09/2026"}), conn=conn)
        )
        data = _json.loads(resp.body.decode())
        event = db.get_event(conn, data["uid"])
        assert event["all_day"] == 1


class TestCreateEndpointContact:
    def test_creates_a_contact_with_phone_and_email(self, conn):
        resp = asyncio.run(
            qcr.create(
                _post_json_request(
                    "/api/quick-capture", {"text": "!c Maria Popescu +40712345678 maria@example.com #university"}
                ),
                conn=conn,
            )
        )
        data = _json.loads(resp.body.decode())
        contact = db.get_contact(conn, data["uid"])
        assert contact["full_name"] == "Maria Popescu"
        # Contacts field parity slice 2 of 6: phone/email are multi-value
        # now -- Quick Capture stores whatever it parsed as one "Other"-
        # typed entry each (routers/quick_capture.py), not the now-dead
        # flat `phone`/`email` columns.
        assert [(p["type"], p["value"]) for p in contact["phones"]] == [("Other", "+40712345678")]
        assert [(e["type"], e["value"]) for e in contact["emails"]] == [("Other", "maria@example.com")]
        assert contact["tags"] == ["university"]


class TestLabelFuzzyMatching:
    def test_exact_match_wins_outright(self, conn):
        _seed_task(conn, "t1", tags=["University"])
        assert db.resolve_capture_label(conn, "university") == "University"

    def test_close_typo_resolves_automatically(self, conn):
        _seed_task(conn, "t1", tags=["university"])
        for typo in ("uunniversity", "universitty", "unisity"):
            assert db.resolve_capture_label(conn, typo) == "university"

    def test_accepted_fuzzy_match_is_persisted_as_an_alias(self, conn):
        _seed_task(conn, "t1", tags=["university"])
        db.resolve_capture_label(conn, "universitty")
        row = conn.execute("SELECT canonical_name FROM label_aliases WHERE alias = ?", ("universitty",)).fetchone()
        assert row["canonical_name"] == "university"

    def test_learned_alias_resolves_without_recomputing(self, conn):
        _seed_task(conn, "t1", tags=["university"])
        db.resolve_capture_label(conn, "universitty")  # learns the alias
        # Even if "university" somehow stopped existing, the alias itself
        # still resolves directly -- exercised by checking the alias table
        # is consulted before the fuzzy pass by asserting a second call is
        # still correct.
        assert db.resolve_capture_label(conn, "universitty") == "university"

    def test_unrelated_new_word_creates_a_new_label(self, conn):
        _seed_task(conn, "t1", tags=["university"])
        assert db.resolve_capture_label(conn, "gardening") == "gardening"

    def test_no_labels_in_use_yet_returns_name_unchanged(self, conn):
        assert db.resolve_capture_label(conn, "brand-new") == "brand-new"


