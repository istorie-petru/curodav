"""Embedded WebDAV server (REWORK_PLAN §5).

Serves `~/CommandCenter/` via wsgidav on `localhost:8080`. Controllable from
Settings (on/off, port, LAN-only toggle). Runs in a background thread.

Fixed 2026-07-18 (see `features/sync-and-webdav.md`): this previously could
not start at all. Two separate bugs, both confirmed with a live smoke test
(constructed a `WsgiDAVApp`, served it, made a real HTTP GET against a temp
file, got 200 + body back):

1. The config passed `"middleware_stack": None`, which wsgidav's own init
   iterates/reverses -- `None` blows that up with
   `TypeError: 'NoneType' object is not reversible`. wsgidav already has a
   sensible default middleware stack; the fix is to not override it at all.
2. `WsgiDAVApp` is a plain WSGI *application* (a callable), not a server --
   it has no `serve_forever()`. The original `_serve()` called it anyway,
   which would have raised `AttributeError` the moment `middleware_stack`
   was fixed and the thread actually ran. `WsgiDAVApp` needs to be handed
   to an actual WSGI server; this uses the stdlib
   `wsgiref.simple_server.make_server` so no extra dependency (e.g.
   cheroot) is required.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

from wsgidav.wsgidav_app import WsgiDAVApp

logger = logging.getLogger(__name__)


class WebDavServer:
    """Manages the embedded WebDAV server lifecycle in a background thread."""

    def __init__(self, base_path: Path | None = None, port: int = 8080) -> None:
        self._base_path = base_path or Path.home() / "CommandCenter"
        self._port = port
        self._lan_mode = False
        self._app: WsgiDAVApp | None = None
        self._httpd: WSGIServer | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    @port.setter
    def port(self, value: int) -> None:
        self._port = value

    @property
    def lan_mode(self) -> bool:
        return self._lan_mode

    @lan_mode.setter
    def lan_mode(self, value: bool) -> None:
        self._lan_mode = value

    @property
    def connection_url(self) -> str:
        host = "0.0.0.0" if self._lan_mode else "127.0.0.1"
        return f"http://{host}:{self._port}/"

    def start(self) -> None:
        if self._running:
            logger.warning("WebDAV already running")
            return

        host = "0.0.0.0" if self._lan_mode else "127.0.0.1"
        config = {
            "host": host,
            "port": self._port,
            "provider_mapping": {"/": str(self._base_path)},
            "simple_dc": {"user_mapping": {"*": True}},
            "verbose": 0,
        }

        self._app = WsgiDAVApp(config)
        try:
            self._httpd = make_server(host, self._port, self._app)
        except OSError as exc:
            logger.error("WebDAV failed to bind %s:%d -- %s", host, self._port, exc)
            self._app = None
            raise

        self._running = True
        self._thread = threading.Thread(
            target=self._serve,
            daemon=True,
            name="webdav",
        )
        self._thread.start()
        logger.info("WebDAV started on %s:%d", host, self._port)

    def stop(self) -> None:
        self._running = False
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
        self._httpd = None
        self._app = None
        self._thread = None
        logger.info("WebDAV stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    def _serve(self) -> None:
        try:
            self._httpd.serve_forever()
        except Exception as exc:
            logger.error("WebDAV server error: %s", exc)
            self._running = False
