"""The PWA shell: service worker route and router wiring. The manifest and
precache integrity checks are core tests (core/test_app_assets.py)."""

from __future__ import annotations

from pathlib import Path

from src.main import app as fastapi_app
from src.routers import pwa as pwa_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


class TestServiceWorker:
    def test_sw_js_route_serves_the_real_script(self):
        response = pwa_router.service_worker()
        assert response.media_type == "application/javascript"
        assert response.headers["cache-control"] == "no-store"
        assert Path(response.path) == _STATIC_DIR / "sw.js"


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
