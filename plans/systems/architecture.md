# Personal Command Center — Architecture

**Status:** Current · v0.2 · 2026-07-17
**Owner:** Peter
**Scope:** Single-user, offline-first, file-tree-backed desktop app with optional P2P sync

> **Supersedes** the v0.1 draft (2026-07-09), which specified a Flutter client
> synced through a custom FastAPI + Postgres backend. That design was
> abandoned in favor of the file-tree + WebDAV/Syncthing rework recorded in
> [`decisions-log.md`](decisions-log.md) (2026-07-15) and built as `desktop/`
> (PySide6, moved to the project root 2026-07-17 — formerly
> `command_center/desktop`). This document reflects the current, built
> architecture. The unified object model (§4) is the one part of the
> original design that survived the rework unchanged — only its
> serialization changed, from SQL rows to JSON files. For what's actually
> implemented today, feature by feature, see [`../../features/`](../../features/README.md).

---

## 1. Purpose and honest scope

This document is the technical foundation for a personal "command center" app: tasks, projects, calendar, notes, kanban, roadmap — later media tracking and homelab monitoring — built as **one object graph with multiple views**, not seven apps under one sidebar.

It exists to lock in the decisions that are expensive to change later (data model, sync approach, storage format) and to explicitly defer everything else.

### 1.1 Why the original (Flutter + FastAPI + Postgres) design was replaced

The v0.1 design was already a correction of an even earlier spec (dropping Supabase, teams/RBAC, and a ten-module v1). The rework recorded in [`decisions-log.md`](decisions-log.md) went further, for reasons worth keeping on record:

1. **Two languages, one maintainer.** The server was already Python; running a second stack (Dart/Flutter) for the client doubled context-switching for no benefit a single user needs.
2. **A custom sync protocol is machinery that needs a customer.** The HLC/LWW sync server (§7 of the old design) was ~500 lines of exhaustively-tested code whose only job was reinventing what mature P2P file sync already does. Syncthing does peer discovery, NAT traversal, transport encryption, and conflict detection for free.
3. **A file tree is a better source of truth for one user than a private database.** Files are directly inspectable, editable by other tools (Obsidian, a text editor, `rclone`), and trivially backed up. A database behind an API is opaque unless you built the API.

### 1.2 Non-goals (still true)

- Multi-user, sharing, teams, RBAC
- Collaborative real-time editing (CRDTs)
- Media tracker, infrastructure dashboard, external API integrations
- Push notifications via FCM/APNs (local/tray notifications only)
- Budget tracking, passkeys, public API
- Mobile (Android/iOS) — abandoned in the rework; desktop only

---

## 2. System overview

```
┌───────────────────────────────────────────────────────────┐
│                Qt Desktop App (PySide6)                     │
│   Linux primary · Windows/macOS secondary                   │
│                                                               │
│  UI (Qt Widgets + QSS)  ──reads/writes──▶  File Repository   │
│                                              │                │
│                                   ┌──────────┴──────────┐     │
│                                   ▼                     ▼     │
│                          File Tree (disk)      SQLite cache   │
│                        ~/CommandCenter/…       (aiosqlite,    │
│                                                  FTS5 search)  │
└──────────────────────────┬──────────────────────┬────────────┘
                            │                      │
                            ▼                      ▼
                  Syncthing (optional, P2P)   Embedded WebDAV
                  mesh sync to other devices   (wsgidav, for
                                                external tools)
```

**The file tree is the source of truth; SQLite is a disposable, rebuildable query cache.** There is no server and no central database. Every device that runs the app holds a complete local copy on disk and works fully offline. If another device exists, Syncthing replicates the file tree to it — the app never talks to Syncthing's protocol directly, only to its local REST API for status.

This is a stronger inversion than the original client/server design: previously "offline-first" meant a local SQLite replica synced against a server of record. Now there is no server of record — the file tree on each device *is* the record, and Syncthing's job is making N copies of it agree.

---

## 3. Stack decisions

| Layer | Choice | Rejected alternatives and why |
|---|---|---|
| UI framework | **PySide6 (Qt6 Widgets)** | Qt Quick/QML: less suited to a dense, keyboard-heavy desktop UI than Widgets; Flutter: two-language project for one maintainer (§1.1); Electron/Tauri+web: heavier runtime, worse native feel |
| Language | **Python 3.12** | Single-language project; server-side logic (HLC, filerepo) was already Python-shaped |
| Source of truth | **File tree** (`~/CommandCenter/objects/<id>/...`) | A database-behind-an-API is opaque without the API; a file tree is inspectable and editable by any tool |
| Query cache | **SQLite via `aiosqlite`**, FTS5 for search | Rebuildable from the file tree at any time; never the source of truth, so schema drift is low-stakes |
| File watching | **`watchdog`** (inotify/FSEvents) | Keeps the SQLite cache incrementally in sync with on-disk changes, including ones made by external tools |
| P2P sync | **Syncthing** (optional, via local REST API) | Mature, encrypted (TLS 1.3), mesh discovery + NAT traversal, zero protocol code to maintain. App works identically without it — local-only mode |
| WebDAV server | **Embedded `wsgidav`** | Lets external tools (Obsidian, Finder/Explorer, `rclone`, `curl`) read/write the same file tree; optional, toggled in Settings |
| Merge algorithm | **HLC per-field**, ~40 lines, ported from the original Dart implementation | Unchanged from v0.1 — still the right tool; now applied on file read (resolving Syncthing conflict files) instead of on server push/pull |
| Markdown rendering | `markdown-it-py` + `QTextBrowser` | Lightweight, no browser engine dependency |

### 3.1 What happened to the sync server

The FastAPI + Postgres sync service from the v0.1 design (`server/`) has been removed. Its role — arbitrating concurrent edits from multiple devices — is now split between Syncthing (transport and conflict *detection*) and the existing HLC/LWW merge logic (conflict *resolution*, applied locally when the app reads a file and finds a Syncthing conflict copy alongside it). No service to deploy, patch, or keep online; backup is "every device is a full replica" plus whatever backup story you run for the folder itself (e.g. a periodic copy off-device).

---

## 4. The unified object model

The defining principle, unchanged from v0.1: **object-centric, not page-centric**. A task, event, note, project, and (later) media entry or infra node are all *objects* — one shape with a type discriminator — and every module screen is a *view over the object graph*.

### 4.1 What is (and is not) an object

Rule: **if it can be independently linked, tagged, scheduled, or searched, it is an object.** Otherwise it is a detail row of one.

- Objects: task, project, event, note, goal, roadmap node, person, board (media/infra objects are deferred, not built)
- Not objects: checklist items, milestones, comments, tag assignments, reminders, activity entries — these belong to exactly one object and never need graph semantics

### 4.2 Serialization: file tree, not SQL rows

Where v0.1 put the object model in Postgres/SQLite tables with a server arbitrating writes, the current design serializes each object as a directory of files, with per-field HLC timestamps carried alongside each value so conflicting edits can be merged without a server:

```
~/CommandCenter/
├── objects/
│   ├── 01AR3Z7.../
│   │   ├── object.json       # shared fields + per-field HLC timestamps
│   │   ├── body.md           # notes: markdown body
│   │   ├── checklist.json    # tasks: [{id, text, done}]
│   │   └── milestones.json   # projects: [{id, title, due_at, done}]
│   └── ...
├── links.json                 # all associative links
├── tags.json                  # tag definitions
├── attachments/
│   └── {sha256}/{meta.json, data}
├── .sync/{device.json, state.json}
└── .stfolder/                 # Syncthing marker
```

`object.json` fields use a `{"v": value, "h": hlc}` envelope per field:

```json
{
  "type": "task",
  "title":    {"v": "BAC critique", "h": "0017523400000-0-phone"},
  "status":   {"v": "doing",        "h": "0017523600000-2-phone"},
  "due_at":   {"v": "2026-07-20",   "h": "0017523400000-0-phone"},
  "priority": {"v": 2,              "h": "0017523500000-1-desktop"}
}
```

The field set and semantics are otherwise the ones specified below (§4.3–4.6), which are the same fields v0.1 put in SQL columns — only the storage medium changed.

### 4.3 Status vocabulary

`status` is a single field interpreted per type, with a shared core so smart lists can query across types:

| Value | task | project | event | note | goal |
|---|---|---|---|---|---|
| `active` | todo | in progress | scheduled | — | in progress |
| `in_progress` | doing | — | — | — | — |
| `waiting` | blocked/waiting | on hold | — | — | — |
| `done` | completed | completed | happened | — | achieved |
| `archived` | archived | archived | — | archived | dropped |

Kanban columns map to statuses (a board column carries an `object_status`), so **moving a card is a status change** — the board is a view, not a second source of truth. Boards may define custom status strings for their own child cards; smart lists treat unknown statuses as `active`.

### 4.4 Two kinds of relationships — do not conflate them

1. **`parent_id`** — structural, tree-shaped, ownership: subtask→task, task→project, note→notebook, roadmap node→roadmap. Deleting/archiving cascades down. One parent max.
2. **`links` (in `links.json`)** — associative, graph-shaped, free-form: "this note is about that event", "this task blocks that task". No cascade. Any-to-any. Link types: `related`, `blocks`, `references`, `mentions`.

Backlinks for the notes module are `links` filtered to entries where `to_id` is the current object — the Obsidian-style graph falls out of this for free. `[[wikilink]]` syntax in note bodies is parsed on save and materialized into `links` entries with `link_type='mentions'`.

### 4.5 Extension data (per type)

Same fields as the original spec, now living in extension files inside each object's directory rather than extension tables:

- **task**: `checklist.json` (`[{id, text, done}]`), `estimate_min`, `time_spent_min`, `recurrence` (RRULE), `waiting_on`
- **event**: `end_at`, `all_day`, `location`, `meeting_url`, `recurrence`, `calendar_id`, `reminders`
- **note**: `body.md` (markdown source of truth), `is_daily`, `daily_date`, `template`
- **project**: `color`, `milestones.json` (`[{id, title, due_at, done}]`)
- **board**: `columns` (`[{id, name, object_status}]`)

Checklist and milestones are still deliberately unstructured JSON, not sub-objects: they're never queried across objects, never linked, and LWW-merging them as one field is an acceptable trade-off for a single user.

### 4.6 SQLite cache schema

The SQLite cache (`src/core/db/schema.py`) mirrors this same logical shape — `objects`, `task_details`, `event_details`, `note_details`, `project_details`, `board_details`, `links`, `tags`, `object_tags`, `attachments` — plus an FTS5 virtual table over title/description/body for search. There is no `change_log` or `field_state` table; those existed only to support the server's push/pull protocol, which no longer exists. The cache is rebuildable at any time from the file tree (Settings → reindex).

---

## 5. Modules as views

Unchanged in spirit from v0.1 — because the model is unified, most "modules" are query + presentation, not new subsystems:

| Screen | Is actually |
|---|---|
| Dashboard "Today" | Objects with `due_at` today, `start_at` today, `pinned`, or overdue, across all types, status not in (done, archived) — sorted overdue → pinned → timed → rest |
| Smart lists (Today/Upcoming/Overdue/Waiting/…) | Stored filter definitions over the cache — data, not code |
| Kanban board | Objects grouped by `status`, ordered by `sort_key`; drag = status/sort_key update |
| Calendar | Tasks with `due_at` + events, RRULE expanded client-side for the visible window |
| Project view | The project object + everything with `parent_id = project` + everything linked to it |
| Roadmap | `roadmap_node` objects grouped by era/year, linked to projects/goals |
| Notes graph | `links` filtered to note endpoints |
| Global search | FTS5 over `objects(title, description)` + `note_details(body)` |

The practical payoff is the same as in v0.1: adding a new object type is an extension file shape, a detail view, and a list view — linking, tagging, search, and dashboard behavior already exist for free.

---

## 6. P2P sync (Syncthing)

Optional, toggled in Settings. When enabled, Syncthing (run as a subprocess or externally) replicates `~/CommandCenter/` to other devices over an encrypted mesh; the app talks to Syncthing only through its local REST API (`localhost:8384`), to show status, connected devices, and trigger rescans.

