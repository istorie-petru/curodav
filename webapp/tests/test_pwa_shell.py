"""1.8 slices 3-5 -- the PWA shell (plans/open-priority.md § Offline-first
editing & synchronization §11).

Slice 3: manifest, service worker, offline app-shell caching -- "can the
app open at all with no network."

Slice 4: the client-side local read path on top of that shell --
static/offline_db.js (an IndexedDB mirror of tasks/events/contacts, keyed
by the same per-field HLC rule offline_sync.py's own field_versions table
uses server-side) and static/offline_sync_client.js (§8's pull half,
run client-side, loaded globally so the mirror is warm before the network
actually drops). templates/offline.html's #offline-local-data now renders
straight from that mirror via static/offline_shell.js.

Slice 5: the local *write* path -- static/offline_write.js
(create/edit/delete a task offline, each queued as a §2 op into
offline_db.js's new `outbox` IndexedDB store and applied optimistically to
the mirror through the same per-field-HLC path a pull already uses).
offline_db.js also gained this device's own §3 HLC clock (`nextHlc`/
`mergeHlc`) -- nothing before this slice ever needed to *mint* an HLC, only
apply server-supplied ones. Still no sync *engine* -- push, retry/backoff,
and the status indicator are slice 6; queued ops just accumulate in the
outbox until then.

Neither a real service worker nor real IndexedDB can be exercised by this
app's usual pytest/router-function-call convention (there's no browser
here to install a worker, intercept fetches, read Cache Storage, or run
indexedDB.open) -- that part needs manual/browser verification, per
plans/STATE.md's own note on this slice. What *is* verifiable server-side,
and covered here:

  - manifest.webmanifest is valid, has the fields a browser's install
    prompt needs, and every icon it references actually exists on disk.
  - GET /sw.js serves static/sw.js's own content as a real script (not a
    404/redirect), with a JS content-type and no-store caching so browsers
    always refetch the script itself to notice an update.
  - GET /offline renders the normal page chrome (tabbar, nav) plus an
    honest "you're offline" message -- reachable normally online, not
    sw.js-only, so this needs no simulated dropped connection.
  - sw.js's own precache list only names static assets that actually
    exist under src/static, /offline, and /manifest.webmanifest --
    confirmed at the source level since nothing else can run the service
    worker. This automatically covers slice 4's own new scripts (offline_
    db.js/offline_sync_client.js/offline_shell.js) once they're added to
    that list, with no test change needed for them specifically.
  - main.py actually registers pwa.router (routers/settings.py's own
    2026-08-14 follow-up note describes a router losing its decorator
    silently while every existing test still passed -- confirmed here via
    `router.routes` directly, the same fix applied there, not just by
    hitting the routes through router-function calls).
  - offline_db.js/offline_sync_client.js/offline_shell.js are structurally
    sound (define the expected object stores/exports/handlers) and are
    actually wired into base.html/offline.html -- the same "read the JS
    source, assert the shape" level of confidence as the sw.js checks
    above, not a claim that the logic runs correctly in a real browser."""

from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.requests import Request

from src.main import app as fastapi_app
from src.routers import pwa as pwa_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


def _request(path="/offline"):
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


