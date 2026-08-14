"""Tests for 1.8 slices 1-2 -- "Field-HLC shadow store + sync API
skeleton" and "Sync conflicts surface" (plans/open-priority.md §
Offline-first editing & synchronization, §11). Per slice 1's own
acceptance shape: POST synthetic operation batches and assert the
resulting field values/HLCs, and (for a deliberately-conflicting batch)
that the losing value is retained somewhere inspectable rather than
silently dropped -- no browser, no PWA client, same router-function-call
pytest convention as every other slice. Slice 2 adds the two §7b/c
conflict-*surfacing* exceptions plus the Settings > Sync conflicts
restore/dismiss actions.

Covers `src/offline_sync.py` (the pure §6/§7a/§4/§7b/§7c apply logic)
directly, `src/routers/sync_api.py` (the §8 push/pull HTTP wrapper), and
`src/routers/settings.py`'s sync-conflicts routes -- the latter two the
same way test_search_api.py exercises routers/search.py: call the route
function directly (`asyncio.run` for the async ones) with a synthetic
Request."""

from __future__ import annotations

import asyncio
import json as _json

import pytest
from starlette.requests import Request

from src import db, offline_sync
from src.routers import settings as settings_router
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


def _delete_op(op_id, entity_type, entity_uid, physical, device_id="device-a") -> dict:
    return {
        "op_id": op_id,
        "entity_type": entity_type,
        "entity_uid": entity_uid,
        "op_type": "delete",
        "device_id": device_id,
        "hlc": _hlc(physical, device=device_id),
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


_DAY_MS = 24 * 60 * 60 * 1000


class TestPurgeExpired:
    """1.8 slice 7 -- "Tombstone GC." `purge_expired`'s two halves: old
    tombstoned entities (+ their field_versions rows) and old
    sync_applied_ops ledger entries. `now_ms` is pinned throughout, same
    convention TestPullPureLogic's own staleness tests already use, so
    "how old" is exact rather than dependent on when the test happens to
    run."""

    def test_old_tombstone_is_physically_purged(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        now_ms = 2000 + 200 * _DAY_MS  # 200 days after the delete, > 90-day horizon
        result = offline_sync.purge_expired(conn, now_ms=now_ms)
        assert result["purged_entities"]["task"] == 1
        assert db.get_task(conn, "t1") is None
        assert db.get_field_hlc(conn, "task", "t1", "title") is None
        assert db.get_field_hlc(conn, "task", "t1", "deleted_at") is None

    def test_tombstone_within_retention_is_left_alone(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        now_ms = 2000 + 5 * _DAY_MS  # only 5 days later, well within the 90-day default
        result = offline_sync.purge_expired(conn, now_ms=now_ms)
        assert result["purged_entities"]["task"] == 0
        assert db.get_task(conn, "t1") is not None

    def test_un_deleted_row_is_never_purged_even_though_the_original_tombstone_is_old(self, conn):
        # §4: an edit newer than the tombstone un-deletes the row -- that
        # newer edit's own HLC becomes field_versions' new deleted_at HLC
        # (offline_sync._apply_field_write's "cleared_by_newer_edit"
        # branch), so this case naturally falls outside the "old
        # tombstone" query with no special-case purge logic needed.
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        offline_sync.apply_op(conn, _field_set_op("op3", "task", "t1", {"title": {"value": "Restored", "hlc": _hlc(3000)}}))
        now_ms = 3000 + 200 * _DAY_MS
        result = offline_sync.purge_expired(conn, now_ms=now_ms)
        assert result["purged_entities"]["task"] == 0
        task = db.get_task(conn, "t1")
        assert task is not None and task["title"] == "Restored" and task["deleted_at"] is None

    def test_purge_removes_related_rows_via_the_normal_delete_path(self, conn):
        # Reuses db.delete_task (not a raw DELETE), so object_labels/
        # event_task_relations cleanup happens the same way any other
        # hard-delete in this app already gets it.
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        db.set_object_labels(conn, "task", "t1", ["Work"])
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        now_ms = 2000 + 200 * _DAY_MS
        offline_sync.purge_expired(conn, now_ms=now_ms)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM object_labels WHERE object_type = 'task' AND object_id = 't1'"
        ).fetchone()[0]
        assert remaining == 0

    def test_old_sync_applied_ops_are_purged_recent_ones_are_not(self, conn):
        old = _field_set_op("old-op", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}})
        offline_sync.apply_op(conn, old)
        # Backdate the ledger row directly -- record_sync_applied_op always
        # stamps real wall-clock "now," so this simulates "applied a long
        # time ago" the same way a real installation would accumulate one.
        conn.execute(
            "UPDATE sync_applied_ops SET applied_at = ? WHERE op_id = ?",
            ("2020-01-01T00:00:00+00:00", "old-op"),
        )
        conn.commit()
        recent = _field_set_op("recent-op", "task", "t2", {"title": {"value": "T2", "hlc": _hlc(1000)}})
        offline_sync.apply_op(conn, recent)
        result = offline_sync.purge_expired(conn)  # real "now" -- old-op is years stale, recent-op is seconds old
        assert result["purged_applied_ops"] == 1
        assert db.get_sync_applied_op(conn, "old-op") is None
        assert db.get_sync_applied_op(conn, "recent-op") is not None

    def test_retention_days_zero_would_purge_everything_strictly_past_now(self, conn):
        # purge_expired itself takes retention_days at face value -- the
        # "0 disables GC" policy decision lives in data_health.run_sync_gc
        # (Settings/CLI/lazy-trigger layer), not here, so this only checks
        # the math: a 0-day horizon means the cutoff equals "now," and
        # anything strictly older than that instant is eligible.
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        result = offline_sync.purge_expired(conn, retention_days=0, now_ms=2001)
        assert result["purged_entities"]["task"] == 1


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

    def test_pull_lazily_runs_gc_at_the_configured_retention(self, conn):
        # 1.8 slice 7 -- pull is the sync engine's own heartbeat (routers/
        # sync_api.py's own docstring note); a genuinely ancient tombstone
        # (physical ~ 1970, guaranteed >> 90 days before whenever this test
        # actually runs) should be gone by the time a pull request returns,
        # with no separate GC call from the test itself.
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        assert db.get_task(conn, "t1") is not None  # sanity: still there before the pull
        asyncio.run(sync_api.pull(_json_request({"device_id": "device-b", "cursor": None}), conn=conn))
        assert db.get_task(conn, "t1") is None

    def test_pull_does_not_run_gc_when_retention_is_disabled(self, conn):
        from src import data_health

        data_health.set_sync_gc_retention_days(conn, 0)
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}}))
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        asyncio.run(sync_api.pull(_json_request({"device_id": "device-b", "cursor": None}), conn=conn))
        assert db.get_task(conn, "t1") is not None


