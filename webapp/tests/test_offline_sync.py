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


class TestDataVersion:
    """2026-08-17 -- the server-side data version (db.get_sync_data_version):
    a monotonic counter that moves exactly when a sync write actually
    changes server state, exposed via GET /api/sync/state and in every pull
    response. The client compares it against its own last-synced copy to
    skip a no-op round entirely (offline_sync_client.js's `nothingToDo()`
    pre-check) -- so "did the version change" must mean exactly the same
    thing as "would a pull return something new"."""

    def test_version_starts_at_zero(self, conn):
        assert db.get_sync_data_version(conn) == 0

    def test_apply_batch_with_a_real_write_bumps_the_version(self, conn):
        assert db.get_sync_data_version(conn) == 0
        offline_sync.apply_batch(
            conn, [_field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}})]
        )
        assert db.get_sync_data_version(conn) == 1
        # A second, separate real write moves it again.
        offline_sync.apply_batch(
            conn, [_field_set_op("op2", "task", "t1", {"due_at": {"value": "2026-09-01", "hlc": _hlc(2000)}})]
        )
        assert db.get_sync_data_version(conn) == 2

    def test_replaying_the_same_batch_does_not_bump_again(self, conn):
        batch = [_field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}})]
        offline_sync.apply_batch(conn, batch)
        assert db.get_sync_data_version(conn) == 1
        # A retried push of the same op_ids replays the cached result (§5)
        # -- nothing changes server-side, so the version must not move, or
        # every retry would send other devices into a pull that returns
        # nothing new.
        offline_sync.apply_batch(conn, batch)
        assert db.get_sync_data_version(conn) == 1

    def test_a_stale_batch_does_not_bump(self, conn):
        offline_sync.apply_op(conn, _field_set_op("op1", "task", "t1", {"title": {"value": "New", "hlc": _hlc(2000)}}))
        # A fully-stale batch (every field write loses to what's already
        # there) changes nothing -- version stays put.
        offline_sync.apply_batch(
            conn, [_field_set_op("op2", "task", "t1", {"title": {"value": "Stale", "hlc": _hlc(1000)}})]
        )
        assert db.get_sync_data_version(conn) == 0

    def test_state_endpoint_returns_the_version(self, conn):
        offline_sync.apply_batch(
            conn, [_field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}})]
        )
        resp = asyncio.run(sync_api.state(conn=conn))
        assert resp.status_code == 200
        assert _json.loads(resp.body.decode()) == {"version": 1}

    def test_pull_response_includes_the_current_version(self, conn):
        offline_sync.apply_batch(
            conn, [_field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}})]
        )
        resp = asyncio.run(sync_api.pull(_json_request({"device_id": "device-b", "cursor": None}), conn=conn))
        body = _json.loads(resp.body.decode())
        assert body["version"] == 1
        # A pull after a GC purge reflects the post-purge version.
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        offline_sync.purge_expired(conn, retention_days=0)
        resp = asyncio.run(sync_api.pull(_json_request({"device_id": "device-b", "cursor": None}), conn=conn))
        body = _json.loads(resp.body.decode())
        assert body["version"] == db.get_sync_data_version(conn)

    def test_purge_expired_bumps_the_version_when_it_purges(self, conn):
        offline_sync.apply_batch(
            conn, [_field_set_op("op1", "task", "t1", {"title": {"value": "T", "hlc": _hlc(1000)}})]
        )
        version_before = db.get_sync_data_version(conn)
        offline_sync.apply_op(conn, _delete_op("op2", "task", "t1", 2000))
        result = offline_sync.purge_expired(conn, retention_days=0)
        assert any(result["purged_entities"].values())
        assert db.get_sync_data_version(conn) == version_before + 1


