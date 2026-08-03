"""WebDAV server tests.

Added 2026-07-18 alongside the fix for the two bugs documented in
`core/dav/server.py` and `features/sync-and-webdav.md`: no automated test
existed for this at all before (the break was only caught by manual/ad-hoc
smoke testing, see STRESS_TEST_2026-07-17.md). This exercises the real
`WebDavServer` -- construct it against a temp directory, start it, make an
actual HTTP request, confirm the response, then stop it -- not mocks.
"""

import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

_src_root = Path(__file__).resolve().parent.parent
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

import pytest

from src.core.dav.server import WebDavServer


def _free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestWebDavServer:
    def test_starts_without_raising(self, tmp_path):
        """The original bug: start() raised TypeError from wsgidav's own
        init before the thread ever ran (middleware_stack: None)."""
        srv = WebDavServer(base_path=tmp_path, port=_free_port())
        srv.start()
        try:
            assert srv.is_running
        finally:
            srv.stop()

    def test_serves_real_file_over_http(self, tmp_path):
        """End-to-end: write a file, start the server, GET it back."""
        (tmp_path / "hello.txt").write_text("fixed webdav")
        port = _free_port()
        srv = WebDavServer(base_path=tmp_path, port=port)
        srv.start()
        try:
            # Give the background thread a moment to bind and start
            # accepting connections.
            deadline = time.time() + 3
            last_error = None
            while time.time() < deadline:
                try:
                    resp = urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/hello.txt", timeout=1
                    )
                    assert resp.status == 200
                    assert resp.read() == b"fixed webdav"
                    break
                except (urllib.error.URLError, ConnectionError) as exc:
                    last_error = exc
                    time.sleep(0.1)
            else:
                pytest.fail(f"WebDAV server never became reachable: {last_error}")
        finally:
            srv.stop()

    def test_stop_actually_stops(self, tmp_path):
        port = _free_port()
        srv = WebDavServer(base_path=tmp_path, port=port)
        srv.start()
        time.sleep(0.2)
        assert srv.is_running
        srv.stop()
        assert not srv.is_running

    def test_connection_url_reflects_lan_mode(self, tmp_path):
        srv = WebDavServer(base_path=tmp_path, port=9999)
        assert srv.connection_url == "http://127.0.0.1:9999/"
        srv.lan_mode = True
        assert srv.connection_url == "http://0.0.0.0:9999/"
