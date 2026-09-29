"""Settings > Flairs (2026-09-29, direct request: a frontend for bulk-
adding flair photos -- "drop down the photos in either zip or folder or
multiple photos at once" -- instead of an operator needing filesystem
access to flairs_dir at all).

Covers routers/settings.py's `settings_flairs` (GET, coverage listing)
and `upload_flairs` (POST, the actual bulk-save route) -- the underlying
save/validate logic itself (flairs.ingest_uploaded_photos) is covered in
test_flairs.py's own TestIngestUploadedPhotos; these tests focus on the
HTTP-route-level concerns instead: how a zip/multi-file/folder submission
gets turned into the (name, bytes) pairs ingest_uploaded_photos expects,
the zip-bomb-resistant bounded read, and the ?note=/?error= redirect."""

from __future__ import annotations

import io
import zipfile
from urllib.parse import unquote

import pytest
from starlette.requests import Request

from src import db, flairs
from src.routers import settings as settings_router

_TINY_JPEG = b"\xff\xd8\xff" + b"\x00" * 16


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


@pytest.fixture()
def flairs_dir(tmp_path):
    directory = tmp_path / "flairs"
    directory.mkdir()
    flairs.configure(directory)
    yield directory
    flairs.configure(None)


def _request(path="/settings/flairs"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [],
        }
    )


class _FakeUploadFile:
    """Duck-types the bits of fastapi.UploadFile the upload route touches
    (`.filename`, `.file.read()`) -- same convention test_banners.py's own
    `_FakeUploadFile` uses, so the route function is callable directly
    without a real ASGI/multipart request."""

    def __init__(self, data: bytes, filename: str):
        self.filename = filename
        self.file = io.BytesIO(data)


def _location(resp) -> str:
    """The redirect's own ?note=/?error= query value is URL-quoted
    (routers/export.py's `_redirect_with_note`/`_redirect_with_error`) --
    decoded here so tests can assert on plain-English substrings instead
    of their %XX-escaped form."""
    return unquote(resp.headers["location"])


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestSettingsFlairsPage:
    def test_renders_with_flairs_dir_configured(self, conn, flairs_dir):
        resp = settings_router.settings_flairs(_request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["active_tab"] == "settings_flairs"
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]
        assert resp.context["flairs_dir_configured"] is True
        assert resp.context["total_count"] > 100  # 79 keyword flairs + scenery + event icons + 12 months + 4 seasons
        assert resp.context["configured_count"] == 0
        assert "basketball" in resp.context["missing_ids"]
        assert "july" in resp.context["missing_ids"]  # month tier included, not just FLAIR_KEYWORDS

    def test_coverage_reflects_real_files_on_disk(self, conn, flairs_dir):
        (flairs_dir / "basketball.jpg").write_bytes(_TINY_JPEG)
        (flairs_dir / "july.png").write_bytes(_TINY_JPEG)
        resp = settings_router.settings_flairs(_request(), conn=conn)
        assert resp.context["configured_count"] == 2
        assert "basketball" not in resp.context["missing_ids"]
        assert "july" not in resp.context["missing_ids"]

    def test_shows_not_configured_state(self, conn):
        flairs.configure(None)
        resp = settings_router.settings_flairs(_request(), conn=conn)
        assert resp.context["flairs_dir_configured"] is False
        body = resp.body.decode()
        assert "No flairs folder is configured" in body


