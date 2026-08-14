// 1.8 slices 4-6 -- §8's sync protocol, run client-side. Loaded globally
// (base.html) so the local IndexedDB mirror (offline_db.js) stays warm
// from every ordinary online page visit, not just when the offline shell
// is open -- the whole point of a local read path is that the data is
// already there *before* the network drops.
//
// Slice 4 built pull only. Slice 5 added a local outbox with nothing yet
// to flush it. Slice 6 -- this revision -- is the sync *engine* itself:
// the push half of §8 (flush offline_write.js's queued ops), §5's retry/
// backoff with jitter, and the status indicator
// (ofline-first-pwa.md's offline/synchronizing/pending/synchronized
// states, rendered by static/offline_status.js off the
// `cc-offline-status-change` event this file dispatches). This is what
// finally wires slices 1-5 together end to end -- before this, an
// offline write was durable locally but never left the device.
(function () {
  const BASE_RETRY_MS = 2000;
  const MAX_RETRY_MS = 30000;

  let inFlight = false;
  let retryDelay = BASE_RETRY_MS;
  let retryTimer = null;

  async function postJson(url, body) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      return null; // offline or unreachable -- expected, not an error to surface
    }
    return response.ok ? await response.json() : null;
  }

  // §8's push phase: send every op still in the outbox, per-entity
  // chronological (own-HLC) order (offline_db.js's `getOutboxOps` already
  // sorts that way). A duplicate resend after a dropped connection is
  // safe -- the server's own `op_id` idempotency ledger (§5) replays the
  // cached result instead of re-applying. Every op the server responds
  // for is acknowledged (removed from the outbox) regardless of its own
  // result status ("applied"/"stale"/"conflict"/"rejected_invariant" all
  // mean the server successfully *processed* it -- a surfaced conflict is
  // recorded server-side in `sync_conflicts`, not something the client
  // needs to keep retrying).
  async function pushOnce() {
    if (!("indexedDB" in window) || !navigator.onLine) return false;
    const ops = await window.CCOfflineDB.getOutboxOps();
    if (ops.length === 0) return true;

    const deviceId = await window.CCOfflineDB.getDeviceId();
    const body = await postJson("/api/sync/push", { device_id: deviceId, ops });
    if (!body) return false;

    const ackedIds = (body.results || []).map((r) => r.op_id);
    await window.CCOfflineDB.removeOutboxOps(ackedIds);
    return ackedIds.length === ops.length;
  }

  // §8's pull phase -- unchanged in shape from slice 4/5, just now
  // returning a boolean so `syncNow` below can decide whether to retry.
  async function pullOnce() {
    if (!("indexedDB" in window) || !navigator.onLine) return false;

    let cursor = await window.CCOfflineDB.getCursor();
    let body = await postJson("/api/sync/pull", { device_id: await window.CCOfflineDB.getDeviceId(), cursor: cursor });
    if (!body) return false;

    if (body.full_resync) {
      // §8: nothing has ever been physically purged yet in this app (§4's
      // GC is slice 7), so "full resync" today is simply "re-pull from
      // the very start" -- a cursor of null already returns everything
      // (offline_sync.pull's own docstring), so one retry with a cleared
      // cursor is enough; a server that somehow answers full_resync again
      // for cursor=null is a bug on the server side, not something to
      // retry forever for.
      await window.CCOfflineDB.setCursor(null);
      body = await postJson("/api/sync/pull", { device_id: await window.CCOfflineDB.getDeviceId(), cursor: null });
      if (!body || body.full_resync) return false;
    }

    await window.CCOfflineDB.applyChanges(body.changes);
    // §3's receive-side merge rule: advance this device's own HLC clock
    // past the newest thing it just observed from the server, so any
    // local write minted after this pull (offline_write.js's `nextHlc()`)
    // is guaranteed to sort strictly after everything just pulled in.
    if (body.cursor) await window.CCOfflineDB.mergeHlc(body.cursor);
    if (body.cursor) await window.CCOfflineDB.setCursor(body.cursor);
    await window.CCOfflineDB.setLastSyncedAt(new Date().toISOString());
    document.dispatchEvent(new CustomEvent("cc-offline-sync-complete"));
    return true;
  }

  // Live-computed, not a stored state machine -- status is a pure
  // function of {online, in-flight, outbox size}, so it can never drift
  // from what's actually true. ofline-first-pwa.md's four states:
  //   offline        -- navigator.onLine is false
  //   synchronizing  -- a push/pull round is in progress right now
  //   pending        -- online, idle, but the outbox isn't empty yet
  //   synced         -- online, idle, outbox empty (the unobtrusive
  //                      common case -- offline_status.js hides the
  //                      indicator entirely in this state, per §8's own
  //                      "successful background sync stays unobtrusive"
  //                      line)
  async function getStatus() {
    const pendingCount = "indexedDB" in window ? await window.CCOfflineDB.getOutboxCount() : 0;
    let status;
    if (!navigator.onLine) status = "offline";
    else if (inFlight) status = "synchronizing";
    else if (pendingCount > 0) status = "pending";
    else status = "synced";
    return { status, pendingCount };
  }

  async function emitStatus() {
    const detail = await getStatus();
    document.dispatchEvent(new CustomEvent("cc-offline-status-change", { detail }));
  }

  // §8: push before pull, always in that order, "so a device's own
  // changes are already applied server-side and can't be immediately
  // re-conflicted against by its own pull."
  async function syncNow() {
    if (!("indexedDB" in window) || !navigator.onLine) {
      await emitStatus();
      return false;
    }
    inFlight = true;
    await emitStatus();
    const pushOk = await pushOnce();
    const pullOk = await pullOnce();
    inFlight = false;
    await emitStatus();
    return pushOk && pullOk;
  }

  function jitter(ms) {
    return Math.round(ms / 2 + Math.random() * (ms / 2));
  }

  // §5's retry policy: exponential backoff with jitter, capped at 30s,
  // while a push/pull attempt is failing; reset back to the base delay
  // the moment a round succeeds. `requestSync` (below) is what triggers
  // the *first* attempt of a round (page load, the browser's `online`
  // event, or a fresh local write) -- this function is only ever
  // responsible for what happens *after* that first attempt, i.e.
  // whether and when to try again.
  function scheduleRetry(delay) {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(attempt, delay);
  }

  async function attempt() {
    if (!navigator.onLine) return; // resumes via the 'online' listener below
    const ok = await syncNow();
    const pendingCount = (await getStatus()).pendingCount;
    if (!ok) {
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS);
      scheduleRetry(jitter(retryDelay));
    } else if (pendingCount > 0) {
      // A successful round can still leave the outbox non-empty (a new
      // write queued mid-attempt, or a batch invariant rejected one op
      // but acknowledged the rest) -- a quick follow-up at the base
      // delay, not a backed-off one, since this isn't a failure.
      retryDelay = BASE_RETRY_MS;
      scheduleRetry(jitter(retryDelay));
    } else {
      // Idle: nothing pending, no timer running, until the next trigger
      // (a write or the 'online' event) calls requestSync() again --
      // avoids polling the server forever once there's truly nothing to
      // do, per §5's "periodic background retry *while a sync attempt is
      // failing*," not unconditionally.
      retryDelay = BASE_RETRY_MS;
    }
  }

  // The one external trigger every caller (page load, the 'online' event,
  // offline_write.js's own submitOp) goes through. Cancels any pending
  // backoff timer and attempts immediately -- an explicit trigger should
  // never wait out a stale backoff from an earlier, unrelated failure.
  function requestSync() {
    if (!("indexedDB" in window)) return;
    clearTimeout(retryTimer);
    attempt();
  }

  if ("indexedDB" in window) {
    window.addEventListener("load", requestSync);
    window.addEventListener("online", () => {
      retryDelay = BASE_RETRY_MS; // a fresh connection deserves a fresh attempt, not a backed-off one
      requestSync();
    });
    window.addEventListener("offline", () => {
      clearTimeout(retryTimer);
      emitStatus(); // no network attempt while offline -- just reflect the state change
    });
  }

  // Exposed for offline_write.js (a local write should try to flush right
  // away when online) and offline_status.js (the indicator's own initial
  // render); `pullOnce`/`pushOnce` stay exposed individually too, same as
  // slice 4 already did for `pullOnce`, in case a future page wants an
  // explicit one-shot rather than the full retry-driving `requestSync`.
  window.CCOfflineSync = { pullOnce, pushOnce, syncNow, getStatus, requestSync };
})();
