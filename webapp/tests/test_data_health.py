"""Data health & maintenance (`plans/open.md` § Data health & maintenance) --
the 1.8 (offline-first editing & synchronization) precondition: "trusted only
once verified backups exist" (plans/STATE.md). Covers src/data_health.py's
service functions directly (the layer both Settings > Data health and
scripts/data_health.py share) plus the Settings routes/page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from src import data_health, db
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid="t1"):
    db.upsert_task(
        conn,
        {
            "uid": uid, "title": "Write bibliography", "description": "",
            "status": "todo", "due_at": None,
            "created_at": _now(), "updated_at": _now(),
        },
    )


def _request(path="/settings/data-health", db_path=None, backup_dir=None):
    app = Starlette()
    app.state.settings = SimpleNamespace(
        db_path=db_path, backup_dir=backup_dir,
        radicale_base_url="http://127.0.0.1:5232/devuser/",
    )
    scope = {
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "",
        "headers": [], "app": app,
    }
    return Request(scope)


class TestCreateAndListBackups:
    def test_list_backups_empty_when_no_directory(self, tmp_path):
        assert data_health.list_backups(tmp_path / "backups") == []

    def test_create_backup_writes_a_file_and_is_listed(self, conn, tmp_path):
        _seed_task(conn)
        backups_dir = tmp_path / "backups"
        path = data_health.create_backup(conn, backups_dir)
        assert path.exists()
        payload = json.loads(path.read_text())
        assert payload["tasks"][0]["uid"] == "t1"

        listed = data_health.list_backups(backups_dir)
        assert len(listed) == 1
        assert listed[0]["filename"] == path.name
        assert listed[0]["verification"] is None

    def test_multiple_backups_sorted_newest_first(self, conn, tmp_path):
        backups_dir = tmp_path / "backups"
        p1 = data_health.create_backup(conn, backups_dir)
        # Force a distinguishable second filename (timestamp granularity is
        # seconds) rather than sleeping in a test.
        p2 = backups_dir / "backup-20990101T000000Z.json"
        p2.write_text(p1.read_text())
        listed = data_health.list_backups(backups_dir)
        assert listed[0]["filename"] == p2.name


class TestVerifyBackup:
    def test_verify_valid_backup_ok(self, conn, tmp_path):
        _seed_task(conn)
        path = data_health.create_backup(conn, tmp_path / "backups")
        result = data_health.verify_backup(path)
        assert result.ok is True
        assert result.errors == []
        assert result.counts["tasks"] == 1
        # Sidecar written and picked up by list_backups.
        listed = data_health.list_backups(tmp_path / "backups")
        assert listed[0]["verification"]["ok"] is True

    def test_verify_missing_file(self, tmp_path):
        result = data_health.verify_backup(tmp_path / "nope.json")
        assert result.ok is False
        assert "does not exist" in result.errors[0]

    def test_verify_empty_file(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("")
        result = data_health.verify_backup(path)
        assert result.ok is False
        assert "empty" in result.errors[0]

    def test_verify_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        result = data_health.verify_backup(path)
        assert result.ok is False
        assert any("invalid JSON" in e for e in result.errors)

    def test_verify_missing_required_key(self, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"tasks": []}))
        result = data_health.verify_backup(path)
        assert result.ok is False
        assert any("events" in e for e in result.errors)

    def test_verify_row_missing_uid(self, conn, tmp_path):
        path = tmp_path / "bad_row.json"
        payload = data_health.create_backup(conn, tmp_path / "backups")
        data = json.loads(payload.read_text())
        data["tasks"].append({"title": "no uid"})
        path.write_text(json.dumps(data))
        result = data_health.verify_backup(path)
        assert result.ok is False
        assert any("uid" in e for e in result.errors)


class TestRestoreBackup:
    def test_restore_round_trips_data(self, conn, tmp_path):
        _seed_task(conn)
        path = data_health.create_backup(conn, tmp_path / "backups")
        db.delete_task(conn, "t1")
        result = data_health.restore_backup(conn, path, backups_dir=tmp_path / "backups")
        assert result["ok"] is True
        assert result["restored"] >= 1
        assert db.get_task(conn, "t1") is not None

    def test_restore_takes_a_safety_backup_first(self, conn, tmp_path):
        _seed_task(conn, "t1")
        backups_dir = tmp_path / "backups"
        path = data_health.create_backup(conn, backups_dir)
        before = len(data_health.list_backups(backups_dir))
        result = data_health.restore_backup(conn, path, backups_dir=backups_dir)
        after = len(data_health.list_backups(backups_dir))
        assert result["safety_backup"] is not None
        assert after == before + 1

    def test_restore_without_backups_dir_skips_safety_backup(self, conn, tmp_path):
        _seed_task(conn)
        path = data_health.create_backup(conn, tmp_path / "backups")
        result = data_health.restore_backup(conn, path, backups_dir=None)
        assert result["ok"] is True
        assert result["safety_backup"] is None

    def test_restore_aborts_on_invalid_backup(self, conn, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        result = data_health.restore_backup(conn, path, backups_dir=tmp_path / "backups")
        assert result["ok"] is False
        assert result["restored"] == 0
        assert data_health.list_backups(tmp_path / "backups") == []  # no safety backup taken


class TestIntegrityAndRepair:
    def test_check_integrity_ok_on_fresh_db(self, conn):
        result = data_health.check_integrity(conn)
        assert result["ok"] is True
        assert result["detail"] == "ok"

    def test_compact_and_reindex_reports_sizes(self, conn, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        # The fixture already created/initialized this path via db.connect.
        result = data_health.compact_and_reindex(conn, db_path)
        assert result["ok"] is True
        assert "size_before_bytes" in result and "size_after_bytes" in result


class TestStorageAndEntityStats:
    def test_storage_stats_reflect_backups(self, conn, tmp_path):
        backups_dir = tmp_path / "backups"
        data_health.create_backup(conn, backups_dir)
        stats = data_health.storage_stats(tmp_path / "cache.sqlite", backups_dir)
        assert stats["backup_count"] == 1
        assert stats["backups_dir_size_bytes"] > 0

    def test_entity_stats_match_export_context(self, conn):
        _seed_task(conn)
        stats = data_health.entity_stats(conn)
        assert stats["task_count"] == 1


class TestHealthSummary:
    def test_summary_has_all_expected_sections(self, conn, tmp_path):
        summary = data_health.health_summary(conn, tmp_path / "cache.sqlite", tmp_path / "backups")
        assert set(summary) == {
            "integrity", "latest_backup", "latest_verified_backup",
            "sync", "sync_gc", "storage", "entities", "backups",
        }
        assert summary["sync"]["configured"] is False
        # 1.8 slice 7 -- retention defaults to offline_sync.RETENTION_DAYS
        # (90) until explicitly configured; no GC has run yet on a fresh db.
        assert summary["sync_gc"]["retention_days"] == 90
        assert summary["sync_gc"]["last_run"] is None


class TestSettingsDataHealthPage:
    def test_renders_empty_state(self, conn, tmp_path):
        resp = settings_router.settings_data_health(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        assert resp.status_code == 200
        assert resp.context["active_tab"] == "settings_data_health"
        body = resp.body.decode()
        assert "No backups yet" in body

    def test_backup_route_creates_a_backup_and_redirects(self, conn, tmp_path):
        backups_dir = tmp_path / "backups"
        resp = settings_router.data_health_backup(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=backups_dir), conn=conn
        )
        assert resp.status_code == 303
        assert len(data_health.list_backups(backups_dir)) == 1

    def test_verify_route_with_no_backups_errors(self, conn, tmp_path):
        resp = settings_router.data_health_verify(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"),
            filename="", conn=conn,
        )
        assert resp.status_code == 303
        assert "error" in resp.headers["location"]

    def test_restore_route_rejects_path_traversal(self, conn, tmp_path):
        with pytest.raises(Exception):
            settings_router.data_health_restore(
                _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"),
                filename="../evil.json", conn=conn,
            )

    def test_restore_route_happy_path(self, conn, tmp_path):
        backups_dir = tmp_path / "backups"
        _seed_task(conn)
        path = data_health.create_backup(conn, backups_dir)
        resp = settings_router.data_health_restore(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=backups_dir),
            filename=path.name, conn=conn,
        )
        assert resp.status_code == 303
        assert "note" in resp.headers["location"]
        # A safety backup was made before restoring -- now 2 backups exist.
        assert len(data_health.list_backups(backups_dir)) == 2

    def test_integrity_check_route(self, conn, tmp_path):
        resp = settings_router.data_health_integrity_check(conn=conn)
        assert resp.status_code == 303
        assert "note" in resp.headers["location"]

    def test_repair_route(self, conn, tmp_path):
        resp = settings_router.data_health_repair(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        assert resp.status_code == 303

    def test_data_health_is_a_hub_category(self):
        urls = [c["url"] for c in settings_router.HUB_CATEGORIES]
        assert "/settings/data-health" in urls


class TestSyncGcRoutes:
    """1.8 slice 7 -- Settings' side of tombstone GC: the retention preset
    field and the manual "Run cleanup now" action."""

    def test_set_retention_stores_a_valid_preset(self, conn):
        resp = settings_router.data_health_set_sync_retention(days="30", conn=conn)
        assert resp.status_code == 303
        assert data_health.sync_gc_retention_days(conn) == 30

    def test_set_retention_rejects_an_unrecognized_value(self, conn):
        # Same "fall back to the safe default rather than storing a typo'd
        # value" convention as set_task_auto_archive.
        resp = settings_router.data_health_set_sync_retention(days="not-a-number", conn=conn)
        assert resp.status_code == 303
        assert data_health.sync_gc_retention_days(conn) == 90

    def test_run_now_purges_and_records_a_last_run(self, conn):
        from src import offline_sync

        offline_sync.apply_op(conn, {
            "op_id": "op1", "entity_type": "task", "entity_uid": "t1", "op_type": "field_set",
            "device_id": "device-a", "fields": {"title": {"value": "T", "hlc": {"physical": 1000, "logical": 0, "device_id": "device-a"}}},
        })
        offline_sync.apply_op(conn, {
            "op_id": "op2", "entity_type": "task", "entity_uid": "t1", "op_type": "delete",
            "device_id": "device-a", "hlc": {"physical": 2000, "logical": 0, "device_id": "device-a"},
        })
        resp = settings_router.data_health_run_sync_gc(conn=conn)
        assert resp.status_code == 303
        assert "note" in resp.headers["location"]
        # force=True runs even though retention defaults to 90 days and
        # this tombstone is only milliseconds old by wall-clock "now" --
        # the manual action isn't gated by the automatic trigger's own
        # retention window at all, it always runs.
        last_run = data_health.sync_gc_last_run(conn)
        assert last_run is not None
        assert last_run["retention_days"] == 90
        assert last_run["purged_entities"]["task"] == 1

    def test_run_now_still_works_when_retention_is_set_to_never(self, conn):
        data_health.set_sync_gc_retention_days(conn, 0)
        resp = settings_router.data_health_run_sync_gc(conn=conn)
        assert resp.status_code == 303
        assert data_health.sync_gc_last_run(conn) is not None