def _seed_event(conn, uid, **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": "active", "all_day": False,
        "start_at": "2026-08-10T09:00:00", "end_at": "2026-08-10T10:00:00", "tags": [],
    }
    row.update(overrides)
    # record_server_write=False: these seeds represent a row that already
    # existed before the sync feature (see TestServerWritesEnterFieldVersions
    # for the server-as-author behavior a *live* upsert now exhibits). With
    # recording on, the seed would mint a real-now "server" field HLC that
    # outranks every synthetic device HLC below and turn every §7b test into
    # a server-vs-device conflict test -- this keeps them focused on the
    # two-device concurrency each one is actually about.
    db.upsert_event(conn, row, record_server_write=False)


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
    def test_page_lists_unresolved_conflicts(self, conn, tmp_path):
        from types import SimpleNamespace

        db.create_sync_conflict(conn, "event", "e1", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        # The merged Data & Maintenance page (2026-08-17; sync conflicts
        # moved off their own page into its "Needs attention" section)
        # reads app.state.settings' db_path/backup_dir/radicale_base_url.
        fake_app = SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    radicale_base_url="http://localhost:5232",
                    db_path=tmp_path / "cache.sqlite",
                    backup_dir=tmp_path / "backups",
                )
            )
        )
        req = Request({"type": "http", "method": "GET", "path": "/settings/data-maintenance", "query_string": b"", "headers": [], "app": fake_app})
        resp = settings_router.settings_data_maintenance(req, conn=conn)
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


