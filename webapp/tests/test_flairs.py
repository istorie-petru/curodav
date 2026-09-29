"""Tests for item 10 of Peter's queued list (2026-09-27), the last item:
"`google-calendar-flairs/` ... is the reference for a new feature:
dynamically attach a photo to an event/task/habit/label/group/project
based on a keyword list matched against its name (a big-but-reasonable
keyword list per photo). Labels/groups/projects always get this
treatment (their default banner before the user picks their own -- this
default behavior can't be removed [confirmed via AskUserQuestion: it CAN
be removed, see TestExplicitClear below]). Events/tasks/habits only get
it when they (a) carry no label/project, or (b) their label/project's
banner is empty/was cleared. The banner upload modal needs a new 'clear
banner' option."

2026-09-27 follow-up (direct correction, same day): the FIRST version of
this feature bundled 79 real Google Calendar flair photos straight into
the repo -- copyrighted material with no license to redistribute. This
suite now covers the corrected shape instead: `FLAIR_KEYWORDS` is pure
keyword data (no bundled images at all), and `flairs.flair_image_url`
only ever resolves a photo an operator has placed themselves under
`flairs.configure()`'s configured directory (`Settings.flairs_dir`,
`CC_FLAIRS_DIR` in real life) -- every test below configures its own
`tmp_path` and writes whichever placeholder image bytes it needs, since
no real photo ships with the app or the test suite either.

Covers: src/flairs.py's own keyword-matching (`match_flair`) and
photo-resolution (`flair_image_url`, `configure`), db.py's
`effective_page_banner`/`set_page_banner_cleared`/`_page_banner_
explicitly_cleared`, `banner_for_object`'s new flair tiers (inherited via
a label/Project/Space, and the object's own name), the contact exclusion,
the renamed-and-repurposed "Clear banner" route/editor, and the new
`GET /flairs/{id}` serving route (routers/flairs.py). Season photos are
deliberately NOT part of this feature (see flairs.py's own header comment
for why that was tried and reverted) -- no tests for that here."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db, flairs
from src.routers import banners as banners_router
from src.routers import flairs as flairs_router
from src.routers import label_pages

# Not a real, decodable JPEG -- just its 3-byte magic-number prefix,
# which is all image_sniff.sniff_image_type actually checks (routers/
# flairs.py/banners.py both re-sniff real bytes rather than trusting a
# file extension, so this has to pass that check, nothing more).
_TINY_JPEG = b"\xff\xd8\xff" + b"\x00" * 16


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


@pytest.fixture(autouse=True)
def flairs_dir(tmp_path):
    """Every test gets its own empty flairs directory by default --
    `configure` (not app.state) is how src/flairs.py learns where to look,
    same module-level convention main.py's own lifespan uses in real
    life. Reset after each test so one test's placeholder files can never
    leak into another's (module-level state, not per-connection)."""
    directory = tmp_path / "flairs"
    directory.mkdir()
    flairs.configure(directory)
    yield directory
    flairs.configure(None)


def _put(flairs_dir, flair_id: str, ext: str = ".jpg") -> None:
    (flairs_dir / f"{flair_id}{ext}").write_bytes(_TINY_JPEG)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []})


class TestFlairKeywordData:
    def test_at_least_79_photos_with_real_keywords(self):
        assert len(flairs.FLAIR_KEYWORDS) >= 79
        assert all(kws for kws in flairs.FLAIR_KEYWORDS.values())

    def test_ids_are_kebab_case_not_googles_own_jammed_spelling(self):
        # e.g. "american-football", not the reference data's own
        # "americanfootball" -- renamed in the same follow-up that
        # dropped the bundled images, so this table no longer mirrors
        # Google's own internal asset naming at all.
        import re

        for flair_id in flairs.FLAIR_KEYWORDS:
            assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", flair_id), flair_id

    def test_no_duplicate_keyword_within_one_photo(self):
        for flair_id, kws in flairs.FLAIR_KEYWORDS.items():
            names = [k for k, _ in kws]
            assert len(names) == len(set(names)), flair_id


class TestMatchFlair:
    def test_exact_name_match(self):
        assert flairs.match_flair("Basketball") == "basketball"

    def test_case_insensitive(self):
        assert flairs.match_flair("BASKETBALL practice") == "basketball"

    def test_substring_match_within_a_longer_title(self):
        assert flairs.match_flair("Weekly yoga class with Ana") == "yoga"

    def test_no_match_returns_none(self):
        assert flairs.match_flair("Quarterly planning sync") is None

    def test_none_and_empty_input(self):
        assert flairs.match_flair(None) is None
        assert flairs.match_flair("") is None

    def test_priority_tie_break_lower_number_wins(self):
        # "christmas-meal" (priority 5) vs "bbq" (priority 2, "cookout").
        name = "Christmas dinner and cookout"
        assert flairs.match_flair(name) == "bbq"

    def test_birthday_keyword_added_despite_no_reference_csv_row(self):
        assert flairs.match_flair("Ada's birthday party") == "birthday"

    def test_matching_is_independent_of_whether_a_photo_file_exists(self):
        # Pure keyword data -- match_flair doesn't care whether the
        # operator has actually supplied basketball.jpg yet (flairs_dir
        # is empty by default in this whole file's own fixture).
        assert flairs.match_flair("Basketball") == "basketball"
        assert flairs.flair_image_url("basketball") is None


class TestFlairImageUrl:
    def test_none_when_nothing_configured(self):
        flairs.configure(None)
        assert flairs.flair_image_url("basketball") is None

    def test_none_when_directory_configured_but_file_missing(self, flairs_dir):
        assert flairs.flair_image_url("basketball") is None

    def test_url_once_a_matching_file_exists(self, flairs_dir):
        _put(flairs_dir, "basketball")
        url = flairs.flair_image_url("basketball")
        assert url is not None
        assert url.startswith("/flairs/basketball?v=")

    def test_any_supported_extension_is_found(self, flairs_dir):
        _put(flairs_dir, "yoga", ext=".png")
        assert flairs.flair_image_url("yoga") is not None

    def test_url_changes_when_the_files_mtime_changes(self, flairs_dir):
        import os

        _put(flairs_dir, "basketball")
        path = flairs_dir / "basketball.jpg"
        os.utime(path, (1_000_000_000, 1_000_000_000))
        first = flairs.flair_image_url("basketball")
        os.utime(path, (2_000_000_000, 2_000_000_000))
        second = flairs.flair_image_url("basketball")
        assert first != second
        assert "v=1000000000" in first
        assert "v=2000000000" in second


class TestFlairImageRoute:
    def test_serves_the_configured_file(self, flairs_dir):
        _put(flairs_dir, "basketball")
        resp = flairs_router.flair_image("basketball")
        assert resp.status_code == 200
        assert resp.body == _TINY_JPEG
        assert resp.media_type == "image/jpeg"

    def test_404_for_an_unconfigured_id(self, flairs_dir):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            flairs_router.flair_image("basketball")
        assert excinfo.value.status_code == 404

    def test_404_for_a_hostile_id_shape(self, flairs_dir):
        from fastapi import HTTPException

        _put(flairs_dir, "basketball")
        for bogus in ("../../etc/passwd", "basketball.jpg", "Basketball", "bas ketball", ""):
            with pytest.raises(HTTPException) as excinfo:
                flairs_router.flair_image(bogus)
            assert excinfo.value.status_code == 404

    def test_404_for_bytes_that_dont_actually_sniff_as_an_image(self, flairs_dir):
        from fastapi import HTTPException

        (flairs_dir / "basketball.jpg").write_bytes(b"not a real image")
        with pytest.raises(HTTPException) as excinfo:
            flairs_router.flair_image("basketball")
        assert excinfo.value.status_code == 404


class TestIngestUploadedPhotos:
    """flairs.ingest_uploaded_photos (2026-09-29, Settings > Flairs bulk
    upload) -- format-agnostic: routers/settings.py's upload route feeds
    it plain (name, bytes) pairs regardless of whether they came from a
    multi-file input or a zip's entries, so these tests exercise the
    function directly with hand-built pairs rather than going through
    either source."""

    def test_none_configured_saves_nothing_and_reports_nothing(self):
        flairs.configure(None)
        result = flairs.ingest_uploaded_photos([("basketball.jpg", _TINY_JPEG)])
        assert result.saved == []
        assert result.skipped == []

    def test_saves_a_valid_photo_under_its_basename(self, flairs_dir):
        result = flairs.ingest_uploaded_photos([("basketball.jpg", _TINY_JPEG)])
        assert result.saved == ["basketball"]
        assert (flairs_dir / "basketball.jpg").read_bytes() == _TINY_JPEG
        assert flairs.flair_image_url("basketball") is not None

    def test_uses_basename_regardless_of_path_depth_or_separator(self, flairs_dir):
        # Exactly what a zip entry's `filename` or a webkitdirectory
        # folder-picker's relative path looks like -- any subfolder
        # structure is discarded, only the leaf name matters.
        result = flairs.ingest_uploaded_photos([
            ("google-calendar-flairs/icons/basketball.jpg", _TINY_JPEG),
            ("some\\windows\\path\\yoga.jpg", _TINY_JPEG),
        ])
        assert sorted(result.saved) == ["basketball", "yoga"]

    def test_directory_entry_is_silently_ignored_not_skipped(self, flairs_dir):
        result = flairs.ingest_uploaded_photos([("icons/", b"")])
        assert result.saved == []
        assert result.skipped == []

    def test_id_not_yet_known_still_saves_fine(self, flairs_dir):
        # Shape, not membership -- same rule the /flairs/{id} serving
        # route already applies (routers/flairs.py's own _SAFE_ID, now
        # `flairs.ID_SHAPE`). An id absent from FLAIR_KEYWORDS/MONTH_
        # BANNER_SCOPES/SEASON_BANNER_SCOPES entirely still saves.
        result = flairs.ingest_uploaded_photos([("not-a-real-flair-yet.jpg", _TINY_JPEG)])
        assert result.saved == ["not-a-real-flair-yet"]

    def test_overwrites_an_existing_photo_silently(self, flairs_dir):
        flairs.ingest_uploaded_photos([("basketball.jpg", _TINY_JPEG)])
        new_bytes = _TINY_JPEG + b"\x01"
        result = flairs.ingest_uploaded_photos([("basketball.jpg", new_bytes)])
        assert result.saved == ["basketball"]
        assert (flairs_dir / "basketball.jpg").read_bytes() == new_bytes

    def test_no_extension_is_skipped_with_a_reason(self, flairs_dir):
        result = flairs.ingest_uploaded_photos([("basketball", _TINY_JPEG)])
        assert result.saved == []
        assert result.skipped == [("basketball", "no file extension")]

    def test_unsupported_extension_is_skipped(self, flairs_dir):
        # .svg specifically -- deliberately still not a supported
        # extension, same reasoning as this module's own header docstring
        # (image_sniff has no SVG sniffing, stored-XSS surface).
        result = flairs.ingest_uploaded_photos([("basketball.svg", b"<svg></svg>")])
        assert result.saved == []
        assert result.skipped[0][0] == "basketball.svg"
        assert "unsupported extension" in result.skipped[0][1]

    def test_bad_id_shape_is_skipped(self, flairs_dir):
        for bad_name in ("basket_ball.jpg", "-basketball.jpg", "basketball-.jpg", "bas ketball.jpg"):
            result = flairs.ingest_uploaded_photos([(bad_name, _TINY_JPEG)])
            assert result.saved == [], bad_name
            assert "valid flair id" in result.skipped[0][1], bad_name

    def test_uppercase_filename_is_lowercased_and_saved(self, flairs_dir):
        # Leniency, not strictness, on case: "Basketball.JPG" is exactly
        # what an operator would have if they renamed a file by hand
        # without thinking about case -- auto-lowercasing it is friendlier
        # than making them redo the upload, and ID_SHAPE only ever rejects
        # genuinely wrong shapes (underscores, stray spaces, leading/
        # trailing hyphens), not merely-uppercase ones.
        result = flairs.ingest_uploaded_photos([("Basketball.JPG", _TINY_JPEG)])
        assert result.saved == ["basketball"]
        assert flairs.flair_image_url("basketball") is not None

    def test_bytes_that_dont_sniff_as_a_real_image_are_skipped(self, flairs_dir):
        result = flairs.ingest_uploaded_photos([("basketball.jpg", b"not a real image")])
        assert result.saved == []
        assert "doesn't look like a real image" in result.skipped[0][1]

    def test_sniffed_type_must_match_the_extension_claimed(self, flairs_dir):
        # Real PNG bytes under a .jpg name -- sniffing catches the
        # mismatch even though the bytes ARE a real image, just not the
        # one this extension claims.
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        result = flairs.ingest_uploaded_photos([("basketball.jpg", png_bytes)])
        assert result.saved == []
        assert "doesn't look like a real image" in result.skipped[0][1]

    def test_oversized_file_is_skipped(self, flairs_dir):
        oversized = _TINY_JPEG + b"\x00" * flairs.MAX_UPLOAD_BYTES
        result = flairs.ingest_uploaded_photos([("basketball.jpg", oversized)])
        assert result.saved == []
        assert "too large" in result.skipped[0][1]

    def test_summary_reports_saved_and_skipped_counts(self, flairs_dir):
        result = flairs.ingest_uploaded_photos([
            ("basketball.jpg", _TINY_JPEG),
            ("yoga.jpg", _TINY_JPEG),
            ("bad name.jpg", _TINY_JPEG),
        ])
        summary = result.summary()
        assert "2 photos saved" in summary
        assert "1 skipped" in summary
        assert "bad name.jpg" in summary

    def test_summary_nothing_to_upload(self):
        assert flairs.ingest_uploaded_photos([]).summary() == "Nothing to upload."


