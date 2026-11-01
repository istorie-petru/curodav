"""Automatic details and covers for library entries from public services: Open Library, Crossref, AniList, TVmaze, and TMDB
(with a key) or the iTunes search for films.

Only these fixed hosts are ever asked, and covers are only downloaded from their image hosts.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import html
import io
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from .log import get_logger

log = get_logger("media")

TIMEOUT = 8
MAX_COVER_BYTES = 6 * 1024 * 1024
COVER_HOSTS = ("covers.openlibrary.org", "s4.anilist.co", "static.tvmaze.com", "image.tmdb.org")
COVER_HOST_SUFFIXES = (".mzstatic.com",)
USER_AGENT = "Curodav library (self-hosted)"
PROVIDERS = {"openlibrary": "Open Library", "crossref": "Crossref", "anilist": "AniList", "tvmaze": "TVmaze", "tmdb": "TMDB", "itunes": "iTunes"}


class LookupError_(Exception):
    """A service could not be reached or answered something unreadable."""


def _fetch(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (fixed https hosts only)
            return response.read(MAX_COVER_BYTES + 1)
    except Exception as exc:  # network, TLS, HTTP status: all mean "not reachable now"
        raise LookupError_(str(exc)) from exc


def _json(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    try:
        return json.loads(_fetch(url, data, headers))
    except ValueError as exc:
        raise LookupError_("unreadable answer") from exc


def _text(value: Any) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""))
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def split_name(name: str) -> dict[str, str]:
    """"Ursula K. Le Guin" into family "Le Guin" and given "Ursula K."; a "Family, Given" name keeps its order."""
    name = " ".join((name or "").split())
    if "," in name:
        family, _, given = name.partition(",")
        return {"family": family.strip(), "given": given.strip()}
    parts = name.split(" ")
    if len(parts) == 1:
        return {"family": name, "given": ""}
    cut = len(parts) - 1
    while cut > 1 and parts[cut - 1].lower() in ("le", "la", "de", "da", "van", "von", "der", "del", "di", "du"):
        cut -= 1
    return {"family": " ".join(parts[cut:]), "given": " ".join(parts[:cut])}


def _candidate(**fields: Any) -> dict[str, Any]:
    base = {"provider": "", "id": "", "title": "", "subtitle": "", "authors": [], "year": "", "publisher": "", "isbn": "", "doi": "",
            "container_title": "", "volume": "", "issue": "", "pages": "", "url": "", "total": 0, "summary": "", "cover_url": "", "type": ""}
    base.update({k: v for k, v in fields.items() if v not in (None, "")})
    return base


def _openlibrary(q: str, isbn: str = "") -> list[dict[str, Any]]:
    params = {"limit": "8", "fields": "key,title,subtitle,author_name,first_publish_year,isbn,publisher,number_of_pages_median,cover_i"}
    params["isbn" if isbn else "q"] = isbn or q
    data = _json("https://openlibrary.org/search.json?" + urllib.parse.urlencode(params))
    out = []
    for d in data.get("docs", [])[:8]:
        out.append(_candidate(provider="openlibrary", id=d.get("key", ""), type="book", title=d.get("title", ""), subtitle=d.get("subtitle", ""),
                              authors=[split_name(a) for a in d.get("author_name", [])[:4]], year=str(d.get("first_publish_year") or ""),
                              publisher=(d.get("publisher") or [""])[0], isbn=isbn or next((i for i in d.get("isbn", []) if len(i) == 13), ""),
                              total=d.get("number_of_pages_median") or 0,
                              cover_url=f"https://covers.openlibrary.org/b/id/{d['cover_i']}-L.jpg" if d.get("cover_i") else ""))
    return out


def _crossref_item(d: dict[str, Any]) -> dict[str, Any]:
    parts = ((d.get("issued") or {}).get("date-parts") or [[None]])[0]
    return _candidate(provider="crossref", id=d.get("DOI", ""), type="article-journal", title=(d.get("title") or [""])[0],
                      authors=[{"family": a.get("family", ""), "given": a.get("given", "")} for a in d.get("author", [])[:8] if a.get("family") or a.get("given")],
                      year=str(parts[0] or "") if parts else "", container_title=(d.get("container-title") or [""])[0], volume=d.get("volume", ""),
                      issue=d.get("issue", ""), pages=d.get("page", ""), doi=d.get("DOI", ""), url=d.get("URL", ""), publisher=d.get("publisher", ""),
                      summary=_text(d.get("abstract", "")))


def _crossref(q: str, doi: str = "") -> list[dict[str, Any]]:
    if doi:
        data = _json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"))
        return [_crossref_item(data.get("message") or {})]
    data = _json("https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": q, "rows": "8"}))
    return [_crossref_item(d) for d in (data.get("message") or {}).get("items", [])[:8]]


_ANILIST_QUERY = """query ($q: String, $type: MediaType) { Page(perPage: 8) { media(search: $q, type: $type) {
  id siteUrl title { romaji english } startDate { year } episodes chapters volumes description(asHtml: false) coverImage { extraLarge large }
  staff(perPage: 3, sort: RELEVANCE) { edges { role node { name { full } } } } studios(isMain: true) { nodes { name } } } } }"""


def _anilist(q: str, kind: str) -> list[dict[str, Any]]:
    body = json.dumps({"query": _ANILIST_QUERY, "variables": {"q": q, "type": "MANGA" if kind == "manga" else "ANIME"}}).encode()
    data = _json("https://graphql.anilist.co", body, {"Content-Type": "application/json"})
    out = []
    for m in ((data.get("data") or {}).get("Page") or {}).get("media", []):
        title = m.get("title") or {}
        people = [e["node"]["name"]["full"] for e in (m.get("staff") or {}).get("edges", []) if kind == "manga" and "Story" in (e.get("role") or "")]
        studio = [n["name"] for n in (m.get("studios") or {}).get("nodes", [])]
        cover = m.get("coverImage") or {}
        out.append(_candidate(provider="anilist", id=str(m.get("id", "")), type=kind, title=title.get("english") or title.get("romaji") or "",
                              subtitle=title.get("romaji") if title.get("english") and title.get("romaji") != title.get("english") else "",
                              authors=[split_name(p) for p in people], publisher=", ".join(studio), year=str((m.get("startDate") or {}).get("year") or ""),
                              total=(m.get("chapters") if kind == "manga" else m.get("episodes")) or 0, url=m.get("siteUrl", ""),
                              summary=_text(m.get("description")), cover_url=cover.get("extraLarge") or cover.get("large") or ""))
    return out


def _tvmaze(q: str) -> list[dict[str, Any]]:
    data = _json("https://api.tvmaze.com/search/shows?" + urllib.parse.urlencode({"q": q}))
    out = []
    for hit in (data if isinstance(data, list) else [])[:8]:
        s = hit.get("show") or {}
        network = (s.get("network") or s.get("webChannel") or {}).get("name", "")
        out.append(_candidate(provider="tvmaze", id=str(s.get("id", "")), type="tv", title=s.get("name", ""), year=(s.get("premiered") or "")[:4],
                              publisher=network, url=s.get("url", ""), summary=_text(s.get("summary")),
                              cover_url=(s.get("image") or {}).get("original") or (s.get("image") or {}).get("medium") or ""))
    return out


def tvmaze_episode_count(show_id: str) -> int:
    try:
        return len(_json(f"https://api.tvmaze.com/shows/{int(show_id)}/episodes"))
    except (LookupError_, ValueError, TypeError):
        return 0


def _tmdb(q: str, key: str) -> list[dict[str, Any]]:
    data = _json("https://api.themoviedb.org/3/search/movie?" + urllib.parse.urlencode({"query": q, "api_key": key}))
    return [_candidate(provider="tmdb", id=str(m.get("id", "")), type="film", title=m.get("title", ""),
                       subtitle=m.get("original_title") if m.get("original_title") != m.get("title") else "", year=(m.get("release_date") or "")[:4],
                       summary=m.get("overview", ""), url=f"https://www.themoviedb.org/movie/{m.get('id')}",
                       cover_url=f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get("poster_path") else "")
            for m in data.get("results", [])[:8]]


def _itunes(q: str) -> list[dict[str, Any]]:
    data = _json("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": q, "media": "movie", "limit": "8"}))
    return [_candidate(provider="itunes", id=str(m.get("trackId", "")), type="film", title=m.get("trackName", ""),
                       authors=[split_name(m["artistName"])] if m.get("artistName") else [], year=(m.get("releaseDate") or "")[:4],
                       summary=m.get("longDescription", ""), url=m.get("trackViewUrl", ""),
                       cover_url=(m.get("artworkUrl100") or "").replace("100x100bb", "600x600bb"))
            for m in data.get("results", [])[:8]]


_ISBN = re.compile(r"^(97[89])?\d{9}[\dXx]$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def search(kind: str, q: str, tmdb_key: str = "") -> list[dict[str, Any]]:
    """Candidates for an entry of `kind` matching `q` (a title, an ISBN or a DOI). Raises LookupError_ when the service fails."""
    q = " ".join((q or "").split())[:200]
    if not q:
        return []
    bare = q.replace("-", "").replace(" ", "")
    if _DOI.match(q.removeprefix("https://doi.org/")):
        return _crossref("", q.removeprefix("https://doi.org/"))
    if kind in ("manga", "anime"):
        return _anilist(q, kind)
    if kind == "tv":
        return _tvmaze(q)
    if kind == "film":
        return _tmdb(q, tmdb_key) if tmdb_key else _itunes(q)
    if kind in ("article-journal", "conference-paper", "report"):
        return _crossref(q)
    return _openlibrary(q, bare if _ISBN.match(bare) else "")


def provider_for(kind: str, tmdb_key: str = "") -> str:
    if kind in ("manga", "anime"):
        return "anilist"
    if kind == "tv":
        return "tvmaze"
    if kind == "film":
        return "tmdb" if tmdb_key else "itunes"
    if kind in ("article-journal", "conference-paper", "report"):
        return "crossref"
    return "openlibrary"


def cover_allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host in COVER_HOSTS or host.endswith(COVER_HOST_SUFFIXES))


def to_webp(data: bytes, max_width: int = 600, max_height: int = 900) -> bytes | None:
    """Any image Pillow reads, shrunk to fit and saved as WebP; None for bytes that are not an image."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGBA") if img.mode in ("P", "LA") else img
            img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
            img.thumbnail((max_width, max_height))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=84)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


def download_cover(url: str, thumbnail: bool = False) -> bytes | None:
    """The cover at `url` as WebP, or None when the host is not a known image host, the download fails or it is no image."""
    if not cover_allowed(url):
        return None
    try:
        data = _fetch(url, headers={"Accept": "image/*"})
    except LookupError_ as exc:
        log.warning("Cover download from %s failed: %s", urllib.parse.urlsplit(url).hostname, exc)
        return None
    if len(data) > MAX_COVER_BYTES:
        return None
    return to_webp(data, 120, 180) if thumbnail else to_webp(data)


FILLABLE = ("title", "subtitle", "year", "container_title", "volume", "issue", "pages", "summary", "url")


def merge(current: dict[str, Any], found: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    """The fields to write from a chosen candidate: only blank ones unless `replace`."""
    out: dict[str, Any] = {}
    for key in FILLABLE:
        if found.get(key) and (replace or not current.get(key)):
            out[key] = str(found[key]).strip()
    if found.get("authors") and (replace or not current.get("authors")):
        out["authors"] = found["authors"]
    if found.get("total") and (replace or not current.get("progress_total")):
        out["progress_total"] = int(found["total"])
    return out
