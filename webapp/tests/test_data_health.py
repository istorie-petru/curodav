"""Data health & maintenance (`plans/open.md` § Data health & maintenance) --
the 1.8 (offline-first editing & synchronization) precondition: "trusted only
once verified backups exist" (plans/STATE.md). Covers src/data_health.py's
service functions directly (the layer both Settings > Data health and
scripts/data_health.py share) plus the Settings routes/page.
"""

from __future__ import annotations

import json
from pathlib import Path
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

    def test_sync_summary_reflects_real_sync_devices(self, conn, tmp_path):
        # open-priority.md §9: the fixed {"configured": False} placeholder
        # data_health.py carried through slices 1-5 is what slice 6 was
        # always meant to flip once a real sync engine exists to populate
        # sync_devices. Relocated here 2026-09-09 from test_pwa_shell.py's
        # TestSyncEngine, which was gutted in the client-side Offline Mode
        # purge -- this test is purely server-side (data_health.py + db.py)
        # and never depended on any of the deleted client files.
        backups_dir = tmp_path / "backups"
        summary = data_health.health_summary(conn, tmp_path / "cache.sqlite", backups_dir)
        assert summary["sync"]["configured"] is False
        assert summary["sync"]["device_count"] == 0

        db.touch_sync_device(conn, "device-a", last_pushed_hlc=(1000, 0, "device-a"))
        summary = data_health.health_summary(conn, tmp_path / "cache.sqlite", backups_dir)
        assert summary["sync"]["configured"] is True
        assert summary["sync"]["device_count"] == 1
        assert summary["sync"]["last_seen_at"] is not None


class TestDataHealthCli:
    """scripts/data_health.py -- the CLI half of the same service layer
    Settings > Data & Maintenance uses. Relocated here 2026-09-09 from
    test_pwa_shell.py's TestTombstoneGc, which was gutted in the
    client-side Offline Mode purge -- this test only reads scripts/
    data_health.py and never depended on any of the deleted client files."""

    def test_has_a_sync_gc_subcommand(self):
        script = (Path(__file__).resolve().parent.parent / "scripts" / "data_health.py").read_text()
        assert '"sync-gc"' in script
        assert "cmd_sync_gc" in script