def _seed_event(conn, uid, **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": "active", "all_day": False,
        "start_at": "2026-08-10T09:00:00", "end_at": "2026-08-10T10:00:00", "tags": [],
    }
    row.update(overrides)
    db.upsert_event(conn, row)


class TestConcurrentEventTimeConflicts:
    """§7b -- a genuinely concurrent edit to the same event's start_at/
    end_at (different device_ids on both sides) is surfaced as a
    sync_conflicts row instead of silently discarded, whichever order the
    two writes happen to apply in."""

    def test_higher_hlc_wins_and_the_loser_is_recorded_not_dropped(self, conn):
        _seed_event(conn, "e1")
        offline_sync.apply_op(conn, {
            "op_id": "op1", "entity_type": "event", "entity_uid": "e1", "op_type": "field_set",
            "device_id": "device-b",
            "fields": {"start_at": {"value": "2026-08-10T11:00:00", "hlc": _hlc(1000, device="device-b")}},
        })
        result = offline_sync.apply_op(conn, {
            "op_id": "op2", "entity_type": "event", "entity_uid": "e1", "op_type": "field_set",
            "device_id": "device-a",
            "fields": {"start_at": {"value": "2026-08-10T12:00:00", "hlc": _hlc(2000, device="device-a")}},
        })
        assert result["status"] == "applied"
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-10T12:00:00"
        conflicts = db.list_sync_conflicts(conn)
        assert len(conflicts) == 1
        assert conflicts[0]["losing_value"] == "2026-08-10T11:00:00"
        assert conflicts[0]["field_name"] == "start_at"

    def test_stale_side_arriving_second_is_also_recorded(self, conn):
        _seed_event(conn, "e1")
        offline_sync.apply_op(conn, {
            "op_id": "op1", "entity_type": "event", "entity_uid": "e1", "op_type": "field_set",
            "device_id": "device-a",
            "fields": {"start_at": {"value": "2026-08-10T12:00:00", "hlc": _hlc(2000, device="device-a")}},
        })
        result = offline_sync.apply_op(conn, {
            "op_id": "op2", "entity_type": "event", "entity_uid": "e1", "op_type": "field_set",
            "device_id": "device-b",
            "fields": {"start_at": {"value": "2026-08-10T11:00:00", "hlc": _hlc(1000, device="device-b")}},
        })
        assert result["status"] == "conflict"
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-10T12:00:00"
        assert len(db.list_sync_conflicts(conn)) == 1

    def test_same_device_sequential_edit_is_never_a_conflict(self, conn):
        _seed_event(conn, "e1")
        offline_sync.apply_op(conn, {
            "op_id": "op1", "entity_type": "event", "entity_uid": "e1", "op_type": "field_set",
            "device_id": "device-a",
            "fields": {"start_at": {"value": "2026-08-10T12:00:00", "hlc": _hlc(2000, device="device-a")}},
        })
        # A later, older op_id from the SAME device (a replay/reorder
        # artifact, not two devices editing without seeing each other).
        result = offline_sync.apply_op(conn, {
            "op_id": "op2", "entity_type": "event", "entity_uid": "e1", "op_type": "field_set",
            "device_id": "device-a",
            "fields": {"start_at": {"value": "2026-08-10T11:00:00", "hlc": _hlc(1000, device="device-a")}},
        })
        assert result["status"] == "stale"
        assert db.list_sync_conflicts(conn) == []

    def test_non_surfaced_fields_still_get_plain_silent_lww(self, conn):
        # title isn't a §7b field -- an ordinary cross-device stale write
        # is still a plain no-op, no conflict recorded.
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "New", "hlc": _hlc(2000, device="device-a")}}))
        offline_sync.apply_op(conn, _field_set_op("op2", "task", "t1", {"title": {"value": "Old", "hlc": _hlc(1000, device="device-b")}}))
        assert db.list_sync_conflicts(conn) == []


