"""A Calibre-compatible book library: the folder layout and metadata.db that Calibre and Calibre-Web read, written by Curodav.

Only Calibre's own tables are written (src/calibre_schema.sql), with the two SQL functions its triggers call. Curodav's own
data about a book lives in Curodav's database, joined by the book's Calibre uuid.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from xml.sax.saxutils import escape

SCHEMA = Path(__file__).with_name("calibre_schema.sql")
USER_VERSION = 27
PATH_LIMIT = 100
NO_DATE = "0101-01-01 00:00:00+00:00"
FORMATS = {"pdf": "PDF", "epub": "EPUB", "mobi": "MOBI", "azw3": "AZW3", "cbz": "CBZ", "cbr": "CBR", "cb7": "CB7", "djvu": "DJVU", "fb2": "FB2", "txt": "TXT",
           "azw": "AZW", "doc": "DOC", "docx": "DOCX", "odt": "ODT", "rtf": "RTF", "md": "MD", "chm": "CHM", "lit": "LIT"}
_ARTICLES = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)


class CalibreError(Exception):
    """The folder is not a library Curodav can write, or a write would break it."""


@dataclass
class BookMeta:
    title: str
    authors: list[str] = field(default_factory=list)  # display names, "Given Family"
    author_sorts: list[str] = field(default_factory=list)  # "Family, Given", same order
    pubdate: str = ""  # a year or an ISO date
    publisher: str = ""
    isbn: str = ""
    doi: str = ""
    tags: list[str] = field(default_factory=list)
    series: str = ""
    series_index: float = 1.0
    rating: int = 0  # Calibre's 0 to 10 (half stars)
    comments: str = ""
    languages: list[str] = field(default_factory=list)


def title_sort(title: str | None) -> str:
    """Calibre's default title sort: a leading English article moves to the end ("Left Hand of Darkness, The")."""
    title = (title or "").strip()
    m = _ARTICLES.match(title)
    return f"{title[m.end():]}, {m.group(1)}" if m and title[m.end():] else title


def author_sort(name: str) -> str:
    """Calibre's default author sort when none is given: the last word first ("Guin, Ursula K. Le")."""
    parts = name.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else name


