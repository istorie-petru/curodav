// 1.8 slice 3 -- PWA shell service worker (plans/open-priority.md §
// Offline-first editing & synchronization §11 slice 3). Served at the
// root path via routers/pwa.py::service_worker (not directly off
// /static/sw.js) so its default scope is the whole app, not just /static/.
//
// Scope of this slice, deliberately: precache the app shell (the CSS/JS/
// icons every page loads, per base.html, plus the /offline fallback page)
// and serve /offline for a navigation request that fails offline with
// nothing better cached. No sync, no IndexedDB, no runtime caching of
// dynamic server-rendered pages (Tasks/Calendar/etc. still require a live
// request -- caching their HTML here would go stale the moment the
// underlying data changes, and there is no local data layer yet to keep
// it honest; that's slices 4-5).
//
// CACHE_NAME is bumped whenever this file's own precache list changes --
// activate's cleanup below deletes any previous cc-shell-* cache, so an
// old shell version never lingers once a new one has installed. v9
// (2026-08-17): reworked offline_sync_client.js / offline_status.js
// (sync-status toasts now fire only on real sync work), so bumping forces
// an installed PWA to re-precache the fresh scripts instead of serving a
// cached copy that still announces "Syncing…"/"Synced" on dead-server
// page loads. v10 (2026-08-18): reworked offline_status.js again (the
// in-progress "Syncing…" toast is deferred by a grace period so a fast
// small sync never flashes it). v11 (2026-08-18): the static handler now
// falls back to caches.match(request, { ignoreSearch: true }) so the
// versioned ?v= URLs every page requests can be served from the precache's
// un-versioned entries (before that, /offline-only scripts failed to load
// on a device's first offline visit). v12 (2026-08-18): added
// /static/offline_quick_capture.js to the precache list (the offline
// "Quick add" toolbar's client-side capture parser), forcing a fresh shell
// install so /offline loads it. v15 (2026-08-29): root-cause fix for a
// whole session's worth of "I edited style.css but the browser still
// shows the old look" reports (habit check-in cell CSS, several rounds).
// This wasn't a CSS bug at all -- v14's precached `/static/style.css` had
// gone stale across every one of those edits, because NOTHING bumps
// CACHE_NAME when only static/style.css itself changes (every prior bump
// here was for a *script* rewrite). The fetch handler below tries an
// exact versioned-URL match first, but falls back to `caches.match(
// request, {ignoreSearch:true})` against the precache's un-versioned
// entry the moment that exact match misses -- which, for a file that's
// never been re-fetched under a brand new `?v=` in a runtime-cached
// visit, is every single request. So every reload kept serving the
// install-time (long before today) style.css regardless of what the
// server actually returned, confirmed by curling the live server
// directly (bypasses the SW) and seeing the fix already correct there.
// Bumping CACHE_NAME is the only thing that forces a fresh precache;
// going forward, treat static/style.css changes the same as a script
// rewrite for this purpose -- bump on every edit expected to be visible
// immediately, not just JS. v16 (2026-08-29): proof the v15 lesson was
// real, not theoretical -- the very next style.css edit (suppressing
// .inline-edit-cell's text-decoration while `[data-editing]`, see that
// rule's own comment) needed this same bump to actually reach a browser.
// v17 (2026-08-29): the habit heatmap's DETAIL_WEEKS widening fix left it
// scrollable with no visible scrollbar on several platforms -- added
// `.heatmap`'s scrollbar-width/::-webkit-scrollbar rules (style.css) plus a
// new static/heatmap_scroll.js (not shell-critical -- same category as
// inline_edit.js/async_crud.js above, so not added to SHELL_ASSETS) that
// defaults the scroll position to today's end. Bumped per the v15/v16
// lesson: any style.css change needs this regardless of whether a script
// also changed. v18 (2026-08-29): superseded v17's approach per direct
// feedback ("I just never want for a scrollbar to ever be needed there") --
// both detail heatmaps now use the existing `heatmap-wide` cell-stretching
// variant instead, so there's structurally nothing to scroll; reverted
// style.css's scrollbar-visibility rules and deleted static/
// heatmap_scroll.js entirely (it's gone from disk, was never in
// SHELL_ASSETS to begin with, so nothing to remove from this list). Bumped
// because style.css changed again.
// v19 (2026-08-29): direct report ("the resize event doesn't always
// trigger, even though it should") after that same day's static/
// sidebar_tree.js fix (dispatching a synthetic `resize` on sidebar
// toggle so the dashboard masonry re-layouts). The fix itself was correct
// -- this was the v15/v16 lesson again, just for a *script* this time
// instead of style.css: the fetch handler below tries an exact
// versioned-URL match first, but for any static asset that had ALREADY
// been runtime-cached under an OLDER `?v=` (deps.py's static_url() bumps
// the query string by mtime, but the SW never revisits an entry once
// cached), the ignoreSearch fallback matches that stale cached entry
// before ever reaching the network -- so a browser with an
// already-installed PWA kept serving the pre-fix sidebar_tree.js
// regardless of the new mtime, which is exactly "doesn't always trigger"
// (only devices with no prior SW-cached copy, or a fresh install, saw the
// fix immediately). Bumping CACHE_NAME deletes the entire previous
// cc-shell-* cache on activate (both its precached AND runtime-cached
// entries), so every static asset -- precached or not -- is forced back
// through a real network fetch at least once. Also added static/
// sidebar_tree.js to SHELL_ASSETS below: it's a base.html script loaded
// on every single page (same category as app.js/modal.js, already
// precached), not a page-specific one, so it belongs in the shell rather
// than relying solely on runtime caching to ever pick it up.
// v20 (2026-08-29): style.css changed again (sidebar-header/app-name rules
// for the expanded-sidebar wordmark) -- bumped per the standing v15 lesson
// (any style.css edit needs a bump to actually reach an already-installed
// PWA), independent of this being CSS rather than a script.
// v21 (2026-08-29): style.css changed again (unified collapsed/expanded
// .tabbar/.tab-btn/.sidebar-header padding so rail icons land at the same
// inset in both states) -- bumped per the same v15 lesson.
// v22 (2026-08-29): style.css changed again (new .page-header-narrow rules,
// sidebar redesign item 13e) -- bumped per the same v15 lesson.
// v23 (2026-08-29): style.css changed again (narrow-header banner/actions-
// slot rules, folding Tasks/Contacts/Calendar's old toolbar-2row into the
// header) -- bumped per the same v15 lesson.
// v24 (2026-08-29): style.css changed again (Dashboard Header (Expanded)
// avatar overlap -- .page-banner-avatar-wrap/.avatar-hero) -- bumped per
// the same v15 lesson.
// v25 (2026-08-29): static/avatar_cropper.js generalized to also handle
// banner uploads (crop/move/aspect-ratio for all image uploads, direct
// request) and static/app.js's now-dead CCBannerUpload removed -- both are
// SHELL_ASSETS scripts, bumped per the v19 lesson (script changes need
// this too, not just style.css).
// v26 (2026-08-29): static/avatar_cropper.js changed again (smaller avatar
// output cap, WebP-with-JPEG-fallback output for every upload kind, direct
// request "convert for smaller sizes... or compress them a bit") -- bumped
// per the same v19 lesson.
// v27 (2026-08-30): static/style.css-only change (collapsed rail's
// per-item height shrunk to match the expanded rail's, and collapsed rail
// items go icon-only, no text label) -- bumped per the same v19 lesson.
// v28 (2026-08-30): static/style.css-only change, same session (collapsed
// rail's icon left-aligned to match expanded's inset instead of centered,
// active-pill switched to a full-box highlight to match) -- bumped per
// the same v19 lesson.
// v29 (2026-08-30): static/style.css-only change, same session (collapsed
// rail narrowed 80px -> 64px, its icon nudged further from the left edge
// to cut the dead space to its right) -- bumped per the same v19 lesson.
// v30 (2026-08-30): static/style.css-only change, same session (collapsed
// rail narrowed again, 64px -> 56px, trimming more of the remaining
// right-side dead space) -- bumped per the same v19 lesson.
// v31 (2026-08-30): static/style.css-only change, same session (collapsed
// rail narrowed once more, 56px -> 52px, so the active-highlight box
// reads closer to 1:1 against its 36px min-height) -- bumped per the
// same v19 lesson.
// v32 (2026-08-30): static/style.css-only change, same session (expanded
// mode's own left/right padding mismatch: sidebar-section-label's 12px
// padding stacked on top of .tabbar's own, and .tab-separator's fixed
// 40px width fell back to flush-left instead of a matching inset under
// expanded's align-items:stretch) -- bumped per the same v19 lesson.
// v33 (2026-08-30): static/style.css-only change, same session (icons
// visibly jumped left/up when toggling collapsed<->expanded, and the
// active-highlight corners had different radii between the two -- .tab-
// btn's left padding and the header/toggle's sizing are unconditional
// now, and both states' highlight uses the same --radius-sm) -- bumped
// per the same v19 lesson.
// v43 (2026-08-30): style.css changed again (new `.kanban-status-select`
// rule + dropped `.kanban-card`'s `cursor:grab`, for the rebuilt Projects
// page's click-based Kanban board, plans/STATE.md backlog item 9) --
// bumped per the same v15 lesson. static/tasks_kanban.js itself is new
// but page-specific (project_detail.html only), not added to
// SHELL_ASSETS -- same "not shell-critical" category as tasks_table.js/
// tasks_board.js above.
// v44 (2026-08-30, immediate follow-up): live bug report -- the Projects
// page's upcoming-events card overlapped the Kanban board below it. Root
// cause: it was built with `.widget-card`, which is `position:absolute`
// (the Dashboard's own JS-positioned masonry grid sets its geometry) --
// with no such JS on this plain page it had no top/left/width at all.
// New `.widget-card-static` repeats only the flattened visual treatment,
// not the positioning; style.css changed, bumped per the same v15 lesson.
// v45 (2026-09-02): direct-feedback design pass -- labels now render as
// colored/iconed pills everywhere (new `.cell-tag.cal-*` usage via
// _label_pill.html, no new classes of their own) instead of the old flat
// `tag-blue`; Unscheduled-work pills (style.css's `.unscheduled-task-*`)
// shrunk and now wrap instead of scrolling; the Kanban board's per-card
// `.kanban-status-select` is gone along with static/tasks_kanban.js
// (removed from the page entirely, was never in SHELL_ASSETS). style.css
// changed, bumped per the same v15 lesson.
// v49 (2026-09-03): the shared date+time range picker's hour selection was
// reworked after a round of mockups (direct feedback: the old scrolling/
// click-drag 24-row hour grid was "too bulky," a follow-up grid/slider/
// preset/typed-field pass was all rejected too) -- static/
// datetime_picker.js (page-specific, not itself a SHELL_ASSETS entry, but
// runtime-cached like any other static file) and style.css both changed;
// bumped per the same v15/v19 lesson so an already-installed PWA doesn't
// keep serving the old click-drag grid from its runtime cache.
// v50 (2026-09-03, same day, two direct follow-ups on the cover-banner
// baseline from v48): (1) bug fix -- the cover's floating icon badge was
// getting clipped by .detail-cover's own overflow:hidden (needed to clip
// the image/gradient fill to the rounded top corners), so the badge's
// bottom overhang -- its whole point -- was invisible; fixed by moving it
// out to a sibling .detail-cover-wrap that isn't itself clipped. (2) Work
// sessions section (task_detail.html/habit_task_detail.html) dropped its
// elevated .detail-card background in favor of .detail-plain-section (a
// hairline, same treatment the meta grid already got), plus a small
// per-row polish pass (.work-session-row). style.css + three templates
// changed, bumped per the same v15 lesson.
// v51 (2026-09-03, same day, immediate follow-up): (1) real bug fix, not
// just polish -- v48's .modal-header rewrite (padding:0, for the cover to
// bleed) had stripped the *only* margin every plain *_form.html edit
// modal's bare <h1> relied on (event_form.html "Edit event" reported
// clipped flush against the dialog's edge) -- .modal-header's original
// padding/row layout is restored, and the cover-bleed behavior moved to a
// new .detail-header-inner wrapper (negative margins matching that
// padding) used only by the 4 detail-view templates, so the other 20+
// plain-title modals go back to their original, correct layout untouched.
// (2) Work sessions' separate "Scheduled work X.Xh / Y.Yh" sub-heading
// merged into the "Work sessions" heading itself (direct feedback:
// redundant, and it was rendering a second, unwanted divider on top of
// .detail-plain-section's own -- see _task_work_allocations.html's own
// comment). style.css + all 4 detail templates + _task_work_allocations.
// html changed, bumped per the same v15 lesson.
// v52 (2026-09-03, same day, immediate follow-up: "the two lines in the
// middle of this modal") -- .detail-plain-section's own border-top is
// gone. It was always redundant: in both real call sites, whatever comes
// right before it already draws that line itself (.detail-meta-panel's
// border-bottom when it isn't :last-child, or the habit heatmap's real
// .detail-card box edge) -- so Work sessions was showing two parallel
// hairlines a margin-top gap apart instead of one. style.css changed,
// bumped per the same v15 lesson.
// v53 (2026-09-04, mobile-nav redesign, plans/STATE.md) -- the old mobile
// bottom bar (all ~8 tabbar destinations crushed into one row, direct
// report against a real install screenshot) is replaced by a 3-button
// `.mobile-tabbar` (Sidebar/Home/Search) plus a bottom-sheet drawer that
// reuses `.tabbar` itself. style.css + templates/base.html changed, plus a
// new static/mobile_nav_drawer.js (added to SHELL_ASSETS below, same
// v19 reasoning as sidebar_tree.js -- a base.html script needed on every
// page for core navigation, not a page-specific one, so it belongs in the
// shell rather than relying solely on runtime caching). Bumped per the
// v15/v16/v19 lesson: any style.css or SHELL_ASSETS-script change needs
// this regardless of how small.
// v54 (2026-09-04, same day, direct follow-up -- "implement and fix the
// other problems described in this conversation," the two gaps flagged
// but not fixed by the earlier mobile touch-equivalents audit): 1)
// `.task-row-delete` gets an `@media (hover:none)` fallback (dimmed but
// visible) since it was hover-only-reveal with no way to discover it on a
// touch device; 2) `.icon-btn` grows to 40px under `@media
// (pointer:coarse)` (was 28px, under the ~44px touch-target guideline).
// style.css changed, bumped per the same v15 lesson.
const CACHE_NAME = "cc-shell-v54";

