"""What a selected word means, for the reader's Define action: a dictionary entry, else the Wikipedia summary.

Only the selected text is sent, and only when the Define action is used. English words go to dictionaryapi.dev; other languages to
Wiktionary, which holds definitions for every language; anything else to Wikipedia's summary of the phrase.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

TIMEOUT = 6.0
MAX_CHARS = 80
HEADERS = {"User-Agent": "Curodav reader (self-hosted)", "Accept": "application/json"}


def _get(url: str) -> Any:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError:
        return None
    return resp.json() if resp.status_code == 200 else None


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def define(text: str, lang: str = "en") -> dict[str, Any]:
    """{"title", "source", "url", "entries": [{"pos", "defs"}], "summary"}; empty entries and summary when nothing was found."""
    word = " ".join((text or "").split())[:MAX_CHARS]
    lang = (lang or "en").split("-")[0].lower()
    if not re.fullmatch(r"[a-z]{2,3}", lang):  # it becomes part of a host name below
        lang = "en"
    out: dict[str, Any] = {"title": word, "source": "", "url": "", "entries": [], "summary": ""}
    if not word:
        return out
    if " " not in word:
        if lang == "en":
            data = _get(f"https://api.dictionaryapi.dev/v2/entries/en/{quote(word.lower())}")
            if isinstance(data, list) and data:
                out["source"], out["url"] = "Dictionary", f"https://en.wiktionary.org/wiki/{quote(word)}"
                for m in data[0].get("meanings", [])[:4]:
                    out["entries"].append({"pos": m.get("partOfSpeech", ""), "defs": [d.get("definition", "") for d in m.get("definitions", [])[:3] if d.get("definition")]})
                return out
        data = _get(f"https://en.wiktionary.org/api/rest_v1/page/definition/{quote(word.lower())}")
        if isinstance(data, dict) and data.get(lang):
            out["source"], out["url"] = "Wiktionary", f"https://en.wiktionary.org/wiki/{quote(word)}"
            for e in data[lang][:4]:
                defs = [_strip(d.get("definition", "")) for d in e.get("definitions", [])[:3]]
                out["entries"].append({"pos": e.get("partOfSpeech", ""), "defs": [d for d in defs if d]})
            return out
    data = _get(f"https://{lang if len(lang) == 2 else 'en'}.wikipedia.org/api/rest_v1/page/summary/{quote(word.replace(' ', '_'))}")
    if isinstance(data, dict) and data.get("extract"):
        out["source"], out["summary"] = "Wikipedia", data["extract"][:900]
        out["title"] = data.get("title") or word
        page = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page", "")
        out["url"] = page if page.startswith("https://") else ""
    return out
