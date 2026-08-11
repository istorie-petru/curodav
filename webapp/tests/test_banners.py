"""Banner routes (routers/banners.py, 2026-08-09 onward).

Covers image serving (/banners/image) and the partial rendering paths for
uploaded banners and for legacy remote banners (set while the SearXNG
web-search feature existed). 2026-08-11: the search picker and its
/banners/set route were removed -- upload is the only way to set a new
banner -- but stored remote banners keep rendering, so those paths stay
covered."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from starlette.requests import Request

from src import db
from src.routers import banners as banners_router
from src.routers import labels as labels_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


def _make_label(conn, name):
    db.upsert_label_config(conn, {"name": name, "color": "blue", "created_at": _now()})


def _set_remote(
    conn, *, cached=False, scope="", image_url="https://cdn.example.com/pic.jpg"
):
    """Store a remote banner directly (bypassing the network fetch) so the
    image-serving/template tests can build the exact state they need."""
    banner = {"kind": "remote", "image_url": image_url}
    if cached:
        data = b"cached-banner-bytes"
        banner.update(
            {
                "image_b64": base64.b64encode(data).decode("ascii"),
                "image_type": "jpeg",
                "version": hashlib.md5(data).hexdigest()[:12],
            }
        )
    db.set_page_banner(conn, scope, banner)
    return banner


class TestBannerImageServesCachedBytes:
    """/banners/image serves the locally-stored bytes for any banner that
    has them -- uploaded, or a legacy remote banner that was downloaded and
    cached at set time -- with the immutable cache header. Hotlink-only
    legacy remote banners 404 here; they were never meant to hit this
    route."""

    def test_serves_cached_remote_bytes(self, conn):
        _set_remote(conn, cached=True)
        resp = banners_router.banner_image(scope="", conn=conn)
        assert isinstance(resp, Response)
        assert resp.body == b"cached-banner-bytes"
        assert resp.media_type == "image/jpeg"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_serves_uploaded_bytes(self, conn):
        db.set_page_banner(
            conn,
            "",
            {
                "kind": "upload",
                "image_b64": base64.b64encode(b"uploaded").decode("ascii"),
                "image_type": "png",
                "version": "abc",
            },
        )
        resp = banners_router.banner_image(scope="", conn=conn)
        assert resp.body == b"uploaded"
        assert resp.media_type == "image/png"

    def test_404_for_hotlink_only_remote(self, conn):
        _set_remote(conn, cached=False)
        with pytest.raises(HTTPException) as excinfo:
            banners_router.banner_image(scope="", conn=conn)
        assert excinfo.value.status_code == 404

    def test_404_when_no_banner(self, conn):
        with pytest.raises(HTTPException) as excinfo:
            banners_router.banner_image(scope="", conn=conn)
        assert excinfo.value.status_code == 404


class TestBannerPartialRendering:
    """_page_banner.html / banner_editor.html render a banner with a
    version through /banners/image and only hotlink legacy no-version
    remote banners."""

    def test_cached_remote_renders_served_url(self, conn):
        _make_label(conn, "CS101")
        _set_remote(conn, cached=True, scope="CS101")
        body = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn).body.decode()
        assert "/banners/image?scope=CS101" in body
        assert "cdn.example.com" not in body

    def test_legacy_hotlink_remote_keeps_image_url(self, conn):
        _make_label(conn, "CS101")
        _set_remote(conn, cached=False, scope="CS101")
        body = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn).body.decode()
        assert "https://cdn.example.com/pic.jpg" in body
        assert "/banners/image?scope=CS101" not in body

    def test_editor_preview_uses_served_url_for_cached_remote(self, conn):
        _set_remote(conn, cached=True)
        body = banners_router.banner_editor(_request("/banners/editor"), conn=conn).body.decode()
        assert "/banners/image?scope=" in body
        assert "cdn.example.com" not in body
