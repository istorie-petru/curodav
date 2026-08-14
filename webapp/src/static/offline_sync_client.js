// 1.8 slice 4 -- the pull half of §8's sync protocol, run client-side.
// Loaded globally (base.html) so the local IndexedDB mirror (offline_db.js)
// stays warm from every ordinary online page visit, not just when the
// offline shell is open -- the whole point of a local read path is that
// the data is already there *before* the network drops.
//
// Deliberately push-free and retry-free: slice 5 adds the local write
// path/outbox (so there's nothing of this device's own to push yet), and
// slice 6 adds real retry/backoff plus the status indicator (ofline-first-
// pwa.md's offline/synchronizing/pending/synchronized states). This is a
// single best-effort pull per trigger -- silent no-op on failure, since
// "the network is down" is an entirely expected reason for it to fail and
// there is nothing here yet for a failure to jeopardize (no pending writes
// to lose).
(function () {
  async function fetchPull(cursor) {
    let response;
    try {
      const deviceId = await window.CCOfflineDB.getDeviceId();
      response = await fetch("/api/sync/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: deviceId, cursor: cursor }),
      });
    } catch (err) {
      return null; // offline or unreachable -- expected, not an error to surface
    }
    return response.ok ? await response.json() : null;
  }

  async function pullOnce() {
    if (!("indexedDB" in window) || !navigator.onLine) return;

    let cursor = await window.CCOfflineDB.getCursor();
    let body = await fetchPull(cursor);
    if (!body) return;

    if (body.full_resync) {
      // §8: nothing has ever been physically purged yet in this app (§4's
      // GC is slice 7), so "full resync" today is simply "re-pull from
      // the very start" -- a cursor of null already returns everything
      // (offline_sync.pull's own docstring), so one retry with a cleared
      // cursor is enough; a server that somehow answers full_resync again
      // for cursor=null is a bug on the server side, not something to
      // retry forever for.
      await window.CCOfflineDB.setCursor(null);
      body = await fetchPull(null);
      if (!body || body.full_resync) return;
    }

    await window.CCOfflineDB.applyChanges(body.changes);
    if (body.cursor) await window.CCOfflineDB.setCursor(body.cursor);
    await window.CCOfflineDB.setLastSyncedAt(new Date().toISOString());
    document.dispatchEvent(new CustomEvent("cc-offline-sync-complete"));
  }

  if ("indexedDB" in window) {
    window.addEventListener("load", pullOnce);
    window.addEventListener("online", pullOnce);
  }

  // Exposed for offline_shell.js (or a future page) to trigger an
  // explicit re-pull, e.g. a manual "Sync now" affordance -- not used by
  // this slice's own UI yet, but no reason to make it load-event-only.
  window.CCOfflineSync = { pullOnce };
})();
