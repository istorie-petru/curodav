"""1.8 slices 3-7 -- the PWA shell (plans/open-priority.md § Offline-first
editing & synchronization §11).

Slice 3: manifest, service worker, offline app-shell caching -- "can the
app open at all with no network."

Slice 4: the client-side local read path on top of that shell --
static/offline_db.js (an IndexedDB mirror of tasks/events/contacts, keyed
by the same per-field HLC rule offline_sync.py's own field_versions table
uses server-side) and static/offline_sync_client.js (§8's pull half,
run client-side, loaded globally so the mirror is warm before the network
actually drops). templates/offline.html's #offline-local-data now renders
straight from that mirror via static/offline_shell.js.

Slice 5: the local *write* path -- static/offline_write.js
(create/edit/delete a task offline, each queued as a §2 op into
offline_db.js's new `outbox` IndexedDB store and applied optimistically to
the mirror through the same per-field-HLC path a pull already uses).
offline_db.js also gained this device's own §3 HLC clock (`nextHlc`/
`mergeHlc`) -- nothing before this slice ever needed to *mint* an HLC, only
apply server-supplied ones.

Slice 6: the sync *engine* -- static/offline_sync_client.js grew a push
half (draining the outbox against POST /api/sync/push) alongside its pull
half, wrapped in §8's push-then-pull order; §5's retry/backoff with
jitter; and static/offline_status.js, the small offline/synchronizing/
pending/synced indicator, computed live off {navigator.onLine, in-flight,
outbox size} rather than stored. This is what wires slices 1-5 together
end to end -- an offline write finally leaves the device once one comes
back online.

Slice 7: "Tombstone GC" -- src/offline_sync.py's `purge_expired` (the
physical-deletion half of §4's retention horizon; slice 1's `pull()`
already had the safety half, forcing a full resync for a stale cursor),
wired into routers/sync_api.py's pull handler as a lazy "check on every
pull" trigger (src/data_health.py's `run_sync_gc`, also reachable from
Settings > Data health and scripts/data_health.py's CLI). Closing this
gap also exposed a real correctness risk in slice 4's own full_resync
handling: once the server can physically purge an old tombstone, a plain
re-pull-and-applyChanges could never tell a badly-stale device that
already-purged entity is gone -- static/offline_db.js's new `clearMirror`
and offline_sync_client.js calling it before a full resync's re-pull is
what closes that gap. This is the last of 1.8's 7 planned slices.

Neither a real service worker nor real IndexedDB can be exercised by this
app's usual pytest/router-function-call convention (there's no browser
here to install a worker, intercept fetches, read Cache Storage, or run
indexedDB.open) -- that part needs manual/browser verification, per
plans/STATE.md's own note on this slice. What *is* verifiable server-side,
and covered here:

  - manifest.webmanifest is valid, has the fields a browser's install
    prompt needs, and every icon it references actually exists on disk.
  - GET /sw.js serves static/sw.js's own content as a real script (not a
    404/redirect), with a JS content-type and no-store caching so browsers
    always refetch the script itself to notice an update.
  - GET /offline renders the normal page chrome (tabbar, nav) plus an
    honest "you're offline" message -- reachable normally online, not
    sw.js-only, so this needs no simulated dropped connection.
  - sw.js's own precache list only names static assets that actually
    exist under src/static, /offline, and /manifest.webmanifest --
    confirmed at the source level since nothing else can run the service
    worker. This automatically covers slice 4's own new scripts (offline_
    db.js/offline_sync_client.js/offline_shell.js) once they're added to
    that list, with no test change needed for them specifically.
  - main.py actually registers pwa.router (routers/settings.py's own
    2026-08-14 follow-up note describes a router losing its decorator
    silently while every existing test still passed -- confirmed here via
    `router.routes` directly, the same fix applied there, not just by
    hitting the routes through router-function calls).
  - offline_db.js/offline_sync_client.js/offline_shell.js are structurally
    sound (define the expected object stores/exports/handlers) and are
    actually wired into base.html/offline.html -- the same "read the JS
    source, assert the shape" level of confidence as the sw.js checks
    above, not a claim that the logic runs correctly in a real browser."""

from __future__ import annotations

import json
import re
from pathlib import Path

from starlette.requests import Request

from src.main import app as fastapi_app
from src.routers import pwa as pwa_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


def _request(path="/offline"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


class TestManifest:
    def test_manifest_is_valid_and_installable(self):
        manifest = json.loads((_STATIC_DIR / "manifest.webmanifest").read_text())
        assert manifest["name"]
        assert manifest["short_name"]
        assert manifest["start_url"] == "/"
        assert manifest["display"] == "standalone"
        assert len(manifest["icons"]) >= 2
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        assert "192x192" in sizes
        assert "512x512" in sizes

    def test_every_manifest_icon_exists_on_disk(self):
        manifest = json.loads((_STATIC_DIR / "manifest.webmanifest").read_text())
        for icon in manifest["icons"]:
            assert icon["src"].startswith("/static/")
            rel = icon["src"][len("/static/"):]
            assert (_STATIC_DIR / rel).exists(), icon["src"]

    def test_base_html_links_the_manifest_and_theme_color(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert 'rel="manifest"' in html
        assert "manifest.webmanifest" in html
        assert 'name="theme-color"' in html
        assert "pwa.js" in html


class TestServiceWorker:
    def test_sw_js_route_serves_the_real_script(self):
        response = pwa_router.service_worker()
        assert response.media_type == "application/javascript"
        assert response.headers["cache-control"] == "no-store"
        assert Path(response.path) == _STATIC_DIR / "sw.js"

    def test_sw_js_registers_install_activate_fetch_handlers(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert 'addEventListener("install"' in script
        assert 'addEventListener("activate"' in script
        assert 'addEventListener("fetch"' in script
        assert "skipWaiting" in script
        assert "clients.claim" in script

    def test_precache_list_only_names_assets_that_exist(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        match = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\];", script, re.S)
        assert match, "couldn't find SHELL_ASSETS in sw.js"
        urls = re.findall(r'"(/[^"]+)"', match.group(1))
        assert urls, "SHELL_ASSETS parsed empty"
        for url in urls:
            if url == "/offline" or url == "/manifest.webmanifest":
                continue
            assert url.startswith("/static/"), url
            rel = url[len("/static/"):]
            assert (_STATIC_DIR / rel).exists(), url
        assert "/offline" in urls

    def test_pwa_js_registers_the_root_scoped_script(self):
        script = (_STATIC_DIR / "pwa.js").read_text()
        assert 'serviceWorker.register("/sw.js")' in script


class TestOfflineShell:
    def test_offline_page_renders_full_chrome_and_offline_message(self):
        body = pwa_router.offline_shell(_request("/offline")).body.decode()
        # Tabbar is hidden in offline mode (hide_tabbar = true)
        assert '<nav class="tabbar"' not in body
        assert "Offline Mode" in body
        # Offline indicator should be present
        assert "You're offline" in body
        # Main panels should be present
        assert "Dashboard" in body
        assert "Calendar" in body
        assert "Tasks" in body
        assert "Contacts" in body
        assert "Notes" in body

    def test_offline_page_reachable_without_simulating_a_dropped_connection(self):
        # A plain route, not sw.js-only -- confirms the page itself needs
        # no DB/network dependency to render (no `conn` in the handler's
        # signature at all).
        import inspect

        params = inspect.signature(pwa_router.offline_shell).parameters
        assert "conn" not in params


class TestLocalReadPath:
    def test_offline_db_defines_the_expected_stores_and_exports(self):
        script = (_STATIC_DIR / "offline_db.js").read_text()
        for store in ('"tasks"', '"events"', '"contacts"', '"notes"', '"field_hlc"', '"meta"'):
            assert store in script
        for export in (
            "getDeviceId",
            "getCursor",
            "setCursor",
            "getLastSyncedAt",
            "setLastSyncedAt",
            "applyChanges",
            "getAllTasks",
            "getAllEvents",
            "getAllContacts",
            "getAllNotes",
        ):
            assert export in script
        assert "window.CCOfflineDB" in script
        # §6's per-field HLC compare must exist, not just a blind
        # overwrite -- the whole reason field_hlc is a separate store.
        assert "isNewer" in script

    def test_offline_sync_client_pulls_only_as_of_slice_4(self):
        # Historical marker for slice 4's own scope, at the point this test
        # was written -- offline_sync_client.js has since grown a push half
        # too (slice 6, see TestSyncEngine below). Kept as a pull-specific
        # smoke check rather than deleted outright.
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "/api/sync/pull" in script
        assert "full_resync" in script
        assert "window.CCOfflineSync" in script

    def test_offline_shell_reads_from_the_mirror_not_the_network(self):
        script = (_STATIC_DIR / "offline_shell.js").read_text()
        assert "CCOfflineDB.getAllTasks" in script
        assert "CCOfflineDB.getAllEvents" in script
        assert "fetch(" not in script

    def test_base_html_loads_the_mirror_and_pull_loop_globally(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert "offline_db.js" in html
        assert "offline_sync_client.js" in html
        # offline_shell.js is /offline-specific, not a global page load --
        # it belongs in offline.html's own extra_scripts block, not here.
        assert "offline_shell.js" not in html

    def test_offline_html_has_the_render_target_and_loads_the_shell_script(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        # New Offline Mode page has multiple panel IDs
        assert 'id="offline-dashboard"' in html
        assert 'id="offline-calendar"' in html
        assert 'id="offline-tasks"' in html
        assert 'id="offline-contacts"' in html
        assert 'id="offline-notes"' in html
        assert "offline_shell.js" in html

    def test_precache_list_includes_the_local_read_path_scripts(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        for asset in ("/static/offline_db.js", "/static/offline_sync_client.js", "/static/offline_shell.js"):
            assert asset in script


class TestLocalWritePath:
    """1.8 slice 5 -- "Local write path + outbox" (open-priority.md §11
    slice 5). Same "read the JS source, assert the shape" level of
    confidence as TestLocalReadPath above -- no real browser/IndexedDB
    here. The actual outbox/HLC merge logic is exercised end-to-end by a
    one-off Node + fake-indexeddb smoke script (not part of this suite,
    same as slice 4's own smoke run) that caught a real ordering bug during
    development: getOutboxOps() must sort explicitly (by each op's own
    HLC), since IndexedDB's default key-order iteration over a random-UUID
    keyPath is not insertion order."""

    def test_offline_db_gained_the_hlc_clock_and_outbox(self):
        script = (_STATIC_DIR / "offline_db.js").read_text()
        assert '"outbox"' in script
        for export in ("nextHlc", "mergeHlc", "enqueueOp", "getOutboxOps", "getOutboxCount"):
            assert export in script

    def test_offline_write_defines_create_edit_delete_for_tasks(self):
        script = (_STATIC_DIR / "offline_write.js").read_text()
        for export in ("createTask", "updateTaskField", "deleteTask"):
            assert export in script
        assert "window.CCOfflineWrite" in script
        # Every op this file builds must go through the outbox, not just
        # straight to the mirror -- that's the whole point of the slice
        # ("queue as ops instead of failing," not "write straight through").
        assert "enqueueOp" in script
        # Still no network call anywhere in the write path itself (push is
        # slice 6) -- a local write must succeed with zero connectivity.
        assert "fetch(" not in script

    def test_offline_write_never_pushes(self):
        script = (_STATIC_DIR / "offline_write.js").read_text()
        assert "/api/sync/push" not in script

    def test_offline_shell_wires_up_the_write_ui(self):
        script = (_STATIC_DIR / "offline_shell.js").read_text()
        assert "CCOfflineWrite.createTask" in script
        assert "CCOfflineWrite.updateTaskField" in script
        assert "CCOfflineWrite.deleteTask" in script

    def test_offline_html_loads_the_write_script(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        assert "offline_write.js" in html
        assert "offline_shell.js" in html

    def test_base_html_does_not_load_the_write_script_globally(self):
        # offline_write.js's UI hooks (the add-task form, per-row buttons)
        # only exist on /offline's own markup -- loading it globally would
        # be dead weight on every other page, unlike offline_db.js/
        # offline_sync_client.js which genuinely need to run everywhere to
        # keep the mirror warm. base.html's own comment block may still
        # *mention* the filename in prose (explaining why it's excluded),
        # so this checks for an actual <script src> tag, not a bare
        # substring match.
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert "static_url('offline_write.js')" not in html

    def test_precache_list_includes_the_write_path_script(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert "/static/offline_write.js" in script

    def test_shell_cache_name_was_bumped_for_the_reworked_sync_scripts(self):
        # cc-shell-v3 was slice 5's own bump (adding offline_write.js);
        # slice 6 added offline_status.js and bumped to v4; v5 fixed the
        # manifest precache entry (was "/manifest.webmanifest", a path that
        # 404s -- the file is only served at "/static/manifest.webmanifest"
        # -- which made cache.addAll() reject and the whole shell precache
        # fail on install); v6 (2026-08-15) dropped schedule_table.js/
        # schedule_grid.js from the precache list along with the whole
        # Schedule module, see plans/STATE.md's removal entry; v7
        # (2026-08-15) added event_format_toggle.js, "Event format for
        # simple events"; v8 (2026-08-16) reworked toast.js /
        # offline_status.js / style.css (sync status + delete confirms as
        # bottom-right toasts), forcing a fresh shell install so no
        # precached copy of the old assets lingers; v9 (2026-08-17)
        # reworked offline_sync_client.js / offline_status.js again (sync-
        # status toasts fire only on real sync work), forcing a fresh
        # shell install so an installed PWA never keeps serving a cached
        # copy that announces "Syncing…"/"Synced" on dead-server page
        # loads; v10 (2026-08-18) reworked offline_status.js again (the
        # in-progress "Syncing…" toast is deferred by a grace period so a
        # fast small sync never flashes it), forcing a fresh shell install
        # so an installed PWA doesn't keep serving the pre-delay renderer;
        # v11 (2026-08-18) made the static-asset handler fall back to
        # `caches.match(request, { ignoreSearch: true })` so the versioned
        # `?v=` URLs every page requests can be served from the precache's
        # un-versioned entries -- before that, scripts only /offline loads
        # (offline_shell.js / offline_write.js / offline_status.js) were
        # never runtime-cached during normal page visits and failed to load
        # on a device's first offline visit, leaving the static empty state
        # visible; v12 (2026-08-18) added offline_quick_capture.js to the
        # precache list (the "Quick add" toolbar's capture parser); v14
        # (2026-08-26) picked up the Data & Maintenance export/import
        # redesign's style.css additions; v15 (2026-08-29) is the root-cause
        # fix for a session's worth of style.css edits silently not showing
        # up in the browser -- the ignoreSearch fallback (v11) means a
        # precached style.css never goes stale on its own, so a style-only
        # change now has to bump CACHE_NAME too, not just a script rewrite;
        # v16 (2026-08-29) is the very next style.css-only edit proving that
        # lesson had to actually be followed, not just written down; v17
        # (2026-08-29) is the heatmap scrollbar-visibility rules added for
        # the "no scrollbar" follow-up; v18 (2026-08-29) superseded that with
        # heatmap-wide cell-stretching instead (no scrollbar ever needed) and
        # reverted the v17 CSS; v19 (2026-08-29) is the same lesson applied to
        # a *script* -- static/sidebar_tree.js's dashboard-resize-dispatch fix
        # wasn't reaching browsers with an already-installed PWA (the
        # ignoreSearch fallback also matches a stale runtime-cached script,
        # not just precached ones), so it needed the same CACHE_NAME bump;
        # sidebar_tree.js was also added to SHELL_ASSETS (it's a base.html
        # script loaded on every page, same category as app.js/modal.js).
        # v20 (2026-08-29): bumped again for a style.css-only change (the
        # sidebar-header/app-name rules), per the same v15 lesson.
        # v21 (2026-08-29): bumped again for the collapsed/expanded item
        # padding unification, same lesson.
        # v22 (2026-08-29): bumped again for the new .page-header-narrow
        # rules (sidebar redesign item 13e), same lesson.
        # v23 (2026-08-29): bumped again for the narrow-header banner/
        # actions-slot rules (folding Tasks/Contacts/Calendar's old
        # toolbar-2row into the header), same lesson.
        # v24 (2026-08-29): bumped again for the Dashboard Header
        # (Expanded) avatar overlap rules, same lesson.
        # v25 (2026-08-29): bumped for two SHELL_ASSETS *scripts* changing
        # (avatar_cropper.js generalized to banners, app.js's CCBannerUpload
        # removed) -- the v19 lesson, not just style.css.
        # v26 (2026-08-29): bumped again for avatar_cropper.js changing once
        # more (smaller avatar output cap, WebP output), same lesson.
        # v27 (2026-08-30): bumped for a style.css-only change (collapsed
        # rail's per-item height + icon-only labels), same lesson.
        # v28 (2026-08-30): bumped again, same session (collapsed rail
        # icon left-aligned + full-box active highlight), same lesson.
        # v29 (2026-08-30): bumped again, same session (collapsed rail
        # narrowed 80px -> 64px, icon nudged further from the left edge),
        # same lesson.
        # v30 (2026-08-30): bumped again, same session (collapsed rail
        # narrowed again, 64px -> 56px), same lesson.
        # v31 (2026-08-30): bumped again, same session (collapsed rail
        # narrowed once more, 56px -> 52px), same lesson.
        # v32 (2026-08-30): bumped again, same session (expanded mode's own
        # left/right padding mismatch fixed), same lesson.
        # v33 (2026-08-30): bumped again, same session (icon jump between
        # collapsed/expanded fixed, active-highlight radius unified),
        # same lesson.
        # v34 (2026-08-30): bumped again, new session (widget CSS pass --
        # item 1 of the design check-up queue: .widget-card chrome, header/
        # section-label typography, widget-content table row style), same
        # style.css-only lesson.
        # v35 (2026-08-30): bumped again, same session (live bug report --
        # Weekly Schedule crash fix, .widget-card--bare for Quick Links/
        # Spaces & Projects cards style) -- style.css changed again.
        # v36 (2026-08-30): bumped again, new session (quick_links merged
        # into spaces_projects cards style; next_deadline/organize_today/
        # streak removed outright) -- .widget-card--bare's own comment in
        # style.css updated to match, comment-only but same file-changed
        # convention as every other entry above.
        # v37 (2026-08-30): bumped again, same session (direct report --
        # "the way widgets are aranged is not ok" -- app.js's dashboard
        # masonry switched from strict-DOM-order first-fit placement to
        # best-fit-among-remaining, so a short widget's dead-space gap can
        # be backfilled by a later, narrower widget instead of forcing
        # everything after it down to the tallest neighbor's height).
        # v38 (2026-08-30): bumped again, same session (direct request --
        # "can't we have a width setting in edit mode (100%,75%,50%,25%)"
        # -- manual per-widget width override reinstated, grid widened
        # 6->12 virtual columns so 25%/75% land exactly; app.js's maxCols
        # and style.css's data-span selectors both changed).
        # v39 (2026-08-30): bumped again, same session -- three more
        # direct-report fixes: widget_card_region's edit_mode no longer
        # hardcoded False (a widget's own card can now refresh live after
        # a Filters/Width save instead of needing a hard reload),
        # dashboard_widget_preview.js's autosave calls refreshRegion,
        # app.js gained a medium-breakpoint quarter->half promotion and a
        # full drag-to-resize handle (both precached files changed).
        # v40 (2026-08-30): bumped again, same session, immediate follow-up
        # -- direct report the resize handle "just selects the text"
        # instead of dragging. The handle is a plain <div> over ordinary
        # text content (unlike the reorder handle, a real <button>, which
        # browsers never start a text-selection drag from) -- its
        # pointerdown now calls preventDefault (the load-bearing fix), and
        # .widget-card.is-resizing/.widget-resize-handle both got
        # user-select:none as a second CSS-only layer for the drag's
        # whole duration, not just its first pixel.
        # v41 (2026-08-30): root-cause fix for the fetch handler's static-
        # asset fallback ORDER, not a precache-list change -- direct report
        # ("edits don't show up, hard refresh fixes it, navigating away and
        # back reverts to stale"). The old order tried the exact versioned
        # match, then went straight to the ignoreSearch precache/runtime-
        # cache match on a miss, BEFORE ever trying the network -- so any
        # already-cached old version of a file was served forever, never
        # re-fetched, regardless of the `?v=` query changing. Network is
        # now tried before the ignoreSearch fallback; that fallback only
        # fires if the network fetch itself fails (genuinely offline).
        # v42 (2026-08-30): bumped again, same session, direct follow-up --
        # "the mouse resize still doesn't work. remove it." The drag-to-
        # resize handle (app.js/style.css/_widget_workspace.html/
        # _widget_card.html/routers/dashboard.py's resize_widget) is gone
        # outright, not fixed a third time -- the Filters panel's own
        # Width field is confirmed working ("the dashboard customise is
        # fine") and is the only way to set width now.
        script = (_STATIC_DIR / "sw.js").read_text()
        assert 'CACHE_NAME = "cc-shell-v46"' in script


class TestOfflineToolbar:
    """2026-08-19 -- Dedicated Offline Mode page: full tabbed interface
    mirroring the main app navigation (Dashboard, Calendar, Tasks, Contacts,
    Notes) with read/write access to the local IndexedDB mirror. Quick add is
    a floating action button on every tab. Same "read the JS/template source,
    assert the shape" level of confidence as every other class here."""

    def test_offline_page_has_the_main_tabs(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        assert 'data-offline-main-tab="dashboard"' in html
        assert 'data-offline-main-tab="calendar"' in html
        assert 'data-offline-main-tab="tasks"' in html
        assert 'data-offline-main-tab="contacts"' in html
        assert 'data-offline-main-tab="notes"' in html
        assert "Dashboard" in html
        assert "Calendar" in html
        assert "Tasks" in html
        assert "Contacts" in html
        assert "Notes" in html

    def test_offline_html_has_the_quick_add_builder(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        # New inline visual builder replaces the modal - included via partial
        assert '_offline_quick_add.html' in html
        # Check the partial directly
        partial_html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "_offline_quick_add.html").read_text()
        assert 'id="offline-quick-add-form"' in partial_html
        assert 'id="offline-entity-type"' in partial_html
        assert 'id="offline-task-fields"' in partial_html
        assert 'id="offline-event-fields"' in partial_html
        assert 'id="offline-contact-fields"' in partial_html
        assert 'id="offline-note-fields"' in partial_html
        assert 'id="offline-capture-text"' in partial_html
        assert 'id="offline-quick-add-result"' in partial_html

    def test_offline_html_loads_the_quick_add_scripts(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "offline.html").read_text()
        assert "offline_quick_capture.js" in html
        assert "offline_write.js" in html
        assert "offline_shell.js" in html

    def test_offline_quick_capture_defines_the_parser_and_markers(self):
        script = (_STATIC_DIR / "offline_quick_capture.js").read_text()
        assert "window.CCOfflineCapture" in script
        assert "parse: parse" in script
        for marker in ("!t", "!e", "!c", "!n"):
            assert marker in script
        # Parser only -- no network call anywhere in it (it must work fully
        # offline, there's no server to preview against).
        assert "fetch(" not in script

    def test_offline_write_gained_event_and_contact_creates(self):
        script = (_STATIC_DIR / "offline_write.js").read_text()
        assert "createEvent" in script
        assert "createContact" in script
        assert "createNote" in script
        # Both built by one shared create helper, not two copies of the
        # create-op plumbing.
        assert "createEntity" in script

    def test_offline_shell_renders_all_panels(self):
        script = (_STATIC_DIR / "offline_shell.js").read_text()
        # Now renders all five panels
        assert "Tasks (" in script
        assert "Upcoming Events (" in script
        assert "Timetabled events (" in script
        assert "Contacts (" in script
        assert "Notes (" in script
        # The timetabled section is driven by the mirror's work-allocation
        # flag -- the thing the server's new is_work_allocation sync field
        # delivers.
        assert "is_work_allocation" in script

    def test_offline_shell_wires_the_quick_add_builder(self):
        script = (_STATIC_DIR / "offline_shell.js").read_text()
        # New inline visual builder (replaces modal-based quick capture)
        assert "offline-quick-add-form" in script
        assert "offline-entity-type" in script
        assert "offline-task-fields" in script
        assert "offline-event-fields" in script
        assert "offline-contact-fields" in script
        assert "offline-note-fields" in script
        assert "offline-capture-text" in script
        assert "CCOfflineWrite.createEvent" in script
        assert "CCOfflineWrite.createContact" in script
        assert "CCOfflineWrite.createTask" in script
        assert "CCOfflineWrite.createNote" in script

    def test_quick_capture_script_not_loaded_globally(self):
        # offline_quick_capture.js is /offline-only, like offline_write.js
        # and offline_shell.js -- loading it on every page would be dead
        # weight (offline_db.js/offline_sync_client.js/offline_status.js
        # are the ones that genuinely run everywhere).
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert "offline_quick_capture.js" not in html

    def test_precache_list_includes_the_quick_capture_script(self):
        script = (_STATIC_DIR / "sw.js").read_text()
        assert "/static/offline_quick_capture.js" in script


class TestSyncEngine:
    """1.8 slice 6 -- "Sync engine" (open-priority.md §11 slice 6): the
    push half of §8's protocol, §5's retry/backoff, and the status
    indicator. Same structural-check level as every other class here --
    the actual push/retry/backoff behavior needs a real browser or a
    Node + fake-indexeddb smoke run (this slice's own, not part of this
    suite, same pattern slices 4-5 already established) to exercise for
    real."""

    def test_offline_sync_client_now_pushes_before_pulling(self):
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "/api/sync/push" in script
        assert "/api/sync/pull" in script
        assert script.index("pushOnce()") < script.index("pullOnce()")

    def test_offline_sync_client_acks_pushed_ops_via_removeOutboxOps(self):
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "removeOutboxOps" in script

    def test_offline_sync_client_has_backoff_with_a_cap_and_jitter(self):
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "MAX_RETRY_MS" in script
        assert "jitter" in script
        assert 'addEventListener("online"' in script
        assert 'addEventListener("offline"' in script

    def test_offline_sync_client_exposes_status_for_the_indicator(self):
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "getStatus" in script
        assert "requestSync" in script
        assert "cc-offline-status-change" in script

    def test_offline_sync_client_tracks_whether_a_round_moved_data(self):
        # 2026-08-17 follow-up -- the "Synced" announcement must only fire
        # when a round actually moved data (pushed a non-empty outbox or
        # pulled a non-empty changes list), not on a routine page-load
        # health check of an up-to-date, continuously-connected machine.
        # `didWork` is reset at the start of every syncNow round and set by
        # pushOnce/pullOnce only when there was something to move, then
        # surfaced through getStatus for offline_status.js to read.
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "didWork" in script
        assert "getOutboxOps()" in script
        assert "body.changes" in script
        assert "didWork }" in script  # getStatus returns it in the detail

    def test_sync_now_announces_round_start_only_with_real_push_work(self):
        # 2026-08-17 follow-up -- the round-start "synchronizing" emission
        # must be gated on a non-empty outbox, so a routine pull-only
        # page-load round never flashes a "Syncing…" toast on an
        # up-to-date, continuously-connected machine; only the round's
        # outcome is announced.
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        sync = script[script.index("async function syncNow()") : script.index("window.CCOfflineSync")]
        assert "getOutboxCount()" in sync
        assert sync.index("getOutboxCount()") < sync.index("pushOnce()")
        # The round-start emission is conditioned on that non-empty outbox.
        assert "if (outboxCount > 0)" in sync
        assert "await emitStatus()" in sync

    def test_sync_now_skips_the_round_entirely_when_the_server_version_is_unchanged(self):
        # 2026-08-17 (the user's "hash attached to the database" idea) --
        # when the outbox is empty and the server's data version matches
        # what this device saved after its last successful pull, the round
        # is skipped outright: no pull request, no status event, no toast.
        # `nothingToDo()` must run only on the empty-outbox branch (a
        # non-empty outbox always pushes, regardless of the version), and a
        # failed state check must fall through to the normal round rather
        # than being wrongly treated as "nothing to do".
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        sync = script[script.index("async function syncNow()") : script.index("window.CCOfflineSync")]
        assert "getServerVersion()" in script
        assert "nothingToDo()" in sync
        assert sync.index("getOutboxCount()") < sync.index("nothingToDo()")
        assert sync.index("nothingToDo()") < sync.index("pushOnce()")
        assert '"GET"' in script and "/api/sync/state" in script
        # A failed/unreachable state check must not count as "nothing to do".
        nothing = script[script.index("async function nothingToDo()") : script.index("async function getStatus()")]
        assert "return false" in nothing
        assert "state.version === saved" in nothing

    def test_offline_db_stores_the_last_synced_server_version(self):
        # 2026-08-17 -- meta helper pair the round-skip pre-check reads.
        script = (_STATIC_DIR / "offline_db.js").read_text()
        assert "getServerVersion" in script
        assert "setServerVersion" in script
        assert "server_version" in script
        assert "getServerVersion," in script  # exposed on window.CCOfflineDB

    def test_offline_write_requests_a_sync_after_queuing_a_write(self):
        # A local write shouldn't have to wait for the next periodic retry
        # if the device is already online.
        script = (_STATIC_DIR / "offline_write.js").read_text()
        assert "CCOfflineSync" in script
        assert "requestSync" in script

    def test_offline_status_renders_from_events_not_direct_state(self):
        script = (_STATIC_DIR / "offline_status.js").read_text()
        assert "cc-offline-status-change" in script
        # Renderer only -- no IndexedDB or network calls of its own.
        assert "indexedDB.open" not in script
        assert "fetch(" not in script

    def test_offline_status_defers_the_in_progress_toast_behind_a_grace(self):
        # 2026-08-18 follow-up -- the in-progress "Syncing…"/"Changes
        # pending" toast is deferred by SYNC_SHOW_DELAY_MS on its first
        # appearance: a small sync round that finishes inside the window
        # never flashes a toast at all, and only a round still in flight
        # once the grace elapses surfaces as "in progress" (the user's "for
        # bigger syncing it shows, but for small ones it doesn't"). The
        # deferral is renderer-side -- offline_sync_client.js's status
        # events stay immediate -- and every new status event cancels a
        # pending grace timer so a fast round's deferred toast can never
        # surface after its outcome.
        script = (_STATIC_DIR / "offline_status.js").read_text()
        render = script[script.index("function render(") : script.index("document.addEventListener")]
        assert "SYNC_SHOW_DELAY_MS" in script
        assert "setTimeout(" in render
        assert "clearSyncGraceTimer()" in render
        # Defer only the *first* appearance -- an already-visible in-progress
        # toast (a genuinely stuck/failing round) keeps updating in place,
        # and the network-offline state surfaces immediately, never deferred.
        assert "isAlive()" in render
        assert 'detail.status === "offline"' in render
        assert "clearTimeout(syncGraceTimer)" in script

    def test_offline_status_script_loaded_globally_and_precached(self):
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "base.html").read_text()
        assert "offline_status.js" in html
        script = (_STATIC_DIR / "sw.js").read_text()
        assert "/static/offline_status.js" in script

    def test_data_health_sync_summary_reflects_real_sync_devices(self, tmp_path):
        # open-priority.md §9: the fixed {"configured": False} placeholder
        # data_health.py carried through slices 1-5 is what slice 6 was
        # always meant to flip once a real sync engine exists to populate
        # sync_devices.
        from src import data_health, db

        with db.connect(tmp_path / "cache.sqlite") as conn:
            backups_dir = tmp_path / "backups"
            summary = data_health.health_summary(conn, tmp_path / "cache.sqlite", backups_dir)
            assert summary["sync"]["configured"] is False
            assert summary["sync"]["device_count"] == 0

            db.touch_sync_device(conn, "device-a", last_pushed_hlc=(1000, 0, "device-a"))
            summary = data_health.health_summary(conn, tmp_path / "cache.sqlite", backups_dir)
            assert summary["sync"]["configured"] is True
            assert summary["sync"]["device_count"] == 1
            assert summary["sync"]["last_seen_at"] is not None


class TestTombstoneGc:
    """1.8 slice 7 -- "Tombstone GC" (open-priority.md §11 slice 7). Same
    structural-check level as every other class here; the real purge logic
    is covered server-side by test_offline_sync.py's TestPurgeExpired, and
    the client-side wipe-before-full-resync fix by a one-off Node +
    fake-indexeddb smoke script (this slice's own, not part of this
    suite, same pattern slices 4-6 already established)."""

    def test_offline_db_gained_clear_mirror(self):
        script = (_STATIC_DIR / "offline_db.js").read_text()
        assert "clearMirror" in script
        assert "window.CCOfflineDB" in script

    def test_full_resync_clears_the_mirror_before_re_pulling(self):
        script = (_STATIC_DIR / "offline_sync_client.js").read_text()
        assert "clearMirror()" in script
        # clearMirror() must run inside the `if (body.full_resync)` branch,
        # strictly before the pull's own applyChanges call that follows it
        # (whether or not that particular round hit the full_resync path).
        assert script.index("if (body.full_resync)") < script.index("clearMirror()") < script.index(
            "applyChanges(body.changes)"
        )

    def test_settings_data_maintenance_page_shows_sync_cleanup_controls(self):
        # 2026-08-17: Data health, Sync conflicts and Advanced merged into
        # the Data & Maintenance page (settings_data_maintenance.html); the
        # sync-retention / sync-gc controls live in its "Maintenance &
        # upkeep" section now.
        html = (Path(__file__).resolve().parent.parent / "src" / "templates" / "settings_data_maintenance.html").read_text()
        assert "sync-retention" in html
        assert "sync-gc" in html

    def test_scripts_data_health_cli_has_a_sync_gc_subcommand(self):
        script = (Path(__file__).resolve().parent.parent / "scripts" / "data_health.py").read_text()
        assert '"sync-gc"' in script
        assert "cmd_sync_gc" in script


# DISABLED - PWA shell is currently disabled
# class TestRouterWiring:
#     def test_pwa_router_is_registered_on_the_real_app(self):
#         def _all_paths(routes):
#             paths = set()
#             for route in routes:
#                 path = getattr(route, "path", None)
#                 if path is not None:
#                     paths.add(path)
#                 nested = getattr(route, "original_router", None)
#                 if nested is not None:
#                     paths |= _all_paths(nested.routes)
#             return paths
# 
#         paths = _all_paths(fastapi_app.routes)
#         assert "/sw.js" in paths
#         assert "/offline" in paths
