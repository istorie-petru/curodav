"""Pulling the text out of a book file: sections (a chapter or a PDF page) of plain text, then passages of about a thousand characters.

Feature document: curodav-notes/documentation/features/book-search.md

EPUB, FB2 and plain text are read in Python. PDF needs poppler's `pdftotext`; other formats are converted to EPUB with Calibre's
`ebook-convert`. A missing tool or an unreadable file raises BookError with a message the assistant can pass on.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from posixpath import dirname, join, normpath
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree

PASSAGE_CHARS = 1000
PASSAGE_MAX = 1500
CONVERT_SECONDS = 120
TOOL_SECONDS = 90
NATIVE = {"epub", "txt", "md", "fb2", "pdf"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section", "article", "pre", "table", "ul", "ol", "dt", "dd"}
HEADINGS = {"h1", "h2", "h3"}


class BookError(Exception):
    """A book that cannot be read, in words for the person or assistant asking."""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading = ""
        self._in_heading = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag in HEADINGS and not self.heading:
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag in HEADINGS:
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.parts.append(data)
        if self._in_heading:
            self.heading += data

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).split("\n"))
        return "\n".join(line for line in lines if line)


def _html_section(markup: str) -> tuple[str, str]:
    parser = _Text()
    parser.feed(markup)
    return " ".join(parser.heading.split()), parser.text()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("latin-1")


def _epub(path: Path) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(path) as z:
            container = ElementTree.fromstring(z.read("META-INF/container.xml"))
            rootfile = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
            opf = ElementTree.fromstring(z.read(rootfile))
            base = dirname(rootfile)
            manifest = {e.get("id"): e.get("href") for e in opf.iter() if e.tag.endswith("}item") or e.tag == "item"}
            spine = [e.get("idref") for e in opf.iter() if e.tag.endswith("itemref")]
            sections = []
            for ref in spine:
                href = manifest.get(ref)
                if not href:
                    continue
                name = normpath(join(base, unquote(href.split("#")[0])))
                try:
                    heading, text = _html_section(_decode(z.read(name)))
                except KeyError:
                    continue
                if len(text) >= 20:
                    sections.append({"title": heading or Path(name).stem, "page": None, "text": text})
            return sections
    except (zipfile.BadZipFile, KeyError, StopIteration, ElementTree.ParseError) as exc:
        raise BookError(f"That EPUB cannot be read ({exc.__class__.__name__})") from None


def _fb2(path: Path) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(path.read_bytes())
    except ElementTree.ParseError:
        raise BookError("That FB2 file cannot be read") from None
    sections = []
    for sec in root.iter():
        if not sec.tag.endswith("}section") or any(c.tag.endswith("}section") for c in sec):
            continue
        title = " ".join("".join(t.itertext()).split() for t in sec if t.tag.endswith("}title"))
        text = "\n".join(" ".join("".join(p.itertext()).split()) for p in sec if p.tag.endswith("}p"))
        if text:
            sections.append({"title": title or f"Section {len(sections) + 1}", "page": None, "text": text})
    return sections


def _plain(path: Path) -> list[dict[str, Any]]:
    return [{"title": "Text", "page": None, "text": _decode(path.read_bytes())}]


def _pdf(path: Path) -> list[dict[str, Any]]:
    tool = shutil.which("pdftotext")
    if not tool:
        raise BookError("Searching PDFs needs pdftotext (the poppler-utils package) on the server")
    try:
        run = subprocess.run([tool, "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=TOOL_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise BookError("Reading that PDF took too long") from None
    if run.returncode != 0:
        raise BookError("That PDF cannot be read (it may be damaged or locked)")
    pages = run.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    sections = [{"title": f"Page {i}", "page": i, "text": page.strip()} for i, page in enumerate(pages, 1)]
    if sum(len(s["text"]) for s in sections) < 40 * max(len(sections), 1) / 4:
        raise BookError("That PDF has no text layer (a scan); reading scanned books is not supported yet")
    return sections


def _converted(path: Path) -> list[dict[str, Any]]:
    tool = shutil.which("ebook-convert")
    if not tool:
        raise BookError(f"Searching {path.suffix.lstrip('.').upper()} files needs Calibre's ebook-convert on the server")
    with tempfile.TemporaryDirectory(prefix="curodav-book-") as tmp:
        out = Path(tmp) / "book.epub"
        try:
            run = subprocess.run([tool, str(path), str(out)], capture_output=True, timeout=CONVERT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            raise BookError("Converting that book took too long") from None
        if run.returncode != 0 or not out.is_file():
            raise BookError("That book could not be converted to text")
        return _epub(out)


def sections_of(path: Path, fmt: str) -> list[dict[str, Any]]:
    """The book's sections in reading order: {title, page, text}. A PDF has one section per page."""
    fmt = fmt.lower()
    if fmt == "epub":
        sections = _epub(path)
    elif fmt == "fb2":
        sections = _fb2(path)
    elif fmt in ("txt", "md"):
        sections = _plain(path)
    elif fmt == "pdf":
        sections = _pdf(path)
    else:
        sections = _converted(path)
    if not sum(len(s["text"]) for s in sections):
        raise BookError("No text could be found in that book")
    return sections


def passages(text: str) -> list[str]:
    """Paragraph-aligned pieces of about PASSAGE_CHARS characters; a very long paragraph is cut at a sentence or space."""
    out, current = [], ""
    for para in (p.strip() for p in re.split(r"\n+", text)):
        while len(para) > PASSAGE_MAX:
            cut = max(para.rfind(". ", 0, PASSAGE_MAX), para.rfind(" ", 0, PASSAGE_MAX))
            cut = cut + 1 if cut > PASSAGE_CHARS // 2 else PASSAGE_MAX
            if current:
                out.append(current)
                current = ""
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if not para:
            continue
        if current and len(current) + len(para) > PASSAGE_CHARS:
            out.append(current)
            current = ""
        current = f"{current}\n{para}" if current else para
    if current:
        out.append(current)
    return out