class TestSettingsDataMaintenancePage:
    """2026-08-17: Data health, Sync conflicts and Advanced merged into
    one Data & Maintenance page (settings_data_maintenance.html); the
    three old URLs redirect to it. The service-level tests above are
    unchanged -- only the page this one renders moved."""

    def test_renders_empty_state(self, conn, tmp_path):
        resp = settings_router.settings_data_maintenance(
            _request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        assert resp.status_code == 200
        assert resp.context["active_tab"] == "settings_data_maintenance"
        body = resp.body.decode()
        assert "No backups yet" in body

    def test_shows_sync_cleanup_controls(self):
        # 2026-08-17: the sync-retention / sync-gc controls live in this
        # page's "Maintenance & upkeep" section. Relocated here 2026-09-09
        # from test_pwa_shell.py's TestTombstoneGc, which was gutted in the
        # client-side Offline Mode purge -- this test only reads this
        # template and never depended on any of the deleted client files.
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "settings_data_maintenance.html").read_text()
        assert "sync-retention" in html
        assert "sync-gc" in html

    def test_old_data_health_url_redirects_to_the_merged_page(self, conn, tmp_path):
        resp = settings_router.settings_data_health(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/data-maintenance"

    def test_needs_attention_section_appears_only_when_something_is_wrong(self, conn, tmp_path):
        req = _request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        # The section's warning-tinted card (and its count pill / restore
        # forms) only render when something is actually wrong; "Needs
        # attention" itself also appears in the template's own comment, so
        # assert on the rendered markers instead.
        warning_card = 'class="card card-danger"'
        # Healthy database, no conflicts -> no "Needs attention" section.
        body = settings_router.settings_data_maintenance(req, conn=conn).body.decode()
        assert warning_card not in body
        assert "unresolved sync conflict" not in body
        # An unresolved sync conflict -> the section appears at the top.
        db.create_sync_conflict(conn, "event", "e1", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        body = settings_router.settings_data_maintenance(req, conn=conn).body.decode()
        assert warning_card in body
        assert "1 unresolved sync conflict" in body
        assert 'action="/settings/sync-conflicts/' in body

    def test_health_status_uses_status_pills_not_plain_text(self, conn, tmp_path):
        req = _request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        body = settings_router.settings_data_maintenance(req, conn=conn).body.decode()
        # New System Status cards replace the old Health status section.
        # Database card: healthy (integrity OK) -> status-card healthy
        assert 'status-card healthy' in body
        # Sync card: not configured -> status-card unknown
        assert 'status-card unknown' in body
        # Backup card: no backup -> status-card unknown
        assert body.count('status-card unknown') >= 2

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

    def test_data_maintenance_is_a_hub_category(self):
        urls = [c["url"] for c in settings_router.HUB_CATEGORIES]
        assert "/settings/data-maintenance" in urls


class TestDataMaintenanceRedesign2026_08_26:
    """The 2026-08-26 page redesign (second pass same day): below the
    (unchanged) System Status cards there is no separate backup or danger
    surface anymore -- backup actions live in the Backup status card's own
    menu (its meta line is the only place naming a last-backup timestamp or
    size), restore-a-file goes through the unified Export & import drop
    zone, and reset-database opens a confirm toast carrying the typed
    DELETE ALL check (2026-09-09: was a standalone modal dialog, see
    TestPurgeAllConfirmToast below)."""

    def _page(self, conn, tmp_path):
        req = _request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        return settings_router.settings_data_maintenance(req, conn=conn).body.decode()

    def test_purge_completed_is_housekeeping_and_danger_zone_is_gone(self, conn, tmp_path):
        db.upsert_task(conn, {"uid": "done1", "title": "Old done task", "description": "",
                              "status": "done", "due_at": None,
                              "created_at": _now(), "updated_at": _now()})
        body = self._page(conn, tmp_path)
        # 2026-09-11: moved into the Database card's context menu (routine
        # housekeeping, grouped with Check integrity/Compact & reindex)...
        assert 'action="/settings/purge-completed"' in body
        assert "Purge completed (1)" in body
        # ...and no Danger zone anywhere: the full wipe moved behind the
        # Database card's own confirm-toast trigger (2026-09-09: a plain
        # button that opens a ccConfirmSheet, not a link to a modal page --
        # see data_maintenance.js).
        assert "Danger zone" not in body
        assert 'action="/settings/purge-all"' not in body
        assert 'data-action="purge-all"' in body

    def test_backup_actions_live_in_the_backup_cards_menu(self, conn, tmp_path):
        settings_router.data_health_backup(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        body = self._page(conn, tmp_path)
        assert 'href="/export/data.json"' in body          # Download full backup
        assert "Download full backup" in body
        assert "Verify integrity" in body                   # per-backup actions
        assert "Restore this backup" in body
        # "Restore a file…" was removed 2026-09-08 (duplicate of the Sync
        # card's "Import data…", same /export/import-modal dialog).
        assert "Restore a file" not in body

    def test_backup_facts_are_human_readable_and_only_in_the_backup_card(self, conn, tmp_path):
        import re

        resp = settings_router.data_health_backup(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        assert resp.status_code == 303
        backup = data_health.list_backups(tmp_path / "backups")[0]
        body = self._page(conn, tmp_path)
        # Raw ISO timestamps became "Aug 25, 2026, 8:57 PM"-style text, and
        # the filename never renders as visible text -- it exists only as
        # the two menu forms' hidden inputs (verify + restore). 2026-09-08
        # direct request (minimal card text): the "Last backup:" label
        # prefix was dropped -- the meta line is just "<date> · <size>" now,
        # the status pill above it already says what state it's in.
        assert re.search(r"status-card-meta[\s\S]{0,80}[A-Z][a-z]{2} \d{1,2}, \d{4}", body)
        assert "Last backup:" not in body
        assert f">{backup['filename']}" not in body
        assert body.count(f'value="{backup["filename"]}"') == 2
        assert re.search(r"\d+(\.\d+)? (kB|MB|bytes)", body)
        # The old redundant surfaces stay gone.
        assert "<th>File</th>" not in body
        assert "Database size" not in body
        assert '<use href="#icon-bar-chart-2">' not in body

    def test_verification_state_flips_the_card_meta_line(self, conn, tmp_path):
        import re

        settings_router.data_health_backup(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn
        )
        body = self._page(conn, tmp_path)
        # 2026-09-08 direct request (minimal card text): an unverified
        # backup no longer gets its own "Not yet verified" meta line --
        # that state is already carried by the status pill above it
        # ("Not verified"), so the meta line stays silent until there's a
        # real timestamp to add.
        assert "Verified " not in body
        backup = data_health.list_backups(tmp_path / "backups")[0]
        settings_router.data_health_verify(
            _request(db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"),
            filename=backup["filename"], conn=conn,
        )
        body = self._page(conn, tmp_path)
        assert re.search(r"Verified [A-Z][a-z]{2} \d{1,2}, \d{4}", body)

    def test_no_backup_yet_message_lives_in_the_card_meta(self, conn, tmp_path):
        body = self._page(conn, tmp_path)
        assert "No backups yet" in body

    def test_redesigned_dropdown_labels_render(self, conn, tmp_path):
        body = self._page(conn, tmp_path)
        for label in ("After 1 week", "After 1 month", "Never", "Keep 30 days", "Keep 90 days", "Keep forever"):
            assert label in body

    def test_legacy_stored_value_stays_visible(self, conn, tmp_path):
        # An install that picked "14 days" before the relabel still stores
        # 14; the select must show that truthfully instead of silently
        # displaying the first preset while storing something else.
        db.set_app_meta(conn, "task_auto_archive_days", "14")
        body = self._page(conn, tmp_path)
        assert '<option value="14" selected>14 days (current)</option>' in body


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


class TestDataMaintenanceScriptGate:
    """Structural checks over static/data_maintenance.js and its two
    remaining dialog templates (2026-08-26 redesign, third pass; 2026-09-09:
    the third dialog, reset-database, became a confirm toast instead of a
    template, see TestPurgeAllConfirmToast below) -- same grep-the-source
    style as the app's other page-local scripts; no browser in this
    environment to drive the real DOM."""

    JS = (Path(__file__).resolve().parent.parent / "src" / "static" / "data_maintenance.js").read_text()
    PAGE = (Path(__file__).resolve().parent.parent / "src" / "templates" / "settings_data_maintenance.html").read_text()
    EXPORT = (Path(__file__).resolve().parent.parent / "src" / "templates" / "export_modal.html").read_text()
    IMPORT = (Path(__file__).resolve().parent.parent / "src" / "templates" / "import_modal.html").read_text()

    def test_all_dialog_bindings_are_delegated_not_load_time_bound(self):
        # The dropzone's drag pair, the file/change previews and the export
        # preview must all attach at the document level -- nothing may query
        # for dialog elements at load time. (The four drag events ride two
        # forEach loops over event-name arrays.)
        # "input" dropped from this list 2026-09-09: the one delegated
        # input listener here was the old reset-database phrase gate,
        # which moved into toast.js (a direct listener on the toast's own
        # freshly-created input -- no delegation needed there, the element
        # is never present at load time to begin with).
        for evt in ("change", "drop"):
            assert f'document.addEventListener("{evt}"' in self.JS
        for evt in ("dragenter", "dragover", "dragleave", "drop"):
            assert f'"{evt}"' in self.JS
        assert "[data-dm-root]" not in self.JS

    def test_action_menu_closes_on_any_item_and_items_are_not_bold(self):
        # 2026-08-26 direct feedback: clicking ANY entry in a status card's
        # three-dot menu must close it (anchor items opening the export/
        # import/reset dialogs previously left it stranded behind the
        # overlay), and entries render non-bold.
        app = (Path(__file__).resolve().parent.parent / "src" / "static" / "app.js").read_text()
        assert 'panel.addEventListener("click", () => closeMenu())' in app
        css = (Path(__file__).resolve().parent.parent / "src" / "static" / "style.css").read_text()
        block = css.split(".action-menu-item{", 1)[1].split("}", 1)[0]
        assert "font-weight:400" in block

    def test_templates_carry_the_data_attributes_the_script_reads(self):
        # The page itself hosts no export/import dialog markup -- the Sync
        # card's menu items are data-modal triggers; the attributes live in
        # the two dialog templates. 2026-09-08 direct request: the Backup
        # card's own "Restore a file…" (a verbatim duplicate of the Sync
        # card's "Import data…", same URL) was removed -- one home per
        # action now, so this link renders exactly once, not twice.
        # 2026-09-09: "Reset database" is a plain data-action button now,
        # not a data-modal link -- see TestPurgeAllConfirmToast.
        assert 'href="/export/modal" data-modal' in self.PAGE
        assert self.PAGE.count('href="/export/import-modal" data-modal') == 1  # Sync card only
        assert 'href="/settings/purge-confirm"' not in self.PAGE
        for marker in ("data-dm-preview=", "data-dm-export-root", "data-modal-get", 'action="/export/download"'):
            assert marker in self.EXPORT
        for marker in ("data-dm-dropzone", "data-dm-file", 'name="merge"', 'action="/export/import/auto"'):
            assert marker in self.IMPORT


class TestPurgeAllConfirmToast:
    """2026-09-09 direct request: "Reset database (purge all)" opens a
    persistent confirm toast (ccConfirmSheet's typedConfirm option,
    static/toast.js) instead of a standalone modal page -- same typed
    "DELETE ALL" gate, just rendered as a toast. Structural (grep-the-
    source) checks only, same reasoning as TestDataMaintenanceScriptGate --
    no browser in this environment to drive the real DOM."""

    PAGE = (Path(__file__).resolve().parent.parent / "src" / "templates" / "settings_data_maintenance.html").read_text()
    DM_JS = (Path(__file__).resolve().parent.parent / "src" / "static" / "data_maintenance.js").read_text()
    TOAST_JS = (Path(__file__).resolve().parent.parent / "src" / "static" / "toast.js").read_text()

    def test_page_has_a_trigger_button_not_a_modal_link(self):
        assert 'data-action="purge-all"' in self.PAGE
        assert 'href="/settings/purge-confirm"' not in self.PAGE
        assert "purge_modal.html" not in self.PAGE

    def test_trigger_opens_a_confirm_sheet_with_the_typed_gate_and_posts(self):
        assert 'closest(e.target, \'[data-action="purge-all"]\')' in self.DM_JS
        assert "window.ccConfirmSheet(" in self.DM_JS
        assert 'typedConfirm: { matchValue: "DELETE ALL" }' in self.DM_JS
        assert 'fetch("/settings/purge-all"' in self.DM_JS
        assert "window.location.reload()" in self.DM_JS

    def test_toast_gate_starts_disabled_and_only_arms_on_exact_match(self):
        # Ported from the old modal's server-disabled-button + input-listener
        # pair: a `gated` action starts disabled, and only the exact
        # matchValue re-enables it -- typing anything else keeps it (or puts
        # it back) disabled.
        assert "btn.disabled = true" in self.TOAST_JS
        assert "gatedButtons.push(btn)" in self.TOAST_JS
        assert "typedInput.value === typedConfirm.matchValue" in self.TOAST_JS
        assert "btn.disabled = !armed" in self.TOAST_JS

    def test_purge_endpoint_never_touches_the_backups_directory(self):
        # The safety property behind the toast's own reassurance copy:
        # purge_all_data (db.py) only DELETEs rows from this app's own
        # SQLite tables. Backups are backup-*.json files discovered by
        # globbing a separate directory (data_health.list_backups) --
        # nothing in the purge path opens, globs, or unlinks that directory.
        db_source = (Path(__file__).resolve().parent.parent / "src" / "db.py").read_text()
        purge_fn = db_source.split("def purge_all_data(", 1)[1].split("\ndef ", 1)[0]
        for marker in ("backups_dir", "backup-", "unlink", "rmtree", "glob"):
            assert marker not in purge_fn
