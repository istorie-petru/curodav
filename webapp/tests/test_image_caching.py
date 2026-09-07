"""Image caching/compression (2026-08-29, direct request: "better cache
these images because they are changed very infrequently... convert for
smaller sizes... or compress them a bit").

Every uploaded image in this app (contact photos, the profile picture,
Home/label banners, the global Page header banner) used to be embedded in
its page's HTML as an inline `data:` URI -- banners were already fixed for
this (routers/banners.py's banner_image, 2026-08-10); this pass extends
the exact same "serve via a real, `?v=`-versioned, immutable-cacheable
request" pattern to contact photos (routers/contacts.py's
contact_photo_image) and the profile picture (routers/settings.py's
profile_photo_image). deps.py's avatar() global prefers a `photo_url` when
one is attached to the dict it's given, falling back to the old inline
`data:` URI only when no stable id/URL exists yet (e.g. a brand-new,
not-yet-saved contact).

Covers: the two new photo routes (serving, 404s, content-type validation),
db.py's content-hash `version`/`photo_version` computation and lazy
backfill for pre-existing rows, and avatar()/each router attaching
`photo_url` so templates actually use the new routes instead of the old
inline behavior."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from src import db, deps
from src.routers import contacts as contacts_router
from src.routers import settings as settings_router


class _FakeUploadFile:
    """Duck-types the bits of fastapi.UploadFile the photo-upload routes
    actually touch (`.filename`, `.content_type`, plus either `.file.read()`
    or async `.read()` -- routers/contacts.py's _read_photo awaits `.read()`,
    routers/settings.py's set_profile_photo reads `.file` synchronously, so
    this supports both)."""

    def __init__(self, data: bytes, content_type: str, filename: str = "x.jpg"):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(data)
        self._data = data

    async def read(self):
        return self._data


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_contact(conn, **overrides):
    now = _now()
    row = {
        "uid": overrides.pop("uid", None) or "c1",
        "full_name": "Ada Lovelace",
        "org": None, "phone": None, "email": None, "address": None, "notes": None,
        "tags": [],
        "photo_b64": None, "photo_type": None,
        "created_at": now, "updated_at": now,
    }
    row.update(overrides)
    db.upsert_contact(conn, row)
    return row["uid"]


class TestContactPhotoVersion:
    def test_upsert_computes_version_when_photo_set(self, conn):
        b64 = base64.b64encode(b"photo-bytes").decode("ascii")
        _make_contact(conn, photo_b64=b64, photo_type="JPEG")
        row = db.get_contact(conn, "c1")
        assert row["photo_version"] == hashlib.md5(b64.encode("ascii")).hexdigest()[:12]

    def test_no_version_without_a_photo(self, conn):
        _make_contact(conn)
        row = db.get_contact(conn, "c1")
        assert row["photo_version"] is None

    def test_legacy_row_with_photo_but_no_version_gets_backfilled(self, conn):
        # Simulates a contact saved before contacts.photo_version existed:
        # write photo_b64 directly, bypassing upsert_contact's own
        # computation, so photo_version stays NULL until read.
        b64 = base64.b64encode(b"legacy-bytes").decode("ascii")
        _make_contact(conn)
        conn.execute("UPDATE contacts SET photo_b64 = ?, photo_type = ? WHERE uid = ?", (b64, "png", "c1"))
        conn.commit()
        row = db.get_contact(conn, "c1")
        assert row["photo_version"] == hashlib.md5(b64.encode("ascii")).hexdigest()[:12]
        # Persisted, not just computed for this one read.
        stored = conn.execute("SELECT photo_version FROM contacts WHERE uid = ?", ("c1",)).fetchone()[0]
        assert stored == row["photo_version"]

    def test_list_contacts_also_backfills(self, conn):
        b64 = base64.b64encode(b"legacy-bytes").decode("ascii")
        _make_contact(conn)
        conn.execute("UPDATE contacts SET photo_b64 = ?, photo_type = ? WHERE uid = ?", (b64, "png", "c1"))
        conn.commit()
        rows = db.list_contacts(conn)
        assert rows[0]["photo_version"] == hashlib.md5(b64.encode("ascii")).hexdigest()[:12]


class TestPhotoUploadImageSniffing:
    """2026-09-07 fix (flagged in an earlier audit): both contacts._read_
    photo and settings.set_profile_photo used to trust the browser-supplied
    Content-Type header alone -- an unauthenticated POST could claim
    "image/jpeg" for any bytes at all. Now the actual bytes are sniffed
    (src/image_sniff.py) and must match a real image signature."""

    def test_contact_photo_rejects_bytes_that_dont_match_any_real_image_signature(self):
        fake = _FakeUploadFile(b"not-an-image-at-all", "image/jpeg")
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(contacts_router._read_photo(fake))
        assert excinfo.value.status_code == 400

    def test_contact_photo_accepts_real_gif_magic_bytes(self):
        fake = _FakeUploadFile(b"GIF89a" + b"rest-of-a-gif", "image/gif")
        result = asyncio.run(contacts_router._read_photo(fake))
        assert result is not None
        _, vcard_type = result
        assert vcard_type == "GIF"

    def test_contact_photo_uses_the_sniffed_type_even_when_the_header_lies(self):
        # Header says GIF, bytes are really a PNG.
        fake = _FakeUploadFile(b"\x89PNG\r\n\x1a\n" + b"rest-of-a-png", "image/gif")
        _, vcard_type = asyncio.run(contacts_router._read_photo(fake))
        assert vcard_type == "PNG"

    def test_profile_photo_rejects_bytes_that_dont_match_any_real_image_signature(self, conn):
        fake = _FakeUploadFile(b"not-an-image-at-all", "image/png")
        with pytest.raises(HTTPException) as excinfo:
            settings_router.set_profile_photo(photo=fake, conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_profile_photo(conn) is None

    def test_profile_photo_accepts_real_webp_magic_bytes(self, conn):
        data = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"rest-of-a-webp"
        fake = _FakeUploadFile(data, "image/webp")
        settings_router.set_profile_photo(photo=fake, conn=conn)
        assert db.get_profile_photo(conn)["photo_type"] == "webp"


class TestProfilePhotoVersion:
    def test_set_computes_version(self, conn):
        b64 = base64.b64encode(b"photo-bytes").decode("ascii")
        db.set_profile_photo(conn, b64, "jpeg")
        photo = db.get_profile_photo(conn)
        assert photo["version"] == hashlib.md5(b64.encode("ascii")).hexdigest()[:12]

    def test_legacy_profile_photo_gets_backfilled(self, conn):
        b64 = base64.b64encode(b"legacy-bytes").decode("ascii")
        # Bypass set_profile_photo's own version computation, same as a
        # pre-migration install would have.
        db.set_app_meta(conn, db.PROFILE_PHOTO_B64_KEY, b64)
        db.set_app_meta(conn, db.PROFILE_PHOTO_TYPE_KEY, "jpeg")
        photo = db.get_profile_photo(conn)
        assert photo["version"] == hashlib.md5(b64.encode("ascii")).hexdigest()[:12]
        assert db.get_app_meta(conn, db.PROFILE_PHOTO_VERSION_KEY) == photo["version"]

    def test_clear_resets_version_too(self, conn):
        db.set_profile_photo(conn, base64.b64encode(b"x").decode("ascii"), "jpeg")
        db.clear_profile_photo(conn)
        assert db.get_profile_photo(conn) is None
        assert db.get_app_meta(conn, db.PROFILE_PHOTO_VERSION_KEY) == ""


class TestContactPhotoRoute:
    def test_serves_photo_bytes_with_immutable_cache_control(self, conn):
        data = b"real-photo-bytes"
        _make_contact(conn, photo_b64=base64.b64encode(data).decode("ascii"), photo_type="JPEG")
        resp = contacts_router.contact_photo_image("c1", conn=conn)
        assert resp.body == data
        assert resp.media_type == "image/jpeg"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_404_when_contact_has_no_photo(self, conn):
        _make_contact(conn)
        with pytest.raises(HTTPException) as excinfo:
            contacts_router.contact_photo_image("c1", conn=conn)
        assert excinfo.value.status_code == 404

    def test_404_for_unknown_contact(self, conn):
        with pytest.raises(HTTPException) as excinfo:
            contacts_router.contact_photo_image("nope", conn=conn)
        assert excinfo.value.status_code == 404

    def test_webp_photo_type_served_correctly(self, conn):
        data = b"webp-bytes"
        _make_contact(conn, photo_b64=base64.b64encode(data).decode("ascii"), photo_type="WEBP")
        resp = contacts_router.contact_photo_image("c1", conn=conn)
        assert resp.media_type == "image/webp"


class TestProfilePhotoRoute:
    def test_serves_photo_bytes_with_immutable_cache_control(self, conn):
        data = b"real-profile-bytes"
        db.set_profile_photo(conn, base64.b64encode(data).decode("ascii"), "png")
        resp = settings_router.profile_photo_image(conn=conn)
        assert resp.body == data
        assert resp.media_type == "image/png"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"

    def test_404_when_no_profile_photo_set(self, conn):
        with pytest.raises(HTTPException) as excinfo:
            settings_router.profile_photo_image(conn=conn)
        assert excinfo.value.status_code == 404


class TestAvatarGlobalPrefersPhotoUrl:
    """deps.py's avatar() -- photo_url wins over inline photo_b64 when
    both are present; inline data: URI is still the fallback when no
    photo_url is given at all (e.g. a caller that hasn't attached one)."""

    def test_photo_url_used_when_present(self):
        html = str(deps._avatar({"photo_url": "/contacts/c1/photo?v=abc123", "photo_b64": "shouldnotappear"}, "avatar-large"))
        assert 'src="/contacts/c1/photo?v=abc123"' in html
        assert "data:image" not in html

    def test_falls_back_to_inline_data_uri_without_photo_url(self):
        html = str(deps._avatar({"photo_b64": "Zm9v", "photo_type": "jpeg"}, "avatar-large"))
        assert "data:image/jpeg;base64,Zm9v" in html

    def test_falls_back_to_initials_with_neither(self):
        html = str(deps._avatar({"full_name": "Grace Hopper"}, "avatar-large"))
        assert "data:image" not in html
        assert ">G<" in html


class TestContactsRoutersAttachPhotoUrl:
    def test_list_contacts_route_attaches_photo_url(self, conn):
        _make_contact(conn, photo_b64=base64.b64encode(b"x").decode("ascii"), photo_type="jpeg")
        resp = contacts_router.list_contacts(_bare_request("/contacts"), conn=conn)
        body = resp.body.decode()
        assert "/contacts/c1/photo?v=" in body
        assert "data:image" not in body

    def test_contact_detail_route_attaches_photo_url(self, conn):
        _make_contact(conn, photo_b64=base64.b64encode(b"x").decode("ascii"), photo_type="jpeg")
        resp = contacts_router.contact_detail("c1", _bare_request("/contacts/c1"), conn=conn)
        body = resp.body.decode()
        assert "/contacts/c1/photo?v=" in body
        assert "data:image" not in body

    def test_edit_form_attaches_photo_url(self, conn):
        _make_contact(conn, photo_b64=base64.b64encode(b"x").decode("ascii"), photo_type="jpeg")
        resp = contacts_router.edit_contact_form("c1", _bare_request("/contacts/c1/edit"), conn=conn)
        body = resp.body.decode()
        assert "/contacts/c1/photo?v=" in body

    def test_contact_with_no_photo_has_no_photo_url(self, conn):
        _make_contact(conn)
        resp = contacts_router.contact_detail("c1", _bare_request("/contacts/c1"), conn=conn)
        body = resp.body.decode()
        assert "/contacts/c1/photo?v=" not in body


def _bare_request(path="/"):
    from starlette.requests import Request

    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )
