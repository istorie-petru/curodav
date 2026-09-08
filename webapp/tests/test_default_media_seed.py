"""main._seed_default_media (2026-09-07, direct request) -- first-run
defaults for the global page banner, the four seasonal task/event banners,
and the app avatar, sourced from repo-root pictures/*.jpg. Covered as a
pure (conn, pictures_dir) function rather than by booting the whole app --
lifespan's own wiring (calling it once at startup, inside a try/except so a
failure here can't refuse to boot the app) isn't re-tested here since it's
a two-line, hard-to-get-wrong call site."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db, main


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_pictures(tmp_path, names):
    pics = tmp_path / "pictures"
    pics.mkdir(parents=True)
    for name in names:
        (pics / name).write_bytes(f"bytes-for-{name}".encode())
    return pics


_ALL_FILES = ["banner_51.jpg", "avatar.jpg", "spring_51.jpg", "summer_51.jpg", "autumn_51.jpg", "winter_51.jpg"]


class TestSeedsAllFiveDefaults:
    def test_seeds_the_global_page_banner(self, conn, tmp_path):
        pics = _write_pictures(tmp_path, _ALL_FILES)
        main._seed_default_media(conn, pics)
        banner = db.get_page_banner(conn, db.PAGE_HEADER_BANNER_SCOPE)
        assert banner["kind"] == "upload"
        assert banner["image_type"] == "jpeg"

    def test_seeds_all_four_season_banners(self, conn, tmp_path):
        pics = _write_pictures(tmp_path, _ALL_FILES)
        main._seed_default_media(conn, pics)
        for season, scope in db.SEASON_BANNER_SCOPES.items():
            banner = db.get_page_banner(conn, scope)
            assert banner is not None, f"{season} banner not seeded"

    def test_seeds_the_avatar(self, conn, tmp_path):
        pics = _write_pictures(tmp_path, _ALL_FILES)
        main._seed_default_media(conn, pics)
        photo = db.get_profile_photo(conn)
        assert photo is not None
        assert photo["photo_type"] == "jpeg"


class TestOneTimeOnly:
    def test_does_not_reseed_once_the_flag_is_set(self, conn, tmp_path):
        pics = _write_pictures(tmp_path, _ALL_FILES)
        main._seed_default_media(conn, pics)
        # User removes the seeded default and sets their own -- a second
        # call (e.g. a restart) must not stomp on that.
        db.set_profile_photo(conn, "dXNlci1jaG9zZW4=", "png")
        main._seed_default_media(conn, pics)
        photo = db.get_profile_photo(conn)
        assert photo["photo_type"] == "png"

    def test_seeds_at_most_once_even_across_two_fresh_calls_with_different_dirs(self, conn, tmp_path):
        pics_a = _write_pictures(tmp_path / "a", _ALL_FILES)
        main._seed_default_media(conn, pics_a)
        db.clear_page_banner(conn, db.PAGE_HEADER_BANNER_SCOPE)
        pics_b = _write_pictures(tmp_path / "b", _ALL_FILES)
        main._seed_default_media(conn, pics_b)
        # The flag from the first call already blocked the second entirely --
        # a banner deliberately cleared afterward stays cleared, not
        # reseeded from pics_b.
        assert db.get_page_banner(conn, db.PAGE_HEADER_BANNER_SCOPE) is None


class TestMissingFilesAreSkippedNotFatal:
    def test_missing_pictures_directory_does_not_raise(self, conn, tmp_path):
        main._seed_default_media(conn, tmp_path / "does-not-exist")
        assert db.get_page_banner(conn, db.PAGE_HEADER_BANNER_SCOPE) is None
        assert db.get_profile_photo(conn) is None

    def test_partial_directory_seeds_only_what_it_finds(self, conn, tmp_path):
        pics = _write_pictures(tmp_path, ["banner_51.jpg", "summer_51.jpg"])
        main._seed_default_media(conn, pics)
        assert db.get_page_banner(conn, db.PAGE_HEADER_BANNER_SCOPE) is not None
        assert db.get_page_banner(conn, db.SEASON_BANNER_SCOPES["summer"]) is not None
        assert db.get_page_banner(conn, db.SEASON_BANNER_SCOPES["winter"]) is None
        assert db.get_profile_photo(conn) is None
        # The one-time flag is still set even though the directory was
        # partial -- a later restart with the missing files added still
        # won't retroactively seed them (documented tradeoff, matches
        # "first setup only" per direct instruction).
        assert db.get_app_meta(conn, main._DEFAULT_MEDIA_SEEDED_KEY) == "1"
