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
import io
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from starlette.requests import Request

from src import db, deps
from src.routers import banners as banners_router
from src.routers import calendar as calendar_router
from src.routers import contacts as contacts_router
from src.routers import dashboard as dashboard_router
from src.routers import labels as labels_router
from src.routers import projects as projects_router
from src.routers import spaces as spaces_router
from src.routers import tasks as tasks_router


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


class _FakeUploadFile:
    """Duck-types the bits of fastapi.UploadFile routers/banners.py's
    upload_banner actually touches (`.filename`, `.content_type`,
    `.file.read()`) -- calling the route function directly (not through a
    real TestClient/multipart request) needs something UploadFile-shaped,
    not a real UploadFile (which wants an ASGI request to build)."""

    def __init__(self, data: bytes, content_type: str, filename: str = "x.jpg"):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(data)


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


class TestBannerUploadUsesCropEditor:
    """2026-08-29 (direct request: "add the ability to crop, move, aspect
    ratio modal window after all image uploads") -- the banner upload
    input now wires into the same interactive crop editor
    (static/avatar_cropper.js) contact photos/the profile picture already
    had, instead of the old silent-resize CCBannerUpload.onFile (removed
    from app.js entirely)."""

    def test_upload_input_carries_the_cropper_class(self, conn):
        body = banners_router.banner_editor(_request("/banners/editor"), conn=conn).body.decode()
        assert 'class="banner-upload-input"' in body

    def test_upload_input_no_longer_has_the_old_inline_onchange(self, conn):
        # Checked against the exact removed attribute, not a bare
        # substring -- this template's own comment legitimately mentions
        # CCBannerUpload.onFile in prose while explaining the removal.
        body = banners_router.banner_editor(_request("/banners/editor"), conn=conn).body.decode()
        assert 'onchange="window.CCBannerUpload' not in body
        assert '<input type="file" name="banner_file" accept="image/jpeg,image/png,image/gif,image/webp" class="banner-upload-input" aria-label="Choose a banner image to upload">' in body