**Merge on read:** when the app loads an object, it checks for a Syncthing conflict file (`object.sync-conflict-...`) alongside it. If one exists, both versions are merged per-field by HLC (higher HLC wins per field, exactly as in the original LWW design), the merged result is written back, and the conflict file is deleted. This makes the app eventually consistent without any server: Syncthing propagates bytes, the app reconciles the next time it reads them.

Without Syncthing running, the app behaves identically in local-only mode — every feature works, there's simply nothing to sync to.

---

## 7. WebDAV

An embedded `wsgidav` server (`src/core/dav/`) can serve `~/CommandCenter/` on `localhost` (LAN access is an explicit opt-in toggle in Settings, off by default). This lets external tools mount the folder as a drive, edit notes with any markdown editor, drag-and-drop attachments, or script against it with `curl`/`rclone`. The app itself always reads the filesystem directly — WebDAV exists purely for external tool interoperability, not as an internal dependency.

---

## 8. Application architecture (PySide6)

### 8.1 Layout

Feature-first, mirroring the original Flutter structure but in Python, without a framework-enforced layer split (no Riverpod/Bloc equivalent — Qt's signal/slot model plus plain repository classes):

```
desktop/src/
├── main.py                # entry point
├── app.py                 # QMainWindow, sidebar, system tray
├── core/
│   ├── models/             # Object, Link, Tag dataclasses
│   ├── filerepo/           # file tree read/write + HLC merge
│   ├── db/                 # SQLite schema + async database (aiosqlite)
│   ├── sync/                # hlc.py, lww.py, syncthing_client.py, watcher.py
│   ├── dav/                 # embedded WebDAV server
│   ├── design/              # OKLCH → QSS theme tokens
│   ├── search/               # FTS5 query logic
│   ├── attachments/          # content-addressed blob store
│   ├── notifications/        # reminder notification engine
│   └── export/                # JSON/markdown/Obsidian import/export
├── features/
│   ├── dashboard/ tasks/ calendar/ notes/ boards/ roadmap/ search/ settings/
└── widgets/                 # ObjectCard, ObjectListTile — shared across modules
```

`core/filerepo` plays the role `core/objects` played in the Flutter design: it owns reads/writes of `object.json` + extension files, HLC merge on read, and emits Qt signals on change so the UI reacts without manual invalidation — the same reactive-by-construction property Drift `Stream` queries gave the old design, now built on `watchdog` events instead.

### 8.2 State and reactivity

- `watchdog` detects file changes → updates the SQLite cache incrementally → emits a Qt signal → connected widgets refresh. No polling.
- Mutations go through `filerepo`, which writes the file (optimistic — the write *is* local, there's no network round trip to wait on) and lets the watcher propagate the cache update.
- No feature module talks to the file tree or SQLite directly; everything goes through `core/filerepo` and `core/db`.

### 8.3 Navigation

`QMainWindow` with a sidebar (vertical nav rail, two-letter mono glyphs per module) rather than GoRouter's declarative routing — Qt Widgets doesn't have an equivalent router, so navigation is imperative (stacked widget / signal-driven view switching). Every object still resolves to a canonical detail view (`/o/{id}`-equivalent lookup by id + type), preserving universal linking. Command palette (`Ctrl+K`) is an app-level overlay: fuzzy search over objects + actions.

### 8.4 Platform notes

Linux is primary; Windows/macOS secondary. Mobile (Android/iOS) was explicitly abandoned in the rework — desktop only. Local notifications use `QSystemTrayIcon.showMessage()` instead of `flutter_local_notifications`.

---

## 9. Design system

**Rewritten 2026-07-17** — the *Personal OS* mockup's OKLCH token system (bg0/bg1/accent/etc. as fixed hex-equivalent values, with Density/Shape/Accent as user-facing props) was the original intent, but was never actually wired up: the QSS generator computed those tokens and then didn't reference them, hardcoding a fixed macOS-style dark palette instead, and `oklch()`/`oklab()` CSS values aren't valid Qt Style Sheet syntax to begin with (Qt's CSS parser is CSS2.1-derived; it doesn't support CSS Color Level 4 functions). None of it rendered, and the app didn't integrate with the desktop it ran on regardless of that setting. Full account in `../../features/design-system.md`.

Current approach: no custom color palette. `core/design/tokens.py` provides `is_dark(widget)` (reads live `QPalette` lightness) and `semantic_colors(dark)` (the handful of status colors — danger/warning/success — that must stay legible regardless of theme, since `QPalette` has no role for those). Everything else is `palette(window)`, `palette(base)`, `palette(text)`, `palette(highlight)`, etc. — real Qt Style Sheet functions resolved against the live system palette, so the app follows the desktop's actual theme (Breeze/Breeze Dark on Plasma, Adwaita on GNOME, whatever the Qt platform theme plugin provides) automatically, including live updates via `QGuiApplication.styleHints().colorSchemeChanged`. Density, Shape, and Accent are no longer user-facing settings — see `../../features/settings.md` for why. Qt Style (which QStyle Qt renders widgets with, e.g. Darkly) is a separate, still-available setting — it's a real Qt mechanism, not part of this OKLCH cleanup, and composes fine with palette-based theming since a chosen style supplies its own palette.

Codified idioms, unchanged: 1px borders, near-zero elevation; mono uppercase section labels with a hairline rule; mono status tags, outlined, color = semantic state; corner-bracket motif for pinned objects; eyebrow-over-title page headers; 4px progress bars; persistent bottom status bar. 4px spacing grid. Motion: implicit, 150–200ms, ease-out — nothing bounces. IBM Plex Mono is still used for data/label text where set explicitly; general UI text now inherits the platform's default font instead of a hardcoded `-apple-system`/"SF Pro" stack.

---

## 10. Search

Client-side and local-only by construction now — there was never a server round trip in v0.1 either, but the reasoning is stronger without one: SQLite **FTS5** external-content tables over `objects(title, description)` and `note_details(body)`, kept in sync by the watchdog-driven cache updates. Query pipeline: exact prefix on title → FTS ranked (bm25) → tag/type/status filters. The command palette and the search screen share the same search logic (`core/search/`).

---

## 11. Testing

Priorities, adjusted for the removal of a server:

1. **File repository + HLC merge — exhaustive.** This replaces "sync core" as the code that can silently lose data: HLC ordering properties, per-field LWW merge matrix, conflict-file resolution, idempotent re-read. Property-based tests simulating two devices writing to the same object tree.
2. **SQLite cache** — unit tests against a temp directory + in-memory SQLite, including the incremental-update path (watchdog event → cache row) and full reindex.
3. **Smart-list/date logic** — pure functions, plain unit tests (timezone edge cases).
4. **Widget tests** — object card, detail views, board drag, using `pytest-qt` or equivalent.

Current test locations: `desktop/tests/`. No server tests remain (the server no longer exists); the old server-side LWW test suite's *properties* were ported into the filerepo test suite, not the code.

---

## 12. Status

The rework is implemented — `desktop/` is the current, sole client, and every module planned for it is built. See [`../../features/`](../../features/README.md) for what each module actually does today, and [`decisions-log.md`](decisions-log.md) for the phase-by-phase delivery history. The old Flutter client (`app/`), the FastAPI+Postgres server (`server/`), and the static HTML mockups (`dashboard.html`, `identity-mockup-v3.html`) have been removed from the repository; this document and `decisions-log.md` are the historical record of what they were and why they were replaced.

---

## 13. Risks

| Risk | Assessment | Mitigation |
|---|---|---|
| File-tree corruption / partial writes | The one catastrophic failure mode now (no server-side append-only log as a safety net) | **Not yet mitigated** — `filerepo._write_json()` is a direct `write_text()`, not a temp-file+rename; verified by reading the code 2026-07-17, this was previously (incorrectly) documented here as already handled. Needs an actual fix, not just a docs correction. In the meantime, each device is a full replica, so a corrupted file is at least recoverable from any synced peer |
| Syncthing conflicts silently mis-merged | Moderate — HLC merge is the only conflict-resolution logic left, with no server to double-check it | §11 priority 1; keep the old server-side LWW test matrix alive as filerepo tests |
| Qt Widgets ecosystem/PySide6 shifts | Low; both are mature and Qt6 is LTS-supported | Pin versions in `pyproject.toml`; `uv.lock` for reproducibility |
| Single maintainer burnout | The realistic project-killer | Each phase leaves a working app — same mitigation as v0.1 |

