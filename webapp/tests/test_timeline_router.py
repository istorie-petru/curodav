"""Tests for routers/timeline.py: context-building (_build_context wiring
timeline_layout.py's output into template-ready pixel geometry), and the
endpoints the drag interactions (static/timeline.js) call -- reschedule,
manual lane, and click-create.

Phase 1 (label-space rework, 2026-08-06) dropped `task_lists` (see
db.py's Phase 1 comments) -- Timeline's gutter is now organized by label:
assign_swimlanes groups tasks by their first tag, so each distinct label
gets its own swimlane block whose header row shows the label's name (and
untagged tasks fall into a trailing "(No label)" block). The old
multi-list-swimlane and custom-row-name tests are gone with `task_lists`,
and every remaining call drops the now-removed `bridge=` kwarg (routers/
timeline.py's endpoints write straight to db.py now)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src import timeline_layout as tl
from src.routers import timeline as timeline_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, start_at=None, due_at="2026-08-10", status="active", tags=None):
    db.upsert_task(conn, {
        "uid": uid,
        "title": uid, "description": "", "status": status, "start_at": start_at, "due_at": due_at,
        "tags": [], "created_at": _now(),
    })
    if tags:
        db.set_object_labels(conn, "task", uid, tags)


class TestBuildContext:
    def test_empty_still_renders(self, conn):
        ctx = timeline_router._build_context(conn)
        assert ctx["bars"] == []
        assert ctx["total_days"] >= 14

    def test_tasks_without_due_date_excluded(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "title": "No due date",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        ctx = timeline_router._build_context(conn)
        assert ctx["bars"] == []

    def test_archived_tasks_excluded(self, conn):
        _seed_task(conn, "t1", status="archived")
        ctx = timeline_router._build_context(conn)
        assert ctx["bars"] == []

    def test_done_tasks_included(self, conn):
        """Unlike the Table view (Phase 9), the timeline doesn't hide
        completed work -- a Gantt chart showing a project's history is
        more useful with what's already done still visible."""
        _seed_task(conn, "t1", status="done")
        ctx = timeline_router._build_context(conn)
        assert len(ctx["bars"]) == 1

    def test_bar_carries_own_local_idx_and_group_lanes(self, conn):
        _seed_task(conn, "t1")
        ctx = timeline_router._build_context(conn)
        bar = ctx["bars"][0]
        assert bar["local_idx"] == 0
        assert bar["group_lanes"] >= 1

    def test_untagged_tasks_pack_into_the_no_label_block(self, conn):
        _seed_task(conn, "t1")
        _seed_task(conn, "t2")
        ctx = timeline_router._build_context(conn)
        rows_by_block = {}
        for row in ctx["rows"]:
            rows_by_block.setdefault(row["label_key"], []).append(row["global_row"])
        # Untagged tasks fall into the "(No label)" block (NO_LABEL_KEY).
        assert set(rows_by_block.keys()) == {tl.NO_LABEL_KEY}
        assert len(ctx["bars"]) == 2

    def test_tasks_group_by_label_blocks_with_a_header_row_each(self, conn):
        _seed_task(conn, "t1", tags=["University"])
        _seed_task(conn, "t2", tags=["University"])
        _seed_task(conn, "t3", tags=["Work"])
        # "University" has an assigned color+icon; "Work" uses the defaults.
        db.upsert_label_config(conn, {"name": "University", "color": "green", "icon": "book"})
        ctx = timeline_router._build_context(conn)
        rows_by_label = {}
        for row in ctx["rows"]:
            rows_by_label.setdefault(row["label_key"], []).append(row)
        assert set(rows_by_label.keys()) == {"university", "work"}
        # each label block gets exactly one is-header gutter row, and that
        # header is generated from the label (its name, row 0 of the block)
        for rows in rows_by_label.values():
            headers = [r for r in rows if r["is_header"]]
            assert len(headers) == 1
            assert headers[0]["label"] == headers[0]["group_label"]
            assert headers[0]["label"] in ("University", "Work")
        # bars carry their block's label key and stay in their own block
        assert len(ctx["bars"]) == 3
        assert {b["label_key"] for b in ctx["bars"]} == {"university", "work"}
        for b in ctx["bars"]:
            assert 0 <= b["local_idx"] < b["group_lanes"]
        # bars + gutter header both use the label's *assigned* color, not
        # a palette cycle -- "University" is green+book, "Work" falls back
        # to the default blue + generic tag icon. Since the swatch set went
        # pastel then converged to one unified medium-tone pack (2026-08-09,
        # see routers/labels.py's CAL_COLOR_HEX/CAL_COLOR_FOREGROUND), the
        # gutter rows carry each swatch's contrast-picked foreground (what
        # the header icon paints in) while the bars paint the swatch
        # background itself -- so a row and its block's bars are
        # deliberately different hexes of the same hue.
        uni_rows = rows_by_label["university"]
        work_rows = rows_by_label["work"]
        assert uni_rows[0]["color"] == "#ffffff"  # cal-green fg (gutter icon)
        assert uni_rows[0]["icon"] == "book"
        assert work_rows[0]["color"] == "#ffffff"  # cal-blue fg (default)
        assert work_rows[0]["icon"] == "tag"
        # Bars/gutter icons render through CSS vars named after the
        # color (one unified pack, both themes).
        assert uni_rows[0]["color_name"] == "green"
        assert work_rows[0]["color_name"] == "blue"
        for b in ctx["bars"]:
            block_rows = rows_by_label[b["label_key"]]
            assert b["color"] != block_rows[0]["color"]
            assert b["color_name"] == block_rows[0]["color_name"]

    def test_no_label_block_uses_neutral_gray(self, conn):
        _seed_task(conn, "t1")
        ctx = timeline_router._build_context(conn)
        block = [r for r in ctx["rows"] if r["label_key"] == tl.NO_LABEL_KEY]
        assert block and block[0]["is_header"]
        # Gutter rows carry the gray swatch's contrast-picked foreground;
        # the bars paint the gray background (2026-08-09 unified pack).
        assert block[0]["color"] == "#ffffff"
        assert ctx["bars"][0]["color"] == "#70767d"
        # Both render via the gray CSS vars.
        assert block[0]["color_name"] == "gray"
        assert ctx["bars"][0]["color_name"] == "gray"