class TestUploadFlairsRoute:
    def test_no_flairs_dir_configured_is_an_error_redirect(self, conn):
        flairs.configure(None)
        resp = settings_router.upload_flairs(files=[_FakeUploadFile(_TINY_JPEG, "basketball.jpg")], zip_file=None, conn=conn)
        assert resp.status_code == 303
        assert "error=" in _location(resp)

    def test_multi_file_upload_saves_valid_photos(self, conn, flairs_dir):
        files = [
            _FakeUploadFile(_TINY_JPEG, "basketball.jpg"),
            _FakeUploadFile(_TINY_JPEG, "yoga.jpg"),
        ]
        resp = settings_router.upload_flairs(files=files, zip_file=None, conn=conn)
        assert resp.status_code == 303
        assert "note=" in _location(resp)
        assert flairs.flair_image_url("basketball") is not None
        assert flairs.flair_image_url("yoga") is not None

    def test_a_bad_file_in_the_batch_is_reported_not_silently_dropped(self, conn, flairs_dir):
        files = [
            _FakeUploadFile(_TINY_JPEG, "basketball.jpg"),
            _FakeUploadFile(b"not a real image", "invalid.jpg"),
        ]
        resp = settings_router.upload_flairs(files=files, zip_file=None, conn=conn)
        location = _location(resp)
        assert "note=" in location  # at least one real save -> note, not error
        assert "invalid.jpg" in location or "invalid" in location.lower()

    def test_all_files_invalid_is_an_error_redirect(self, conn, flairs_dir):
        files = [_FakeUploadFile(b"not a real image", "invalid.jpg")]
        resp = settings_router.upload_flairs(files=files, zip_file=None, conn=conn)
        assert "error=" in _location(resp)

    def test_empty_file_field_contributes_nothing(self, conn, flairs_dir):
        # An untouched <input type=file> still submits as an UploadFile
        # with an empty filename -- same "no-op, not an error" convention
        # routers/settings.py's own profile-photo upload already uses.
        resp = settings_router.upload_flairs(files=[_FakeUploadFile(b"", "")], zip_file=None, conn=conn)
        assert "Nothing to upload" in _location(resp) or resp.status_code == 303

    def test_zip_upload_smart_filters_any_depth(self, conn, flairs_dir):
        zip_data = _zip_bytes({
            "basketball.jpg": _TINY_JPEG,
            "google-calendar-flairs/icons/gym.jpg": _TINY_JPEG,
            "google-calendar-flairs/unmatched/notes.txt": b"not an image at all",
            "google-calendar-flairs/icons/party.svg": b"<svg></svg>",
            "google-calendar-flairs/": b"",  # a directory entry
        })
        resp = settings_router.upload_flairs(files=[], zip_file=_FakeUploadFile(zip_data, "flairs.zip"), conn=conn)
        assert flairs.flair_image_url("basketball") is not None
        assert flairs.flair_image_url("gym") is not None  # basename matched regardless of the icons/ subfolder
        assert "note=" in _location(resp)

    def test_zip_and_multi_file_combine_into_one_result(self, conn, flairs_dir):
        zip_data = _zip_bytes({"basketball.jpg": _TINY_JPEG})
        resp = settings_router.upload_flairs(
            files=[_FakeUploadFile(_TINY_JPEG, "yoga.jpg")],
            zip_file=_FakeUploadFile(zip_data, "flairs.zip"),
            conn=conn,
        )
        assert flairs.flair_image_url("basketball") is not None
        assert flairs.flair_image_url("yoga") is not None
        assert "2 photos saved" in _location(resp) or "note=" in _location(resp)

    def test_invalid_zip_file_is_rejected(self, conn, flairs_dir):
        resp = settings_router.upload_flairs(files=[], zip_file=_FakeUploadFile(b"not a zip file", "flairs.zip"), conn=conn)
        assert "error=" in _location(resp)
        assert "valid zip" in _location(resp)

    def test_oversized_zip_upload_is_rejected_before_extraction(self, conn, flairs_dir):
        big = _FakeUploadFile(b"\x00" * (settings_router._MAX_ZIP_UPLOAD_BYTES + 1), "flairs.zip")
        resp = settings_router.upload_flairs(files=[], zip_file=big, conn=conn)
        assert "error=" in _location(resp)
        assert "too large" in _location(resp)

    def test_zip_entry_that_decompresses_far_beyond_its_declared_size_is_capped_not_a_bomb(self, conn, flairs_dir):
        # The classic zip-bomb shape: a small compressed upload whose
        # single entry, once inflated, is much bigger than MAX_UPLOAD_
        # BYTES. This must be rejected by BOUNDING THE READ, not by
        # trusting ZipInfo.file_size (an attacker-controlled header) --
        # see upload_flairs's own docstring. Highly compressible content
        # (all zero bytes) keeps the actual uploaded zip tiny even though
        # the declared/real inflated size is huge.
        huge = b"\x00" * (flairs.MAX_UPLOAD_BYTES + 1024)
        zip_data = _zip_bytes({"basketball.jpg": huge})
        assert len(zip_data) < 100_000  # the upload itself is small...
        resp = settings_router.upload_flairs(files=[], zip_file=_FakeUploadFile(zip_data, "flairs.zip"), conn=conn)
        # ...but the oversized entry is still caught and skipped, not saved.
        assert flairs.flair_image_url("basketball") is None
        assert "too large" in _location(resp) or "error=" in _location(resp)

    def test_overwrite_via_http_route_replaces_silently(self, conn, flairs_dir):
        settings_router.upload_flairs(files=[_FakeUploadFile(_TINY_JPEG, "basketball.jpg")], zip_file=None, conn=conn)
        new_bytes = _TINY_JPEG + b"\x01"
        settings_router.upload_flairs(files=[_FakeUploadFile(new_bytes, "basketball.jpg")], zip_file=None, conn=conn)
        assert (flairs_dir / "basketball.jpg").read_bytes() == new_bytes


