"""1.8 slice 3 -- the PWA shell (plans/open-priority.md § Offline-first
editing & synchronization §11 slice 3): manifest, service worker, offline
app-shell caching -- "can the app open at all with no network."

2026-09-09: everything past slice 3 -- the client-side local read path
(slice 4: static/offline_db.js, offline_sync_client.js), the local write
path (slice 5: offline_write.js), the sync engine's client half (slice 6:
offline_sync_client.js's push/retry, offline_status.js's indicator), the
`/offline` page and its Quick Add builder (offline_shell.js,
offline_quick_capture.js, templates/offline.html, _offline_quick_add.html)
-- was purged outright, direct request ("let's just remove offline mode...
purge it"), after two earlier rounds of direct UI complaints against
screenshots concluded the whole surface wasn't worth salvaging. All eight
`static/offline_*.js` files and both templates are deleted; the `/offline`
route is gone from routers/pwa.py; sw.js's precache list and offline
navigation fallback are gone too. See routers/pwa.py's and sw.js's own
header comments for the full removal note.

Explicitly out of scope for that purge, and unaffected here: the
server-side sync engine (src/offline_sync.py, routers/sync_api.py, the
Sync card + cleanup controls on Settings > Data & Maintenance) -- covered
by test_offline_sync.py and test_data_health.py respectively, neither of
which depended on the client-side files/route that are now gone.

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
  - sw.js's own precache list only names static assets that actually
    exist under src/static and /manifest.webmanifest -- confirmed at the
    source level since nothing else can run the service worker.
  - main.py actually registers pwa.router (routers/settings.py's own
    2026-08-14 follow-up note describes a router losing its decorator
    silently while every existing test still passed -- confirmed here via
    `router.routes` directly, the same fix applied there, not just by
    hitting the routes through router-function calls)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.main import app as fastapi_app
from src.routers import pwa as pwa_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


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
            if url == "/manifest.webmanifest":
                continue
            assert url.startswith("/static/"), url
            rel = url[len("/static/"):]
            assert (_STATIC_DIR / rel).exists(), url

    def test_precache_list_has_no_offline_mode_leftovers(self):
        # 2026-09-09: the purge dropped /offline itself (the route is gone)
        # and every static/offline_*.js entry (the files are gone) from
        # this list -- locking that in so a future edit can't silently
        # reintroduce a reference to a route/file that no longer exists.
        script = (_STATIC_DIR / "sw.js").read_text()
        match = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\];", script, re.S)
        assert "/offline" not in match.group(1)
        assert "offline_" not in match.group(1)

    def test_navigate_fallback_no_longer_serves_a_cached_offline_page(self):
        # The service worker's navigation handler used to fall back to a
        # cached copy of /offline on a failed fetch; that page is gone, so
        # a failed navigation now just fails, same as with no service
        # worker installed at all.
        script = (_STATIC_DIR / "sw.js").read_text()
        assert 'caches.match("/offline")' not in script

    def test_pwa_js_registers_the_root_scoped_script(self):
        script = (_STATIC_DIR / "pwa.js").read_text()
        assert 'serviceWorker.register("/sw.js")' in script


class TestOfflineModeFullyRemoved:
    """2026-09-09 direct request: "let's just remove offline mode. purge
    it." Locks in that every client-side piece is actually gone, not just
    disconnected -- files deleted from disk, the route gone, nothing left
    loading them. The server-side sync engine (src/offline_sync.py,
    routers/sync_api.py, Settings' Sync card) was explicitly out of scope
    and is untouched -- see test_offline_sync.py and test_data_health.py."""

    _DELETED_STATIC_FILES = (
        "offline_shell.js",
        "offline_db.js",
        "offline_sync_client.js",
        "offline_write.js",
        "offline_status.js",
        "offline_quick_capture.js",
    )
    _DELETED_TEMPLATES = ("offline.html", "_offline_quick_add.html")

    def test_offline_static_files_are_gone(self):
        for name in self._DELETED_STATIC_FILES:
            assert not (_STATIC_DIR / name).exists(), name

    def test_offline_templates_are_gone(self):
        templates_dir = Path(__file__).resolve().parent.parent / "src" / "templates"
        for name in self._DELETED_TEMPLATES:
            assert not (templates_dir / name).exists(), name

    def test_offline_route_is_gone(self):
        assert not hasattr(pwa_router, "offline_shell")
        paths = {getattr(route, "path", None) for route in pwa_router.router.routes}
        assert "/offline" not in paths
        # /sw.js and /favicon.ico are unrelated to the offline feature and
        # must still be there.
        assert "/sw.js" in paths
        assert "/favicon.ico" in paths

    def test_base_html_no_longer_references_any_deleted_offline_script(self):
        # Checks for the real `static_url('name')` call a <script> tag would
        # use, not a bare filename substring -- base.html's own header
        # comment mentions several of these filenames in prose, explaining
        # the removal, which isn't a real reference to a live script tag.
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        for name in self._DELETED_STATIC_FILES:
            assert f"static_url('{name}')" not in html, name


class TestRouterWiring:
    def test_pwa_router_is_registered_on_the_real_app(self):
        # routers/settings.py's own 2026-08-14 follow-up note describes a
        # router losing its decorator silently while every existing test
        # still passed -- checked here via `router.routes` directly, not
        # just by calling the route functions in isolation.
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
        assert "/favicon.ico" in paths
        # 2026-09-09 purge: this route is gone along with the rest of the
        # client-side offline feature.
        assert "/offline" not in paths


class TestShellCacheVersion:
    def test_shell_cache_name_was_bumped_for_the_offline_mode_purge(self):
        # v79/v80 (2026-09-09): two rounds of Offline Mode UI fixes against
        # direct screenshot reports (collapsing the five-tab page to a
        # single Quick Add screen, then fixing header/card/button/Labels
        # issues on that collapsed screen) -- see plans/STATE.md for the
        # full history of both.
        # v81 (2026-09-09): the whole client-side Offline Mode feature
        # those two passes were polishing is gone -- direct request
        # ("let's just remove offline mode. purge it."). /offline and
        # every static/offline_*.js entry dropped from SHELL_ASSETS (the
        # route and files no longer exist), and the navigate handler's
        # fallback to a cached /offline copy removed. Same pass: the Sync
        # card's "Force sync" button (Settings > Data & Maintenance) only
        # worked via window.CCOfflineSync, now permanently undefined --
        # removed outright (data_maintenance.js, settings_data_maintenance.
        # html) rather than left as a guaranteed-broken control.
        # v82 (2026-09-08): FullCalendar-parity interactions slice 1 --
        # Month/4-Week spanning-bar layout (style.css's .month-week-bars/
        # .month-bar-*/.month-bars-offset-* rules, calendar_month_drag.js's
        # updated header comment on the temporary all-day-drag regression
        # that slice introduces).
        # v83 (2026-09-08): slice 2 -- drag-move + edge-resize for those
        # bars, plus the pointer-follow drag ghost (calendar_month_drag.js's
        # new setupBar/postReschedule, style.css's .month-bar-label/
        # -resize-handle/-ghost rules).
        # v84 (2026-09-08, this entry, same-day bug fix): direct report that
        # bar resize was unreliable -- `cellAtPoint` rewritten from an
        # `elementsFromPoint` DOM hit-test to plain rectangle-containment
        # against the day cells' own bounding rects.
        # v86 (2026-09-09, FullCalendar-parity slice 4): Week view drag
        # between the "All day" row and the timed grid, both directions
        # (calendar.js gained a drop-onto-.allday-col branch, calendar_
        # week_allday_drag.js gained a drop-onto-.time-col branch).
        # v87 (2026-09-09, FullCalendar-parity slice 5): Week view no longer
        # resets scroll position on an async refresh (async_calendar.js's
        # refreshWeek() captures/restores .time-grid-wrap's scrollTop around
        # the #week-grid node swap).
        # v88 (2026-09-09, FullCalendar-parity slice 6): 4-Week/Week prev/
        # next navigate via AJAX (async_calendar.js's bindCalNav) with a
        # live date-range label instead of a full page reload.
        # v89 (same-day bug fix, round 2): month-bar resize handle hit-area
        # widened, drop-hover ring strengthened, resize-guard rejections now
        # toast instead of silently no-op'ing (calendar_month_drag.js,
        # style.css).
        script = (_STATIC_DIR / "sw.js").read_text()
        assert 'CACHE_NAME = "cc-shell-v89"' in script
