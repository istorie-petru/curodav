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
// immediately, not just JS.
const CACHE_NAME = "cc-shell-v15";

const SHELL_ASSETS = [
  "/offline",
  "/static/manifest.webmanifest",
  "/static/style.css",
  "/static/toast.js",
  "/static/app.js",
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
    // un-versioned precache entry is the fallback. The one accepted
    // staleness: between a file changing and the SW itself updating, an
    // offline device may get the old precached copy -- the cache-busting
    // query still governs the online path, where the fresh file loads and
    // is runtime-cached under its new versioned URL.
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          caches.match(request, { ignoreSearch: true }).then(
            (precached) =>
              precached ||
              fetch(request).then((response) => {
                const copy = response.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
                return response;
              })
          )
      )
    );
  }
  // Everything else (JSON APIs, non-precached GETs) is left alone --
  // default browser network handling, no caching.
});
