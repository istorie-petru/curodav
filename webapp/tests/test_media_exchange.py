"""Media lists in open formats: MyAnimeList XML, Letterboxd CSV and Curodav's JSON, out and back in."""

from __future__ import annotations

import json

import pytest

from src import db, media_exchange


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


MAL_EXPORT = b"""<?xml version="1.0" encoding="UTF-8" ?>
<myanimelist>
  <myinfo><user_export_type>1</user_export_type></myinfo>
  <anime>
    <series_animedb_id>52991</series_animedb_id>
    <series_title><![CDATA[Sousou no Frieren]]></series_title>
    <series_type>TV</series_type>
    <series_episodes>28</series_episodes>
    <my_watched_episodes>10</my_watched_episodes>
    <my_start_date>2023-10-01</my_start_date>
    <my_finish_date>0000-00-00</my_finish_date>
    <my_score>9</my_score>
    <my_status>Watching</my_status>
    <my_times_watched>0</my_times_watched>
  </anime>
</myanimelist>
"""

LETTERBOXD_DIARY = b"""Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
2024-03-02,Dune: Part Two,2024,https://boxd.it/abc,4.5,,"sf, cinema",2024-03-01
"""


def test_a_myanimelist_export_becomes_tracked_anime(conn):
    assert media_exchange.import_file(conn, MAL_EXPORT, "animelist.xml") == (1, 0)
    [c] = db.list_citations(conn)
    assert (c["type"], c["title"], c["status"], c["progress"], c["progress_total"], c["score"], c["started_on"], c["finished_on"]) == (
        "anime", "Sousou no Frieren", "current", 10, 28, 90.0, "2023-10-01", "")
    assert db.external_ids(c) == {"mal": "52991"}


def test_importing_the_same_list_again_updates_instead_of_duplicating(conn):
    media_exchange.import_mal(conn, MAL_EXPORT)
    assert media_exchange.import_mal(conn, MAL_EXPORT.replace(b"<my_watched_episodes>10", b"<my_watched_episodes>12")) == (0, 1)
    assert [c["progress"] for c in db.list_citations(conn)] == [12]


def test_the_anime_list_exports_as_myanimelist_xml_and_reads_back(conn, tmp_path):
    media_exchange.import_mal(conn, MAL_EXPORT)
    xml = media_exchange.mal_xml(conn, "anime")
    assert b"<my_status>Watching</my_status>" in xml and b"<series_animedb_id>52991</series_animedb_id>" in xml and b"<my_score>9</my_score>" in xml
    with db.connect(tmp_path / "other.sqlite") as other:
        assert media_exchange.import_mal(other, xml) == (1, 0)
        assert db.list_citations(other)[0]["progress"] == 10


def test_a_letterboxd_diary_becomes_watched_films(conn):
    assert media_exchange.import_file(conn, LETTERBOXD_DIARY, "diary.csv") == (1, 0)
    [c] = db.list_citations(conn)
    assert (c["type"], c["title"], c["year"], c["status"], c["score"], c["finished_on"], c["keywords"]) == (
        "film", "Dune: Part Two", "2024", "finished", 90.0, "2024-03-01", ["sf", "cinema"])


def test_a_letterboxd_watchlist_becomes_films_to_watch(conn):
    media_exchange.import_letterboxd(conn, b"Date,Name,Year,Letterboxd URI\n2024-01-01,Perfect Days,2023,https://boxd.it/x\n")
    assert db.list_citations(conn)[0]["status"] == "planned"


def test_films_export_in_letterboxd_import_columns(conn):
    media_exchange.import_letterboxd(conn, LETTERBOXD_DIARY)
    lines = media_exchange.letterboxd_csv(conn).decode().splitlines()
    assert lines[0] == ",".join(media_exchange.LETTERBOXD_COLUMNS)
    assert lines[1].startswith("Dune: Part Two,2024,,4.5,2024-03-01,false")


def test_the_json_file_carries_kinds_criteria_and_ratings_and_restores_them(conn, tmp_path):
    kind = db.save_media_kind(conn, {"name": "Game", "verb": "play", "unit": "hours"})
    crit = db.save_rating_criterion(conn, "Story", 2, [])
    uid = db.upsert_citation(conn, {"title": "Outer Wilds", "type": f"custom:{kind}", "status": "finished"})
    db.set_citation_ratings(conn, uid, {crit: 95.0})
    data = media_exchange.media_json(conn)
    with db.connect(tmp_path / "other.sqlite") as other:
        assert media_exchange.import_json(other, data) == (1, 0)
        assert media_exchange.import_json(other, data) == (0, 1)
        assert db.kind_of(other, f"custom:{kind}").name == "Game"
        assert db.citation_ratings(other, uid) == {crit: 95.0}


def test_a_json_file_from_elsewhere_is_refused(conn):
    with pytest.raises(ValueError):
        media_exchange.import_json(conn, json.dumps({"hello": 1}).encode())
