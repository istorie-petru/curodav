// 1.8 slices 4-5 -- the client-side local data layer (plans/open-priority.md
// § Offline-first editing & synchronization §11). Slice 4 built the *read*
// side: a per-field-HLC-tracked mirror of tasks/events/contacts, kept warm
// by offline_sync_client.js's pull loop. Slice 5 adds the other half of
// §2's "IndexedDB on the client" role -- an append-only `outbox` store for
// ops a local write produces, plus this device's own §3 HLC clock (nothing
// through slice 4 ever needed to *mint* an HLC, only apply server-supplied
// ones). Still no sync engine wired up (slice 6) -- outbox ops just
// accumulate here until then.
//
// 2026-08-19 -- Added "notes" entity store for the Offline Mode page.
//
// Schema (IndexedDB database "cc-offline", version 3):
//   tasks/events/contacts/notes -- keyPath "uid", one row per entity, fields
//                               written incrementally as pull()/local
//                               writes deliver them (never a whole-row
//                               replace).
//   field_hlc               -- keyPath "key" ("entityType:entityUid:field"),
//                               the client's own copy of §6's per-field HLC
//                               shadow store, so a pull (or a local write)
//                               can never regress a field to an older value
//                               if changes ever arrive out of order.
//   outbox                  -- keyPath "op_id", one row per §2 operation
//                               record a local write has queued, oldest-
//                               first by insertion order (§5: "ops sync in
//                               per-entity chronological order," which push
//                               -- slice 6 -- will re-sort by HLC anyway).
//   meta                    -- keyPath "key", singleton rows: device_id,
//                               cursor (the pull cursor, §8),
//                               last_synced_at, hlc_clock (this device's own
//                               (physical_time_ms, logical_counter) pair --
//                               device_id itself lives under its own key
//                               and is appended to form the full triple),
//                               server_version (the server's data version
//                               at this device's last successful pull --
//                               2026-08-17, the round-skip pre-check).
//
// Deliberately entity-shape-agnostic: this file never hardcodes a task's
// or event's field list (routers/../offline_sync.py's _ENTITY_FIELDS
// whitelist is the server's own concern) -- it just writes whatever
// field_name/value pairs a change/op sends into the matching row.
(function () {
  const DB_NAME = "cc-offline";
  const DB_VERSION = 3;
  const ENTITY_STORES = { task: "tasks", event: "events", contact: "contacts", note: "notes" };

  let dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("tasks")) db.createObjectStore("tasks", { keyPath: "uid" });
        if (!db.objectStoreNames.contains("events")) db.createObjectStore("events", { keyPath: "uid" });
        if (!db.objectStoreNames.contains("contacts")) db.createObjectStore("contacts", { keyPath: "uid" });
        if (!db.objectStoreNames.contains("notes")) db.createObjectStore("notes", { keyPath: "uid" });
        if (!db.objectStoreNames.contains("field_hlc")) db.createObjectStore("field_hlc", { keyPath: "key" });
        if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "key" });
        // Slice 5 -- added on top of a slice-4 (version 1) database via
        // IndexedDB's own version-upgrade path, so a device that already
        // has a local mirror keeps it; only the new store is created.
        if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "op_id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  function tx(db, storeNames, mode) {
    return db.transaction(storeNames, mode);
  }

  function reqToPromise(req) {
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function getMeta(key) {
    const db = await openDb();
    const row = await reqToPromise(tx(db, "meta", "readonly").objectStore("meta").get(key));
    return row ? row.value : null;
  }

  async function setMeta(key, value) {
    const db = await openDb();
    await reqToPromise(tx(db, "meta", "readwrite").objectStore("meta").put({ key, value }));
  }

  async function getDeviceId() {
    let id = await getMeta("device_id");
    if (!id) {
      // Same "generated once per install, stored locally" rule as §1 --
      // crypto.randomUUID() is this file's equivalent of the server's
      // uuid.uuid4(), collision-safe with no central allocation needed
      // (single-user app, per abandoned.md).
      id = crypto.randomUUID();
      await setMeta("device_id", id);
    }
    return id;
  }

  async function getCursor() {
    return await getMeta("cursor");
  }

  async function setCursor(hlcPayload) {
    await setMeta("cursor", hlcPayload);
  }

  async function getLastSyncedAt() {
    return await getMeta("last_synced_at");
  }

  async function setLastSyncedAt(isoString) {
    await setMeta("last_synced_at", isoString);
  }

  // 2026-08-17 -- the server's data version, saved after every successful
  // pull (offline_sync_client.js stores `body.version`). Compared against
  // a fresh GET /api/sync/state before a pull-only round: when they match
  // and the outbox is empty, nothing has changed server-side since this
  // device last synced, so the round is skipped entirely.
  async function getServerVersion() {
    return await getMeta("server_version");
  }

  async function setServerVersion(version) {
    await setMeta("server_version", version);
  }

  // §3's HLC clock, client-side half. Nothing through slice 4 ever minted
  // its own HLC (only applied server-supplied ones from pull()) -- a local
  // write is the first thing on this device that needs to. `nextHlc()` is
  // the "generate a write's own HLC" rule: bump the logical counter within
  // the same millisecond (or when the wall clock hasn't advanced past the
  // last-used physical time), otherwise reset it against the new physical
  // time -- the same rule `mergeHlc` below applies for HLCs *received* from
  // the server, per §3's "merged (max + increment) on every operation they
  // observe from the other side."
  async function nextHlc() {
    const db = await openDb();
    const store = tx(db, "meta", "readwrite").objectStore("meta");
    const row = await reqToPromise(store.get("hlc_clock"));
    const now = Date.now();
    let physical = now;
    let logical = 0;
    if (row && row.value && row.value[0] >= physical) {
      physical = row.value[0];
      logical = row.value[1] + 1;
    }
    await reqToPromise(store.put({ key: "hlc_clock", value: [physical, logical] }));
    const deviceId = await getDeviceId();
    return [physical, logical, deviceId];
  }

  // The receive-side half of §3's merge rule: advance this device's own
  // clock past an HLC it has just observed from the server (a pull), so a
  // subsequent local write's HLC is guaranteed to sort after everything
  // this device has seen -- the standard HLC synchronization algorithm
  // (physical = max of both sides and the wall clock; logical resets to 0
  // only if the wall clock strictly exceeded both prior physical times,
  // otherwise increments past whichever tied for the max).
  //
  // Takes the `{physical, logical, device_id}` payload shape every server
  // HLC uses on the wire (offline_sync.hlc_to_payload's own dict, not the
  // `[physical, logical, device_id]` array this file uses internally for
  // field_hlc/hlc_clock) -- `offline_sync_client.js` passes `body.cursor`
  // straight through from the pull response, unconverted. A real bug once
  // lived here: this function used to destructure its argument as an
  // array (`const [remotePhysical, remoteLogical] = remoteHlc`), which
  // silently threw against every real pull response with a non-null
  // cursor -- caught by a one-off Node smoke script exercising an actual
  // full-resync round trip, not by any test that happened to pass a null
  // cursor.
  async function mergeHlc(remoteHlc) {
    if (!remoteHlc) return;
    const db = await openDb();
    const store = tx(db, "meta", "readwrite").objectStore("meta");
    const row = await reqToPromise(store.get("hlc_clock"));
    const [localPhysical, localLogical] = row && row.value ? row.value : [0, 0];
    const remotePhysical = remoteHlc.physical;
    const remoteLogical = remoteHlc.logical;
    const now = Date.now();
    const newPhysical = Math.max(localPhysical, remotePhysical, now);
    let newLogical;
    if (newPhysical === localPhysical && newPhysical === remotePhysical) {
      newLogical = Math.max(localLogical, remoteLogical) + 1;
    } else if (newPhysical === localPhysical) {
      newLogical = localLogical + 1;
    } else if (newPhysical === remotePhysical) {
      newLogical = remoteLogical + 1;
    } else {
      newLogical = 0;
    }
    await reqToPromise(store.put({ key: "hlc_clock", value: [newPhysical, newLogical] }));
  }

  // Lexicographic HLC compare, the same total order §3 defines server-side
  // -- (physical_time_ms, logical_counter, device_id). Returns true if `a`
  // is strictly newer than `b` (or `b` is absent).
  function isNewer(a, b) {
    if (!b) return true;
    if (a[0] !== b[0]) return a[0] > b[0];
    if (a[1] !== b[1]) return a[1] > b[1];
    return a[2] > b[2];
  }

  function fieldKey(entityType, entityUid, fieldName) {
    return entityType + ":" + entityUid + ":" + fieldName;
  }

  // Applies one pull() delta batch (routers/sync_api.py's own `changes`
  // shape: {entity_type, entity_uid, field_name, value, hlc}) into the
  // local mirror -- the same §6 "newer HLC wins, per field" rule the
  // server applies to its own field_versions table, just replayed
  // client-side against this store instead.
  async function applyChanges(changes) {
    if (!changes || changes.length === 0) return;
    const db = await openDb();
    const storeNames = new Set(["field_hlc"]);
    for (const c of changes) {
      const storeName = ENTITY_STORES[c.entity_type];
      if (storeName) storeNames.add(storeName);
    }
    const t = tx(db, Array.from(storeNames), "readwrite");
    const fieldStore = t.objectStore("field_hlc");
    const rowCache = {};

    for (const change of changes) {
      const storeName = ENTITY_STORES[change.entity_type];
      if (!storeName) continue; // unknown entity_type -- ignore, don't fail the whole batch

      const key = fieldKey(change.entity_type, change.entity_uid, change.field_name);
      const existingHlc = await reqToPromise(fieldStore.get(key));
      const incomingHlc = [change.hlc.physical, change.hlc.logical, change.hlc.device_id];
      if (existingHlc && !isNewer(incomingHlc, existingHlc.hlc)) continue; // stale, same rule as server-side §6

      await reqToPromise(fieldStore.put({ key, hlc: incomingHlc }));

      const store = t.objectStore(storeName);
      const cacheKey = storeName + ":" + change.entity_uid;
      let row = rowCache[cacheKey];
      if (!row) {
        row = (await reqToPromise(store.get(change.entity_uid))) || { uid: change.entity_uid };
        rowCache[cacheKey] = row;
      }
      row[change.field_name] = change.value;
      await reqToPromise(store.put(row));
    }
  }

  // Read helpers -- deliberately minimal for this slice (no filtering/
  // sorting/pagination beyond "not soft-deleted"): offline_shell.js is
  // this slice's one consumer, and it does its own sort/limit over the
  // small result set a single-user install's local mirror realistically
  // holds. A richer query layer belongs to whichever later slice actually
  // needs one (e.g. if the read path grows past the /offline page).
  async function getAll(storeName) {
    const db = await openDb();
    const rows = await reqToPromise(tx(db, storeName, "readonly").objectStore(storeName).getAll());
    return rows.filter((r) => !r.deleted_at);
  }

  async function getAllTasks() {
    return getAll("tasks");
  }

  async function getAllEvents() {
    return getAll("events");
  }

  async function getAllContacts() {
    return getAll("contacts");
  }

  async function getAllNotes() {
    return getAll("notes");
  }

  // §2's outbox -- append-only from a local write's point of view through
  // slice 5 (that slice never mutated or removed a queued op). Slice 6's
  // push loop (offline_sync_client.js) is the first thing that does,
  // via `removeOutboxOps` below, once the server has acknowledged an op
  // (§2: "an op, once written, is never mutated, only marked
  // 'acknowledged' once the server confirms it (or dropped after a
  // bounded retention once acknowledged, to keep the local store
  // small)" -- this slice takes the simpler of those two options and
  // drops an acknowledged op immediately rather than modeling a separate
  // acknowledged-but-retained state, since nothing else in this app ever
  // reads outbox history after a push has confirmed it). The store's own
  // keyPath is `op_id` (a random UUID, per §2), which is *not* insertion-
  // ordered, so `getOutboxOps` explicitly sorts on each op's own top-level
  // `hlc` (offline_write.js stamps one on every op it builds, including
  // create/field_set -- §5's own "ops sync in per-entity chronological
  // (HLC) order" rule, applied here too rather than inventing a separate
  // insertion-order field). A real ordering bug this slice's own smoke
  // test caught: two ops enqueued back-to-back came back in plain UUID
  // key order, not the order they were written, before this sort existed.
  async function enqueueOp(op) {
    const db = await openDb();
    await reqToPromise(tx(db, "outbox", "readwrite").objectStore("outbox").put(op));
  }

  function _opHlcTuple(op) {
    const h = op.hlc;
    return h ? [h.physical, h.logical, h.device_id] : [0, 0, ""];
  }

  async function getOutboxOps() {
    const db = await openDb();
    const rows = await reqToPromise(tx(db, "outbox", "readonly").objectStore("outbox").getAll());
    return rows.sort((a, b) => {
      const ta = _opHlcTuple(a);
      const tb = _opHlcTuple(b);
      if (ta[0] !== tb[0]) return ta[0] - tb[0];
      if (ta[1] !== tb[1]) return ta[1] - tb[1];
      return ta[2] < tb[2] ? -1 : ta[2] > tb[2] ? 1 : 0;
    });
  }

  async function getOutboxCount() {
    const db = await openDb();
    return await reqToPromise(tx(db, "outbox", "readonly").objectStore("outbox").count());
  }

  async function removeOutboxOps(opIds) {
    if (!opIds || opIds.length === 0) return;
    const db = await openDb();
    const store = tx(db, "outbox", "readwrite").objectStore("outbox");
    for (const opId of opIds) {
      await reqToPromise(store.delete(opId));
    }
  }

  // 1.8 slice 7 -- the client-side half of tombstone GC's own safety
  // requirement (§4/§11's acceptance line: "restoring from an old client
  // cursor never resurrects a tombstoned row past the GC horizon; it
  // forces a full resync instead"). A `full_resync` response
  // (offline_sync_client.js) means the server may have already *purged*
  // some old tombstones entirely -- a purged entity's field_versions rows
  // are gone, so a plain incremental-style `applyChanges` over the full-
  // resync payload would never tell this device to delete its own stale
  // local copy of that entity (there's nothing left server-side to say
  // "this is deleted," only silence). The only way a full resync can
  // honestly mean "start over" is to actually start over: wipe the local
  // mirror and field_hlc shadow store first, then rebuild purely from
  // what the resync returns -- anything genuinely still relevant comes
  // back in that payload; anything this device had that's now gone (a
  // purged tombstone included) simply never reappears. The outbox and
  // `meta` (device_id, in particular) are deliberately untouched -- a
  // full resync is about *pulled* state, not this device's own identity
  // or its own not-yet-acknowledged local writes.
  async function clearMirror() {
    const db = await openDb();
    const t = tx(db, ["tasks", "events", "contacts", "notes", "field_hlc"], "readwrite");
    await Promise.all(
      ["tasks", "events", "contacts", "notes", "field_hlc"].map((name) => reqToPromise(t.objectStore(name).clear()))
    );
  }

  window.CCOfflineDB = {
    open: openDb,
    getDeviceId,
    getCursor,
    setCursor,
    getLastSyncedAt,
    setLastSyncedAt,
    getServerVersion,
    setServerVersion,
    nextHlc,
    mergeHlc,
    applyChanges,
    getAllTasks,
    getAllEvents,
    getAllContacts,
    getAllNotes,
    enqueueOp,
    getOutboxOps,
    getOutboxCount,
    removeOutboxOps,
    clearMirror,
  };
})();