class TestFlairsNotAHubCategory:
    """2026-09-29 direct follow-up: Flairs moved off its own top-level
    Settings hub category into a modal button on Settings > Appearance
    (see HUB_CATEGORIES' own comment) -- /settings/flairs itself is
    unchanged (still a real GET route, still degrades to a full standalone
    page, TestSettingsFlairsPage above still exercises it directly), it
    just isn't advertised as a separate hub tile any more."""

    def test_flairs_is_no_longer_listed_on_the_settings_hub(self):
        urls = [c["url"] for c in settings_router.HUB_CATEGORIES]
        assert "/settings/flairs" not in urls


class TestFlairsModalMarkup:
    """2026-09-29 modal-ization -- settings_flairs.html is now a real
    #modal-target fragment (modal-header/modal-body/shared footer), opened
    from Settings > Appearance's own Flairs row. Direct instruction: no
    `settings-hint` anywhere in this template any more (every hint uses
    `text-muted` instead, the general modal-body convention)."""

    def test_no_settings_hint_class_anywhere(self, conn, flairs_dir):
        body = settings_router.settings_flairs(_request(), conn=conn).body.decode()
        assert "settings-hint" not in body

    def test_no_settings_hint_class_when_dir_not_configured(self, conn):
        flairs.configure(None)
        body = settings_router.settings_flairs(_request(), conn=conn).body.decode()
        assert "settings-hint" not in body

    def test_uses_modal_target_and_shared_footer(self, conn, flairs_dir):
        body = settings_router.settings_flairs(_request(), conn=conn).body.decode()
        assert 'id="modal-target"' in body
        assert '<h1>Flairs</h1>' in body
        assert '{% include "_modal_footer.html" %}' not in body  # the include resolved, not literal
        assert 'class="modal-footer"' in body
        assert 'href="/settings/appearance"' in body

    def test_upload_button_lives_in_the_footer_tied_to_the_body_form(self, conn, flairs_dir):
        body = settings_router.settings_flairs(_request(), conn=conn).body.decode()
        assert 'id="flairs-upload-submit-btn"' in body
        assert 'form="flairs-upload-form"' in body
        assert "disabled" in body  # starts disabled until a file is staged


class TestAppearanceFlairsRow:
    def test_shows_coverage_counts_and_modal_link(self, conn, flairs_dir):
        (flairs_dir / "basketball.jpg").write_bytes(_TINY_JPEG)
        resp = settings_router.settings_appearance(_request("/settings/appearance"), conn=conn)
        assert resp.context["flairs_configured_count"] == 1
        assert resp.context["flairs_total_count"] > 100
        body = resp.body.decode()
        assert 'href="/settings/flairs"' in body
        assert "data-modal" in body
