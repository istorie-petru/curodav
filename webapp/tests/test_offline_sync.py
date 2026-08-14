"""Tests for 1.8 slice 1 -- "Field-HLC shadow store + sync API skeleton"
(plans/open-priority.md § Offline-first editing & synchronization, §11
slice 1). Per that slice's own acceptance shape: POST synthetic operation
batches and assert the resulting field values/HLCs, and (for a
deliberately-conflicting batch) that the losing value is retained
somewhere inspectable rather than silently dropped -- no browser, no PWA
client, same router-function-call pytest convention as every other slice.

Covers `src/offline_sync.py` (the pure §6/§7a/§4 apply logic) directly,
and `src/routers/sync_api.py` (the §8 push/pull HTTP wrapper) the same
way test_search_api.py exercises routers/search.py -- call the async
route function with a synthetic Request, `asyncio.run` it."""

from __future__ import annotations

import asyncio
import json as _json

import pytest
from starlette.requests import Request

from src import db, offline_sync
from src.routers import sync_api


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _hlc(physical: int, logical: int = 0, device: str = "device-a") -> dict:
    return {"physical": physical, "logical": logical, "device_id": device}


def _field_set_op(op_id, entity_type, entity_uid, fields: dict, device_id="device-a") -> dict:
    return {
        "op_id": op_id,
        "entity_type": entity_type,
        "entity_uid": entity_uid,
        "op_type": "field_set",
        "device_id": device_id,
        "fields": fields,
    }


def _json_request(payload: dict) -> Request:
    req = Request({
        "type": "http", "method": "POST", "path": "/x",
        "headers": [(b"content-type", b"application/json")],
    })

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


class TestApplyFieldSet:
    def test_create_op_writes_row_and_field_versions(self, conn):
        op = _field_set_op(
            "op1", "task", "t1",
            {"title": {"value": "Write bibliography", "hlc": _hlc(1000)}},
        )
        result = offline_sync.apply_op(conn, op)
        assert result == {"op_id": "op1", "status": "applied", "fields": {"title": "applied"}}
        task = db.get_task(conn, "t1")
        assert task["title"] == "Write bibliography"
        assert db.get_field_hlc(conn, "task", "t1", "title") == (1000, 0, "device-a")

    def test_newer_write_wins(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "Old", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _field_set_op("op2", "task", "t1", {"title": {"value": "New", "hlc": _hlc(2000)}}))
        assert db.get_task(conn, "t1")["title"] == "New"

    def test_older_write_is_a_silent_no_op_for_that_field_only(self, conn):
        offline_sync.apply_op(conn, _field_set_op(
            "op1", "task", "t1",
            {"title": {"value": "New", "hlc": _hlc(2000)}, "description": {"value": "keep me", "hlc": _hlc(2000)}},
        ))
        result = offline_sync.apply_op(conn, _field_set_op(
            "op2", "task", "t1", {"title": {"value": "Stale", "hlc": _hlc(1000)}}
        ))
        assert result["status"] == "stale"
        assert result["fields"]["title"] == "stale"
        task = db.get_task(conn, "t1")
        # The losing value never overwrote the winner -- not silently applied.
        assert task["title"] == "New"
        # The other field this losing op never touched is untouched either way.
        assert task["description"] == "keep me"

    def test_partial_batch_some_fields_applied_some_stale(self, conn):
        offline_sync.apply_op(conn, _field_set_op(
            "op1", "task", "t1",
            {"title": {"value": "T", "hlc": _hlc(5000)}, "due_at": {"value": "2026-09-01", "hlc": _hlc(1000)}},
        ))
        result = offline_sync.apply_op(conn, _field_set_op(
            "op2", "task", "t1",
            {"title": {"value": "stale title", "hlc": _hlc(1000)}, "due_at": {"value": "2026-09-05", "hlc": _hlc(6000)}},
        ))
        assert result["status"] == "applied_partial"
        assert result["fields"] == {"title": "stale", "due_at": "applied"}
        task = db.get_task(conn, "t1")
        assert task["title"] == "T"
        assert task["due_at"] == "2026-09-05"

    def test_unknown_field_name_is_rejected_not_interpolated(self, conn):
        result = offline_sync.apply_op(conn, _field_set_op(
            "op1", "task", "t1", {"'; DROP TABLE tasks; --": {"value": "x", "hlc": _hlc(1000)}}
        ))
        assert result["fields"]["'; DROP TABLE tasks; --"] == "rejected_unknown_field"
        # Table survives -- the whitelist check happened before any SQL
        # ever referenced the untrusted field name.
        assert db.get_task(conn, "t1") is not None


