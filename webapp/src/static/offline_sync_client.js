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
// finally wires slices 1-5 together end to end -- before this, an offline
// write was durable locally but never left the device.
//
// Status is computed live, never stored, and the `cc-offline-status-change`
// detail now also carries a `didWork` boolean -- whether that round actually
// moved data (2026-08-17 follow-up: a routine page-load round on an
// up-to-date, continuously-connected machine does no push work and pulls
// nothing, and shouldn't announce "Synced" as if a real sync had happened).
// The same follow-up also gates the round-start "synchronizing" emission on
// a non-empty outbox, so even the "Syncing…" persistent toast never flashes
// on such a round -- only the round's outcome ("Synced", or silence) is
// announced. A second follow-up the same day (the user's "hash attached to
// the database" idea) makes a pull-only round with nothing to pull not even
// run: the server exposes a monotonic data version (GET /api/sync/state,
// bumped whenever a sync write actually applies) that the client compares
// against the version saved after its last successful pull -- on a match
// with an empty outbox the round is skipped outright (no pull request, no
// status event, no toast).
(function () {
  const BASE_RETRY_MS = 2000;
  const MAX_RETRY_MS = 30000;

  let inFlight = false;
  let retryDelay = BASE_RETRY_MS;
  let retryTimer = null;
  // Whether the current/last sync round actually moved data -- either
  // pushed local changes to the server (a non-empty outbox) or pulled new
  // changes from it (a non-empty `changes` list). A routine round on an
  // up-to-date, continuously-connected machine (a page-load health check
  // with an empty outbox and nothing new server-side) does neither; that
  // distinction is what offline_status.js uses to decide whether a
  // non-synced -> synced return is a real, announce-worthy sync or just
  // a silent no-op round.
  let didWork = false;

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

  // 2026-08-17 -- the server-side data-version pre-flight ("a hash attached
  // to the database": the server bumps a monotonic version whenever a sync
  // write actually applies, and a device compares it against the version it
  // saved after its last successful pull to decide whether a sync round is
  // needed at all). A pull-only round with a matching version would return
  // an empty changes list -- this check skips it entirely (no pull, no
  // status churn, no toast) rather than running a network round just to
  // learn "nothing changed". A failed check (server unreachable) falls
  // through to the normal round, whose own failure then drives the usual
  // retry/backoff -- never skipped on a fetch error.
  async function getServerState() {
    let response;
    try {
      response = await fetch("/api/sync/state", {
        method: "GET",
        headers: { Accept: "application/json" },
      });
    } catch (err) {
      return { ok: false, version: null };
    }
    if (!response.ok) return { ok: false, version: null };
    try {
      const body = await response.json();
      return { ok: true, version: typeof body.version === "number" ? body.version : null };
    } catch (err) {
      return { ok: false, version: null };
    }
  }

  async function nothingToDo() {
    const saved = await window.CCOfflineDB.getServerVersion();
    if (saved === null) return false; // never synced -- run a real round
    const state = await getServerState();
    if (!state.ok || state.version === null) return false; // let the round fail/retry normally
    return state.version === saved;
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
    didWork = true; // real work -- this device's own local changes are being sent

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
      // 1.8 slice 7 -- now that the server actually purges old tombstones
      // (offline_sync.purge_expired), a full resync can no longer be
      // treated as "just re-pull, applyChanges will sort it out": a
      // purged entity's field_versions rows are gone server-side, so the
      // resync payload can never carry a "this is deleted" signal for it.
      // The only honest way to guarantee this device can't resurrect a
      // stale local copy of something that's since been purged is to
      // actually start over -- wipe the local mirror first, then rebuild
      // purely from what the resync returns (see offline_db.js's
      // `clearMirror` for the full reasoning). One retry with a cleared
      // cursor is enough (a cursor of null already returns everything,
      // per offline_sync.pull's own docstring); a server that somehow
      // answers full_resync again for cursor=null is a bug on the server
      // side, not something to retry forever for.
      await window.CCOfflineDB.clearMirror();
      await window.CCOfflineDB.setCursor(null);
      body = await postJson("/api/sync/pull", { device_id: await window.CCOfflineDB.getDeviceId(), cursor: null });
      if (!body || body.full_resync) return false;
    }

    if (body.changes && body.changes.length > 0) didWork = true; // real work -- the server had something new for this device
    await window.CCOfflineDB.applyChanges(body.changes);
    // §3's receive-side merge rule: advance this device's own HLC clock
    // past the newest thing it just observed from the server, so any
    // local write minted after this pull (offline_write.js's `nextHlc()`)
    // is guaranteed to sort strictly after everything just pulled in.
    if (body.cursor) await window.CCOfflineDB.mergeHlc(body.cursor);
    if (body.cursor) await window.CCOfflineDB.setCursor(body.cursor);
    await window.CCOfflineDB.setLastSyncedAt(new Date().toISOString());
    // Save the server's data version now that this device is fully caught
    // up, so the next round's `nothingToDo()` pre-check compares against
    // a current value. Only saved after a *successful pull* -- never after
    // a push alone (a successful push with a failed pull leaves changes
    // unpulled, and recording the post-push version would wrongly let the
    // next round skip the pull this device still needs).
    if (body.version != null) await window.CCOfflineDB.setServerVersion(body.version);
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
    return { status, pendingCount, didWork };
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
    didWork = false; // per-round -- the announcement decision reflects only this round
    let ok;
    try {
      const outboxCount = await window.CCOfflineDB.getOutboxCount();
      if (outboxCount > 0) {
        // Announce the round's start only when it has real push work queued
        // (a non-empty outbox). A pull-only/no-op round -- the routine page-
        // load health check of an up-to-date machine -- must stay silent until
        // its outcome is known; emitting "synchronizing" here would flash a
        // "Syncing…" toast on every page visit (2026-08-17 follow-up).
        await emitStatus();
      } else if (await nothingToDo()) {
        // Nothing local to push and the server's data version matches this
        // device's last-synced one -- no sync needed at all, so don't even
        // run a pull-only round. Silent, no status churn, no toast, no
        // pull request (2026-08-17: the user's "hash attached to the
        // database" idea -- skip the round entirely when nothing changed).
        ok = true;
      }
      // A round with real push work queued (first branch) or an out-of-date
      // server (second branch) still runs the push-then-pull exchange --
      // this is deliberately NOT an `else` of the round-start branch above,
      // so an announce-worthy round also actually syncs its data
      // (2026-08-18: caught while smoke-testing -- the earlier restructure
      // parked push/pull in an `else` and rounds with a non-empty outbox
      // never pushed, retrying forever).
      if (ok === undefined) {
        const pushOk = await pushOnce();
        const pullOk = await pullOnce();
        ok = pushOk && pullOk;
      }
    } finally {
      // `inFlight` must always be reset, even when a round throws (e.g. a
      // malformed pull response making applyChanges fail) -- a round that
      // dies mid-flight with the flag left true would otherwise report
      // "synchronizing" forever, which offline_status.js renders as a
      // stuck "Syncing…" toast. The status is emitted *after* this reset
      // (below), never while inFlight is still set.
      inFlight = false;
    }
    await emitStatus();
    return ok;
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
