"""Minimal SearXNG JSON-API client for the banner editor's "search the
web" tab (routers/banners.py, 2026-08-09). Talks to a self-hosted
SearXNG instance's `?format=json` endpoint (the standard, JSON-enabled
way to query SearXNG programmatically -- same endpoint a browser's
"JSON" results toggle hits) and normalizes its image results into the
small {title, url, img_src, thumbnail_src, source, resolution} shape the
banner editor modal renders.

Only the image category is ever queried -- a banner is a wide/landscape
image, and SearXNG's `categories=images` already restricts engines to
the ones that return direct `img_src` URLs, which is what a hotlinked
banner needs. Two decisions are hardcoded rather than user-togglable
(2026-08-09 follow-up): safesearch is always strict (`safesearch=2`,
the "SFW filter") with no on/off control in the modal, and the search
always asks for `resolution=large` so results trend toward high-res
images that survive being stretched across a wide banner. The old
user-facing image-type / size filter dropdowns were removed with them.
"""

from __future__ import annotations

import httpx

# Defaults mirroring config.py's, used when a bare request has no real app
# settings to read (this app's own test suite constructs bare Request({...})
# objects with no ASGI app in scope -- same graceful-fallback convention as
# deps.py's Jinja globals).
DEFAULT_BASE_URL = "http://127.0.0.1:8080"

# Implicit filters (2026-08-09 follow-up): every banner search is biased
# toward wallpaper-quality photo content -- the positive terms below ride
# along on the engine query invisibly, so the search box keeps showing
# only what the user typed. "No icon" can't go in that query: engines
# keyword-match the word "icon" itself and happily return icon sets, so
# it's enforced below on the returned results instead (see
# _ICON_PATTERNS).
_IMPLICIT_FILTER_TERMS = ("photos", "wallpaper", "4k")

# Title/URL tells an icon set, logo pack, favicon, or screenshot apart
# from a photo, and none of those survive being stretched across a 3:1
# banner. The "no icon" implicit filter: any result whose title or URL
# smells like one is dropped before it reaches the modal.
_ICON_PATTERNS = ("icon", "logo", "favicon", "devicon", "screenshot", ".svg")

_TIMEOUT_SECONDS = 8.0


def search_banner_images(base_url: str, query: str) -> list[dict]:
    """Search SearXNG's image category for wide, banner-suitable images and
    return a normalized list of dicts (title/url/img_src/thumbnail_src/
    source/resolution). Every entry is guaranteed to have a usable `img_src`
    -- a result without a direct image URL is unusable as a hotlinked
    banner, so it's dropped rather than surfaced as a broken card.

    Always strict-safe (safesearch=2, the SFW filter -- there is no
    off switch in the app) and always requests high-resolution images
    (`resolution=large`), the two settings the old filter dropdowns used
    to expose.

    Raises on a non-2xx response or a body that isn't SearXNG's JSON search
    shape. The caller (routers/banners.py's editor route) catches and shows
    the message inline in the modal instead of failing the page, since a
    SearXNG instance being down shouldn't block the upload tab still
    working."""
    query = query.strip()
    if not query:
        return []
    params: dict[str, str] = {
        "q": f"{query} {' '.join(_IMPLICIT_FILTER_TERMS)}",
        "format": "json",
        "categories": "images",
        "safesearch": "2",
        "resolution": "large",
    }
    resp = httpx.get(
        base_url.rstrip("/") + "/search",
        params=params,
        timeout=_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    resp.raise_for_status()
    payload = resp.json()

    results = []
    for item in payload.get("results", []):
        img_src = item.get("img_src") or ""
        if not img_src:
            continue
        title = item.get("title") or ""
        url = item.get("url") or ""
        if any(p in f"{title} {url}".lower() for p in _ICON_PATTERNS):
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "img_src": img_src,
                "thumbnail_src": item.get("thumbnail_src") or img_src,
                "source": item.get("source") or item.get("engine") or "",
                "resolution": item.get("resolution") or "",
            }
        )
    return results