def safe_name(text: str, limit: int = PATH_LIMIT) -> str:
    """A folder or file name as Calibre makes it: accents dropped, characters that are unsafe in paths replaced by _."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    plain = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in plain)
    plain = re.sub(r'[\\/:*?"<>|]', "_", plain).strip().strip(".")
    return (plain[:limit].rstrip() or "Unknown")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(sep=" ")


def _pubdate(value: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"\d{4}", value):
        return f"{value}-01-01 00:00:00+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return f"{value} 00:00:00+00:00"
    return NO_DATE


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.create_function("title_sort", 1, title_sort, deterministic=True)
    conn.create_function("uuid4", 0, lambda: str(uuid.uuid4()))
    # Calibre's views call these; registering them keeps a SELECT on a view from failing here.
    conn.create_function("books_list_filter", 1, lambda _book: 1)
    conn.create_aggregate("concat", 1, _Concat)
    conn.create_aggregate("sortconcat", 2, _SortConcat)
    conn.execute("PRAGMA foreign_keys = OFF")
    return conn


class _Concat:
    def __init__(self) -> None:
        self.items: list[str] = []

    def step(self, value: Any) -> None:
        if value is not None:
            self.items.append(str(value))

    def finalize(self) -> str:
        return ",".join(self.items)


class _SortConcat:
    def __init__(self) -> None:
        self.items: list[tuple[Any, str]] = []

    def step(self, order: Any, value: Any) -> None:
        if value is not None:
            self.items.append((order, str(value)))

    def finalize(self) -> str:
        return "|".join(v for _, v in sorted(self.items, key=lambda x: x[0]))


def create(folder: Path) -> Path:
    """Makes an empty library in `folder` (which must be empty or absent) and returns the metadata.db path."""
    folder.mkdir(parents=True, exist_ok=True)
    db_path = folder / "metadata.db"
    if db_path.exists():
        raise CalibreError("A library already exists in this folder")
    conn = _open(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {USER_VERSION}")
        conn.execute("INSERT INTO library_id (uuid) VALUES (?)", (str(uuid.uuid4()),))
        for key, value in (("bools_are_tristate", "true"), ("user_categories", "{}"), ("saved_searches", "{}"), ("grouped_search_terms", "{}")):
            conn.execute("INSERT INTO preferences (key, val) VALUES (?, ?)", (key, value))
    finally:
        conn.close()
    return db_path


def is_library(folder: Path) -> bool:
    return (folder / "metadata.db").is_file()


class Library:
    """One Calibre library folder. Every write is one short transaction, so Calibre-Web can keep the same file open."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.db_path = self.folder / "metadata.db"
        if not self.db_path.is_file():
            raise CalibreError("No metadata.db in this folder")
        with self._conn() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < 20:
                raise CalibreError(f"This library uses an old Calibre format ({version}); open it in Calibre once to upgrade it")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = _open(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # Reading

    def books(self) -> list[dict[str, Any]]:
        """Every book with what Curodav shows and imports."""
        with self._conn() as conn:
            rows = conn.execute("SELECT id, uuid, title, sort, pubdate, series_index, path, has_cover, last_modified FROM books ORDER BY id").fetchall()
            return [self._book(conn, r) for r in rows]

    def book(self, book_uuid: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT id, uuid, title, sort, pubdate, series_index, path, has_cover, last_modified FROM books WHERE uuid = ?",
                               (book_uuid,)).fetchone()
            return self._book(conn, row) if row else None

    def _book(self, conn: sqlite3.Connection, r: sqlite3.Row) -> dict[str, Any]:
        bid = r["id"]
        one = lambda sql: [x[0] for x in conn.execute(sql, (bid,))]
        authors = conn.execute("SELECT a.name, a.sort FROM books_authors_link l JOIN authors a ON a.id = l.author WHERE l.book = ? ORDER BY l.id", (bid,)).fetchall()
        rating = one("SELECT r.rating FROM books_ratings_link l JOIN ratings r ON r.id = l.rating WHERE l.book = ?")
        comments = one("SELECT text FROM comments WHERE book = ?")
        idents = {x[0]: x[1] for x in conn.execute("SELECT type, val FROM identifiers WHERE book = ?", (bid,))}
        return {
            "id": bid, "uuid": r["uuid"], "title": r["title"], "pubdate": "" if (r["pubdate"] or NO_DATE).startswith("0101") else r["pubdate"][:10],
            "authors": [a[0] for a in authors], "author_sorts": [a[1] for a in authors],
            "publisher": next(iter(one("SELECT p.name FROM books_publishers_link l JOIN publishers p ON p.id = l.publisher WHERE l.book = ?")), ""),
            "tags": one("SELECT t.name FROM books_tags_link l JOIN tags t ON t.id = l.tag WHERE l.book = ? ORDER BY t.name"),
            "series": next(iter(one("SELECT s.name FROM books_series_link l JOIN series s ON s.id = l.series WHERE l.book = ?")), ""),
            "series_index": r["series_index"], "rating": rating[0] if rating else 0, "comments": comments[0] if comments else "",
            "isbn": idents.get("isbn", ""), "doi": idents.get("doi", ""), "identifiers": idents,
            "languages": one("SELECT g.lang_code FROM books_languages_link l JOIN languages g ON g.id = l.lang_code WHERE l.book = ? ORDER BY l.item_order"),
            "formats": [{"format": f[0], "name": f[1], "size": f[2], "path": self.folder / r["path"] / f"{f[1]}.{f[0].lower()}"}
                        for f in conn.execute("SELECT format, name, uncompressed_size FROM data WHERE book = ?", (bid,))],
            "cover": (self.folder / r["path"] / "cover.jpg") if r["has_cover"] else None,
            "path": r["path"], "last_modified": r["last_modified"],
        }

    # Writing

    def add_book(self, meta: BookMeta) -> str:
        """Adds a book without files and returns its uuid; its folder and metadata.opf are written at once."""
        now = _now()
        with self._write() as conn:
            cur = conn.execute("INSERT INTO books (title, timestamp, pubdate, series_index, author_sort, path, last_modified) VALUES (?, ?, ?, ?, ?, '', ?)",
                               (meta.title or "Unknown", now, _pubdate(meta.pubdate), meta.series_index or 1.0, "", now))
            bid = cur.lastrowid
            self._set_meta(conn, bid, meta)
            path = self._path_for(conn, bid)
            conn.execute("UPDATE books SET path = ? WHERE id = ?", (path, bid))
            book_uuid = conn.execute("SELECT uuid FROM books WHERE id = ?", (bid,)).fetchone()[0]
            (self.folder / path).mkdir(parents=True, exist_ok=True)
        self.write_opf(book_uuid)
        return book_uuid

    def update_book(self, book_uuid: str, meta: BookMeta) -> None:
        """Changes the metadata; a new title or first author moves the folder and renames its files, as Calibre does."""
        with self._write() as conn:
            bid = self._id(conn, book_uuid)
            conn.execute("UPDATE books SET title = ?, pubdate = ?, series_index = ?, last_modified = ? WHERE id = ?",
                         (meta.title or "Unknown", _pubdate(meta.pubdate), meta.series_index or 1.0, _now(), bid))
            self._set_meta(conn, bid, meta)
            self._move_if_needed(conn, bid)
        self.write_opf(book_uuid)

    def delete_book(self, book_uuid: str) -> None:
        with self._write() as conn:
            bid = self._id(conn, book_uuid)
            path = conn.execute("SELECT path FROM books WHERE id = ?", (bid,)).fetchone()[0]
            conn.execute("DELETE FROM data WHERE book = ?", (bid,))
            conn.execute("DELETE FROM comments WHERE book = ?", (bid,))
            conn.execute("DELETE FROM identifiers WHERE book = ?", (bid,))
            conn.execute("DELETE FROM books WHERE id = ?", (bid,))
            self._drop_unused(conn)
        if path:
            target = self.folder / path
            if target.is_dir():
                shutil.rmtree(target)
            parent = target.parent
            if parent != self.folder and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()

    def add_format(self, book_uuid: str, data: bytes, ext: str) -> str:
        """Stores one file of the book (one per format, a second replaces the first) and returns the format name."""
        fmt = FORMATS.get(ext.lower().lstrip("."))
        if fmt is None:
            raise CalibreError(f"Calibre does not keep .{ext} files")
        with self._write() as conn:
            bid = self._id(conn, book_uuid)
            path = conn.execute("SELECT path FROM books WHERE id = ?", (bid,)).fetchone()[0]
            name = self._file_stem(conn, bid)
            folder = self.folder / path
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{name}.{fmt.lower()}").write_bytes(data)
            conn.execute("DELETE FROM data WHERE book = ? AND format = ?", (bid, fmt))
            conn.execute("INSERT INTO data (book, format, uncompressed_size, name) VALUES (?, ?, ?, ?)", (bid, fmt, len(data), name))
            conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (_now(), bid))
        return fmt

    def remove_format(self, book_uuid: str, fmt: str) -> None:
        with self._write() as conn:
            bid = self._id(conn, book_uuid)
            row = conn.execute("SELECT d.name, b.path FROM data d JOIN books b ON b.id = d.book WHERE d.book = ? AND d.format = ?", (bid, fmt.upper())).fetchone()
            if row:
                (self.folder / row["path"] / f"{row['name']}.{fmt.lower()}").unlink(missing_ok=True)
                conn.execute("DELETE FROM data WHERE book = ? AND format = ?", (bid, fmt.upper()))

    def set_cover(self, book_uuid: str, jpeg: bytes | None) -> None:
        """Writes cover.jpg (Calibre keeps covers as JPEG), or removes it with None."""
        with self._write() as conn:
            bid = self._id(conn, book_uuid)
            path = self.folder / conn.execute("SELECT path FROM books WHERE id = ?", (bid,)).fetchone()[0] / "cover.jpg"
            if jpeg:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(jpeg)
            else:
                path.unlink(missing_ok=True)
            conn.execute("UPDATE books SET has_cover = ?, last_modified = ? WHERE id = ?", (1 if jpeg else 0, _now(), bid))
        self.write_opf(book_uuid)

    def write_opf(self, book_uuid: str) -> None:
        """metadata.opf next to the files, the backup Calibre restores a library from."""
        b = self.book(book_uuid)
        if b is None:
            return
        lines = ['<?xml version=\'1.0\' encoding=\'utf-8\'?>',
                 '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">',
                 '    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">',
                 f'        <dc:identifier opf:scheme="calibre" id="calibre_id">{b["id"]}</dc:identifier>',
                 f'        <dc:identifier opf:scheme="uuid" id="uuid_id">{b["uuid"]}</dc:identifier>',
                 f'        <dc:title>{escape(b["title"])}</dc:title>']
        lines += [f'        <dc:creator opf:file-as="{escape(s, {chr(34): "&quot;"})}" opf:role="aut">{escape(a)}</dc:creator>' for a, s in zip(b["authors"], b["author_sorts"])]
        lines.append(f'        <dc:date>{(b["pubdate"] or "0101-01-01")}T00:00:00+00:00</dc:date>')
        if b["publisher"]:
            lines.append(f'        <dc:publisher>{escape(b["publisher"])}</dc:publisher>')
        lines += [f'        <dc:identifier opf:scheme="{escape(k.upper() if k == "isbn" else k)}">{escape(v)}</dc:identifier>' for k, v in b["identifiers"].items()]
        if b["comments"]:
            lines.append(f'        <dc:description>{escape(b["comments"])}</dc:description>')
        lines += [f'        <dc:language>{escape(lang)}</dc:language>' for lang in b["languages"]]
        lines += [f'        <dc:subject>{escape(t)}</dc:subject>' for t in b["tags"]]
        if b["series"]:
            lines.append(f'        <meta name="calibre:series" content="{escape(b["series"], {chr(34): "&quot;"})}"/>')
            lines.append(f'        <meta name="calibre:series_index" content="{b["series_index"]:g}"/>')
        if b["rating"]:
            lines.append(f'        <meta name="calibre:rating" content="{b["rating"]}"/>')
        lines.append(f'        <meta name="calibre:title_sort" content="{escape(title_sort(b["title"]), {chr(34): "&quot;"})}"/>')
        lines.append('    </metadata>')
        if b["cover"]:
            lines += ['    <guide>', '        <reference type="cover" title="Cover" href="cover.jpg"/>', '    </guide>']
        lines.append('</package>')
        folder = self.folder / b["path"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "metadata.opf").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Helpers

    def _id(self, conn: sqlite3.Connection, book_uuid: str) -> int:
        row = conn.execute("SELECT id FROM books WHERE uuid = ?", (book_uuid,)).fetchone()
        if row is None:
            raise CalibreError("That book is not in the library any more")
        return row[0]

    @staticmethod
    def _item(conn: sqlite3.Connection, table: str, column: str, value: str, sort: str | None = None) -> int:
        row = conn.execute(f"SELECT id FROM {table} WHERE {column} = ? COLLATE NOCASE", (value,)).fetchone()
        if row:
            if sort is not None:
                conn.execute(f"UPDATE {table} SET sort = ? WHERE id = ?", (sort, row[0]))
            return row[0]
        if sort is not None:
            return conn.execute(f"INSERT INTO {table} ({column}, sort) VALUES (?, ?)", (value, sort)).lastrowid
        return conn.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,)).lastrowid

    def _set_meta(self, conn: sqlite3.Connection, bid: int, meta: BookMeta) -> None:
        authors = [a.strip() for a in meta.authors if a.strip()] or ["Unknown"]
        sorts = [(meta.author_sorts[i] if i < len(meta.author_sorts) and meta.author_sorts[i] else author_sort(a)) for i, a in enumerate(authors)]
        conn.execute("DELETE FROM books_authors_link WHERE book = ?", (bid,))
        for name, sort in zip(authors, sorts):
            conn.execute("INSERT INTO books_authors_link (book, author) VALUES (?, ?)", (bid, self._item(conn, "authors", "name", name, sort)))
        conn.execute("UPDATE books SET author_sort = ? WHERE id = ?", (" & ".join(sorts), bid))
        conn.execute("DELETE FROM books_publishers_link WHERE book = ?", (bid,))
        if meta.publisher.strip():
            conn.execute("INSERT INTO books_publishers_link (book, publisher) VALUES (?, ?)",
                         (bid, self._item(conn, "publishers", "name", meta.publisher.strip(), meta.publisher.strip())))
        conn.execute("DELETE FROM books_tags_link WHERE book = ?", (bid,))
        for tag in dict.fromkeys(t.strip() for t in meta.tags if t.strip()):
            conn.execute("INSERT INTO books_tags_link (book, tag) VALUES (?, ?)", (bid, self._item(conn, "tags", "name", tag)))
        conn.execute("DELETE FROM books_series_link WHERE book = ?", (bid,))
        if meta.series.strip():
            conn.execute("INSERT INTO books_series_link (book, series) VALUES (?, ?)", (bid, self._item(conn, "series", "name", meta.series.strip(), meta.series.strip())))
        conn.execute("DELETE FROM books_ratings_link WHERE book = ?", (bid,))
        if 0 < meta.rating <= 10:
            conn.execute("INSERT INTO books_ratings_link (book, rating) VALUES (?, ?)", (bid, self._item(conn, "ratings", "rating", meta.rating)))
        conn.execute("DELETE FROM books_languages_link WHERE book = ?", (bid,))
        for order, lang in enumerate(dict.fromkeys(meta.languages)):
            conn.execute("INSERT INTO books_languages_link (book, lang_code, item_order) VALUES (?, ?, ?)", (bid, self._item(conn, "languages", "lang_code", lang), order))
        for kind, value in (("isbn", meta.isbn.replace("-", "").strip()), ("doi", meta.doi.strip())):
            conn.execute("DELETE FROM identifiers WHERE book = ? AND type = ?", (bid, kind))
            if value:
                conn.execute("INSERT INTO identifiers (book, type, val) VALUES (?, ?, ?)", (bid, kind, value))
        conn.execute("DELETE FROM comments WHERE book = ?", (bid,))
        if meta.comments.strip():
            conn.execute("INSERT INTO comments (book, text) VALUES (?, ?)", (bid, meta.comments.strip()))
        self._drop_unused(conn)

    @staticmethod
    def _drop_unused(conn: sqlite3.Connection) -> None:
        """Authors, tags and the like that no book uses any more go, as Calibre cleans them up."""
        for table, link, column in (("authors", "books_authors_link", "author"), ("publishers", "books_publishers_link", "publisher"),
                                    ("tags", "books_tags_link", "tag"), ("series", "books_series_link", "series"), ("ratings", "books_ratings_link", "rating")):
            conn.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT {column} FROM {link})")

    def _first_author(self, conn: sqlite3.Connection, bid: int) -> str:
        row = conn.execute("SELECT a.name FROM books_authors_link l JOIN authors a ON a.id = l.author WHERE l.book = ? ORDER BY l.id LIMIT 1", (bid,)).fetchone()
        return row[0] if row else "Unknown"

    def _path_for(self, conn: sqlite3.Connection, bid: int) -> str:
        title = conn.execute("SELECT title FROM books WHERE id = ?", (bid,)).fetchone()[0]
        suffix = f" ({bid})"
        limit = PATH_LIMIT - len(suffix) // 2 - 2
        return f"{safe_name(self._first_author(conn, bid), limit)}/{safe_name(title, limit)}{suffix}"

    def _file_stem(self, conn: sqlite3.Connection, bid: int) -> str:
        title = conn.execute("SELECT title FROM books WHERE id = ?", (bid,)).fetchone()[0]
        return f"{safe_name(title, 42)} - {safe_name(self._first_author(conn, bid), 42)}"

    def _move_if_needed(self, conn: sqlite3.Connection, bid: int) -> None:
        old = conn.execute("SELECT path FROM books WHERE id = ?", (bid,)).fetchone()[0]
        new = self._path_for(conn, bid)
        stem = self._file_stem(conn, bid)
        old_dir, new_dir = self.folder / old, self.folder / new
        if new != old:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            if old_dir.is_dir():
                shutil.move(str(old_dir), str(new_dir))
                parent = old_dir.parent
                if parent != self.folder and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            else:
                new_dir.mkdir(parents=True, exist_ok=True)
            conn.execute("UPDATE books SET path = ? WHERE id = ?", (new, bid))
        for fmt, name in conn.execute("SELECT format, name FROM data WHERE book = ?", (bid,)).fetchall():
            if name != stem:
                src = new_dir / f"{name}.{fmt.lower()}"
                if src.exists():
                    src.rename(new_dir / f"{stem}.{fmt.lower()}")
                conn.execute("UPDATE data SET name = ? WHERE book = ? AND format = ?", (stem, bid, fmt))
