"""1.8 slice 3 -- PWA shell (plans/open-priority.md § Offline-first editing
& synchronization §11 slice 3): manifest, service worker, offline app-shell
caching. No sync, no IndexedDB, no local read/write path yet (those are
slices 4-6) -- this slice is purely "can the app open at all with no
network."

A real service worker can't be exercised by this app's usual pytest/
router-function-call convention (there's no browser here to install it,
intercept fetches, or read from the Cache Storage API) -- that part needs
manual/browser verification, per plans/STATE.md's own note on this slice.
What *is* verifiable server-side, and covered here:

  - manifest.webmanifest is valid, has the fields a browser's install
    prompt needs, and every icon it references actually exists on disk.
  - GET /sw.js serves static/sw.js's own content as a real script (not a
    404/redirect), with a JS content-type and no-store caching so browsers
    always refetch the script itself to notice an update.
  - GET /offline renders the normal page chrome (tabbar, nav) plus an
    honest "you're offline" message -- reachable normally online, not
    sw.js-only, so this needs no simulated dropped connection.
  - sw.js's own precache list only names static assets that actually
    exist under src/static, and /offline -- confirmed at the source level
    since nothing else can run the service worker.
  - main.py actually registers pwa.router (routers/settings.py's own
    2026-08-14 follow-up note describes a router losing its decorator
    silently while every existing test still passed -- confirmed here via
    `router.routes` directly, the same fix applied there, not just by
    hitting the routes through router-function calls)."""

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
