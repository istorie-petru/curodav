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
//   - "synced" is transient: the persistent toast goes away and, only
//     when this is a real non-synced -> synced transition (never on a
//     page load that was already synced), a brief confirmation toast
//     announces it -- §8's "successful background sync stays unobtrusive,
//     while errors are visible" line, unchanged.
//
// Loaded globally (base.html), not just on /offline -- sync can be
// actively retrying (or genuinely stuck offline) no matter which page is
// open, and the person should be able to tell that's happening without
// navigating anywhere.
(function () {
  let statusToast = null;
  let wasNonSynced = false;

  function countLabel(n) {
    return n + (n === 1 ? " change" : " changes") + " waiting to sync";
  }

  // The synchronizing state also carries the live outbox count; a round
  // flushing queued changes (pendingCount > 0) keeps showing the pending
  // message rather than flickering to "Syncing…" and back on every retry,
  // so "Syncing…" only ever means a pull-only round with nothing queued.
  function configFor(status, detail) {
    if (status === "offline") {
      return { title: "You're offline", message: "Changes will sync when you're back online.", variant: "warning" };
    }
    if (status === "pending" || (status === "synchronizing" && detail.pendingCount > 0)) {
      return { title: "Changes pending", message: countLabel(detail.pendingCount), variant: "warning" };
    }
    return { title: "Syncing…", message: "Pulling the latest changes.", variant: "default" };
  }

  function render(detail) {
    if (!detail || !window.ccToast || !("indexedDB" in window)) return;
    if (detail.status === "synced") {
      if (statusToast) {
        statusToast.dismiss();
        statusToast = null;
      }
      if (wasNonSynced) {
        window.ccToast({ title: "Synced", message: "All changes are up to date.", duration: 3000 });
      }
      wasNonSynced = false;
      return;
    }
    wasNonSynced = true;
    const cfg = configFor(detail.status, detail);
    if (statusToast && statusToast.isAlive()) {
      statusToast.set(cfg);
    } else {
      statusToast = window.ccToast(Object.assign({}, cfg, { persistent: true }));
    }
  }

  document.addEventListener("cc-offline-status-change", (event) => render(event.detail));

  document.addEventListener("DOMContentLoaded", async () => {
    if (!window.CCOfflineSync) return;
    render(await window.CCOfflineSync.getStatus());
  });
})();
