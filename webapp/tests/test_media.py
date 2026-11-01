"""Media in the library: kinds, tracking, the custom rating system, covers, automatic details and the now page."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from src import db, media, media_metadata
from src.routers import media as media_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _png(w=60, h=90) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


class _Upload:
    def __init__(self, data: bytes, filename="cover.png"):
        self.data, self.filename = data, filename

    async def read(self, size=-1):
        return self.data


def test_status_words_follow_the_kind():
    assert media.status_label("current", media.kind_for("anime").verb) == "Watching"
    assert media.status_label("finished", media.kind_for("book").verb) == "Read"
    assert media.status_label("planned", "play") == "To play"


def test_old_reading_statuses_are_understood():
    assert [media.normal_status(s) for s in ("to_read", "reading", "read", "dropped", "bogus")] == ["planned", "current", "finished", "dropped", ""]


def test_stepping_progress_starts_and_reaching_the_total_finishes():
    row = {"progress": 0, "progress_total": 3, "status": "planned", "started_on": "", "finished_on": ""}
    row.update(media.advance(row, 1, "2026-10-29"))
    assert (row["status"], row["started_on"], row["finished_on"]) == ("current", "2026-10-29", "")
    row.update(media.advance(row, 5, "2026-10-30"))
    assert (row["progress"], row["status"], row["finished_on"]) == (3, "finished", "2026-10-30")


def test_progress_never_goes_below_zero():
    assert media.advance({"progress": 0, "progress_total": 0, "status": ""}, -1, "2026-10-29")["progress"] == 0


def test_marking_finished_by_hand_fills_the_progress_and_dates():
    out = media.on_status_change({"progress": 4, "progress_total": 12, "status": "current", "started_on": "2026-10-01"}, "finished", "2026-10-29")
    assert out == {"finished_on": "2026-10-29", "progress": 12}


@pytest.mark.parametrize("scale,typed,stored,shown", [("stars5", "4", 80.0, "★★★★"), ("stars5half", "3.5", 70.0, "★★★½"),
                                                      ("points10", "7", 70.0, "7 / 10"), ("points100", "85", 85.0, "85 / 100")])
def test_ratings_are_stored_exactly_whatever_the_scale(scale, typed, stored, shown):
    assert media.from_scale(typed, scale) == stored
    assert media.stars(stored, scale) == shown


def test_changing_the_scale_keeps_ratings_meaningful():
    stored = media.from_scale("4", "stars5")
    assert media.to_scale(stored, "points10") == 8


def test_overall_is_the_weighted_mean_of_criteria_unless_set_by_hand():
    criteria = [{"uid": "story", "weight": 2}, {"uid": "art", "weight": 1}]
    assert media.overall(None, criteria, {"story": 90, "art": 60}) == 80
    assert media.overall(50, criteria, {"story": 90}) == 50
    assert media.overall(None, criteria, {}) is None


def test_criteria_apply_to_their_kinds_or_to_all():
    criteria = [{"uid": "a", "kinds": []}, {"uid": "b", "kinds": ["anime"]}]
    assert [c["uid"] for c in media.criteria_for(criteria, "book")] == ["a"]
    assert [c["uid"] for c in media.criteria_for(criteria, "anime")] == ["a", "b"]


def test_old_star_rating_becomes_a_score_and_status_is_renamed(tmp_path):
    from src import migrations_media

    with db.connect(tmp_path / "cache.sqlite") as conn:
        conn.execute("ALTER TABLE citations DROP COLUMN score")
        conn.execute("ALTER TABLE citations ADD COLUMN rating INTEGER NOT NULL DEFAULT 0")
        conn.execute("INSERT INTO citations (uid, title, status, rating) VALUES ('c1', 'Capital', 'reading', 4)")
        migrations_media.media_tracking(conn)
        migrations_media.media_tracking(conn)
        row = conn.execute("SELECT status, score FROM citations WHERE uid = 'c1'").fetchone()
        assert (row[0], row[1]) == ("current", 80.0)
        assert "rating" not in {r[1] for r in conn.execute("PRAGMA table_info(citations)")}


def test_the_window_saves_tracking_and_criteria_ratings(conn):
    from src.routers import notebook as notebook_router

    story = db.save_rating_criterion(conn, "Story", "2", ["anime"])
    db.set_rating_scale(conn, "points10")
    resp = notebook_router.create_citation(title="Frieren", type="anime", year="", container_title="", author_family=[], author_given=[],
                                           status="current", progress="3", progress_total="28", season="1", score="",
                                           crit_uid=[story], crit_value=["9"], x_requested_with="fetch", conn=conn)
    uid = json.loads(resp.body)["uid"]
    c = db.get_citation(conn, uid)
    assert (c["progress"], c["progress_total"], c["season"], c["status"]) == (3, 28, 1, "current")
    assert c["started_on"]
    assert db.citation_ratings(conn, uid) == {story: 90.0}
    assert db.overall_ratings(conn, [c])[uid] == 90.0


def test_only_books_and_manga_keep_uploaded_files(conn):
    from src.routers import notebook as notebook_router

    class _Pdf:
        filename = "a.pdf"

        class file:
            @staticmethod
            def read():
                return b"%PDF-1.4"

    resp = notebook_router.create_citation(title="Paper", type="article-journal", year="", container_title="", author_family=[], author_given=[],
                                           edition_uid="", ed_source="local", file=_Pdf(), x_requested_with="fetch", conn=conn)
    assert resp.status_code == 422
    assert db.page_citations(conn)["total"] == 0


def test_deleting_a_custom_kind_keeps_its_entries_as_other(conn):
    kind = db.save_media_kind(conn, {"name": "Game", "verb": "play", "unit": "hours", "icon": "gamepad-2"})
    uid = db.upsert_citation(conn, {"title": "Outer Wilds", "type": f"custom:{kind}"})
    assert db.kind_of(conn, f"custom:{kind}").verb == "play"
    db.delete_media_kind(conn, kind)
    assert db.get_citation(conn, uid)["type"] == "other"


def test_a_custom_cover_overrides_the_fetched_one_and_can_be_removed(conn):
    import asyncio

    uid = db.upsert_citation(conn, {"title": "Dune"})
    db.set_cover(conn, uid, media_metadata.to_webp(_png()), "fetched")
    fetched = db.cover_path(conn, uid)
    asyncio.run(media_router.upload_cover(uid, _Upload(_png(30, 45)), x_requested_with="fetch", conn=conn))
    custom = db.cover_path(conn, uid)
    assert custom != fetched and "custom" in custom.name
    media_router.remove_cover(uid, x_requested_with="fetch", conn=conn)
    assert db.cover_path(conn, uid) == fetched


def test_a_cover_that_is_not_an_image_is_refused(conn):
    import asyncio

    uid = db.upsert_citation(conn, {"title": "Dune"})
    resp = asyncio.run(media_router.upload_cover(uid, _Upload(b"not an image"), x_requested_with="fetch", conn=conn))
    assert resp.status_code == 422 and db.cover_path(conn, uid) is None


def test_deleting_an_entry_deletes_its_covers_and_ratings(conn):
    uid = db.upsert_citation(conn, {"title": "Dune"})
    db.set_cover(conn, uid, media_metadata.to_webp(_png()), "custom")
    path = db.cover_path(conn, uid)
    crit = db.save_rating_criterion(conn, "Story", 1, [])
    db.set_citation_ratings(conn, uid, {crit: 50.0})
    db.delete_citation(conn, uid)
    assert not path.exists() and db.citation_ratings(conn, uid) == {}


def test_covers_are_only_downloaded_from_known_image_hosts():
    assert media_metadata.cover_allowed("https://covers.openlibrary.org/b/id/1-L.jpg")
    assert media_metadata.cover_allowed("https://is1-ssl.mzstatic.com/image/x.jpg")
    assert not media_metadata.cover_allowed("http://covers.openlibrary.org/b/id/1-L.jpg")
    assert not media_metadata.cover_allowed("https://169.254.169.254/latest")
    assert not media_metadata.cover_allowed("https://evil.example/covers.openlibrary.org")


def test_names_are_split_into_family_and_given():
    assert media_metadata.split_name("Ursula K. Le Guin") == {"family": "Le Guin", "given": "Ursula K."}
    assert media_metadata.split_name("Tolkien, J. R. R.") == {"family": "Tolkien", "given": "J. R. R."}


def _fake_service(monkeypatch, answers: dict[str, object]):
    asked = []

    def fetch(url, data=None, headers=None):
        asked.append(url)
        for prefix, answer in answers.items():
            if url.startswith(prefix):
                return answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        raise media_metadata.LookupError_("offline")

    monkeypatch.setattr(media_metadata, "_fetch", fetch)
    return asked


def test_the_service_is_chosen_by_kind_and_an_isbn_or_doi(monkeypatch):
    asked = _fake_service(monkeypatch, {"https://": {}})
    for kind, q in (("book", "9780140449136"), ("book", "10.1000/xyz"), ("tv", "Severance"), ("film", "Dune")):
        media_metadata.search(kind, q)
    assert asked[0].startswith("https://openlibrary.org/search.json?") and "isbn=9780140449136" in asked[0]
    assert asked[1].startswith("https://api.crossref.org/works/10.1000/xyz")
    assert asked[2].startswith("https://api.tvmaze.com/search/shows")
    assert asked[3].startswith("https://itunes.apple.com/search")
    media_metadata.search("film", "Dune", tmdb_key="k")
    assert asked[4].startswith("https://api.themoviedb.org/3/search/movie")


def test_finding_details_makes_a_new_entry_with_its_cover(conn, monkeypatch):
    _fake_service(monkeypatch, {"https://covers.openlibrary.org/": _png()})
    found = media_metadata._candidate(provider="openlibrary", id="/works/1", type="book", title="The Dispossessed",
                                      authors=[{"family": "Le Guin", "given": "Ursula K."}], year="1974", publisher="Harper", total=387,
                                      cover_url="https://covers.openlibrary.org/b/id/1-L.jpg")
    resp = media_router.apply_lookup(choice=json.dumps(found), uid="", kind="book", replace="", x_requested_with="fetch", conn=conn)
    uid = json.loads(resp.body)["uid"]
    c = db.get_citation(conn, uid)
    assert (c["title"], c["year"], c["progress_total"], c["publisher"]) == ("The Dispossessed", "1974", 387, "Harper")
    assert db.cover_path(conn, uid) is not None
    assert db.external_ids(c) == {"openlibrary": "/works/1"}


def test_finding_details_fills_only_blank_fields_unless_replacing(conn, monkeypatch):
    _fake_service(monkeypatch, {})
    uid = db.upsert_citation(conn, {"title": "My title", "type": "anime"})
    found = media_metadata._candidate(provider="anilist", id="1", type="anime", title="Frieren", year="2023", total=28, summary="Elves.")
    media_router.apply_lookup(choice=json.dumps(found), uid=uid, kind="anime", replace="", x_requested_with="fetch", conn=conn)
    c = db.get_citation(conn, uid)
    assert (c["title"], c["year"], c["progress_total"], c["summary"]) == ("My title", "2023", 28, "Elves.")
    media_router.apply_lookup(choice=json.dumps(found), uid=uid, kind="anime", replace="1", x_requested_with="fetch", conn=conn)
    assert db.get_citation(conn, uid)["title"] == "Frieren"


def test_a_service_that_cannot_be_reached_is_reported_not_raised(conn, monkeypatch):
    _fake_service(monkeypatch, {})

    class _Req:
        pass

    monkeypatch.setattr(media_router.templates, "TemplateResponse", lambda name, ctx: ctx)
    ctx = media_router.lookup_modal(_Req(), kind="book", q="Dune", uid="", conn=conn)
    assert ctx["results"] == [] and "could not be reached" in ctx["error"]


def test_the_now_page_splits_reading_and_watching(conn, monkeypatch):
    db.upsert_citation(conn, {"title": "Dune", "type": "book", "status": "current"})
    db.upsert_citation(conn, {"title": "Frieren", "type": "anime", "status": "current"})
    db.upsert_citation(conn, {"title": "Next", "type": "film", "status": "planned"})
    monkeypatch.setattr(media_router.templates, "TemplateResponse", lambda name, ctx: ctx)
    ctx = media_router.now_page(object(), conn=conn)
    assert [c["title"] for c in ctx["reading"]] == ["Dune"]
    assert [c["title"] for c in ctx["watching"]] == ["Frieren"]
    assert [c["title"] for c in ctx["planned"]] == ["Next"]


def test_the_step_button_answers_with_the_new_progress(conn):
    uid = db.upsert_citation(conn, {"title": "Frieren", "type": "anime", "progress_total": 2})
    body = json.loads(media_router.step_progress(uid, step=2, x_requested_with="fetch", conn=conn).body)
    assert (body["progress"], body["status"], body["status_label"], body["percent"]) == (2, "finished", "Watched", 100)


def test_the_library_can_be_filtered_by_status_and_sorted_by_rating(conn):
    a = db.upsert_citation(conn, {"title": "A", "status": "current", "score": 40.0})
    b = db.upsert_citation(conn, {"title": "B", "status": "finished", "score": 90.0})
    db.upsert_citation(conn, {"title": "C"})
    assert [c["uid"] for c in db.page_citations(conn, statuses=["current"])["items"]] == [a]
    assert [c["title"] for c in db.page_citations(conn, sort="rating")["items"]] == ["B", "A", "C"]
    assert [c["title"] for c in db.page_citations(conn, statuses=["none"])["items"]] == ["C"]


def test_the_tmdb_key_is_kept_out_of_the_database(conn):
    db.set_tmdb_key(conn, "abc123")
    assert db.tmdb_key(conn) == "abc123"
    assert db.get_app_meta(conn, db.media.TMDB_KEY) is None
    db.set_tmdb_key(conn, "")
    assert db.tmdb_key(conn) == ""


def test_the_sources_table_names_each_kinds_service_store_and_export(conn):
    rows = {r["name"]: r for r in media_router._sources(conn)}
    assert (rows["Anime"]["details"], rows["Anime"]["stored"], rows["Anime"]["exports"]) == ("AniList", "Curodav", "MyAnimeList XML, JSON")
    assert rows["Film"]["details"] == "iTunes, TMDB once its key is saved"
    db.set_tmdb_key(conn, "k")
    assert media_router._sources(conn)[[r["name"] for r in media_router._sources(conn)].index("Film")]["details"] == "TMDB"


@pytest.mark.parametrize("type_key,row,text", [
    ("book", {"progress": 120, "progress_total": 387}, "p. 120 of 387 · 31%"),
    ("tv", {"progress": 10, "progress_total": 28, "season": 1}, "S1 · E10 of 28"),
    ("manga", {"progress": 45, "progress_total": 0}, "Ch. 45"),
    ("film", {"status": "finished", "finished_on": "2026-03-01"}, "Watched 2026-03-01"),
    ("film", {"status": "planned"}, ""),
])
def test_progress_is_worded_for_each_kind(type_key, row, text):
    assert media.progress_text(row, media.kind_for(type_key)) == text


def test_each_day_of_progress_is_logged_once_with_its_total_move(conn, monkeypatch):
    uid = db.upsert_citation(conn, {"title": "Frieren", "type": "anime", "progress_total": 28})
    monkeypatch.setattr(media_router, "_today", lambda: "2026-10-30")
    for _ in range(3):
        media_router.step_progress(uid, step=1, x_requested_with="fetch", conn=conn)
    monkeypatch.setattr(media_router, "_today", lambda: "2026-10-31")
    media_router.step_progress(uid, step=1, x_requested_with="fetch", conn=conn)
    assert db.progress_log(conn, uid) == [{"day": "2026-10-31", "delta": 1, "progress": 4}, {"day": "2026-10-30", "delta": 3, "progress": 3}]
    assert media.step_words(3, media.kind_for("anime")) == "+3 episodes" and media.step_words(1, media.kind_for("book")) == "+1 page"


def test_an_entry_carries_curodav_tags_and_the_library_filters_by_tag_and_shelf(conn):
    from src import tags as tag_store
    from src.routers import notebook as notebook_router

    conn.execute("INSERT INTO label_tags (name, label_name, color) VALUES ('sf', 'Reading list', 'blue')")
    conn.commit()
    body = notebook_router.create_citation(title="Dune", type="book", year="", container_title="", author_family=[], author_given=[],
                                           item_tags=["sf"], item_tags_field="1", x_requested_with="fetch", conn=conn).body
    uid = json.loads(body)["uid"]
    db.upsert_citation(conn, {"title": "Untagged"})
    assert tag_store.tags_for_object(conn, "media", uid) == ["sf"]
    assert [c["uid"] for c in db.page_citations(conn, tags=["SF"])["items"]] == [uid]
    assert [c["uid"] for c in db.page_citations(conn, shelves=["Reading list"])["items"]] == [uid]
    db.delete_citation(conn, uid)
    assert tag_store.tags_for_object(conn, "media", uid) == []


def test_a_shelf_page_links_to_its_library_entries_only_when_it_has_some(conn):
    from src.routers import label_pages

    conn.execute("INSERT INTO label_tags (name, label_name, color) VALUES ('sf', 'Reading list', 'blue')")
    conn.commit()
    assert label_pages._page_common(conn, "Reading list")["library_count"] == 0
    uid = db.upsert_citation(conn, {"title": "Dune"})
    from src import tags as tag_store
    tag_store.set_object_tags(conn, "media", uid, ["sf"])
    assert label_pages._page_common(conn, "Reading list")["library_count"] == 1
