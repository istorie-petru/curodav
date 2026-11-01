"""The OPDS 1.2 catalogue of the book library, for e-book readers (KOReader, Moon+ Reader, Librera, Calibre-Web).

Readers cannot use the login page, so every path here asks for the Curodav user name and password with HTTP Basic, only
over HTTPS (or from this machine), under the same failed-login limit as the login page. The session cookie is never read.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import base64
import binascii
from datetime import timezone
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .. import auth, clock, media_books
from ..deps import get_db

router = APIRouter(prefix="/opds", tags=["opds"])

PAGE = 50
NAV = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ = "application/atom+xml;profile=opds-catalog;kind=acquisition"
_REALM = 'Basic realm="Curodav library", charset="UTF-8"'


def _local(request: Request) -> bool:
    return bool(request.client) and request.client.host in ("127.0.0.1", "::1")


def require_reader(request: Request, conn=Depends(get_db)):
    """The Basic sign-in of every OPDS path. Answers 401 with a challenge, 403 over plain HTTP, 429 when rate limited."""
    settings = getattr(request.app.state, "settings", None)
    if not auth.auth_enabled(settings, conn) or auth.skip_auth_applies(settings, request.scope):
        return conn
    if request.url.scheme != "https" and not _local(request):
        raise HTTPException(403, "The library feed needs HTTPS")
    key = auth.client_ip(request)
    if auth.login_rate_limited(key):
        raise HTTPException(429, "Too many failed sign-ins; try again later")
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    try:
        user, _, password = base64.b64decode(value.strip()).decode("utf-8").partition(":") if scheme.lower() == "basic" else ("", "", "")
    except (binascii.Error, UnicodeDecodeError):
        user, password = "", ""
    if not auth.verify_credentials(settings, user, password, conn):
        if user or password:
            auth.record_failed_login(key)
        raise HTTPException(401, "Sign in", headers={"WWW-Authenticate": _REALM})
    auth.clear_login_attempts(key)
    return conn


def _now() -> str:
    return clock.now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed(feed_id: str, title: str, kind: str, entries: list[str], links: list[tuple[str, str, str]] = ()) -> Response:
    head = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/" xmlns:opds="http://opds-spec.org/2010/catalog" '
            'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">',
            f"  <id>urn:curodav:opds:{escape(feed_id)}</id>", f"  <title>{escape(title)}</title>", f"  <updated>{_now()}</updated>",
            "  <author><name>Curodav</name></author>",
            f'  <link rel="start" href="/opds" type="{NAV}"/>',
            f'  <link rel="self" href="/opds/{escape(feed_id)}" type="{kind}"/>',
            '  <link rel="search" href="/opds/search.xml" type="application/opensearchdescription+xml"/>']
    head += [f'  <link rel="{rel}" href={quoteattr(href)} type="{mime}"/>' for rel, href, mime in links]
    return Response("\n".join(head + entries + ["</feed>"]) + "\n", media_type=kind + ";charset=utf-8")


def _nav_entry(entry_id: str, title: str, href: str, content: str = "") -> str:
    return (f"  <entry><title>{escape(title)}</title><id>urn:curodav:opds:{escape(entry_id)}</id><updated>{_now()}</updated>"
            f'<link rel="subsection" href={quoteattr(href)} type="{ACQ}"/>'
            + (f'<content type="text">{escape(content)}</content>' if content else "") + "</entry>")


def _book_entry(b: dict) -> str:
    parts = [f"  <entry><title>{escape(b['title'])}</title><id>urn:uuid:{escape(b['uuid'])}</id>",
             f"<updated>{escape((b['last_modified'] or '')[:19].replace(' ', 'T'))}Z</updated>"]
    parts += [f"<author><name>{escape(a)}</name></author>" for a in b["authors"]]
    if b["pubdate"]:
        parts.append(f"<dc:issued>{escape(b['pubdate'][:10])}</dc:issued>")
    if b["publisher"]:
        parts.append(f"<dc:publisher>{escape(b['publisher'])}</dc:publisher>")
    parts += [f"<dc:language>{escape(lang)}</dc:language>" for lang in b["languages"]]
    if b["isbn"]:
        parts.append(f"<dc:identifier>urn:isbn:{escape(b['isbn'])}</dc:identifier>")
    parts += [f'<category term={quoteattr(t)} label={quoteattr(t)}/>' for t in b["tags"]]
    if b["comments"]:
        parts.append(f'<summary type="text">{escape(media_books._plain(b["comments"])[:2000])}</summary>')
    if b["cover"]:
        parts.append(f'<link rel="http://opds-spec.org/image" href="/opds/books/{b["uuid"]}/cover" type="image/jpeg"/>')
        parts.append(f'<link rel="http://opds-spec.org/image/thumbnail" href="/opds/books/{b["uuid"]}/cover" type="image/jpeg"/>')
    for f in b["formats"]:
        mime = media_books.MIME.get(f["format"], "application/octet-stream")
        parts.append(f'<link rel="http://opds-spec.org/acquisition" href="/opds/books/{b["uuid"]}/{f["format"].lower()}" type="{mime}" title="{f["format"]}"/>')
    parts.append("</entry>")
    return "".join(parts)


def _books(conn) -> list[dict]:
    lib = media_books.library(conn)
    if lib is None:
        raise HTTPException(404, "No book library is set up")
    return [b for b in lib.books() if b["formats"]]


def _paged(feed_id: str, title: str, books: list[dict], page: int, base: str) -> Response:
    page = max(page, 1)
    chunk = books[(page - 1) * PAGE: page * PAGE]
    links = []
    if page * PAGE < len(books):
        links.append(("next", f"{base}{'&' if '?' in base else '?'}page={page + 1}", ACQ))
    if page > 1:
        links.append(("previous", f"{base}{'&' if '?' in base else '?'}page={page - 1}", ACQ))
    return _feed(feed_id, title, ACQ, [_book_entry(b) for b in chunk], links)


@router.get("")
def root(conn=Depends(require_reader)):
    books = _books(conn)
    entries = [_nav_entry("recent", "Recently added", "/opds/recent", f"{len(books)} books"),
               _nav_entry("authors", "Authors", "/opds/authors"),
               _nav_entry("series", "Series", "/opds/series"),
               _nav_entry("tags", "Tags", "/opds/tags")]
    return _feed("root", "Curodav library", NAV, entries)


@router.get("/recent")
def recent(page: int = 1, conn=Depends(require_reader)):
    books = sorted(_books(conn), key=lambda b: b["id"], reverse=True)
    return _paged("recent", "Recently added", books, page, "/opds/recent")


@router.get("/search.xml", include_in_schema=False)
def search_description(conn=Depends(require_reader)):
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
            "<ShortName>Curodav</ShortName><Description>Search the Curodav library</Description>"
            f'<Url type="{ACQ}" template="/opds/search?q={{searchTerms}}"/></OpenSearchDescription>\n')
    return Response(body, media_type="application/opensearchdescription+xml")


@router.get("/search")
def search(q: str = "", page: int = 1, conn=Depends(require_reader)):
    words = [w.lower() for w in q.split() if w]
    found = [b for b in _books(conn) if all(w in " ".join([b["title"], *b["authors"], *b["tags"], b["series"], b["isbn"]]).lower() for w in words)]
    return _paged("search", f"Search: {q}", found, page, f"/opds/search?q={quote(q)}")


def _group(key: str, books: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for b in books:
        values = b["authors"] if key == "authors" else (b["tags"] if key == "tags" else ([b["series"]] if b["series"] else []))
        for v in values:
            groups.setdefault(v, []).append(b)
    return dict(sorted(groups.items(), key=lambda kv: kv[0].lower()))


_GROUP_TITLES = {"authors": "Authors", "series": "Series", "tags": "Tags"}


@router.get("/{key}")
def groups(key: str, conn=Depends(require_reader)):
    if key not in _GROUP_TITLES:
        raise HTTPException(404)
    found = _group(key, _books(conn))
    entries = [_nav_entry(f"{key}:{name}", name, f"/opds/{key}/{quote(name, safe='')}", f"{len(items)} books") for name, items in found.items()]
    return _feed(key, _GROUP_TITLES[key], NAV, entries)


@router.get("/{key}/{name}")
def group_books(key: str, name: str, page: int = 1, conn=Depends(require_reader)):
    if key not in _GROUP_TITLES:
        raise HTTPException(404)
    books = _group(key, _books(conn)).get(name, [])
    if key == "series":
        books = sorted(books, key=lambda b: b["series_index"] or 0)
    return _paged(f"{key}/{quote(name, safe='')}", name, books, page, f"/opds/{key}/{quote(name, safe='')}")


def _book(conn, book_uuid: str) -> dict:
    lib = media_books.library(conn)
    b = lib.book(book_uuid) if lib else None
    if b is None:
        raise HTTPException(404)
    return b


@router.get("/books/{book_uuid}/cover")
def cover(book_uuid: str, conn=Depends(require_reader)):
    b = _book(conn, book_uuid)
    if not b["cover"] or not b["cover"].is_file():
        raise HTTPException(404)
    return FileResponse(b["cover"], media_type="image/jpeg")


@router.get("/books/{book_uuid}/{fmt}")
def download(book_uuid: str, fmt: str, conn=Depends(require_reader)):
    b = _book(conn, book_uuid)
    f = next((f for f in b["formats"] if f["format"] == fmt.upper() and f["path"].is_file()), None)
    if f is None:
        raise HTTPException(404)
    return FileResponse(f["path"], media_type=media_books.MIME.get(f["format"], "application/octet-stream"), filename=f["path"].name)