class TestIdempotency:
    def test_duplicate_op_id_replays_cached_result_not_reapplied(self, conn):
        op = _field_set_op("op1", "task", "t1", {"title": {"value": "First", "hlc": _hlc(1000)}})
        first = offline_sync.apply_op(conn, op)
        # A retried push resends the same op_id, possibly with a mutated
        # payload if a buggy client re-serialized it -- the server must
        # still return the original cached result and must not re-apply.
        mutated = dict(op)
        mutated["fields"] = {"title": {"value": "Should never apply", "hlc": _hlc(9999)}}
        second = offline_sync.apply_op(conn, mutated)
        assert second == first
        assert db.get_task(conn, "t1")["title"] == "First"


class TestDeleteAndUndelete:
    def test_delete_sets_deleted_at_tombstone(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        result = offline_sync.apply_op(conn, {
            "op_id": "op2", "entity_type": "task", "entity_uid": "t1",
            "op_type": "delete", "device_id": "device-a", "hlc": _hlc(2000),
        })
        assert result["status"] == "applied"
        task = db.get_task(conn, "t1")
        assert task["deleted_at"] is not None

    def test_edit_newer_than_tombstone_undeletes(self, conn):
        offline_sync.apply_op(conn, {
            "op_id": "op1", "entity_type": "task", "entity_uid": "t1",
            "op_type": "delete", "device_id": "device-a", "hlc": _hlc(1000),
        })
        assert db.get_task(conn, "t1")["deleted_at"] is not None
        offline_sync.apply_op(conn, _field_set_op("op2", "task", "t1", {"title": {"value": "Revived", "hlc": _hlc(2000)}}))
        task = db.get_task(conn, "t1")
        assert task["title"] == "Revived"
        assert task["deleted_at"] is None

    def test_edit_older_than_tombstone_leaves_it_deleted(self, conn):
        offline_sync.apply_op(conn, {
            "op_id": "op1", "entity_type": "task", "entity_uid": "t1",
            "op_type": "delete", "device_id": "device-a", "hlc": _hlc(5000),
        })
        offline_sync.apply_op(conn, _field_set_op("op2", "task", "t1", {"title": {"value": "Too late", "hlc": _hlc(1000)}}))
        task = db.get_task(conn, "t1")
        assert task["deleted_at"] is not None


class TestLabelOpsAreCommutative:
    def test_add_applied_twice_converges(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active", "tags": []})
        op = {
            "op_id": "op1", "entity_type": "object_label", "entity_uid": "t1",
            "op_type": "label_add", "device_id": "device-a",
            "target": {"object_type": "task", "object_id": "t1", "label_name": "Work"},
        }
        offline_sync.apply_op(conn, {**op, "op_id": "op1"})
        offline_sync.apply_op(conn, {**op, "op_id": "op2"})
        assert db.get_task(conn, "t1")["tags"] == ["Work"]

    def test_remove_applied_twice_converges(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active", "tags": ["Work"]})
        op = {
            "op_id": "op1", "entity_type": "object_label", "entity_uid": "t1",
            "op_type": "label_remove", "device_id": "device-a",
            "target": {"object_type": "task", "object_id": "t1", "label_name": "Work"},
        }
        offline_sync.apply_op(conn, {**op, "op_id": "op1"})
        offline_sync.apply_op(conn, {**op, "op_id": "op2"})
        assert db.get_task(conn, "t1")["tags"] == []


class TestPullPureLogic:
    def test_pull_with_no_cursor_returns_everything(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        result = offline_sync.pull(conn, None)
        assert result["full_resync"] is False
        assert len(result["changes"]) == 1
        assert result["changes"][0] == {
            "entity_type": "task", "entity_uid": "t1", "field_name": "title",
            "value": "T", "hlc": (1000, 0, "device-a"),
        }
        assert result["cursor"] == (1000, 0, "device-a")

    def test_pull_since_cursor_only_returns_newer_changes(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        cursor = (1000, 0, "device-a")
        offline_sync.apply_op(conn, _field_set_op("op2", "task", "t1", {"description": {"value": "D", "hlc": _hlc(2000)}}))
        # now_ms pinned close to these synthetic HLC physical times -- real
        # wall-clock "now" would make a physical=1000 cursor look 50+ years
        # stale and trip the retention-horizon full-resync path this test
        # isn't exercising (see TestPullPureLogic's own staleness tests).
        result = offline_sync.pull(conn, cursor, now_ms=2000)
        assert [c["field_name"] for c in result["changes"]] == ["description"]

    def test_stale_cursor_past_retention_forces_full_resync(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        old_cursor = (1000, 0, "device-a")
        now_ms = 1000 + 200 * 24 * 60 * 60 * 1000  # 200 days later, > 90-day horizon
        result = offline_sync.pull(conn, old_cursor, now_ms=now_ms)
        assert result["full_resync"] is True
        assert result["changes"] == []

    def test_recent_cursor_within_retention_is_a_normal_incremental_pull(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        cursor = (1000, 0, "device-a")
        now_ms = 1000 + 5 * 24 * 60 * 60 * 1000  # 5 days later, well within horizon
        result = offline_sync.pull(conn, cursor, now_ms=now_ms)
        assert result["full_resync"] is False
        assert result["changes"] == []


class TestSyncApiRouter:
    def test_push_applies_ops_and_returns_per_op_results(self, conn):
        resp = asyncio.run(sync_api.push(_json_request({
            "device_id": "device-a",
            "ops": [_field_set_op("op1", "task", "t1", {"title": {"value": "Via router", "hlc": _hlc(1000)}})],
        }), conn=conn))
        assert resp.status_code == 200
        body = _json.loads(resp.body.decode())
        assert body["results"] == [{"op_id": "op1", "status": "applied", "fields": {"title": "applied"}}]
        assert db.get_task(conn, "t1")["title"] == "Via router"

    def test_push_updates_the_device_cursor(self, conn):
        asyncio.run(sync_api.push(_json_request({
            "device_id": "device-a",
            "ops": [_field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1234)}})],
        }), conn=conn))
        device = db.get_sync_device(conn, "device-a")
        assert device["last_pushed_hlc"] == (1234, 0, "device-a")

    def test_pull_returns_changes_and_a_cursor(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        resp = asyncio.run(sync_api.pull(_json_request({"device_id": "device-b", "cursor": None}), conn=conn))
        body = _json.loads(resp.body.decode())
        assert body["full_resync"] is False
        assert body["changes"][0]["value"] == "T"
        assert body["cursor"] == {"physical": 1000, "logical": 0, "device_id": "device-a"}
        device = db.get_sync_device(conn, "device-b")
        assert device["last_pulled_hlc"] == (1000, 0, "device-a")

    def test_push_then_pull_round_trip_between_two_devices(self, conn):
        asyncio.run(sync_api.push(_json_request({
            "device_id": "device-a",
            "ops": [_field_set_op("op1", "task", "t1", {"title": {"value": "From A", "hlc": _hlc(1000)}})],
        }), conn=conn))
        resp = asyncio.run(sync_api.pull(_json_request({"device_id": "device-b", "cursor": None}), conn=conn))
        body = _json.loads(resp.body.decode())
        assert any(c["entity_uid"] == "t1" and c["value"] == "From A" for c in body["changes"])
