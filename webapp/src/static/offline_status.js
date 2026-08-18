// 1.8 slice 6 -- the small status indicator ofline-first-pwa.md calls for
// ("offline, synchronizing, pending changes, or synchronized"). Purely a
// renderer: all state lives in offline_sync_client.js, which computes it
// fresh from {navigator.onLine, in-flight, outbox size} and dispatches
// `cc-offline-status-change` whenever it might have changed. This file
// never touches IndexedDB or the network directly -- same read/render
// split as offline_db.js (data) vs. offline_shell.js (UI).
//
// Rendered as bottom-right toasts (2026-08-16 follow-up: "sync
// announcements and status should have the bottom right announcement
// style"): it used to be a small pill in the top-right corner; now it
// lives in the same ccToast stack as the app's warnings/errors/
// confirmations, so sync state reads as part of the normal notification
// language instead of a separate chrome widget.
//
//   - offline / pending / synchronizing are *persistent* states -- a
//     persistent toast (no auto-dismiss countdown) stays in the stack for
//     as long as the condition is true, updated in place as it changes,
//     dismissible via its ✕. A sync engine stuck in a failing retry loop
//     keeps "N changes waiting to sync" honestly visible the whole time.
//     A sync round's *start* is only announced when it has real push work
//     queued (a non-empty outbox, per offline_sync_client.js's gating) --
//     a routine pull-only round on an up-to-date machine never flashes a
//     "Syncing…" toast; only the round's outcome ("Synced", or silence)
//     is announced.
//   - The in-progress toast itself is *deferred* by SYNC_SHOW_DELAY_MS on
//     its first appearance (2026-08-18 follow-up): a small sync round -- a
//     handful of queued ops against a reachable server -- completes in a
//     few hundred ms and should never announce "Syncing…"/"Changes pending"
//     at all; only a state still current once the grace period has elapsed
//     is worth surfacing as "in progress" (this covers the round-start
//     emission *and* the initial page-load render of a non-empty outbox,
//     which can both be resolved by a quick round before the grace ends).
//     The deferral lives here in the renderer (the "frontend showing"),
//     not in the engine -- status events stay honest and immediate.
//   - "synced" is transient: the persistent toast goes away and, only
//     when the round that just completed actually moved data -- either
//     pushed local changes to the server or pulled new changes from it
//     (`detail.didWork`, computed by offline_sync_client.js) -- a brief
//     confirmation toast announces it. A routine page-load round on an
//     up-to-date, continuously-connected machine (empty outbox, nothing
//     new server-side) does neither and stays silent -- §8's "successful
//     background sync stays unobtrusive, while errors are visible" line,
//     unchanged.
//
// Loaded globally (base.html), not just on /offline -- sync can be
// actively retrying (or genuinely stuck offline) no matter which page is
// open, and the person should be able to tell that's happening without
// navigating anywhere.
(function () {
  let statusToast = null;
  // How long a synchronizing/pending status is allowed to sit unannounced
  // before its persistent toast is shown. Any round that resolves within
  // this window -- the small-sync case -- never flashes a toast at all;
  // only a state still current when the timer fires gets one.
  const SYNC_SHOW_DELAY_MS = 1500;
  let syncGraceTimer = null;

  function clearSyncGraceTimer() {
    if (syncGraceTimer !== null) {
      clearTimeout(syncGraceTimer);
      syncGraceTimer = null;
    }
  }

  function countLabel(n) {
    return n + (n === 1 ? " change" : " changes") + " waiting to sync";
  }

  // The synchronizing state also carries the live outbox count; a round
  // flushing queued changes (pendingCount > 0) keeps showing the pending
  // message rather than flickering to "Syncing…" and back on every retry.
  // The bare "Syncing…" default is effectively unreachable since
  // offline_sync_client.js only announces a round's start when the outbox
  // is non-empty (2026-08-17) -- kept as a defensive fallback.
  function configFor(status, detail) {
    if (status === "offline") {
      return { title: "You're offline", message: "Changes will sync when you're back online.", variant: "warning" };
    }
    if (status === "pending" || (status === "synchronizing" && detail.pendingCount > 0)) {
      return { title: "Changes pending", message: countLabel(detail.pendingCount), variant: "warning" };
    }
    return { title: "Syncing…", message: "Pulling the latest changes.", variant: "default" };
  }

  function showStatus(detail) {
    const cfg = configFor(detail.status, detail);
    if (statusToast && statusToast.isAlive()) {
      statusToast.set(cfg);
    } else {
      statusToast = window.ccToast(Object.assign({}, cfg, { persistent: true }));
    }
  }

  function render(detail) {
    if (!detail || !window.ccToast || !("indexedDB" in window)) return;
    // Any new status event cancels a pending deferred in-progress toast --
    // the round moved on (its outcome, or a state change), so the deferred
    // "Syncing…"/"Changes pending" must never surface after the fact.
    clearSyncGraceTimer();
    if (detail.status === "synced") {
      if (statusToast) {
        statusToast.dismiss();
        statusToast = null;
      }
      if (detail.didWork) {
        window.ccToast({ title: "Synced", message: "All changes are up to date.", duration: 3000 });
      }
      return;
    }
    if (detail.status === "offline") {
      // The network state is worth knowing right away -- never deferred.
      showStatus(detail);
      return;
    }
    if (statusToast && statusToast.isAlive()) {
      // An already-visible persistent state (a genuinely stuck/failing
      // round) keeps updating in place with no flash.
      showStatus(detail);
      return;
    }
    // First appearance of a synchronizing/pending state (a sync round just
    // started, or changes are queued): don't show it yet. This covers both
    // the round-start emission and the initial page-load render of a
    // non-empty outbox -- either way the round that's about to resolve it
    // may finish inside the grace period. If it does, the toast never
    // appears at all ("for bigger syncing it shows, for small ones it
    // doesn't", 2026-08-18); only a state still current when the timer
    // fires gets its persistent toast.
    syncGraceTimer = setTimeout(() => {
      syncGraceTimer = null;
      showStatus(detail);
    }, SYNC_SHOW_DELAY_MS);
  }

  document.addEventListener("cc-offline-status-change", (event) => render(event.detail));

  document.addEventListener("DOMContentLoaded", async () => {
    if (!window.CCOfflineSync) return;
    render(await window.CCOfflineSync.getStatus());
  });
})();