class TestManifest:
    def test_manifest_is_valid_and_installable(self):
        manifest = json.loads((_STATIC_DIR / "manifest.webmanifest").read_text())
        assert manifest["name"]
        assert manifest["short_name"]
        assert manifest["start_url"] == "/"
        assert manifest["display"] == "standalone"
        assert len(manifest["icons"]) >= 2
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        assert "192x192" in sizes
        assert "512x512" in sizes

    def test_every_manifest_icon_exists_on_disk(self):
        manifest = json.loads((_STATIC_DIR / "manifest.webmanifest").read_text())
        for icon in manifest["icons"]:
            assert icon["src"].startswith("/static/")
            rel = icon["src"][len("/static/"):]
            assert (_STATIC_DIR / rel).exists(), icon["src"]

    def test_base_html_links_the_manifest_and_theme_color(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert 'rel="manifest"' in html
        assert "manifest.webmanifest" in html
        assert 'name="theme-color"' in html
        assert "pwa.js" in html


class TestServiceWorker:
    def test_sw_js_route_serves_the_real_script(self):
        response = pwa_router.service_worker()
        assert response.media_type == "application/javascript"
        assert response.headers["cache-control"] == "no-store"
        assert Path(response.path) == _STATIC_DIR / "sw.js"

    def test_sw_js_registers_install_activate_fetch_handlers(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert 'addEventListener("install"' in script
        assert 'addEventListener("activate"' in script
        assert 'addEventListener("fetch"' in script
        assert "skipWaiting" in script
        assert "clients.claim" in script

    def test_precache_list_only_names_assets_that_exist(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        match = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\];", script, re.S)
        assert match, "couldn't find SHELL_ASSETS in sw.js"
        urls = re.findall(r'"(/[^"]+)"', match.group(1))
        assert urls, "SHELL_ASSETS parsed empty"
        for url in urls:
            if url == "/offline" or url == "/manifest.webmanifest":
                continue
            assert url.startswith("/static/"), url
            rel = url[len("/static/"):]
            assert (_STATIC_DIR / rel).exists(), url
        assert "/offline" in urls

    def test_pwa_js_registers_the_root_scoped_script(self):
        script = (_STATIC_DIR / "pwa.js").read_text()
        assert 'serviceWorker.register("/sw.js")' in script


class TestOfflineShell:
    def test_offline_page_renders_full_chrome_and_offline_message(self):
        body = pwa_router.offline_shell(_request("/offline")).body.decode()
        assert '<nav class="tabbar"' in body
        assert "offline" in body.lower()
        assert "You&#39;re offline" in body or "You're offline" in body

    def test_offline_page_reachable_without_simulating_a_dropped_connection(self):
        # A plain route, not sw.js-only -- confirms the page itself needs
        # no DB/network dependency to render (no `conn` in the handler's
        # signature at all).
        import inspect

        params = inspect.signature(pwa_router.offline_shell).parameters
        assert "conn" not in params


class TestLocalReadPath:
    def test_offline_db_defines_the_expected_stores_and_exports(self):
        script = (_STATIC_DIR / "offline_db.js").read_text()
        for store in ('"tasks"', '"events"', '"contacts"', '"field_hlc"', '"meta"'):
            assert store in script
        for export in (
            "getDeviceId",
            "getCursor",
            "setCursor",
            "getLastSyncedAt",
            "setLastSyncedAt",
            "applyChanges",
            "getAllTasks",
            "getAllEvents",
            "getAllContacts",
        ):
            assert export in script
        assert "window.CCOfflineDB" in script
        # §6's per-field HLC compare must exist, not just a blind
        # overwrite -- the whole reason field_hlc is a separate store.
        assert "isNewer" in script

    def test_offline_sync_client_pulls_and_never_pushes(self):
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "/api/sync/pull" in script
        # Slice 5 adds the outbox/push path -- this slice must not call
        # push at all yet, since there is nothing of this device's own to
        # send (no local writes exist).
        assert "/api/sync/push" not in script
        assert "full_resync" in script
        assert "window.CCOfflineSync" in script

    def test_offline_shell_reads_from_the_mirror_not_the_network(self):
        script = (_STATIC_DIR / "offline_shell.js").read_text()
        assert "CCOfflineDB.getAllTasks" in script
        assert "CCOfflineDB.getAllEvents" in script
        assert "fetch(" not in script

    def test_base_html_loads_the_mirror_and_pull_loop_globally(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert "offline_db.js" in html
        assert "offline_sync_client.js" in html
        # offline_shell.js is /offline-specific, not a global page load --
        # it belongs in offline.html's own extra_scripts block, not here.
        assert "offline_shell.js" not in html

    def test_offline_html_has_the_render_target_and_loads_the_shell_script(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        assert 'id="offline-local-data"' in html
        assert "offline_shell.js" in html

    def test_precache_list_includes_the_local_read_path_scripts(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        for asset in ("/static/offline_db.js", "/static/offline_sync_client.js", "/static/offline_shell.js"):
            assert asset in script


class TestLocalWritePath:
    """1.8 slice 5 -- "Local write path + outbox" (open-priority.md §11
    slice 5). Same "read the JS source, assert the shape" level of
    confidence as TestLocalReadPath above -- no real browser/IndexedDB
    here. The actual outbox/HLC merge logic is exercised end-to-end by a
    one-off Node + fake-indexeddb smoke script (not part of this suite,
    same as slice 4's own smoke run) that caught a real ordering bug during
    development: getOutboxOps() must sort explicitly (by each op's own
    HLC), since IndexedDB's default key-order iteration over a random-UUID
    keyPath is not insertion order."""

    def test_offline_db_gained_the_hlc_clock_and_outbox(self):
        script = (_STATIC_DIR / "offline_db.js").read_text()
        assert '"outbox"' in script
        for export in ("nextHlc", "mergeHlc", "enqueueOp", "getOutboxOps", "getOutboxCount"):
            assert export in script

    def test_offline_write_defines_create_edit_delete_for_tasks(self):
        script = (_STATIC_DIR / "offline_write.js").read_text()
        for export in ("createTask", "updateTaskField", "deleteTask"):
            assert export in script
        assert "window.CCOfflineWrite" in script
        # Every op this file builds must go through the outbox, not just
        # straight to the mirror -- that's the whole point of the slice
        # ("queue as ops instead of failing," not "write straight through").
        assert "enqueueOp" in script
        # Still no network call anywhere in the write path itself (push is
        # slice 6) -- a local write must succeed with zero connectivity.
        assert "fetch(" not in script

    def test_offline_write_never_pushes(self):
        script = (_STATIC_DIR / "offline_write.js").read_text()
        assert "/api/sync/push" not in script

    def test_offline_shell_wires_up_the_write_ui(self):
        script = (_STATIC_DIR / "offline_shell.js").read_text()
        assert "CCOfflineWrite.createTask" in script
        assert "CCOfflineWrite.updateTaskField" in script
        assert "CCOfflineWrite.deleteTask" in script

    def test_offline_html_loads_the_write_script(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        assert "offline_write.js" in html
        assert "offline_shell.js" in html

    def test_base_html_does_not_load_the_write_script_globally(self):
        # offline_write.js's UI hooks (the add-task form, per-row buttons)
        # only exist on /offline's own markup -- loading it globally would
        # be dead weight on every other page, unlike offline_db.js/
        # offline_sync_client.js which genuinely need to run everywhere to
        # keep the mirror warm.
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert "offline_write.js" not in html

    def test_precache_list_includes_the_write_path_script(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert "/static/offline_write.js" in script

    def test_shell_cache_name_was_bumped_for_the_new_precached_script(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert 'CACHE_NAME = "cc-shell-v3"' in script


class TestRouterWiring:
    def test_pwa_router_is_registered_on_the_real_app(self):
        # This FastAPI version wraps each include_router() call as an
        # opaque `_IncludedRouter` rather than flattening its routes onto
        # `app.routes` directly (unlike the plain `Route`/`Mount` entries
        # also in that list) -- `original_router.routes` is where each
        # wrapped router's own paths actually live. Recursing rather than
        # hand-picking pwa.router specifically also means this test would
        # catch the same "route silently missing its decorator" class of
        # bug settings.py hit in the 2026-08-14 label-icons incident (see
        # routers/settings.py's own docstring note), for any router.
        def _all_paths(routes):
            paths = set()
            for route in routes:
                path = getattr(route, "path", None)
                if path is not None:
                    paths.add(path)
                nested = getattr(route, "original_router", None)
                if nested is not None:
                    paths |= _all_paths(nested.routes)
            return paths

        paths = _all_paths(fastapi_app.routes)
        assert "/sw.js" in paths
        assert "/offline" in paths
