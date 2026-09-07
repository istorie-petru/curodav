# Offline-first editing & synchronization

Shipped 2026-08-14 (1.8, all 7 implementation slices). Full design record:
`plans/abandoned.md`'s "Decision history" (the pre-rework HLC per-field merge
decision this ports forward) and the git history of `plans/open-priority.md`'s
former "Offline-first editing & synchronization" section (removed on shipping,
per this repo's own "How open work gets tracked" convention — its content is
summarized here instead).

## What it does

The app supports creating, editing, scheduling, and completing entries while
offline. Installed as a PWA, it opens directly into its normal interface with
no network — a local IndexedDB mirror is the primary data source for the
installed app's own views, kept warm by ordinary online browsing. Local
changes queue as operations and sync automatically once connectivity returns,
with a status indicator (offline / synchronizing / pending changes /
synchronized) rendered as bottom-right toasts and no user action required.

This is additive, not a replacement: the plain browser-tab experience (no
install, no service worker) is untouched, fully online-only, server-rendered
exactly as it always has been. Two parallel builds meet at the sync API —
the server-side sync engine (fully testable without a browser) and the PWA
client (service worker, IndexedDB, offline UI).

## Data model

- **Entity identifiers** — tasks/events/contacts already carry a stable
  `uid`; that's the sync identifier too. A device creates new entities
  offline with a client-generated `uuid4`, no central allocation (single-user
  app). Work allocations are plain `events` rows, recurrence overrides are
  second `events` rows sharing the master's `uid` — nothing new needed for
  either. Labels have no `uid` (name is the natural key) and no delete/rename
  lifecycle, so they need no sync identity scheme at all.
- **Operation log** (`static/offline_write.js`'s outbox, `offline_db.js`'s
  `outbox` IndexedDB store) — every offline write is a field-level operation
  record (`op_id`, `entity_type`, `entity_uid`, `op_type`, `fields`,
  `device_id`, `hlc`), not a whole-row diff. This is what makes per-field
  conflict resolution possible.
- **Hybrid Logical Clock** — `(physical_time_ms, logical_counter,
  device_id)`, a total order surviving clock skew without requiring devices
  to be online together. Both client (`offline_db.js`'s `nextHlc`/`mergeHlc`)
  and server maintain their own clock, merged forward on every op observed
  from the other side.
- **Tombstones** — a delete is a `deleted_at` field write (`tasks`/`events`/
  `contacts` gained the column in slice 1), not a row removal. An edit newer
  than the tombstone un-deletes the row for free, since detection is
  per-field. A configurable retention horizon (default 90 days) governs
  physical purge — see Tombstone GC below.

## Conflict resolution

Default: per-field last-write-wins by HLC (`src/offline_sync.py`'s
`apply_op`/`_apply_field_write`). Two deliberate exceptions, both still
auto-picking a winner (no device is ever blocked) but recording the losing
value as an inspectable **sync conflict** instead of discarding it silently:

- **Concurrent event time edits** — two devices moving/resizing the same
  event's `start_at`/`end_at` while both offline. Detected via a
  simplification of full causal tracking: a losing write from a *different*
  device than the current winner is, by the HLC merge rule's own guarantee,
  necessarily concurrent (never a stale replay).
- **Conflicting project labels** — two devices attaching different project
  labels to the same task while offline violates 1.5's single-project-per-
  task invariant only as a combination; each individual `label_add` is valid
  on its own (label add/remove is commutative, needing no HLC arbitration at
  all). `apply_batch` re-validates after the whole batch applies.

Both surface to **Settings > Sync conflicts** (`routers/settings.py`,
`sync_conflicts` table) with Restore (re-applies the losing value as a fresh
op) and Dismiss actions.

## Sync protocol

`POST /api/sync/push` / `POST /api/sync/pull` (`routers/sync_api.py`, thin
HTTP wrapper around `src/offline_sync.py`'s pure logic). Every round is
push-then-pull, always in that order, so a device's own changes can't
immediately re-conflict against its own pull. Push is idempotent per `op_id`
(`sync_applied_ops` ledger); pull is an incremental delta since the caller's
cursor, or `full_resync: true` if that cursor predates the retention horizon.

Client-side (`static/offline_sync_client.js`): `syncNow()` wraps both halves;
retry uses exponential backoff with jitter (capped 30s), reset on the
browser's `online` event or any successful round. A local write
(`offline_write.js`) triggers an immediate sync attempt via `requestSync()`
if already online. Status (`static/offline_status.js`) is computed live from
`{navigator.onLine, in-flight, outbox size}`, never stored. It renders as
bottom-right toasts in the same `ccToast` stack as the app's warnings/errors/
confirmations (2026-08-16 follow-up, was a small top-right pill): the
offline / pending / synchronizing states stay as a persistent toast (no
auto-dismiss countdown, updated in place as the state changes, dismissible
via its ✕), while a successful sync is announced with a brief "Synced" toast
only on a real non-synced → synced transition — §8's "successful background
sync stays unobtrusive, while errors are visible" line, unchanged.

## PWA shell & local data layer

`static/manifest.webmanifest` + `static/sw.js` (served at `/sw.js` via
`routers/pwa.py`, not under `/static/`, so its scope covers the whole app).
Static assets are cache-first (already cache-busted by `deps.py`'s
`static_url()`); page navigations stay network-first, falling back to
`GET /offline` only on a genuine network failure.

`static/offline_db.js` is the local IndexedDB database (`cc-offline`):
`tasks`/`events`/`contacts` (field-by-field, never whole-row), a `field_hlc`
shadow store mirroring the server's own per-field HLC rule, `outbox`, and
`meta` (device id, pull cursor, this device's own HLC clock).
`templates/offline.html`'s `#offline-local-data` renders straight from this
mirror (`static/offline_shell.js`) — read-only for events, but full
create/complete/delete for tasks (`static/offline_write.js`), each queued as
an operation and applied optimistically to the mirror through the same
per-field-HLC path a pull uses.

## Tombstone GC

`src/offline_sync.py`'s `purge_expired`: once an entity's tombstone is older
than the retention horizon, it's physically removed via the existing
`db.delete_task`/`delete_event`/`delete_contact` (so related-row cleanup
matches every other hard delete in the app) plus its `field_versions` rows;
`sync_applied_ops` rows past the same horizon are purged too. Runs lazily on
every `/api/sync/pull` (`data_health.run_sync_gc`, the same "check on a
natural request path, no cron" idiom `routers/tasks.py`'s auto-archive check
already established), configurable from **Settings > Data health** (0/14/
30/90/180-day presets, plus a manual "Run cleanup now") and from
`scripts/data_health.py sync-gc`.

Because the server can now physically purge an old tombstone, a device whose
cursor is stale enough to trigger `full_resync` can't be handed a plain
incremental-style delta and trusted to notice a since-purged deletion on its
own — `offline_db.js::clearMirror()` wipes the local mirror before a full
resync re-pulls, so "start over" is an actual rebuild, not a merge into
whatever the device already had.

## What's explicitly out of scope

Real-time collaborative editing (CRDTs) and multi-user/sharing — this app is
single-user by design (`plans/abandoned.md`), for which per-field HLC/LWW is
sufficient without either. The Sync conflicts list is deliberately minimal
(see the losing value, restore or dismiss) — no diff view, no three-way merge
editor.

## Tests

`tests/test_offline_sync.py` (apply/conflict/pull/GC logic, the sync API
router), `tests/test_data_health.py` (retention config, manual GC trigger),
`tests/test_pwa_shell.py` (manifest/service-worker/local-read-write-sync
structural checks — the JS logic itself has no browser to run in under this
app's pytest convention, so several slices were additionally verified via
one-off Node + fake-indexeddb smoke scripts exercising real IndexedDB merge/
push/retry/full-resync behavior end to end, not committed to the suite).
