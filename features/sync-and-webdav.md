# Feature: Sync (Syncthing) & WebDAV

**Code:** `desktop/src/core/sync/` (`hlc.py`, `lww.py`, `syncthing_client.py`, `watcher.py`), `desktop/src/core/dav/server.py`
**Status:** Syncthing side implemented and verified; WebDAV fixed 2026-07-18 and verified starting/serving requests — see below

See [`../plans/systems/architecture.md`](../plans/systems/architecture.md) §6–7 for the full design rationale; this doc covers what's built.

## P2P sync (Syncthing) — verified working

Optional, toggled in Settings. When enabled, Syncthing (launched as a subprocess or run externally) replicates `~/CommandCenter/` to other devices over an encrypted mesh. The app talks to Syncthing only through its local REST API (`localhost:8384`) — status, connected devices, rescan trigger. The Settings UI call site pings before calling `.status()`/`.connections()` and wraps both in `try/except`, so it degrades gracefully when Syncthing isn't running; the `SyncthingClient` methods themselves don't guard internally, so any future call site needs to copy that pattern rather than call them raw.

**HLC merge on read** (`hlc.py`, `lww.py`): when the app loads an object, it checks for a Syncthing conflict file (`object.sync-conflict-...`). If found, both versions are merged per-field by HLC (higher HLC wins per field), the merged result is written back, and the conflict file is deleted. This makes the app eventually consistent with no server involved. Verified against a synthetic conflict file with a mixed newer/older field split — merges correctly.

Without Syncthing running, the app behaves identically in local-only mode.

## WebDAV — fixed 2026-07-18, verified working

Was broken since at least 2026-07-17 (`WebDavServer.start()` raised `TypeError: 'NoneType' object is not reversible` from inside `wsgidav`'s own init). Two separate bugs, found by actually constructing and serving a `WsgiDAVApp` in isolation and making a real HTTP request against it:

1. The config passed `"middleware_stack": None` — wsgidav iterates/reverses its middleware stack during init, and `None` isn't iterable. wsgidav already ships a sensible default stack; the fix is to just not set this key.
2. `WsgiDAVApp` is a WSGI *application* (a callable), not a server, and has no `serve_forever()`. The original code called it anyway — masked by bug 1, since the app never got far enough to reach that line. Fixed by handing the app to `wsgiref.simple_server.make_server()` (stdlib, no new dependency).

Verified end-to-end: started `WebDavServer` against a temp directory containing a real file, confirmed `is_running`, issued an HTTP GET for that file, got `200` with the correct body back, then confirmed `stop()` actually tears it down. `start()` now also raises `OSError` if the port is already bound rather than failing silently; `MainWindow._apply_webdav` catches that and reports it in the status bar instead of crashing app startup.

An embedded `wsgidav` server (`core/dav/server.py`) serves `~/CommandCenter/` on `localhost` (LAN access an explicit opt-in, off by default), so external tools (Finder/Explorer/Nautilus, Obsidian, `rclone`, `curl`) can mount, browse, and edit the same file tree. The app always reads the filesystem directly regardless — WebDAV is for external-tool interoperability only, never an internal dependency. No auth beyond wsgidav's default "allow everyone" `simple_dc` mapping — fine for localhost-only use, worth revisiting before ever recommending LAN mode for anything but a trusted network.

## Sync status UI

Sidebar sync indicator, system tray icon with notifications, connected-devices list — all sourced from the Syncthing REST client above.
