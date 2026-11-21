"""Word, OpenDocument, RTF and plain-text files in the book library, converted once to EPUB so the page reader can open them.

Calibre's `ebook-convert` does the work (DOCX, ODT, RTF, TXT, Markdown); an old .doc goes through LibreOffice first. The result is kept
in `book_conversions` beside the database, named after the source file's path, size and time, so a changed file converts again.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path

from . import config
from .book_text import BookError

CONVERTIBLE = ("docx", "doc", "odt", "rtf", "txt", "md", "cbr", "cb7")
COMIC_SOURCES = ("cbr", "cb7")  # become CBZ, which the reader opens; the others become EPUB
_ENV = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}  # Calibre has no screen on a server
CONVERT_SECONDS = 300
_lock = threading.Lock()


def cache_dir(conn: sqlite3.Connection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    return (Path(row[2]).parent if row and row[2] else config.default_db_path().parent) / "book_conversions"


def database_file(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2] if row and row[2] else ""


def tools_available() -> bool:
    return shutil.which("ebook-convert") is not None


def converted_name(source: Path) -> str:
    return "cbz" if source.suffix.lower().lstrip(".") in COMIC_SOURCES else "epub"


def to_epub(conn: sqlite3.Connection, source: Path) -> Path:
    """The file the reader opens in place of `source` (an EPUB, or a CBZ for a CBR or CB7), converting first when there is none yet;
    raises BookError when that cannot be done."""
    tool = shutil.which("ebook-convert")
    if not tool:
        raise BookError("Opening this kind of file needs Calibre's ebook-convert on the server")
    kind = converted_name(source)
    stat = source.stat()
    key = hashlib.sha1(f"2|{source}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()  # the leading number changes when the conversion options do
    out = cache_dir(conn) / f"{key}.{kind}"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with _lock, tempfile.TemporaryDirectory(prefix="curodav-convert-") as tmp:
        if out.is_file():
            return out
        work = source
        if source.suffix.lower() == ".doc":
            office = shutil.which("soffice") or shutil.which("libreoffice")
            if not office:
                raise BookError("Opening an old .doc file needs LibreOffice on the server")
            try:
                subprocess.run([office, "--headless", "--convert-to", "docx", "--outdir", tmp, str(source)], capture_output=True, timeout=CONVERT_SECONDS, check=False, env=_ENV)
            except subprocess.TimeoutExpired:
                raise BookError("Converting that file took too long") from None
            made = Path(tmp) / (source.stem + ".docx")
            if not made.is_file():
                raise BookError("That .doc file could not be converted")
            work = made
        made_book = Path(tmp) / f"book.{kind}"
        args = [tool, str(work), str(made_book)] + (["--no-default-epub-cover"] if kind == "epub" else [])
        try:
            run = subprocess.run(args, capture_output=True, timeout=CONVERT_SECONDS, check=False, env=_ENV)
        except subprocess.TimeoutExpired:
            raise BookError("Converting that file took too long") from None
        if run.returncode != 0 or not made_book.is_file():
            raise BookError(f"That file could not be converted to a {kind.upper()}")
        shutil.move(str(made_book), str(out))
    return out


# ---- OCR for PDFs without text ----
OCR_SECONDS = 3600


def _ocr_key(source: Path) -> str:
    stat = source.stat()
    return hashlib.sha1(f"ocr|{source}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()


def ocr_available() -> bool:
    return shutil.which("ocrmypdf") is not None


def ocr_path(conn: sqlite3.Connection, source: Path) -> Path | None:
    """The searchable copy of a PDF made by OCR, when there is one."""
    out = cache_dir(conn) / f"ocr-{_ocr_key(source)}.pdf"
    return out if out.is_file() else None


def ocr_pdf(conn: sqlite3.Connection, source: Path) -> Path:
    """A copy of the PDF with a text layer, from ocrmypdf and tesseract (languages from CC_OCR_LANGS, English by default).
    The original is not changed; the copy is kept beside the converted books."""
    tool = shutil.which("ocrmypdf")
    if not tool:
        raise BookError("Making a PDF searchable needs ocrmypdf and tesseract on the server")
    out = cache_dir(conn) / f"ocr-{_ocr_key(source)}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        return out
    work = out.with_suffix(".part")
    langs = os.environ.get("CC_OCR_LANGS", "eng")
    try:
        run = subprocess.run([tool, "--skip-text", "--rotate-pages", "-l", langs, "--output-type", "pdf", str(source), str(work)],
                             capture_output=True, timeout=OCR_SECONDS, check=False, env=_ENV)
    except subprocess.TimeoutExpired:
        work.unlink(missing_ok=True)
        raise BookError("Reading that PDF took too long") from None
    if run.returncode == 6 and not work.is_file():  # it already had text everywhere
        shutil.copy(source, out)
        return out
    if run.returncode != 0 or not work.is_file():
        work.unlink(missing_ok=True)
        raise BookError("That PDF could not be read by OCR")
    work.replace(out)
    return out


def read_metadata(data: bytes, filename: str) -> dict[str, str]:
    """Title, authors (joined with " & "), year and publisher written inside a book file, from Calibre's ebook-meta; {} when there is
    nothing to read or the tool is missing. Used to name an uploaded book better than its file name does."""
    tool = shutil.which("ebook-meta")
    if not tool or Path(filename).suffix.lower().lstrip(".") in ("txt", "md"):
        return {}
    with tempfile.TemporaryDirectory(prefix="curodav-meta-") as tmp:
        path = Path(tmp) / ("book" + Path(filename).suffix.lower())
        path.write_bytes(data)
        try:
            run = subprocess.run([tool, str(path)], capture_output=True, timeout=60, check=False, env=_ENV, text=True)
        except subprocess.TimeoutExpired:
            return {}
    out: dict[str, str] = {}
    for line in run.stdout.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not value or value.lower() in ("unknown", "none"):
            continue
        if key == "title":
            out["title"] = value
        elif key.startswith("author"):
            out["authors"] = " & ".join(part.split("[")[0].strip() for part in value.split(" & "))
        elif key == "published":
            out["year"] = value[:4] if value[:4].isdigit() else ""
        elif key == "publisher":
            out["publisher"] = value
    return out