class TestBannerUploadImageSniffing:
    """2026-09-07 fix (flagged in an earlier audit): upload_banner used to
    trust the browser-supplied Content-Type header alone -- an
    unauthenticated POST (this app has no auth) could claim "image/jpeg"
    for any bytes at all. Now the actual bytes are sniffed
    (src/image_sniff.py) and must match a real image signature."""

    def test_rejects_bytes_that_dont_match_any_real_image_signature(self, conn):
        fake = _FakeUploadFile(b"not-an-image-at-all", "image/jpeg")
        with pytest.raises(HTTPException) as excinfo:
            banners_router.upload_banner(scope="", page_url="", banner_file=fake, conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_page_banner(conn, "") is None

    def test_accepts_real_jpeg_magic_bytes(self, conn):
        data = b"\xff\xd8\xff\xe0" + b"rest-of-a-jpeg"
        fake = _FakeUploadFile(data, "image/jpeg")
        banners_router.upload_banner(scope="", page_url="", banner_file=fake, conn=conn)
        banner = db.get_page_banner(conn, "")
        assert banner["kind"] == "upload"
        assert banner["image_type"] == "jpeg"

    def test_stores_the_sniffed_type_even_when_the_header_claims_otherwise(self, conn):
        # Content-Type header says JPEG, bytes are really a PNG -- the
        # sniffed type wins, since the header is just an unverified claim.
        data = b"\x89PNG\r\n\x1a\n" + b"rest-of-a-png"
        fake = _FakeUploadFile(data, "image/jpeg")
        banners_router.upload_banner(scope="", page_url="", banner_file=fake, conn=conn)
        assert db.get_page_banner(conn, "")["image_type"] == "png"


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
        # 2026-08-29 (direct request: "better cache these images") -- the
        # avatar now renders via a real, cacheable /settings/profile-photo
        # /image?v=... URL (routers/settings.py's profile_photo_image),
        # not an inline data: URI -- see deps.py's avatar() own comment.
        db.set_profile_photo(conn, base64.b64encode(b"photo-bytes").decode("ascii"), "png")
        _set_remote(conn, cached=True, scope="")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        assert 'class="avatar-circle avatar-hero"' in body
        assert "data:image/png;base64," not in body
        assert '/settings/profile-photo/image?v=' in body

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


class TestPageBannerNotionStyleHeaderRow:
    """2026-09-07 rework (direct report: "the avatar and text for the big
    banner is a bit off... remake it Notion-like") -- the title used to be
    white overlay text pinned right next to the avatar on the cover photo
    itself; it now renders below the cover in a normal-colored
    `.page-banner-header-row`, and the edit-mode action buttons became a
    real child of `.page-banner` (floating over the photo) instead of a
    sibling anchored to the whole `.page-banner-wrap`. See
    _page_banner.html's `page_banner()` macro and style.css's own
    `.page-banner-header-row` comment for the full rationale."""

    def test_title_renders_inside_the_header_row_below_the_cover_not_on_it(self, conn):
        _set_remote(conn, cached=True, scope="")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        assert '<div class="page-banner-header-row">' in body
        # The header row (avatar + title) comes after .page-banner's own
        # closing tag, not nested inside it -- title is below the cover,
        # not overlaid on it.
        cover_end = body.index("</div>", body.index('class="page-banner"'))
        row_start = body.index('class="page-banner-header-row"')
        title_start = body.index('class="page-banner-title"')
        assert cover_end < row_start < title_start

    def test_avatar_still_comes_before_the_title_in_the_header_row(self, conn):
        _set_remote(conn, cached=True, scope="")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        avatar_start = body.index('class="page-banner-avatar-wrap"')
        title_start = body.index('class="page-banner-title"')
        assert avatar_start < title_start

    def test_edit_mode_actions_are_nested_inside_the_cover_not_the_header_row(self, conn):
        _set_remote(conn, cached=True, scope="")
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        body = dashboard_router.dashboard_view(_request("/"), conn=conn).body.decode()
        cover_start = body.index('class="page-banner"')
        cover_end = body.index("</div>", body.index('class="page-banner-actions"'))
        actions_start = body.index('class="page-banner-actions"')
        header_row_start = body.index('class="page-banner-header-row"')
        # Actions sit between the cover's own opening tag and the header
        # row that follows -- i.e. still inside .page-banner, not moved
        # down alongside the avatar/title.
        assert cover_start < actions_start < header_row_start

    def test_project_page_gets_the_same_header_row(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "start_date": "2026-01-01", "end_date": "2026-12-31", "created_at": _now()})
        _set_remote(conn, cached=True, scope=deps.PAGE_HEADER_BANNER_SCOPE)
        body = projects_router.project_detail("Garden", _request("/projects/Garden"), conn=conn).body.decode()
        assert '<div class="page-banner-header-row">' in body


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


