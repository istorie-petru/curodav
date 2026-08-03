# Feature: Attachments, notifications, import/export, activity feed

**Code:** `desktop/src/core/attachments/store.py`, `desktop/src/core/notifications/engine.py`, `desktop/src/core/export/impex.py`, `desktop/src/features/dashboard/activity.py`
**Status:** Attachments verified working; import/export has real bugs — see [`../STRESS_TEST_2026-07-17.md`](../STRESS_TEST_2026-07-17.md)

Smaller cross-cutting systems that don't warrant their own module doc.

## Attachments — verified working

Content-addressed blob store (SHA-256) — files live under `~/CommandCenter/attachments/{sha256}/` (`meta.json` + raw blob). Verified: storing two different filenames with identical bytes correctly dedupes into the same `sha256` directory; delete correctly removes the data. Metadata syncs as a regular object op; the blob itself is fetched/uploaded separately, idempotent and deduplicated by hash. Drag-and-drop into the WebDAV mount doesn't currently work since [WebDAV itself doesn't start](sync-and-webdav.md); the inspector's attachment section is the working path.

## Notifications

Tray reminders for overdue/due items via `QSystemTrayIcon.showMessage()` — no push infrastructure, this is a single-desktop-app concern only (see [`../plans/expansion-deferred.md`](../plans/expansion-deferred.md) for why FCM/APNs-style push isn't built). Not independently stress-tested this pass.

## Import/export — verified broken in two places

- **JSON export drops tags.** `export_json()`'s field list doesn't include `tags` — round-tripping export→import silently loses every object's tags. Everything else (title, status, priority, dates) round-trips correctly.
- **JSON import doesn't persist to disk.** `MainWindow._on_import()` appends imported objects to the in-memory object list and refreshes the UI, but never calls `file_repo.write_object()`. Imported data is gone on next launch — it was never written to `~/CommandCenter/objects/`.
- **Obsidian vault import is unreachable.** `import_obsidian_vault()` is a real function in `core/export/impex.py`, but the only import action wired to the UI (Settings → About → Import) calls `import_json()` — there is no UI path that calls the Obsidian importer. It also isn't idempotent even in isolation: it derives object ids from Python's built-in `hash()`, which is randomized per process, so importing the same vault twice (two app runs) produces different ids for the same files both times — confirmed by running it in two separate processes and comparing ids.

## Activity feed

Computed (not stored as a separate log) from object history: created / edited / completed / overdue transitions, ordered by time. Feeds the Dashboard's activity section.
