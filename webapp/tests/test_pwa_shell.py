"""The PWA shell: install manifest, service worker route and router wiring.

The service worker itself cannot run under pytest; this checks what the
server can vouch for: the manifest is installable, its icons and the
precache list point at files that exist, and /sw.js is served as a script."""

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


class TestServiceWorker:
    def test_sw_js_route_serves_the_real_script(self):
        response = pwa_router.service_worker()
        assert response.media_type == "application/javascript"
        assert response.headers["cache-control"] == "no-store"
        assert Path(response.path) == _STATIC_DIR / "sw.js"


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
