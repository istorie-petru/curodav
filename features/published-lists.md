# Published Lists

`routers/published_lists.py` — a Settings-created, named, saved boolean filter
over labels (`{"all": [...], "any": [...], "none": [...]}`, e.g.
`all=["University"], none=["Archived"]`) over one entity type (task/event/
contact).

- `ENTITY_TYPES = ["task", "event", "contact"]` — one Radicale collection per
  List, slug-derived path `published-{slug}` with `-2/-3…` dedupe.
- v1 is **read-only** (`sync_direction` always `"read_only"`; the column exists
  for a future two-way mode, unimplemented).
- Materialization into Radicale is diff-based (`src/published_lists.py::
  materialize`) and runs on a periodic background tick (`sync.py::
  full_refresh`), not on every write.
- CRUD: `GET /published-lists` (the page), `GET /new` (create modal),
  `POST /create`, `POST /{id}/visibility`, `POST /{id}/delete` (the one genuine
  permanent delete — tears down the Radicale collection too). No edit route —
  a List's name/filter/entity type are fixed after creation; delete and
  recreate instead.
- Lives under Settings (hub category, breadcrumb root "Settings").

## Visibility (2026-08-29)

Every List has one of three states (`published_lists.visibility`,
`routers/published_lists.py::VISIBILITIES`), changed any time via
`POST /{id}/visibility`:

- **`private`** (default) — the original behavior: materialized into Radicale
  only, reachable by whoever has the shared Radicale/CalDAV account
  (`CC_RADICALE_USER`/`PASSWORD`). Not reachable via the public link below.
- **`public`** — everything `private` gets, plus a standalone, unguessable
  link served directly by this app (`GET /public/lists/{token}.ics`/`.vcf`,
  `routers/public_lists.py`) — no login, no Radicale account, works even when
  Radicale isn't configured at all, since the feed is generated live from the
  label filter on every request rather than read back out of the Radicale
  collection. This is the "share with a friend/colleague" case the page's own
  copy always promised but, before 2026-08-29, didn't actually deliver — every
  List required the shared Radicale account too, regardless of what the UI
  said.
- **`archived`** — paused: the Radicale collection is torn down
  (`published_lists.teardown_collection`) and the public link (if any) stops
  serving, but the row itself — name, filter, and `public_token` if it had one
  — stays in the database, so reactivating later needs no reconfiguring.
  `materialize_all` (the periodic background tick) skips an archived row
  entirely; un-archiving triggers a best-effort immediate re-materialize
  (`routers/published_lists.py::_try_materialize`) on top of that.

`public_token` (`secrets.token_urlsafe(32)`, `published_lists.new_public_token`)
is generated once, the first time a List becomes public, and stays stable
across later private/public/archived toggles — a re-shared public link keeps
working. Switching a List away from `public` doesn't clear the token; the
public feed route just refuses to serve unless `visibility == "public"` right
now (`db.get_published_list_by_token` + the visibility check in
`routers/public_lists.py::_get_public_list`), so a stale link a friend still
has correctly stops resolving instead of relying on a token being erased.

Radicale is optional for this whole feature: every mutating route
(`create_list`, `set_visibility`, `delete_list`) is best-effort about the
bridge — a None/unreachable bridge (`main.py`'s lifespan sets `bridge=None`
when Radicale is unreachable) never blocks creating, sharing, archiving, or
deleting a List; the Radicale-side effect just doesn't happen until a bridge
is available, and the next successful `materialize_all` tick catches up
automatically.

## The public feed (`routers/public_lists.py`)

`GET /public/lists/{token}.ics` (task/event Lists) or `.vcf` (contact Lists) —
exempt from login in `src/auth.py::AuthMiddleware` (the `/public/` path
prefix, checked before both the normal auth gate and the forced first-run
`/setup` redirect, so an already-shared link keeps working during setup too).
`GET /public/lists/{token}` with no extension 302s to the right one. A token
that's unknown, or exists but isn't currently `visibility == "public"`, gets
the same plain 404 either way — deliberately not distinguishing the two, so
the route can't be used to probe whether a particular token used to work.

The feed is built the same way `export.py`'s `/export/events.ics` etc. are —
an `icalendar.Calendar`/joined vCards wrapping each member row — except the
membership comes from `evaluate_label_filter` evaluated fresh on every
request, not a Radicale round-trip. GET-only, so `CSRFMiddleware` never
inspects these routes (it only checks state-changing methods).