class TestEffectivePageBanner:
    def test_no_name_no_stored_banner_is_none(self, conn):
        assert db.effective_page_banner(conn, "Random Label", name=None) is None

    def test_matching_name_with_no_photo_configured_is_none(self, conn):
        # A keyword match alone isn't enough -- the operator has to have
        # actually placed a file too (this whole file's own fixture keeps
        # flairs_dir empty by default).
        assert db.effective_page_banner(conn, "Basketball", name="Basketball") is None

    def test_matching_name_computes_a_flair_once_a_photo_exists(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        banner = db.effective_page_banner(conn, "Basketball", name="Basketball")
        assert banner is not None
        assert banner["kind"] == "remote"
        assert "/flairs/basketball" in banner["image_url"]

    def test_non_matching_name_is_none(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        assert db.effective_page_banner(conn, "Quarterly Sync", name="Quarterly Sync") is None

    def test_explicit_upload_beats_a_flair_match(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.set_page_banner(conn, "Basketball", {"kind": "upload", "image_b64": "", "image_type": "jpeg"})
        banner = db.effective_page_banner(conn, "Basketball", name="Basketball")
        assert banner["kind"] == "upload"

    def test_get_page_banner_is_untouched_by_any_of_this(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        assert db.get_page_banner(conn, "Basketball") is None


class TestExplicitClear:
    """Confirmed via AskUserQuestion: flairs must stay genuinely
    removable -- "Clear banner" stores an explicit marker, not just a
    blank-out, so the flair can't silently reappear once its stored
    override is gone."""

    def test_cleared_page_returns_none_even_with_a_matching_name(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.set_page_banner_cleared(conn, "Basketball")
        assert db.effective_page_banner(conn, "Basketball", name="Basketball") is None

    def test_get_page_banner_still_reads_a_cleared_page_as_none(self, conn):
        db.set_page_banner_cleared(conn, "Basketball")
        assert db.get_page_banner(conn, "Basketball") is None

    def test_explicitly_cleared_flag_itself(self, conn):
        assert db._page_banner_explicitly_cleared(conn, "Basketball") is False
        db.set_page_banner_cleared(conn, "Basketball")
        assert db._page_banner_explicitly_cleared(conn, "Basketball") is True

    def test_an_upload_after_clearing_still_wins(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.set_page_banner_cleared(conn, "Basketball")
        db.set_page_banner(conn, "Basketball", {"kind": "upload", "image_b64": "", "image_type": "jpeg"})
        banner = db.effective_page_banner(conn, "Basketball", name="Basketball")
        assert banner["kind"] == "upload"


class TestBannerForObjectInheritsLabelFlair:
    def test_task_tagged_with_a_matching_label_gets_its_flair(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        db.upsert_task(conn, {
            "uid": "t1", "title": "Random title", "description": "", "status": "active",
            "tags": ["Basketball"], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert banner is not None
        assert "/flairs/basketball" in banner["image_url"]
        assert banner["scope"] == "Basketball"

    def test_a_labels_own_cleared_banner_blocks_inheritance_too(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        db.set_page_banner_cleared(conn, "Basketball")
        db.upsert_task(conn, {
            "uid": "t1", "title": "Random title", "description": "", "status": "active",
            "tags": ["Basketball"], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert banner is None

    def test_matched_label_with_no_photo_configured_falls_through(self, conn):
        # The label matches the keyword table, but the operator hasn't
        # placed basketball.jpg yet -- must fall through to the task's
        # own name (which matches nothing here) rather than erroring.
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        db.upsert_task(conn, {
            "uid": "t1", "title": "Quarterly sync", "description": "", "status": "active",
            "tags": ["Basketball"], "created_at": _now(),
        })
        assert db.banner_for_task(conn, db.get_task(conn, "t1")) is None


class TestBannerForObjectOwnNameFallback:
    def test_no_label_at_all_falls_back_to_its_own_title(self, conn, flairs_dir):
        _put(flairs_dir, "yoga")
        db.upsert_task(conn, {
            "uid": "t1", "title": "Evening yoga session", "description": "", "status": "active",
            "tags": [], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert banner is not None
        assert "/flairs/yoga" in banner["image_url"]
        assert banner["scope"] == "task"

    def test_labels_own_banner_empty_no_match_falls_back_to_own_title(self, conn, flairs_dir):
        _put(flairs_dir, "yoga")
        db.upsert_label_config(conn, {"name": "Meeting Room", "created_at": _now()})
        db.upsert_task(conn, {
            "uid": "t1", "title": "Evening yoga session", "description": "", "status": "active",
            "tags": ["Meeting Room"], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert banner is not None
        assert "/flairs/yoga" in banner["image_url"]

    def test_event_own_title_also_matches(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_event(conn, {
            "uid": "e1", "title": "Basketball with friends", "description": "", "start_at": None,
            "end_at": None, "all_day": False, "status": "active", "tags": [],
            "created_at": _now(), "updated_at": _now(),
        })
        banner = db.banner_for_object(conn, "event", db.get_event(conn, "e1"))
        assert banner is not None
        assert "/flairs/basketball" in banner["image_url"]

    def test_no_match_at_all_is_none_not_an_error(self, conn, flairs_dir):
        db.upsert_task(conn, {
            "uid": "t1", "title": "Quarterly OKR sync", "description": "", "status": "active",
            "tags": [], "created_at": _now(),
        })
        assert db.banner_for_task(conn, db.get_task(conn, "t1")) is None


class TestBannerForObjectDescriptionFallback:
    """2026-09-29 (direct request: "could we include the description as a
    valid place to search?") -- the object's-own-title tier now also
    tries its own description, but only as a backstop (confirmed via
    AskUserQuestion): title stays the dominant signal, description is
    only ever consulted once the title itself has produced nothing
    usable (no keyword match at all, or a match with no photo configured
    yet) -- never weighed equally against it."""

    def test_title_with_no_match_falls_back_to_description(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_task(conn, {
            "uid": "t1", "title": "Evening plans", "description": "Playing basketball with friends",
            "status": "active", "tags": [], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert banner is not None
        assert "/flairs/basketball" in banner["image_url"]
        assert banner["scope"] == "task"

    def test_title_matches_but_has_no_photo_still_tries_description(self, conn, flairs_dir):
        # "yoga" matches the title's own keyword, but no yoga.jpg has been
        # placed under flairs_dir -- same "matched but no image = keep
        # falling through" rule every other tier already applies.
        _put(flairs_dir, "basketball")
        db.upsert_task(conn, {
            "uid": "t1", "title": "Yoga session", "description": "Followed by basketball practice",
            "status": "active", "tags": [], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert banner is not None
        assert "/flairs/basketball" in banner["image_url"]

    def test_a_real_title_match_wins_over_a_description_match(self, conn, flairs_dir):
        _put(flairs_dir, "yoga")
        _put(flairs_dir, "basketball")
        db.upsert_task(conn, {
            "uid": "t1", "title": "Yoga session", "description": "Then maybe basketball later",
            "status": "active", "tags": [], "created_at": _now(),
        })
        banner = db.banner_for_task(conn, db.get_task(conn, "t1"))
        assert "/flairs/yoga" in banner["image_url"]

    def test_neither_title_nor_description_matches_falls_through(self, conn, flairs_dir):
        db.upsert_task(conn, {
            "uid": "t1", "title": "Quarterly OKR sync", "description": "Review last quarter's numbers",
            "status": "active", "tags": [], "created_at": _now(),
        })
        assert db.banner_for_task(conn, db.get_task(conn, "t1")) is None

    def test_event_description_fallback_too(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_event(conn, {
            "uid": "e1", "title": "Evening out", "description": "Basketball with the team",
            "start_at": None, "end_at": None, "all_day": False, "status": "active", "tags": [],
            "created_at": _now(), "updated_at": _now(),
        })
        banner = db.banner_for_object(conn, "event", db.get_event(conn, "e1"))
        assert banner is not None
        assert "/flairs/basketball" in banner["image_url"]

    def test_empty_description_is_a_no_op_not_an_error(self, conn, flairs_dir):
        db.upsert_task(conn, {
            "uid": "t1", "title": "Quarterly OKR sync", "description": "", "status": "active",
            "tags": [], "created_at": _now(),
        })
        assert db.banner_for_task(conn, db.get_task(conn, "t1")) is None


class TestContactsAreExcluded:
    def test_contact_named_like_a_flair_keyword_gets_no_banner(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_contact(conn, {
            "uid": "c1", "full_name": "Basketball Jones", "tags": [], "created_at": _now(),
        })
        contact = db.get_contact(conn, "c1")
        banner = db.banner_for_object(conn, "contact", contact)
        assert banner is None

    def test_contact_tagged_with_a_matching_label_still_inherits_the_labels_own_flair(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        db.upsert_contact(conn, {
            "uid": "c1", "full_name": "Random Person", "tags": ["Basketball"], "created_at": _now(),
        })
        contact = db.get_contact(conn, "c1")
        banner = db.banner_for_object(conn, "contact", contact)
        assert banner is not None
        assert "/flairs/basketball" in banner["image_url"]


class TestLabelPageOwnBanner:
    def test_label_page_shows_its_flair_by_default(self, conn, flairs_dir):
        _put(flairs_dir, "yoga")
        db.upsert_label_config(conn, {"name": "Yoga", "has_dashboard": 1, "created_at": _now()})
        body = label_pages.label_page("Yoga", _request("/labels/Yoga"), conn=conn).body.decode()
        assert "/flairs/yoga" in body

    def test_has_own_banner_is_true_for_a_flair_default_too(self, conn, flairs_dir):
        _put(flairs_dir, "yoga")
        db.upsert_label_config(conn, {"name": "Yoga", "has_dashboard": 1, "created_at": _now()})
        resp = label_pages.label_page("Yoga", _request("/labels/Yoga"), conn=conn)
        assert resp.context["has_own_banner"] is True

    def test_label_with_no_match_has_no_own_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Quarterly Sync", "has_dashboard": 1, "created_at": _now()})
        resp = label_pages.label_page("Quarterly Sync", _request("/labels/Quarterly Sync"), conn=conn)
        assert resp.context["has_own_banner"] is False

    def test_group_page_matches_against_its_plain_name_not_its_prefixed_key(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Hoops", "label_group": "Basketball", "created_at": _now()})
        db.ensure_group(conn, "Basketball")
        body = label_pages.group_page("Basketball", _request("/groups/Basketball"), conn=conn).body.decode()
        assert "/flairs/basketball" in body


class TestBannerEditorRoute:
    def test_editor_shows_a_flair_as_the_plain_current_banner(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        body = banners_router.banner_editor(_request("/banners/editor"), scope="Basketball", conn=conn).body.decode()
        assert "/flairs/basketball" in body
        assert "No banner set yet" not in body

    def test_editor_resolves_a_groups_plain_name_through_its_prefixed_scope(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Hoops", "label_group": "Basketball", "created_at": _now()})
        db.ensure_group(conn, "Basketball")
        key = db.group_page_key("Basketball")
        body = banners_router.banner_editor(_request("/banners/editor"), scope=key, conn=conn).body.decode()
        assert "/flairs/basketball" in body

    def test_home_scope_never_gets_a_flair(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        body = banners_router.banner_editor(_request("/banners/editor"), scope="", conn=conn).body.decode()
        assert "No banner set yet" in body

    def test_clear_banner_button_present_when_a_banner_is_showing(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        body = banners_router.banner_editor(_request("/banners/editor"), scope="Basketball", conn=conn).body.decode()
        assert "/banners/remove" in body
        assert "Clear</button>" in body
        assert "Remove</button>" not in body

    def test_remove_route_stores_the_explicit_clear_marker_not_a_plain_blank(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        banners_router.remove_banner(scope="Basketball", page_url="/labels/Basketball", conn=conn)
        assert db._page_banner_explicitly_cleared(conn, "Basketball") is True
        assert db.effective_page_banner(conn, "Basketball", name="Basketball") is None

    def test_clearing_then_reopening_the_editor_shows_no_banner_set(self, conn, flairs_dir):
        _put(flairs_dir, "basketball")
        db.upsert_label_config(conn, {"name": "Basketball", "created_at": _now()})
        banners_router.remove_banner(scope="Basketball", page_url="/labels/Basketball", conn=conn)
        body = banners_router.banner_editor(_request("/banners/editor"), scope="Basketball", conn=conn).body.decode()
        assert "No banner set yet" in body
        assert "/flairs/basketball" not in body