class TestServerWritesEnterFieldVersions:
    """2026-08-18 follow-up -- the fix for the "offline shows nothing" bug.
    The sync protocol only ever delivers changes to a device through
    field_versions, and field_versions was only ever written by *device*
    pushes. The ordinary rendered UI's own writes (db.upsert_*/delete_*)
    bypassed it entirely, so a fresh device's pull returned an empty delta
    and its local mirror stayed empty forever -- leaving the /offline
    shell's static "Nothing to load right now" empty state visible. The
    server is now itself a participant in the same scheme: every server
    write records its changed fields into field_versions under a "server"
    HLC (db.SERVER_DEVICE_ID), and a pull delivers them like any other
    change. These tests pin that behavior server-side (no browser)."""

    def test_server_create_records_its_fields_and_pull_delivers_them(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "title": "Buy groceries", "description": "",
            "status": "active", "due_at": "2026-08-20T10:00:00",
            "created_at": "2026-08-18T09:00:00",
        })
        result = offline_sync.pull(conn, None)
        assert result["full_resync"] is False
        changes = {c["field_name"]: c for c in result["changes"]}
        assert changes["title"]["value"] == "Buy groceries"
        assert changes["due_at"]["value"] == "2026-08-20T10:00:00"
        assert changes["status"]["value"] == "active"
        assert all(c["hlc"][2] == db.SERVER_DEVICE_ID for c in result["changes"])
        # Exactly one version bump for the whole create -- one server write,
        # not one per field.
        assert db.get_sync_data_version(conn) == 1

    def test_server_edit_records_only_the_fields_that_changed(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "A", "description": "", "status": "active"})
        first_hlc = db.get_field_hlc(conn, "task", "t1", "title")
        db.upsert_task(conn, {"uid": "t1", "title": "B", "description": "", "status": "active"})
        # title changed -> its HLC advanced past the create's...
        assert db.get_field_hlc(conn, "task", "t1", "title") > first_hlc
        # ...but status/description did not -- recording *every* column on
        # every edit would overwrite a device's newer HLC on fields the
        # server never touched, so unchanged fields keep their old HLC.
        assert db.get_field_hlc(conn, "task", "t1", "status") == first_hlc
        assert db.get_field_hlc(conn, "task", "t1", "description") == first_hlc

    def test_server_delete_records_a_tombstone_a_pull_can_deliver(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "A", "description": "", "status": "active"})
        db.delete_task(conn, "t1")
        assert db.get_task(conn, "t1") is None
        result = offline_sync.pull(conn, None)
        tombstones = [
            c for c in result["changes"]
            if c["field_name"] == "deleted_at" and c["entity_uid"] == "t1"
        ]
        assert len(tombstones) == 1
        # The row is physically gone; the value is synthesized from the
        # tombstone's HLC (offline_sync._current_field_value) so a device's
        # mirror hides the entity rather than seeing a null deleted_at.
        assert tombstones[0]["value"]

    def test_server_clock_merges_past_an_applied_device_op(self, conn):
        offline_sync.apply_op(conn, _field_set_op(
            "op1", "task", "t1",
            {"title": {"value": "From device", "hlc": _hlc(5000, device="device-a")}},
        ))
        # The server observed the device's HLC -- its own clock must now be
        # past it, or a server edit causally *after* the device's offline
        # edit could mint an HLC that fails to outrank it (§3's merge rule).
        clock = db.get_server_hlc_clock(conn)
        assert clock is not None and clock[0] >= 5000
        db.upsert_task(conn, {"uid": "t1", "title": "Server edit", "description": "", "status": "active"})
        hlc = db.get_field_hlc(conn, "task", "t1", "title")
        assert hlc[0] > 5000 or (hlc[0] == 5000 and hlc[1] > 0)
        assert db.get_task(conn, "t1")["title"] == "Server edit"

    def test_device_edit_newer_than_a_pulled_server_write_wins_plainly(self, conn):
        # A device that pulled the server's write first (mirroring the
        # client's mergeHlc on pull) then edits offline pushes a strictly
        # newer HLC and wins -- plain §6, no different from any two devices.
        db.upsert_task(conn, {"uid": "t1", "title": "Server title", "description": "", "status": "active"})
        server_hlc = db.get_field_hlc(conn, "task", "t1", "title")
        result = offline_sync.apply_op(conn, _field_set_op(
            "op1", "task", "t1",
            {"title": {"value": "Device title", "hlc": _hlc(server_hlc[0] + 1, device="device-a")}},
        ))
        assert result["status"] == "applied"
        assert db.get_task(conn, "t1")["title"] == "Device title"

    def test_server_write_is_a_sync_conflict_participant_on_surfaced_fields(self, conn):
        # §7b's surfaced scheduling fields treat a cross-device overwrite as
        # a conflict -- the server's seed HLC carries device "server", so a
        # device edit to an event's start_at that beats it is recorded as a
        # conflict exactly like a two-device edit would be.
        db.upsert_event(conn, {
            "uid": "e1", "title": "E", "description": "", "status": "active",
            "all_day": False, "start_at": "2026-08-10T09:00:00",
            "end_at": "2026-08-10T10:00:00",
        })
        server_hlc = db.get_field_hlc(conn, "event", "e1", "start_at")
        offline_sync.apply_op(conn, _field_set_op(
            "op1", "event", "e1",
            {"start_at": {"value": "2026-08-10T11:00:00", "hlc": _hlc(server_hlc[0] + 1, device="device-a")}},
        ))
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-10T11:00:00"
        conflicts = db.list_sync_conflicts(conn)
        assert len(conflicts) == 1
        assert conflicts[0]["field_name"] == "start_at"
        assert conflicts[0]["losing_value"] == "2026-08-10T09:00:00"


