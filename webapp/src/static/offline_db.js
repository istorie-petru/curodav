// 1.8 slice 4 -- the client-side local data layer (plans/open-priority.md
// § Offline-first editing & synchronization §11 slice 4; §2's "IndexedDB
// on the client" outbox/mirror role). This slice only builds the *read*
// side of that role: a per-field-HLC-tracked mirror of tasks/events/
// contacts, kept warm by offline_sync_client.js's pull loop. No outbox,
// no local writes yet -- that's slice 5.
//
// Schema (IndexedDB database "cc-offline", version 1):
//   tasks/events/contacts   -- keyPath "uid", one row per entity, fields
//                               written incrementally as pull() delivers
//                               them (never a whole-row replace).
//   field_hlc               -- keyPath "key" ("entityType:entityUid:field"),
//                               the client's own copy of §6's per-field HLC
//                               shadow store, so a pull can never regress a
//                               field to an older value if changes ever
//                               arrive out of order (today they don't --
//                               offline_sync.pull() already returns them in
//                               ascending HLC order -- but comparing rather
//                               than blindly overwriting costs nothing and
//                               is what slice 5's own local writes will
//                               need this store to already do correctly).
//   meta                    -- keyPath "key", a small handful of singleton
//                               rows: device_id, cursor (the pull cursor,
//                               §8), last_synced_at.
//
// Deliberately entity-shape-agnostic: this file never hardcodes a task's
// or event's field list (routers/../offline_sync.py's _ENTITY_FIELDS
// whitelist is the server's own concern) -- it just writes whatever
// field_name/value pairs pull() sends into the matching row.
(function () {
  const DB_NAME = "cc-offline";
  const DB_VERSION = 1;
  const ENTITY_STORES = { task: "tasks", event: "events", contact: "contacts" };

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
        if (!db.objectStoreNames.contains("field_hlc")) db.createObjectStore("field_hlc", { keyPath: "key" });
        if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "key" });
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

  window.CCOfflineDB = {
    open: openDb,
    getDeviceId,
    getCursor,
    setCursor,
    getLastSyncedAt,
    setLastSyncedAt,
    applyChanges,
    getAllTasks,
    getAllEvents,
    getAllContacts,
  };
})();
