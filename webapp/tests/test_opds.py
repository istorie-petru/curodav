"""The OPDS catalogue: its feeds list the books of the Calibre library, and its Basic sign-in refuses anything else."""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src import auth, calibre_library as cl, db, media_books
from src.routers import opds

ATOM = "{http://www.w3.org/2005/Atom}"


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        media_books.set_library_path(c, str(tmp_path / "books"))
        lib = media_books.library(c)
        a = lib.add_book(cl.BookMeta(title="The Dispossessed", authors=["Ursula K. Le Guin"], tags=["sf"], series="Hainish", isbn="9780060512750"))
        lib.add_format(a, b"PK\x03\x04", "epub")
        b = lib.add_book(cl.BookMeta(title="Vagabond 1", authors=["Takehiko Inoue"], tags=["manga"]))
        lib.add_format(b, b"PK", "cbz")
        lib.add_book(cl.BookMeta(title="No files", authors=["Nobody"]))
        auth.reset_rate_limits()
        yield c


def _titles(response) -> list[str]:
    root = ET.fromstring(response.body)
    return [e.findtext(f"{ATOM}title") for e in root.findall(f"{ATOM}entry")]


def test_recent_lists_the_books_that_have_files(conn):
    assert _titles(opds.recent(conn=conn)) == ["Vagabond 1", "The Dispossessed"]


def test_a_book_entry_links_its_file_for_download(conn):
    root = ET.fromstring(opds.search(q="dispossessed", conn=conn).body)
    links = [(l.get("rel"), l.get("type")) for l in root.find(f"{ATOM}entry").findall(f"{ATOM}link")]
    assert ("http://opds-spec.org/acquisition", "application/epub+zip") in links


def test_authors_series_and_tags_group_the_books(conn):
    assert _titles(opds.groups("authors", conn=conn)) == ["Takehiko Inoue", "Ursula K. Le Guin"]
    assert _titles(opds.group_books("tags", "manga", conn=conn)) == ["Vagabond 1"]
    assert _titles(opds.group_books("series", "Hainish", conn=conn)) == ["The Dispossessed"]


def test_the_file_is_served_from_the_library(conn):
    book = next(b for b in media_books.library(conn).books() if b["title"] == "Vagabond 1")
    assert str(opds.download(book["uuid"], "cbz", conn=conn).path).endswith(".cbz")


def _request(conn, header: str = "", scheme: str = "https", host: str = "203.0.113.5"):
    settings = SimpleNamespace(auth_username="reader", auth_password="s3cret-pass", deploy_mode="production", skip_auth=False, db_path=None)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)), scope={"server": ("0.0.0.0", 80), "client": (host, 1)},
                           url=SimpleNamespace(scheme=scheme), client=SimpleNamespace(host=host), headers={"authorization": header} if header else {})


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_the_feed_needs_the_curodav_user_and_password(conn):
    assert opds.require_reader(_request(conn, _basic("reader", "s3cret-pass")), conn) is conn
    with pytest.raises(HTTPException) as refused:
        opds.require_reader(_request(conn), conn)
    assert refused.value.status_code == 401 and "Basic" in refused.value.headers["WWW-Authenticate"]


def test_plain_http_from_another_machine_is_refused(conn):
    with pytest.raises(HTTPException) as refused:
        opds.require_reader(_request(conn, _basic("reader", "s3cret-pass"), scheme="http"), conn)
    assert refused.value.status_code == 403


def test_repeated_wrong_passwords_are_rate_limited(conn):
    for _ in range(auth.RATE_LIMIT_MAX_ATTEMPTS):
        with pytest.raises(HTTPException):
            opds.require_reader(_request(conn, _basic("reader", "wrong")), conn)
    with pytest.raises(HTTPException) as limited:
        opds.require_reader(_request(conn, _basic("reader", "s3cret-pass")), conn)
    assert limited.value.status_code == 429