class TestBannerForTask:
    """db.banner_for_task -- 2026-08-30 (direct request, tasks/kanban banner
    strip + task detail modal header): resolves which of a task's own
    label(s)/Project/Space banner wins, by priority. No new storage --
    every case below just sets the ordinary per-label banner
    (db.set_page_banner, the same one a label's own generated page shows)
    and checks banner_for_task picks the right one back up."""

    def test_no_banner_anywhere_resolves_to_none(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": [], "created_at": _now()})
        task = db.get_task(conn, "t1")
        assert db.banner_for_task(conn, task) is None

    def test_a_plain_labels_own_banner_wins(self, conn):
        _make_label(conn, "Client call")
        _set_remote(conn, cached=True, scope="Client call", image_url="https://cdn.example.com/label.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Client call"], "created_at": _now()})
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/label.jpg"

    def test_falls_back_to_the_project_labels_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "created_at": _now()})
        _set_remote(conn, cached=True, scope="Garden", image_url="https://cdn.example.com/project.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Garden"], "created_at": _now()})
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/project.jpg"

    def test_falls_back_to_the_projects_parent_space_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "parent_name": "Home", "created_at": _now()})
        _set_remote(conn, cached=True, scope="Home", image_url="https://cdn.example.com/space.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Garden"], "created_at": _now()})
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/space.jpg"

    def test_a_plain_label_banner_beats_the_project_and_space_banners(self, conn):
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "parent_name": "Home", "created_at": _now()})
        _make_label(conn, "Urgent")
        _set_remote(conn, cached=True, scope="Home", image_url="https://cdn.example.com/space.jpg")
        _set_remote(conn, cached=True, scope="Garden", image_url="https://cdn.example.com/project.jpg")
        _set_remote(conn, cached=True, scope="Urgent", image_url="https://cdn.example.com/label.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Garden", "Urgent"], "created_at": _now()})
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/label.jpg"

    def test_project_with_no_parent_space_and_no_own_banner_resolves_to_none(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Garden"], "created_at": _now()})
        task = db.get_task(conn, "t1")
        assert db.banner_for_task(conn, task) is None


class TestBannerSeasonAndDefaultFallback:
    """2026-09-07 (direct request: "all data (events and tasks) default to
    their season") -- a task/event with no matching label/Project/Space
    banner now falls back further than None: first to the seasonal banner
    matching its own due/start date (db.SEASON_BANNER_SCOPES,
    db.season_for_date), then to the single global default every page
    already uses (db.PAGE_HEADER_BANNER_SCOPE). Contacts are untouched --
    db._SEASON_DATE_FIELD has no "contact" entry, so
    test_contact_detail_falls_back_to_a_stable_color_when_no_banner above
    still passes unchanged."""

    def test_season_for_date_covers_all_twelve_months(self):
        assert db.season_for_date("2026-01-15") == "winter"
        assert db.season_for_date("2026-02-01") == "winter"
        assert db.season_for_date("2026-03-01") == "spring"
        assert db.season_for_date("2026-04-01") == "spring"
        assert db.season_for_date("2026-05-01") == "spring"
        assert db.season_for_date("2026-06-01") == "summer"
        assert db.season_for_date("2026-07-04T09:00:00") == "summer"
        assert db.season_for_date("2026-08-01") == "summer"
        assert db.season_for_date("2026-09-07") == "autumn"
        assert db.season_for_date("2026-10-01") == "autumn"
        assert db.season_for_date("2026-11-01") == "autumn"
        assert db.season_for_date("2026-12-25") == "winter"

    def test_season_for_date_none_for_missing_or_bad_input(self):
        assert db.season_for_date(None) is None
        assert db.season_for_date("") is None
        assert db.season_for_date("not-a-date") is None

    def test_task_with_no_label_falls_back_to_its_season_banner(self, conn):
        _set_remote(conn, cached=True, scope=db.SEASON_BANNER_SCOPES["summer"], image_url="https://cdn.example.com/summer.jpg")
        db.upsert_task(
            conn,
            {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": [],
             "due_at": "2026-07-15", "created_at": _now()},
        )
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/summer.jpg"
        assert banner["scope"] == db.SEASON_BANNER_SCOPES["summer"]

    def test_a_labels_own_banner_still_beats_the_season_fallback(self, conn):
        _make_label(conn, "Client call")
        _set_remote(conn, cached=True, scope="Client call", image_url="https://cdn.example.com/label.jpg")
        _set_remote(conn, cached=True, scope=db.SEASON_BANNER_SCOPES["summer"], image_url="https://cdn.example.com/summer.jpg")
        db.upsert_task(
            conn,
            {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Client call"],
             "due_at": "2026-07-15", "created_at": _now()},
        )
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/label.jpg"

    def test_task_falls_back_to_the_global_default_when_its_season_has_no_banner(self, conn):
        _set_remote(conn, cached=True, scope=db.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        db.upsert_task(
            conn,
            {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": [],
             "due_at": "2026-07-15", "created_at": _now()},
        )
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/default.jpg"
        assert banner["scope"] == db.PAGE_HEADER_BANNER_SCOPE

    def test_undated_task_skips_season_straight_to_the_global_default(self, conn):
        _set_remote(conn, cached=True, scope=db.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": [], "created_at": _now()})
        task = db.get_task(conn, "t1")
        banner = db.banner_for_task(conn, task)
        assert banner["image_url"] == "https://cdn.example.com/default.jpg"

    def test_event_with_no_label_falls_back_to_its_season_banner(self, conn):
        _set_remote(conn, cached=True, scope=db.SEASON_BANNER_SCOPES["winter"], image_url="https://cdn.example.com/winter.jpg")
        db.upsert_event(
            conn,
            {
                "uid": "e1", "title": "e1", "description": "", "start_at": "2026-01-10T09:00:00",
                "status": "active", "all_day": False, "created_at": _now(), "updated_at": _now(),
            },
        )
        event = db.get_event(conn, "e1")
        banner = db.banner_for_object(conn, "event", event)
        assert banner["image_url"] == "https://cdn.example.com/winter.jpg"

    def test_contact_is_unaffected_by_season_or_default_fallback(self, conn):
        # No due_at/start_at concept for a contact -- _SEASON_DATE_FIELD has
        # no "contact" entry, so even with a global default set, a
        # label-less contact still resolves to None (the gradient fallback),
        # exactly as before this change.
        _set_remote(conn, cached=True, scope=db.PAGE_HEADER_BANNER_SCOPE, image_url="https://cdn.example.com/default.jpg")
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Ada Lovelace", "created_at": _now(), "updated_at": _now()})
        contact = db.get_contact(conn, "c1")
        assert db.banner_for_object(conn, "contact", contact) is None


class TestLabelSettingsBannerEntryPoint:
    """label_form_modal.html's Banner field (2026-08-30 direct request) --
    a label's banner used to be reachable only via a dashboard page's own
    edit-mode button; this is the same /banners/editor dialog, scoped to
    the label, opened from Settings > Labels instead."""

    def test_edit_modal_offers_add_banner_when_unset(self, conn):
        _make_label(conn, "Client call")
        resp = labels_router.edit_label_modal("Client call", _request("/settings/labels/Client call/edit"), conn=conn)
        assert resp.context["banner"] is None
        body = resp.body.decode()
        assert "/banners/editor?scope=Client" in body
        assert "Add banner" in body
        assert "Change banner" not in body

    def test_edit_modal_shows_preview_and_change_link_when_set(self, conn):
        _make_label(conn, "Client call")
        _set_remote(conn, cached=True, scope="Client call", image_url="https://cdn.example.com/pic.jpg")
        resp = labels_router.edit_label_modal("Client call", _request("/settings/labels/Client call/edit"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/pic.jpg"
        body = resp.body.decode()
        assert "Change banner" in body
        assert "Add banner" not in body

    def test_new_label_modal_has_no_banner_field_yet(self, conn):
        resp = labels_router.new_label_modal(_request("/settings/labels/new"), conn=conn)
        body = resp.body.decode()
        assert "/banners/editor" not in body


class TestBannerRendersOnTaskDetailAndKanban:
    """The consumers of db.banner_for_task/db.banner_for_object besides a
    label's own generated page (2026-08-30 direct request for tasks/kanban;
    2026-09-03 direct request generalized the resolution to every detail
    modal's cover banner -- "I like variant B so much I want it to be the
    baseline for all view modal windows"): task_detail.html's (and now
    event_detail.html's/contact_detail.html's) cover banner, and
    project_detail.html's Kanban cards. 2026-09-03: task_detail.html's old
    standalone `.detail-modal-banner` body strip is gone -- the resolved
    image now renders inside the shared `.detail-cover` (`.detail-cover-img`)
    in the header instead, so these two tests assert the new class/location."""

    def test_task_detail_shows_the_gradient_fallback_by_default(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": [], "created_at": _now()})
        resp = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn)
        assert resp.context["banner"] is None
        body = resp.body.decode()
        assert 'class="detail-cover-fill"' in body
        assert "detail-cover-img" not in body

    def test_task_detail_shows_the_resolved_label_banner(self, conn):
        # cached=False (the default) -- a hotlink-only legacy remote banner
        # with no local bytes, so the template's own image_url fallback
        # branch is what's under test here (the version/served-bytes
        # branch is covered by test_serves_uploaded_bytes et al above).
        _make_label(conn, "Client call")
        _set_remote(conn, scope="Client call", image_url="https://cdn.example.com/label.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Client call"], "created_at": _now()})
        resp = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/label.jpg"
        body = resp.body.decode()
        assert 'class="detail-cover-img"' in body
        assert 'src="https://cdn.example.com/label.jpg"' in body
        assert "detail-cover-fill" not in body

    def test_event_detail_shows_the_resolved_label_banner(self, conn):
        # db.banner_for_object generalized from db.banner_for_task
        # 2026-09-03 -- events now resolve the same way, wired up in
        # routers/calendar.py's event_detail (STATE.md had flagged this as
        # "generalizes, just not wired to event_detail.html yet").
        _make_label(conn, "Work")
        _set_remote(conn, scope="Work", image_url="https://cdn.example.com/work.jpg")
        db.upsert_event(
            conn,
            {
                "uid": "e1", "title": "e1", "description": "", "start_at": "2026-09-04T09:00:00",
                "status": "active", "all_day": False, "created_at": _now(), "updated_at": _now(),
            },
        )
        db.set_object_labels(conn, "event", "e1", ["Work"])
        resp = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn)
        assert resp.context["banner"]["image_url"] == "https://cdn.example.com/work.jpg"
        body = resp.body.decode()
        assert 'class="detail-cover-img"' in body
        assert 'src="https://cdn.example.com/work.jpg"' in body

    def test_contact_detail_falls_back_to_a_stable_color_when_no_banner(self, conn):
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Ada Lovelace", "created_at": _now(), "updated_at": _now()})
        resp = contacts_router.contact_detail("c1", _request("/contacts/c1"), conn=conn)
        assert resp.context["banner"] is None
        body = resp.body.decode()
        assert 'class="detail-cover-fill"' in body
        # deps._stable_color("c1") is deterministic, so this is exact, not
        # just "some cal-accent value is present."
        assert f"--cover-accent:var(--cal-accent-{deps._stable_color('c1')})" in body

    def test_kanban_card_carries_the_resolved_project_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "created_at": _now()})
        _set_remote(conn, scope="Garden", image_url="https://cdn.example.com/project.jpg")
        db.upsert_task(conn, {"uid": "t1", "title": "Water the plants", "description": "", "status": "active", "tags": ["Garden"], "created_at": _now()})
        resp = projects_router.project_detail("Garden", _request("/projects/Garden"), conn=conn)
        card = [t for t in resp.context["columns"]["active"] if t["uid"] == "t1"][0]
        assert card["banner"]["image_url"] == "https://cdn.example.com/project.jpg"
        body = resp.body.decode()
        assert 'class="kanban-card-banner"' in body
        assert 'src="https://cdn.example.com/project.jpg"' in body

    def test_kanban_card_has_no_banner_markup_when_none_resolves(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Water the plants", "description": "", "status": "active", "tags": ["Garden"], "created_at": _now()})
        resp = projects_router.project_detail("Garden", _request("/projects/Garden"), conn=conn)
        assert "kanban-card-banner" not in resp.body.decode()
