// 1.8 slice 6 -- the small status indicator ofline-first-pwa.md calls for
// ("offline, synchronizing, pending changes, or synchronized"). Purely a
// renderer: all state lives in offline_sync_client.js, which computes it
// fresh from {navigator.onLine, in-flight, outbox size} and dispatches
// `cc-offline-status-change` whenever it might have changed. This file
// never touches IndexedDB or the network directly -- same read/render
// split as offline_db.js (data) vs. offline_shell.js (UI).
//
// Loaded globally (base.html), not just on /offline -- sync can be
// actively retrying (or genuinely stuck offline) no matter which page is
// open, and the person should be able to tell that's happening without
// navigating anywhere.
(function () {
  let pill = null;

  function ensurePill() {
    if (pill) return pill;
    pill = document.createElement("div");
    pill.className = "sync-status-pill";
    pill.setAttribute("aria-live", "polite");
    const dot = document.createElement("span");
    dot.className = "sync-status-dot";
    const text = document.createElement("span");
    text.className = "sync-status-text";
    pill.appendChild(dot);
    pill.appendChild(text);
    document.body.appendChild(pill);
    return pill;
  }

  function labelFor(detail) {
    if (detail.status === "offline") return "Offline";
    if (detail.status === "synchronizing") return "Syncing…";
    if (detail.status === "pending") {
      return detail.pendingCount + (detail.pendingCount === 1 ? " change pending" : " changes pending");
    }
    return "";
  }

  // §8's "successful background sync stays unobtrusive, while errors are
  // visible" -- the "synced" state (nothing pending, nothing in flight,
  // online) hides the pill entirely rather than showing a transient
  // checkmark; every other state stays visible for as long as it's true,
  // which is exactly how a stuck retry loop (still "pending" after
  // several failed attempts) stays honestly visible without this file
  // needing to know anything about retries itself.
  function render(detail) {
    if (!detail || !("indexedDB" in window)) return;
    const el = ensurePill();
    el.classList.remove("is-offline", "is-synchronizing", "is-pending");
    if (detail.status === "synced") {
      el.classList.remove("is-visible");
      return;
    }
    el.classList.add("is-visible", "is-" + detail.status);
    el.querySelector(".sync-status-text").textContent = labelFor(detail);
  }

  document.addEventListener("cc-offline-status-change", (event) => render(event.detail));

  document.addEventListener("DOMContentLoaded", async () => {
    if (!window.CCOfflineSync) return;
    render(await window.CCOfflineSync.getStatus());
  });
})();
