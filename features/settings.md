# Feature: Preferences

**Code:** `desktop/src/features/settings/widgets.py` (`PreferencesDialog`)
**Status:** Implemented — rebuilt 2026-07-17, corrected 2026-07-18, restructured 2026-07-19, see below

Stored as a local JSON file at `~/.command_center/settings.json` — per-device, not synced.

## What changed 2026-07-17

Three things about this feature were wrong and got fixed in the same pass (Plasma-integration work — see `design-system.md`):

1. **Settings used to be a sidebar module (a page in the main content stack).** It's now `PreferencesDialog`, a non-modal popup window — `MainWindow` keeps one instance and shows/raises it, the same pattern every other desktop app uses for a preferences window. Opened via **Settings → Preferences…** in the menu bar or `Ctrl+,`. It is no longer in `MODULES` and does not appear in the sidebar or bottom nav.
2. **The Appearance tab lost Theme/Density/Shape/Accent.** None of the four were a working feature to begin with — see `design-system.md` for the full story, but in short: Density and Shape were saved and never read back anywhere, and Theme/Accent fed a stylesheet generator that ignored them. The app follows the desktop's native theme automatically now, so there's nothing left for those specific controls to do.
3. **Folder path is no longer a stub.** Previously this field saved to `settings.json` but `FileRepository()` always defaulted to `~/CommandCenter` regardless (flagged in `../STRESS_TEST_2026-07-17.md`). `FileRepository`'s default `base_path` now reads this same setting directly (`core/filerepo/repository.py`), so every bare `FileRepository()` call site in the app — not just the one `MainWindow` holds — honors it. Changing the folder still requires an app restart to take effect (the running file watcher/SQLite cache aren't torn down and rebuilt live); the dialog tells you that when you save a changed path.

## Corrected 2026-07-18: Qt Style was wrongly removed along with the rest

The 2026-07-17 pass deleted the *entire* Appearance tab, including the **Qt Style** picker — and that part was a mistake, caught and fixed the next day. Unlike Theme/Density/Shape/Accent, Qt Style was never dead: it calls `QStyleFactory.create(style_name)` and `QApplication.setStyle(...)`, a real Qt mechanism for running the app under a specific installed style (e.g. Darkly) instead of whatever the platform provides by default. It's back, as a slim Appearance tab containing only that one control. It composes correctly with the native-palette theming from the same pass: choosing a style applies that style's own palette, and the app's QSS reads colors via `palette()` regardless of which style is active — so picking Darkly gives you Darkly's palette *and* the app's structural styling on top of it, not a fight between two theming systems.

## Restructured 2026-07-19: sections, not tabs

Compared against a provided design reference ("ModernPlasma Productivity" — see `design-system.md`), whose Settings screen is one scrolling page of titled `QGroupBox` sections rather than a tabbed dialog. Converted `PreferencesDialog` to match: the `QTabWidget` is gone, replaced by a `QScrollArea` containing one native `QGroupBox` per section, stacked vertically. Each section still owns the exact same field-collection widget class as before (`GeneralTab`, `WebDavTab`, etc. — renamed in spirit but not in code, they're just embedded in a group box now instead of a tab page), so nothing about *what* each section does changed, only the container. This needed no new QSS — `QGroupBox` renders its border/title/corner-rounding from whatever Qt style is active — and let the old `settings-tabs::tab` custom styling be deleted outright rather than trimmed.

`PreferencesDialog.open_on_tab(name)` is now `open_on_section(name)` — scrolls the named `QGroupBox` into view instead of switching a tab index.

## Sections

1. **General** — folder path (wired to the data location, see above), language, autosave interval.
2. **Appearance** — Qt Style picker only (see above).
3. **WebDAV** — enable/disable, port, LAN-only toggle, connection URL display. (The server itself doesn't currently start regardless of these settings — see `sync-and-webdav.md`.)
4. **Syncthing** — enable/disable, device list, status, folder ID, auto-launch toggle.
5. **Calendar** — default calendar, week start day, working hours.
6. **Tags** — tag manager (list, rename, recolor, delete).
7. **About** — version, data location size, "reindex SQLite cache" button, import/export.

Save persists to disk and applies live (WebDAV/Syncthing restart if their settings changed; Qt Style applies immediately; color theme is native so there's nothing to reapply there specifically). Close just dismisses the window.
