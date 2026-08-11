# Published Lists

`routers/published_lists.py` — the one thing Radicale is used for
(see `architecture.md` §1.3). A **List** is a Settings-created, named, saved
boolean filter over labels (`{"all": [...], "any": [...], "none": [...]}`, e.g.
`all=["University"], none=["Archived"]`) that the app materializes into a real
Radicale collection and serves a subscribable CalDAV/CardDAV URL — so a phone
calendar app can subscribe to just `University` events without seeing everything.

- `ENTITY_TYPES = ["task", "event", "contact"]` — one collection per List,
  slug-derived path `published-{slug}` with `-2/-3…` dedupe.
- v1 is **read-only** (`sync_direction` always `"read_only"`; the column exists
  for a future two-way mode, unimplemented).
- Materialization is diff-based (`src/published_lists.py::materialize`) and runs
  on a periodic background tick (`sync.py::full_refresh`), not on every write.
- CRUD: `POST /create`, `/{id}/set` (name + filter; entity type and collection
  path immutable), `/{id}/delete` (the one genuine "delete" anywhere — tears down
  the real Radicale collection too), `/{id}/resync` ("Sync now").
- Lives under Settings (hub category, breadcrumb root "Settings").