class TestTimelineViewRoute:
    def test_renders(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/tasks/timeline", "headers": []})
        resp = timeline_router.timeline_view(req, conn=conn)
        assert resp.status_code == 200


class TestReschedule:
    def test_move_updates_both_dates(self, conn):
        import asyncio
        from starlette.requests import Request

        _seed_task(conn, "t1", start_at="2026-08-01", due_at="2026-08-03")

        async def _call():
            req = Request({"type": "http", "method": "POST", "path": "/x", "headers": [(b"content-type", b"application/json")]})

            async def receive():
                import json as _json
                body = _json.dumps({"start_at": "2026-08-05", "due_at": "2026-08-07"}).encode()
                return {"type": "http.request", "body": body, "more_body": False}

            req._receive = receive
            return await timeline_router.timeline_reschedule("t1", req, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 200
        task = db.get_task(conn, "t1")
        assert task["start_at"] == "2026-08-05"
        assert task["due_at"] == "2026-08-07"

    def test_missing_task_returns_404(self, conn):
        import asyncio
        from starlette.requests import Request

        async def _call():
            req = Request({"type": "http", "method": "POST", "path": "/x", "headers": [(b"content-type", b"application/json")]})

            async def receive():
                import json as _json
                body = _json.dumps({"start_at": "2026-08-05", "due_at": "2026-08-07"}).encode()
                return {"type": "http.request", "body": body, "more_body": False}

            req._receive = receive
            return await timeline_router.timeline_reschedule("does-not-exist", req, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 404


def _json_request(payload: dict):
    from starlette.requests import Request
    import json as _json

    req = Request({"type": "http", "method": "POST", "path": "/x", "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


class TestSetLane:
    def test_sets_and_clears(self, conn):
        import asyncio

        _seed_task(conn, "t1")
        asyncio.run(timeline_router.timeline_set_lane("t1", _json_request({"lane": 2}), conn=conn))
        assert db.get_task(conn, "t1")["timeline_lane"] == 2
        asyncio.run(timeline_router.timeline_set_lane("t1", _json_request({"lane": None}), conn=conn))
        assert db.get_task(conn, "t1")["timeline_lane"] is None


class TestCreate:
    def test_creates_task_with_lane(self, conn):
        import asyncio

        resp = asyncio.run(
            timeline_router.timeline_create(
                _json_request({"start_at": "2026-08-10", "due_at": "2026-08-12", "local_idx": 2}),
                conn=conn,
            )
        )
        assert resp.status_code == 200
        tasks = db.list_tasks(conn)
        assert len(tasks) == 1
        assert tasks[0]["start_at"] == "2026-08-10"
        assert tasks[0]["due_at"] == "2026-08-12"
        assert tasks[0]["timeline_lane"] == 2
        assert tasks[0]["title"] == "New task"

    def test_creates_task_with_label(self, conn):
        """Dragging in a labeled swimlane block carries that label's name
        through and attaches it, so the new task lands back in the same
        block on the next layout."""
        import asyncio

        resp = asyncio.run(
            timeline_router.timeline_create(
                _json_request({"start_at": "2026-08-10", "due_at": "2026-08-12", "label": "University"}),
                conn=conn,
            )
        )
        assert resp.status_code == 200
        assert db.list_tasks(conn)[0]["tags"] == ["University"]
