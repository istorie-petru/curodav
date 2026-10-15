"""How a citation is written: footnote and bibliography forms in Chicago and in the Academia Română style.

The functions are pure: they take a citation dict (as stored) and return HTML with only <i> for italics.
Features and decisions: curodav-notes/documentation/features/notebook-rework/citations.md.
"""

from __future__ import annotations

import html
import re

STYLES = {"chicago": "Chicago", "romanian": "Academia Română"}
DEFAULT_STYLE = "chicago"

_RO_MONTHS = ["ian.", "febr.", "mart.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."]
_ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _e(text) -> str:
    return html.escape(str(text or "").strip(), quote=False)


def _i(text) -> str:
    return f"<i>{_e(text)}</i>" if str(text or "").strip() else ""


def _ie(escaped: str) -> str:
    """Italics for text that is already escaped."""
    return f"<i>{escaped}</i>" if escaped.strip() else ""


def _join(parts, sep=", ") -> str:
    return sep.join(p for p in parts if p)


def _end(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", "", text)
    return text if plain.endswith((".", "?", "!")) else text + "."


def _pages(c: dict, page: str = "") -> str:
    return (page or "").strip() or str(c.get("pages") or "").strip()


def _roman(value: str) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        return text
    n, out = int(text), ""
    for size, letters in _ROMAN:
        while n >= size:
            out += letters
            n -= size
    return out


def _given_family(a: dict) -> str:
    return _join([_e(a.get("given")), _e(a.get("family"))], " ")


def _family_given(a: dict) -> str:
    return _join([_e(a.get("family")), _e(a.get("given"))], ", ")


def _people(authors: list[dict], style: str, bibliography: bool = False) -> str:
    names = [a for a in (authors or []) if (a.get("family") or a.get("given"))]
    if not names:
        return ""
    if style == "romanian":
        shown = [_family_given(names[0])] + [_given_family(a) for a in names[1:]] if bibliography else [_given_family(a) for a in names]
        return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " și " + shown[-1]
    if bibliography:
        shown = [_family_given(names[0])] + [_given_family(a) for a in names[1:]]
        if len(shown) == 1:
            return shown[0]
        if len(shown) == 2:
            return shown[0] + ", and " + shown[1]
        return ", ".join(shown[:-1]) + ", and " + shown[-1]
    shown = [_given_family(a) for a in names]
    if len(shown) == 1:
        return shown[0]
    if len(shown) == 2:
        return shown[0] + " and " + shown[1]
    if len(shown) == 3:
        return f"{shown[0]}, {shown[1]}, and {shown[2]}"
    return shown[0] + " et al."


def _title(c: dict) -> str:
    title = _e(c.get("title")) or "Untitled"
    sub = _e(c.get("subtitle"))
    return f"{title}: {sub}" if sub else title


def _publication(c: dict, style: str) -> tuple[str, str, str]:
    publisher = _e(c.get("publisher") or c.get("institution"))
    if style == "romanian":
        publisher = re.sub(r"^Editura\s+", "", publisher)
    return _e(c.get("place")), publisher, _e(c.get("year"))


def _link(c: dict) -> str:
    doi = str(c.get("doi") or "").strip()
    if doi:
        return doi if doi.startswith("http") else "https://doi.org/" + doi
    return str(c.get("url") or "").strip()


def _accessed_ro(value: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (value or "").strip())
    if not m:
        return _e(value)
    return f"{int(m.group(3))} {_RO_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def _accessed_en(value: str) -> str:
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (value or "").strip())
    return f"{months[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}" if m else _e(value)


# ---- Chicago (notes and bibliography) ------------------------------------------------------------------

def _chicago_pub(c: dict) -> str:
    place, publisher, year = _publication(c, "chicago")
    place_pub = f"{place}: {publisher}" if place and publisher else place or publisher
    inner = _join([place_pub, year])
    return f" ({inner})" if inner else ""


def _chicago_note(c: dict, page: str, with_author: bool) -> str:
    kind = c.get("type") or "book"
    who = _people(c.get("authors"), "chicago") if with_author else ""
    title = _title(c)
    pages = _e(_pages(c, page))
    link = _e(_link(c))
    if kind == "article-journal":
        vol = _join([_e(c.get("volume")), f"no. {_e(c.get('issue'))}" if c.get("issue") else ""])
        body = _join([who, f"“{title},” {_i(c.get('container_title'))}".strip() + (f" {vol}" if vol else "")], ", ")
        year = f" ({_e(c.get('year'))})" if c.get("year") else ""
        text = body.replace(",” ", ",” ") + year + (f": {pages}" if pages else "") + (f", {link}" if link else "")
        return _end(text)
    if kind == "chapter":
        editors = f", ed. {_e(c.get('editors'))}" if c.get("editors") else ""
        head = _join([who, f"“{title},” in {_i(c.get('container_title'))}{editors}".strip()], ", ")
        return _end(_join([head + _chicago_pub(c), pages], ", "))
    if kind == "conference-paper":
        head = _join([who, f"“{title},” in {_i(c.get('container_title'))}".strip()], ", ")
        return _end(_join([head + _chicago_pub(c), pages], ", "))
    if kind == "webpage":
        when = _accessed_en(c.get("accessed")) or _e(c.get("year"))
        return _end(_join([who, f"“{title},” {_e(c.get('container_title'))}".strip(), when, link], ", "))
    if kind == "thesis":
        degree = _join([_e(c.get("degree")), _e(c.get("institution")), _e(c.get("year"))])
        return _end(_join([who, f"“{title}” ({degree})" if degree else f"“{title}”", pages], ", "))
    title_part = _ie(title)
    edition = f"{_e(c.get('edition'))} ed." if c.get("edition") else ""
    volume = f"vol. {_e(c.get('volume'))}" if c.get("volume") else ""
    head = _join([who, title_part, edition, volume], ", ")
    return _end(_join([head + _chicago_pub(c), pages], ", "))