class TestServerWritesBackfill:
    """The one-time backfill half of the same fix: rows that *predate*
    server-as-author recording (created before this change, so they have
    no field_versions entries at all) get recorded into field_versions by
    db.backfill_server_sync_writes when init_schema runs on an upgraded
    installation -- otherwise a device's first pull would still return an
    empty delta for them and the offline shell would still show nothing."""

    def _clear_backfill_marker(self, conn):
        # init_schema already ran the (empty-database, no-op) backfill on
        # the fixture connection and set the done-marker; clear it to
        # exercise the backfill itself, exactly as an upgraded install's
        # first connection would.
        conn.execute("DELETE FROM app_meta WHERE key = ?", (db._SERVER_WRITES_BACKFILLED_KEY,))
        conn.commit()

    def test_backfill_records_pre_existing_rows_and_a_pull_delivers_them(self, conn):
        conn.execute("INSERT INTO tasks (uid, title, description, status) VALUES ('t-old', 'Old task', '', 'active')")
        conn.execute("INSERT INTO events (uid, title, description, status, all_day) VALUES ('e-old', 'Old event', '', 'active', 0)")
        conn.commit()
        self._clear_backfill_marker(conn)
        db.backfill_server_sync_writes(conn)
        assert db.get_field_hlc(conn, "task", "t-old", "title") is not None
        assert db.get_field_hlc(conn, "event", "e-old", "title") is not None
        changes = offline_sync.pull(conn, None)["changes"]
        titles = [c for c in changes if c["entity_uid"] == "t-old" and c["field_name"] == "title"]
        assert titles and titles[0]["value"] == "Old task"
        # Idempotent: the marker is set once the scan has run, so a second
        # call adds nothing and moves the data version nothing.
        version = db.get_sync_data_version(conn)
        db.backfill_server_sync_writes(conn)
        assert db.get_sync_data_version(conn) == version

    def test_backfill_never_overwrites_a_field_a_device_already_synced(self, conn):
        offline_sync.apply_op(conn, _field_set_op(
            "op1", "task", "t1",
            {"title": {"value": "Device wrote", "hlc": _hlc(1000, device="device-a")}},
        ))
        before = db.get_field_hlc(conn, "task", "t1", "title")
        self._clear_backfill_marker(conn)
        db.backfill_server_sync_writes(conn)
        # The backfill only ever ADDS missing field_versions entries
        # (INSERT OR IGNORE); a field a device has already synced keeps its
        # own HLC untouched.
        assert db.get_field_hlc(conn, "task", "t1", "title") == before
        assert db.get_field_hlc(conn, "task", "t1", "status") is not None


