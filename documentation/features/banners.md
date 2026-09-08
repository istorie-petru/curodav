# Banners

`routers/banners.py` — per-dashboard-page cover image (Home + label pages),
stored base64 in `app_meta` keyed by scope ("" = Home).

- `GET /banners/editor` — modal fragment to set/remove the banner.
- `POST /banners/upload` — 8MB cap + content-type allowlist, content-hash
  `version` for cache-busting.
- `POST /banners/remove`.
- `GET /banners/image` — serves the local bytes immutable-cached
  (`Content-Encoding: identity` to skip gzip).

A SearXNG remote "search the web" picker was removed 2026-08-11; upload is the
only setter. Legacy remote banners still render (via `/banners/image` if cached
locally, else hotlink).