const SHELL_ASSETS = [
  "/offline",
  "/static/manifest.webmanifest",
  "/static/style.css",
  "/static/toast.js",
  "/static/app.js",
  "/static/sidebar_tree.js",
  "/static/mobile_nav_drawer.js",
  "/static/modal.js",
  "/static/tag_input.js",
  "/static/recurrence_picker.js",
  "/static/reminders_picker.js",
  "/static/stepper.js",
  "/static/dashboard_widget_preview.js",
  "/static/avatar_cropper.js",
  "/static/task_habit_field_toggle.js",
  "/static/event_format_toggle.js",
  "/static/command_palette.js",
  "/static/quick_add.js",
  "/static/pwa.js",
  // 1.8 slice 4 -- the local read path's own scripts must be in the
  // shell precache too: a device that opens /offline fully offline still
  // needs offline_db.js/offline_shell.js to read the mirror it already
  // built while online (offline_sync_client.js is included for
  // completeness/consistency, even though its own pull attempts are
  // harmless no-ops with no network).
  "/static/offline_db.js",
  "/static/offline_sync_client.js",
  "/static/offline_status.js",
  "/static/offline_write.js",
  "/static/offline_quick_capture.js",
  "/static/offline_shell.js",
  "/static/favicon-16.png",
  "/static/favicon-32.png",
  "/static/apple-touch-icon.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      // Take over immediately on first install instead of waiting for
      // every open tab to close -- this app has no in-page "update
      // available, reload?" prompt (out of scope for this slice), so the
      // alternative is a stale worker sitting idle until the user
      // happens to close and reopen the tab themselves.
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("cc-shell-") && key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Only ever intervene for this app's own GETs -- cross-origin requests
  // (none today, but future-proofing) and non-GET writes (every task/
  // event/contact mutation in this app is a plain form POST, per
  // features/architecture.md) always go straight to the network
  // untouched.
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    // Network-first for real page loads: this app's pages are server-
    // rendered from live SQLite state (main.py's own comment on why
    // full-page HTTP caching is deliberately avoided), so a page that
    // *can* reach the network must never be served a stale cached copy.
    // Only a genuine network failure (offline, DNS, timeout) falls
    // through to the offline shell.
    event.respondWith(
      fetch(request).catch(() =>
        caches.match("/offline").then((cached) => cached || caches.match(request))
      )
    );
    return;
  }

  if (new URL(request.url).pathname.startsWith("/static/")) {
    // Cache-first for static assets: every static URL this app renders
    // is already cache-busted with a `?v=<mtime>` query string
    // (deps.py's static_url()) whenever the underlying file changes, so
    // the plain un-versioned path cached here can never silently serve
    // stale content under a *new* version's URL -- a changed file simply
    // gets requested under a different URL than the one already cached.
    // Falls back to the network (and refreshes the cache entry) for
    // anything not in the precache list above.
    //
    // 2026-08-18 -- `ignoreSearch` fallback: pages request these assets
    // with the `?v=` suffix, and `caches.match` never matches that against
    // the precached un-versioned entry, so the precache only actually
    // served anything for assets the runtime path had ALSO cached under
    // their versioned URL during a controlled online visit. Scripts that
    // only /offline loads (offline_shell.js/offline_write.js/
    // offline_status.js) are never requested by a normal page visit, so
    // they were never runtime-cached -- and a device's first offline visit
    // then failed to load them, leaving /offline's static empty state
    // visible no matter how well-populated the local mirror was. The
    // versioned-exact match is tried first (a runtime-cached copy is the
    // freshest thing the SW knows); the ignoreSearch match against the
    // un-versioned precache entry is the fallback.
    //
    // v41 (2026-08-30): root-cause fix for the actual bug behind every one
    // of the v15-v33 "I edited a file, the browser still shows the old
    // version" reports -- this wasn't just a "forgot to bump CACHE_NAME"
    // problem, the fallback ORDER was wrong. The old code tried the exact
    // versioned match, and on a miss went straight to the ignoreSearch
    // precache/runtime-cache match -- BEFORE ever trying the network. Once
    // any old version of a file had been cached (either precached
    // unversioned at install, or runtime-cached under a previous `?v=`),
    // ignoreSearch always matched it by path, so a new `?v=` request was
    // served that stale entry directly and NEVER reached the network --
    // even while fully online. That's exactly the reported symptom: a hard
    // refresh works (it bypasses the SW entirely), but a normal navigation
    // to another page re-requests the asset through the SW and gets the
    // stale ignoreSearch hit again. Fixed by trying the network *before*
    // the ignoreSearch fallback: an exact cache hit is still served
    // instantly (fast path for a version already fetched), but any miss
    // now goes to the network first and only falls back to the stale
    // ignoreSearch precache entry if that fetch itself fails (genuinely
    // offline) -- which is what the ignoreSearch fallback was actually
    // meant for (see the offline_shell.js/offline_write.js note below).
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request)
            .then((response) => {
              const copy = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
              return response;
            })
            .catch(() => caches.match(request, { ignoreSearch: true }))
      )
    );
  }
  // Everything else (JSON APIs, non-precached GETs) is left alone --
  // default browser network handling, no caching.
});
