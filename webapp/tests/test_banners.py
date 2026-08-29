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

from src import db, deps
from src.routers import banners as banners_router
from src.routers import dashboard as dashboard_router
from src.routers import labels as labels_router
from src.routers import spaces as spaces_router


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


class TestPageBannerAvatar:
    """2026-08-29 (sidebar redesign follow-up, direct request,
    plans/sidebar-redesign.md § "The Standard Header") -- "Dashboard
    Header (Expanded)... large, circular avatar overlapping the bottom
    left of the banner." _page_banner.html renders it (avatar-hero,
    inside .page-banner-avatar-wrap) whenever a banner is set, reusing
    the same profile-photo feature Settings > General's own avatar row
    already has -- no new storage. Covers Home, a Project page
    (labels_router.label_detail), and a Space page (spaces_router.
    space_detail) -- all three are "dashboard type" pages sharing
    _page_banner.html."""

    def test_no_avatar_wrap_without_a_banner(self, conn):
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        assert "page-banner-avatar-wrap" not in body

    def test_home_shows_avatar_initial_fallback_with_a_banner(self, conn):
        _set_remote(conn, cached=True, scope="")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        assert 'class="page-banner-avatar-wrap"' in body
        # No display name/photo set -- falls back to the "U" initial, same
        # convention as settings_general.html's own avatar row.
        assert '<span class="avatar-circle avatar-hero">U</span>' in body

    def test_home_avatar_uses_display_name_initial(self, conn):
        db.set_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY, "Petru")
        _set_remote(conn, cached=True, scope="")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        assert '<span class="avatar-circle avatar-hero">P</span>' in body

    def test_home_avatar_renders_uploaded_photo(self, conn):
        db.set_profile_photo(conn, base64.b64encode(b"photo-bytes").decode("ascii"), "png")
        _set_remote(conn, cached=True, scope="")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        assert 'class="avatar-circle avatar-hero"' in body
        assert "data:image/png;base64," in body

    def test_project_page_shows_avatar_with_a_banner(self, conn):
        _make_label(conn, "CS101")
        _set_remote(conn, cached=True, scope="CS101")
        body = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn).body.decode()
        assert 'class="page-banner-avatar-wrap"' in body

    def test_project_page_has_no_avatar_wrap_without_a_banner(self, conn):
        _make_label(conn, "CS101")
        body = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn).body.decode()
        assert "page-banner-avatar-wrap" not in body

    def test_space_page_shows_avatar_with_a_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Work", "generate_space": 1, "created_at": _now()})
        _set_remote(conn, cached=True, scope="Work")
        body = spaces_router.space_detail("Work", _request("/spaces/Work"), conn=conn).body.decode()
        assert 'class="page-banner-avatar-wrap"' in body


class TestPageBannerDefaultFallback:
    """2026-08-29 (direct request): Home/Project/Space pages with no
    banner of their own now fall back to the single default set in
    Settings > Appearance (deps.PAGE_HEADER_BANNER_SCOPE) instead of
    showing no banner at all -- routers/dashboard.py's
    _page_banner_context. A page's own banner (set via its own
    "Add/Change banner" edit-mode button) still overrides the default
    when present."""

    def test_home_falls_back_to_the_default_banner(self, conn):
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        resp = dashboard_router.dashboard_view(_request("/"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/default.jpg"
        assert resp.context["has_own_banner"] is False
        body = resp.body.decode()
        assert "/banners/image?scope=__page_header__" in body

    def test_home_own_banner_overrides_the_default(self, conn):
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        _set_remote(conn, cached=True, scope="", image_url="https://cdn.example.com/home-own.jpg")
        resp = dashboard_router.dashboard_view(_request("/"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/home-own.jpg"
        assert resp.context["has_own_banner"] is True
        body = resp.body.decode()
        # scope="" -> the querystring param is simply absent, not empty --
        # urlencode('') renders nothing after "scope=".
        assert "/banners/image?scope=&amp;v=" in body

    def test_home_no_default_no_own_banner_means_no_banner_at_all(self, conn):
        resp = dashboard_router.dashboard_view(_request("/"), conn=conn)
        assert resp.context["banner"] is None
        assert resp.context["has_own_banner"] is False
        assert 'class="page-banner"' not in resp.body.decode()

    def test_home_edit_mode_button_says_add_banner_while_only_default_shows(self, conn):
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE)
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        link_start = body.index("/banners/editor?scope=&")
        link_end = body.index("</a>", link_start)
        link = body[link_start:link_end]
        assert "Add banner" in link
        assert "Change banner" not in link

    def test_home_edit_mode_button_says_change_banner_once_home_has_its_own(self, conn):
        _set_remote(conn, cached=True, scope="")
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        link_start = body.index("/banners/editor?scope=&")
        link_end = body.index("</a>", link_start)
        link = body[link_start:link_end]
        assert "Change banner" in link

    def test_project_page_falls_back_to_the_default_banner(self, conn):
        _make_label(conn, "CS101")
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/default.jpg"
        assert resp.context["has_own_banner"] is False

    def test_project_page_own_banner_overrides_the_default(self, conn):
        _make_label(conn, "CS101")
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        _set_remote(conn, cached=True, scope="CS101", image_url="https://cdn.example.com/cs101-own.jpg")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/cs101-own.jpg"
        assert resp.context["has_own_banner"] is True

    def test_space_page_falls_back_to_the_default_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Work", "generate_space": 1, "created_at": _now()})
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        resp = spaces_router.space_detail("Work", _request("/spaces/Work"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/default.jpg"
        assert resp.context["has_own_banner"] is False

    def test_removing_a_page_own_banner_reverts_to_the_default(self, conn):
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        _set_remote(conn, cached=True, scope="", image_url="https://cdn.example.com/home-own.jpg")
        banners_router.remove_banner(scope="", page_url="/", conn=conn)
        resp = dashboard_router.dashboard_view(_request("/"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/default.jpg"
        assert resp.context["has_own_banner"] is False
