# Feature: Window chrome, top navigation & menu bar

**Code:** `desktop/src/app.py` (`TopNav`, `MainWindow._setup_actions`, `_setup_menu_bar`)
**Status:** Implemented 2026-07-17, navigation rebuilt 2026-07-19, placement fixed 2026-07-20

## Top navigation (rebuilt 2026-07-19)

The sidebar + responsive bottom-nav pair is gone, replaced by `TopNav`: a single horizontal bar of `QToolButton`s, one per module, using `ToolButtonTextUnderIcon` (icon above label) — a real native Qt toolbar style, not a custom-drawn nav rail. This is literally how Calibre's own toolbar renders (a reference screenshot was provided); no custom button chrome is needed beyond minimal padding, since `ToolButtonTextUnderIcon` checkable buttons already render correctly under any active Qt style.

Icons come from the desktop's icon theme via `QIcon.fromTheme(name, fallback)` — e.g. `"go-home"`, `"view-task"`, `"view-calendar"`, `"edit-find"`, `"folder"` — with a `QStyle.StandardPixmap` fallback for platforms/environments with no icon theme available (headless test runs, some non-Linux platforms). This is the native mechanism for "use the system's icons": no bundled icon assets, whatever Breeze (or the active theme) provides is what renders.

One consequence worth calling out: a single top bar works at every window width, so the old responsive sidebar-vs-bottom-nav switch (`resizeEvent` toggling visibility by a 900px threshold) is gone entirely — there's nothing to switch between anymore.

**Fixed 2026-07-20 — TopNav was rendering as a left-side rail, not a top bar.** `MainWindow._setup_ui`'s root layout was never actually changed when the sidebar was rebuilt into `TopNav`: it was still a `QHBoxLayout` with `self._topnav` added as the first item next to the rest of the window content, which places any widget on the *left*, full stop, regardless of how that widget lays out its own children internally. `TopNav`'s buttons were correctly arranged left-to-right in its own internal `QHBoxLayout`, so the bug wasn't visible by reading `TopNav` in isolation — the widget itself was still being slotted into the sidebar position by its *parent's* layout. Fixed by changing the root layout to `QVBoxLayout` (`TopNav` on top, full width; `TopBar` + content + status bar stacked below it), which is what "top navigation" actually requires. Verified with real widget geometry after a resize (not just structural code reading, since this exact bug was invisible to code reading the first time): at a 1200×800 window, `TopNav` is `(0, 0, 1200, 60)` -- spans the full width, sits at y=0 -- and the content stack starts at y=93, below both `TopNav` and `TopBar`.

## Global menu

`MainWindow.menuBar()` — a real `QMenuBar`, not a custom-drawn toolbar. On KDE Plasma with the appmenu platform integration active (`appmenu-qt6`/`kf6` and the Global Menu widget), Qt routes a native `QMenuBar` into Plasma's global menu automatically; there's no separate "global menu" API to call, and no extra code needed beyond using a real menu bar instead of, say, a row of buttons. Where that integration isn't present (other desktops, or Plasma without the widget), the same menu bar renders in-window at the top, which is also correct.

Menus:

- **File** — New Task (Alt+1), New Event (Alt+3), Import…, Export…, Quit (Ctrl+Q). ("New Note" removed 2026-07-19 along with the Notes module — see below.)
- **View** — one entry per module (Dashboard/Tasks/Calendar/Search) plus Projects, then Focus Search (Ctrl+F), Command Palette (Ctrl+K), Toggle Navigation Bar (Ctrl+B, renamed from "Toggle Sidebar")
- **Tools** — Reindex SQLite Cache
- **Settings** — Preferences… (Ctrl+,), opens `PreferencesDialog` — see `settings.md`
- **Help** — About Command Center

## Actions are shared, not duplicated

Every `QAction` is created once in `_setup_actions` (stored as `self._action_*` attributes) and reused both for the global keyboard shortcut (`self.addAction(...)`, works regardless of which menu is focused) and as the menu entry. One definition per action means the shortcut shown in the menu is always the one that actually fires — there's no second, separately-typed shortcut string to drift out of sync.

## Fixed while touching this code (2026-07-17)

Building the View menu required enumerating `MODULES` by id rather than by position, which surfaced three existing bugs where module navigation used a hardcoded index that had drifted out of sync with `MODULES` (New Note and daily-note-from-calendar opened Roadmap instead of Notes; Focus Search opened what was then the Settings module instead of Search). All three were fixed by resolving the target module by id via a `_module_index(module_id)` helper instead of a magic number. (Two of the three call sites — New Note and daily-note — no longer exist at all after the 2026-07-19 Notes removal; `_module_index` itself remains and still protects Focus Search and every other lookup.)

## Notes & Roadmap removed (2026-07-19)

Both modules were removed from `MODULES`, the top nav, the menu bar, and the content stack — they're planned to come back later as a folder-and-markdown-first feature, not the current object-model-backed implementation. What stayed:

- **The data model.** `ObjectType.note` and `ObjectType.roadmap_node` still exist; nothing was done to purge or migrate existing user data of these types. A `note`-type object created before this change (or synced in from another device) still opens fine in the generic Inspector — title, description, tags, linking all still work — it just has no dedicated module UI anymore.
- **Search.** Note/roadmap-node objects are still indexed and findable (to the extent Search works at all — see `../STRESS_TEST_2026-07-17.md`).

What was removed along with the modules: the Calendar day-cell right-click "Open daily note" context menu (its only purpose was opening the now-gone Notes module, so the menu action — and the now-dead-end `daily_note_requested` signal it drove — were deleted rather than left as a no-op), and the seed/demo data's one `note` object and three `roadmap_node` objects (kept the `goal`-type seed objects, since those don't depend on a dedicated module to make sense generically).

## Window decorations

`MainWindow` has never set a frameless window hint — it always used native window decorations (title bar, minimize/maximize/close drawn by KWin/the window manager, not the app). A `TitleBar` widget existed in the source with macOS-style traffic-light buttons but was never instantiated anywhere; it was deleted as dead code (2026-07-17) rather than left in place implying the app draws its own chrome.
