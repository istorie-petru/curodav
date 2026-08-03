# Plan: Trello-like kanban, CalDAV

**Status:** Open · logged 2026-07-19 · §1/§2/§3 (recurrence, table rework, timeline swimlanes) shipped the same day, see below
**Feature areas:** [`../features/calendar.md`](../features/calendar.md), [`../features/tasks.md`](../features/tasks.md), [`../features/boards.md`](../features/boards.md)

Five items from the same request that produced the topbar nav, Notes/Roadmap removal, and calendar overlap/border/snap fixes (all shipped — see `../features/window-and-menu.md` and `../features/calendar.md`). Three of the five shipped the same day as this plan (below); the remaining two didn't: each is independently as large as everything else in this batch combined, and neither composes safely with a rushed implementation — a half-built CalDAV client with no error handling is worse than not having one, because it looks like it works until it silently doesn't.

## 1. Recurrence — done, see `../features/calendar.md`

Built the same day this plan was written: `core/recurrence.py` (a purpose-built daily/weekly + interval + weekdays + until/count + exception-dates rule, not full RFC 5545), wired into all four calendar views via `expand_recurring_objects`, with a real editor in the inspector (frequency, interval, weekday checkboxes, end condition, exception-date add/clear). 21 engine tests plus integration tests driving the actual widgets. Full account, including the "per-instance edits vs. whole-occurrence exceptions" scoping call this section originally asked about (exceptions *remove* an occurrence; editing a single occurrence's time without affecting the series is still not built — see `../expansion-deferred.md`), is in `../features/calendar.md`'s Recurrence section, not repeated here.

## 2. Tasks Table view: Notion-like editable database — done, see `../features/tasks.md`

Built the same day: dropdown editors for status/priority/project (and a real bug fixed along the way — the dropdown-editor resolution logic never actually worked through the `QSortFilterProxyModel`, so every column silently fell back to plain text regardless of the dropdown code already being there), user-configurable + persisted column visibility/order via a header right-click menu, and every inspector-opening code path removed from the view entirely (not just the row-click case originally asked about). Full account in `../features/tasks.md`.

## 3. Tasks Timeline: project swimlanes — done, see `../features/tasks.md`

Built the same day: rows grouped by `parent_id` (project), each project's own overlapping tasks bin-packed into extra rows via the same interval-packing algorithm the calendar uses for concurrent events (extracted to a shared `core/utils/interval_packing.py` rather than duplicated), tasks from different projects structurally unable to share a row (each project gets its own contiguous row range), and a left gutter showing project names. Two tests verify the overlap-packing and the never-share-a-row invariant. Full account in `../features/tasks.md`.

## 4. Tasks Kanban: Trello-like rethink

**The ask:** screenshot showed the current board (dead space at the top of every column before cards start, thin/sparse cards) and asked for something closer to Trello's actual density and visual language.

**Investigated 2026-07-19, not changed:** read `kanban_view.py` (`_KanbanColumn.__init__`) end to end looking for the layout bug that would produce dead space specifically *between* the header and the first card. Didn't find one — the column's `QVBoxLayout` is header → card list → add-input in sequence, no stretch inserted anywhere that would push cards down, no fixed-height spacer, no image/icon loading that could be leaving reserved-but-blank space. This sandbox has no way to actually render the app and take a screenshot to compare against the one provided, so rather than guess at a fix for a bug I can't reproduce or visually confirm, this is left open. If the dead space is still there, the next step is a real screenshot of the current build (post the rest of this session's changes) compared side by side with the original — it's possible something upstream (the tab/stack container, `TasksView`'s view-switcher sizing) is responsible rather than `kanban_view.py` itself.

**Restyle itself still needs more direction:** "Trello-like" could mean denser cards, cover-color strips, avatar/label chips, drag-shadow feedback during drag, or all of the above — worth a concrete reference point (which specific Trello visual elements matter most) before changing anything, rather than guessing at a redesign blind.

## 5. CalDAV/WebDAV external calendar + task list integration

**The ask (confirmed 2026-07-19, not the smaller "internal named lists" option):** connect to real external CalDAV servers (Nextcloud, Radicale, etc.) as independent calendar/task-list sources, selectable via a button similar to the Project filter, alongside the app's local lists.

**Why this is the largest item here:** CalDAV is a different protocol from the WebDAV file-serving the app already has (`core/dav/server.py` serves the local file tree; CalDAV is XML-over-WebDAV with calendar-specific extensions — `calendar-query` REPORT, `calendar-home-set` discovery, VEVENT/VTODO bodies). This is new surface area, not an extension of existing code.

**What it needs, roughly in build order:**
1. **Dependency:** the `caldav` PyPI package (a mature CalDAV client) plus its transitive deps (`icalendar`, `vobject`, `lxml`), added to `desktop/pyproject.toml`.
2. **Account storage:** server URL, username, password (or app-password) per account. Needs a decision on where credentials live — plaintext in `settings.json` is not acceptable for a password; likely the OS keyring via `keyring` (another new dependency) rather than inventing local encryption.
3. **`core/caldav/client.py`:** wraps the `caldav` library — connect, list calendars (`principal.calendars()`), list todo-lists, fetch VEVENT/VTODO within a date window.
4. **Model mapping:** VEVENT → `Object(type=event, ...)`, VTODO → `Object(type=task, ...)`, including a stable way to track "this Object came from remote account X, calendar Y, UID Z" so re-fetching updates instead of duplicating. This needs a real field, not a details-dict guess — likely a `source` field on `Object` (`{"provider": "caldav", "account": ..., "calendar": ..., "uid": ...}`), which is itself a small schema change worth getting right rather than bolting on.
5. **UI:** a Preferences section to add/remove/test accounts (mirroring the existing WebDAV/Syncthing settings tabs' shape), and a list-selector button in Calendar and Tasks (per the ask, "similar to filters and project") showing local lists plus every discovered remote calendar/task-list, each toggleable.
6. **Sync direction and cadence:** decide read-only-refresh vs. write-back (creating/editing a task or event that then pushes to the remote server) before writing any fetch code — this changes the object model mapping (a read-only remote object needs different UI affordances than a fully editable one) and is the single biggest scope decision in this whole item.

This is realistically the size of its own multi-session project, not a checklist item — flagged clearly so it isn't picked up expecting a quick pass.