class TestProjectLabelInvariantAfterBatch:
    """§7c -- two devices each attach a different project label to the
    same task within one synced batch."""

    def _seed_projects(self, conn, *names):
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active", "tags": []})
        for name in names:
            conn.execute("INSERT INTO label_config (name, is_project) VALUES (?, 1)", (name,))
        conn.commit()

    def _label_add_op(self, op_id, task_uid, label_name, physical, device):
        return {
            "op_id": op_id, "entity_type": "object_label", "entity_uid": task_uid,
            "op_type": "label_add", "device_id": device,
            "hlc": _hlc(physical, device=device),
            "target": {"object_type": "task", "object_id": task_uid, "label_name": label_name},
        }

    def test_higher_hlc_label_wins_the_other_is_reverted_and_conflict_recorded(self, conn):
        self._seed_projects(conn, "ProjA", "ProjB")
        ops = [
            self._label_add_op("op1", "t1", "ProjA", 1000, "device-a"),
            self._label_add_op("op2", "t1", "ProjB", 2000, "device-b"),
        ]
        results = offline_sync.apply_batch(conn, ops)
        assert db.get_task(conn, "t1")["tags"] == ["ProjB"]
        by_op_id = {r["op_id"]: r for r in results}
        assert by_op_id["op1"]["status"] == "rejected_invariant"
        assert by_op_id["op2"]["status"] == "applied"
        conflicts = db.list_sync_conflicts(conn)
        assert len(conflicts) == 1
        assert conflicts[0]["losing_value"] == "ProjA"
        assert conflicts[0]["field_name"] == "project_label"

    def test_pre_existing_project_label_always_wins_over_a_batch_addition(self, conn):
        self._seed_projects(conn, "ProjA", "ProjB")
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active", "tags": ["ProjA"]})
        ops = [self._label_add_op("op1", "t1", "ProjB", 9999, "device-b")]
        results = offline_sync.apply_batch(conn, ops)
        assert db.get_task(conn, "t1")["tags"] == ["ProjA"]
        assert results[0]["status"] == "rejected_invariant"
        assert len(db.list_sync_conflicts(conn)) == 1

    def test_two_devices_adding_the_same_label_is_not_a_conflict(self, conn):
        self._seed_projects(conn, "ProjA")
        ops = [
            self._label_add_op("op1", "t1", "ProjA", 1000, "device-a"),
            self._label_add_op("op2", "t1", "ProjA", 2000, "device-b"),
        ]
        offline_sync.apply_batch(conn, ops)
        assert db.get_task(conn, "t1")["tags"] == ["ProjA"]
        assert db.list_sync_conflicts(conn) == []


