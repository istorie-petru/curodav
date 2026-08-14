// 1.8 slice 5 -- "Local write path + outbox" (plans/open-priority.md §
// Offline-first editing & synchronization §11 slice 5). An offline
// create/edit/delete no longer fails on /offline -- it becomes a §2
// operation record, queued into offline_db.js's `outbox` store, and
// applied immediately to the local mirror so the UI reflects the change
// right away (optimistic, same-device apply -- a write's own freshly
// minted HLC is always newer than anything already in field_hlc for that
// field, so it can never lose to itself).
//
// Deliberately scoped to tasks only, matching this slice's "extends local-
// read coverage" framing rather than rebuilding every entity type's write
// UI at once -- offline.html's task list is the one local-read surface
// that already exists to extend. Events/contacts get no offline write UI
// yet; a later slice can repeat this same shape for them once there's a
// real sync engine (slice 6) to actually flush the outbox against.
//
// Still no sync engine: ops queued here just accumulate in `outbox` until
// slice 6's push loop exists. Nothing here ever talks to the network.
(function () {
  function hlcPayload(hlc) {
    return { physical: hlc[0], logical: hlc[1], device_id: hlc[2] };
  }

  // Mirrors offline_db.js's own `applyChanges` shape so a freshly-queued
  // op is reflected in the local mirror through the exact same per-field-
  // HLC-wins path a pull uses -- no separate "optimistic write" logic to
  // keep in sync with that one.
  async function applyOpLocally(op) {
    const changes = [];
    if (op.op_type === "delete") {
      changes.push({
        entity_type: op.entity_type,
        entity_uid: op.entity_uid,
        field_name: "deleted_at",
        value: new Date(op.hlc.physical).toISOString(),
        hlc: op.hlc,
      });
    } else {
      for (const [fieldName, spec] of Object.entries(op.fields)) {
        changes.push({
          entity_type: op.entity_type,
          entity_uid: op.entity_uid,
          field_name: fieldName,
          value: spec.value,
          hlc: spec.hlc,
        });
      }
    }
    await window.CCOfflineDB.applyChanges(changes);
  }

  async function submitOp(op) {
    await window.CCOfflineDB.enqueueOp(op);
    await applyOpLocally(op);
    // Same event offline_sync_client.js fires after a pull lands --
    // offline_shell.js already listens for it to re-render, so a local
    // write refreshes the visible list with no separate signal needed.
    document.dispatchEvent(new CustomEvent("cc-offline-sync-complete"));
    return op;
  }

  // `create` is a single field_set covering every field at once, stamped
  // with one shared HLC (§2: "a plain-form create with no prior state to
  // conflict against").
  async function createTask(fields) {
    const deviceId = await window.CCOfflineDB.getDeviceId();
    const uid = crypto.randomUUID();
    const hlc = hlcPayload(await window.CCOfflineDB.nextHlc());
    const nowIso = new Date().toISOString();
    const base = Object.assign({ status: "open", created_at: nowIso, updated_at: nowIso }, fields);
    const opFields = {};
    for (const [name, value] of Object.entries(base)) {
      opFields[name] = { value, hlc };
    }
    const op = {
      op_id: crypto.randomUUID(),
      entity_type: "task",
      entity_uid: uid,
      op_type: "create",
      fields: opFields,
      device_id: deviceId,
      // Every field in a create shares one HLC (§2), so it's also this
      // op's own top-level ordering key -- offline_db.js's outbox sort
      // reads this the same way it reads a delete op's own `hlc`.
      hlc,
    };
    await submitOp(op);
    return uid;
  }

  // A single field edit (e.g. marking a task complete) -- `updated_at`
  // rides along on the same HLC as the edited field, since both describe
  // the same write event.
  async function updateTaskField(uid, fieldName, value) {
    const deviceId = await window.CCOfflineDB.getDeviceId();
    const hlc = hlcPayload(await window.CCOfflineDB.nextHlc());
    const op = {
      op_id: crypto.randomUUID(),
      entity_type: "task",
      entity_uid: uid,
      op_type: "field_set",
      fields: {
        [fieldName]: { value, hlc },
        updated_at: { value: new Date().toISOString(), hlc },
      },
      device_id: deviceId,
      hlc, // see createTask's own comment on this convenience top-level copy
    };
    await submitOp(op);
  }

  // §4: a delete is a tombstone (`deleted_at` field write), never a row
  // removal -- an edit with a newer HLC than this can still un-delete the
  // row later (falls out of the shared apply path, no special-casing
  // needed here either).
  async function deleteTask(uid) {
    const deviceId = await window.CCOfflineDB.getDeviceId();
    const hlc = hlcPayload(await window.CCOfflineDB.nextHlc());
    const op = {
      op_id: crypto.randomUUID(),
      entity_type: "task",
      entity_uid: uid,
      op_type: "delete",
      device_id: deviceId,
      hlc,
    };
    await submitOp(op);
  }

  window.CCOfflineWrite = { createTask, updateTaskField, deleteTask };
})();