def _chicago_bibliography(c: dict) -> str:
    kind = c.get("type") or "book"
    who = _people(c.get("authors"), "chicago", bibliography=True)
    title = _title(c)
    link = _e(_link(c))
    place, publisher, year = _publication(c, "chicago")
    pub = f"{place}: {publisher}" if place and publisher else place or publisher
    pages = _e(c.get("pages"))
    if kind == "article-journal":
        vol = _join([_e(c.get("volume")), f"no. {_e(c.get('issue'))}" if c.get("issue") else ""])
        journal = _i(c.get("container_title")) + (f" {vol}" if vol else "")
        yr = f" ({year})" if year else ""
        return _join([_end(who), _end(f"“{title}.”".replace(".”", ".”") + " " + (journal + yr + (f": {pages}" if pages else "")).strip() + (f". {link}" if link else ""))], " ")
    if kind in ("chapter", "conference-paper"):
        editors = f", edited by {_e(c.get('editors'))}" if c.get("editors") else ""
        container = f"In {_i(c.get('container_title'))}{editors}" + (f", {pages}" if pages else "")
        return _join([_end(who), f"“{title}.”", _end(container), _end(_join([pub, year]))], " ")
    if kind == "webpage":
        when = _accessed_en(c.get("accessed")) or year
        return _join([_end(who), f"“{title}.”", _end(_join([_e(c.get("container_title")), when])), _end(link) if link else ""], " ")
    if kind == "thesis":
        degree = _join([_e(c.get("degree")), _e(c.get("institution")), year])
        return _join([_end(who), f"“{title}.”", _end(degree)], " ")
    edition = f"{_e(c.get('edition'))} ed." if c.get("edition") else ""
    volume = f"Vol. {_e(c.get('volume'))}." if c.get("volume") else ""
    return _join([_end(who), _end(_ie(title)), edition, volume, _end(_join([pub, year]))], " ")


# ---- Academia Română ----------------------------------------------------------------------------------

def _ro_year(c: dict) -> str:
    return _e(c.get("year")) or "f. a."


def _ro_pages(c: dict, page: str) -> str:
    pages = _e(_pages(c, page))
    return f"p. {pages}" if pages else ""


def _ro_note(c: dict, page: str, with_author: bool, bibliography: bool = False) -> str:
    kind = c.get("type") or "book"
    who = _people(c.get("authors"), "romanian", bibliography) if with_author else ""
    place, publisher, _ = _publication(c, "romanian")
    pages = _ro_pages(c, "" if bibliography else page)
    volume = f"vol. {_e(c.get('volume'))}" if c.get("volume") else ""
    if kind == "webpage":
        return _end(_join([_e(_link(c)) or _title(c), _accessed_ro(c.get("accessed")) or _e(c.get("year"))]))
    if kind == "article-journal":
        issue = f"nr. {_e(c.get('issue'))}" if c.get("issue") else ""
        return _end(_join([who, _ie(_title(c)), "în " + _i(c.get("container_title")) if c.get("container_title") else "", _roman(c.get("volume")), _e(c.get("year")), issue, pages]))
    if kind in ("chapter", "conference-paper"):
        return _end(_join([who, _title(c), "în " + _i(c.get("container_title")) if c.get("container_title") else "", place, publisher, _ro_year(c), pages]))
    return _end(_join([who, _ie(_title(c)), volume, place, publisher, _ro_year(c), pages]))


# ---- The public functions ------------------------------------------------------------------------------

def footnote(c: dict, style: str = DEFAULT_STYLE, page: str = "", with_author: bool = True) -> str:
    """A full note for one source, with the page when given."""
    return _ro_note(c, page, with_author) if style == "romanian" else _chicago_note(c, page, with_author)


def bibliography(c: dict, style: str = DEFAULT_STYLE) -> str:
    """The reference-list entry for one source."""
    return _ro_note(c, "", True, bibliography=True) if style == "romanian" else _chicago_bibliography(c)


def repeated(kind: str, c: dict | None, style: str = DEFAULT_STYLE, page: str = "", secondary: dict | None = None) -> str:
    """A note of the given kind: page_citation, confer, ibidem, opere_citato, idem, passim or apud.

    For apud, `c` is the original source and `secondary` the work it was found quoted in."""
    ro = style == "romanian"
    page = (page or "").strip()
    pg = (lambda p: f"p. {_e(p)}") if ro else (lambda p: _e(p))
    if kind == "ibidem":
        return f"Ibidem, {pg(page)}." if page and ro else (f"Ibid., {_e(page)}." if page else ("Ibidem." if ro else "Ibid."))
    if c is None:
        return ""
    if kind == "confer":
        return "Cf. " + footnote(c, style, page)
    if kind == "idem":
        return "Idem, " + footnote(c, style, page, with_author=False)
    if kind == "passim":
        return (footnote(c, style, "").rstrip(".") + ", passim.")
    if kind == "opere_citato":
        who = _people(c.get("authors"), style) or _ie(_title(c))
        tail = f", {pg(page)}" if page else ""
        return f"{who}, <i>op. cit.</i>{tail}."
    if kind == "apud":
        who = _people(c.get("authors"), style)
        original = _join([who, _ie(_title(c)) if ro else _title(c)])
        return f"{original}, apud {footnote(secondary or {}, style, page)}"
    return footnote(c, style, page)