class TestWorkAllocationSyncFlag:
    """2026-08-18 -- the offline "Upcoming" view needs to tell a
    work-allocation event (a scheduled task work session) apart from an
    ordinary event in the local mirror. The flag isn't an `events` column
    -- it lives in event_task_relations.is_work_allocation -- and the sync
    protocol only ever delivers a device's mirror something through
    field_versions, so the server records it as its own sync field
    (`db.record_work_allocation_flag`) and `offline_sync._current_field_
    value` derives the delivered value back from the relation table. These
    tests pin that server-side, the same way TestServerWritesEnterField
    Versions pins the server-as-author mechanism."""

    def test_create_work_allocation_pull_delivers_the_flag(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "Write report", "description": "", "status": "active"})
        event_uid = db.create_work_allocation(
            conn, "t1", "2026-08-20T10:00:00", "2026-08-20T11:00:00"
        )
        changes = offline_sync.pull(conn, None)["changes"]
        flag = [c for c in changes if c["entity_uid"] == event_uid and c["field_name"] == "is_work_allocation"]
        assert len(flag) == 1
        assert flag[0]["value"] == 1
        assert flag[0]["hlc"][2] == db.SERVER_DEVICE_ID

    def test_regular_event_has_no_flag_change(self, conn):
        # No flag entry is written for a regular event, and pull never
        # mentions it -- the mirror reads the absence as "not a work
        # allocation," which is exactly what a plain event is.
        db.upsert_event(conn, {
            "uid": "e1", "title": "Dentist", "description": "", "status": "active",
            "all_day": False, "start_at": "2026-08-20T09:00:00", "end_at": "2026-08-20T09:30:00",
        })
        changes = offline_sync.pull(conn, None)["changes"]
        assert all(c["field_name"] != "is_work_allocation" for c in changes)

    def test_undated_work_allocation_still_delivers_the_flag(self, conn):
        # An undated session placeholder (no start/end yet, the "+"-added
        # kind) is still a work allocation -- the flag must travel
        # regardless of whether the block has been scheduled yet.
        db.upsert_task(conn, {"uid": "t1", "title": "Read", "description": "", "status": "active"})
        event_uid = db.create_work_allocation(conn, "t1")
        changes = offline_sync.pull(conn, None)["changes"]
        flag = [c for c in changes if c["entity_uid"] == event_uid and c["field_name"] == "is_work_allocation"]
        assert flag and flag[0]["value"] == 1

    def test_backfill_records_pre_existing_work_allocation_flags(self, conn):
        # Rows created before this feature have no flag entry (only the
        # main entity-column backfill ran, which never reads the relation
        # table) -- backfill_work_allocation_flags fills exactly those in.
        conn.execute("INSERT INTO events (uid, title, description, status, all_day) VALUES ('e-wa', 'Old session', '', 'active', 0)")
        conn.execute("INSERT INTO events (uid, title, description, status, all_day) VALUES ('e-link', 'Linked event', '', 'active', 0)")
        conn.execute(
            "INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
            "VALUES ('e-wa', 't1', '2026-08-18T00:00:00', 1)"
        )
        conn.execute(
            "INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
            "VALUES ('e-link', 't1', '2026-08-18T00:00:00', 0)"
        )
        conn.commit()
        conn.execute("DELETE FROM app_meta WHERE key = ?", (db._WORK_ALLOCATION_FLAGS_BACKFILLED_KEY,))
        conn.commit()
        db.backfill_work_allocation_flags(conn)
        changes = offline_sync.pull(conn, None)["changes"]
        flags = {c["entity_uid"]: c["value"] for c in changes if c["field_name"] == "is_work_allocation"}
        # Only the =1 relation's event gets a flag entry; a plain task link
        # (=0) is an ordinary event and stays flagless.
        assert flags == {"e-wa": 1}

    def test_backfill_is_idempotent_and_never_overwrites_device_state(self, conn):
        conn.execute("INSERT INTO events (uid, title, description, status, all_day) VALUES ('e-wa', 'Old', '', 'active', 0)")
        conn.execute(
            "INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
            "VALUES ('e-wa', 't1', '2026-08-18T00:00:00', 1)"
        )
        conn.commit()
        # Simulate a device that already synced a flag value for this event
        # (e.g. pulled a server-written flag before the install ever ran
        # the backfill) -- the backfill's INSERT OR IGNORE must leave its
        # HLC untouched.
        db.set_field_hlc(conn, "event", "e-wa", "is_work_allocation", (9999, 0, "device-a"))
        conn.execute("DELETE FROM app_meta WHERE key = ?", (db._WORK_ALLOCATION_FLAGS_BACKFILLED_KEY,))
        conn.commit()
        db.backfill_work_allocation_flags(conn)
        assert db.get_field_hlc(conn, "event", "e-wa", "is_work_allocation") == (9999, 0, "device-a")
        # Idempotent: the marker is set once the scan has run, so a second
        # call records nothing and moves the data version nothing.
        version = db.get_sync_data_version(conn)
        db.backfill_work_allocation_flags(conn)
        assert db.get_sync_data_version(conn) == version

    def test_device_cannot_push_the_flag_itself(self, conn):
        # The flag is server-derived (it describes a relation row, which a
        # device op has no way to express) -- a device push that tries to
        # set it is rejected like any other unknown field, not silently
        # interpolated into a SQL column that doesn't exist.
        result = offline_sync.apply_op(conn, _field_set_op(
            "op1", "event", "e1",
            {"title": {"value": "E", "hlc": _hlc(1000)}, "is_work_allocation": {"value": 1, "hlc": _hlc(1001)}},
        ))
        assert result["fields"]["is_work_allocation"] == "rejected_unknown_field"
        assert result["fields"]["title"] == "applied"
        assert db.get_field_hlc(conn, "event", "e1", "is_work_allocation") is None