class TestSyncConflictsSettingsPage:
    def test_page_lists_unresolved_conflicts(self, conn):
        db.create_sync_conflict(conn, "event", "e1", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        req = Request({"type": "http", "method": "GET", "path": "/settings/sync-conflicts", "query_string": b"", "headers": []})
        resp = settings_router.settings_sync_conflicts(req, conn=conn)
        body = resp.body.decode()
        assert "2026-08-10T11:00:00" in body
        assert "Restore" in body and "Dismiss" in body

    def test_restore_reapplies_the_losing_value_and_resolves(self, conn):
        _seed_event(conn, "e1", start_at="2026-08-10T12:00:00")
        conflict_id = db.create_sync_conflict(conn, "event", "e1", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        resp = settings_router.restore_sync_conflict(conflict_id, conn=conn)
        assert resp.status_code == 303
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-10T11:00:00"
        assert db.get_sync_conflict(conn, conflict_id)["resolved_at"] is not None

    def test_restore_of_a_project_label_conflict_re_adds_the_label(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active", "tags": ["ProjB"]})
        conn.execute("INSERT INTO label_config (name, is_project) VALUES ('ProjA', 1)")
        conn.execute("INSERT INTO label_config (name, is_project) VALUES ('ProjB', 1)")
        conn.commit()
        conflict_id = db.create_sync_conflict(conn, "task", "t1", "project_label", "ProjA", (1000, 0, "device-a"), (2000, 0, "device-b"))
        settings_router.restore_sync_conflict(conflict_id, conn=conn)
        # Restoring re-adds ProjA -- this task now (again) violates
        # single-project-per-task, but restore is a plain apply_op call,
        # not a batch, so §7c's batch-only re-validation correctly doesn't
        # re-trigger here; that's a pre-existing narrower gap (a person
        # manually restoring a losing label is a deliberate override, not
        # an unattended sync writing two labels at once).
        assert "ProjA" in db.get_task(conn, "t1")["tags"]

    def test_dismiss_resolves_without_reapplying(self, conn):
        _seed_event(conn, "e1", start_at="2026-08-10T12:00:00")
        conflict_id = db.create_sync_conflict(conn, "event", "e1", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        resp = settings_router.dismiss_sync_conflict(conflict_id, conn=conn)
        assert resp.status_code == 303
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-10T12:00:00"
        assert db.get_sync_conflict(conn, conflict_id)["resolved_at"] is not None
