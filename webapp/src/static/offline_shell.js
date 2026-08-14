// 1.8 slices 4-5 -- renders /offline's content straight from the local
// IndexedDB mirror (offline_db.js), no network request of its own. This
// is the one page in this slice that actually reads *and now writes* the
// local store -- every other page is untouched server-rendered HTML, per
// §0's "a second read/write path alongside the server-rendered one, not a
// replacement."
//
// Slice 4 was read-only. Slice 5 adds create/complete/delete for the task
// list specifically (offline_write.js), each going through the same §2 op
// + outbox path a real sync engine (slice 6) will eventually flush -- this
// file never talks to `outbox` directly, only to CCOfflineWrite's own
// entity-level functions, and re-renders on the same `cc-offline-sync-
// complete` event a pull already fires, so a local write and an incoming
// pull refresh the list identically.
//
// Deliberately still partial: events stay read-only (no offline write UI
// for them yet, see offline_write.js's own scope note), and labels/tags
// aren't mirrored at all (object_label ops are commutative, §7a, and never
// flow through the field-HLC pull/write path this mirrors) -- the task
// list shows title/due/status only, no project pill.
(function () {
  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Same markup deps.py's `icon()` Jinja global renders server-side
  // (`<svg class="icon" ...><use href="#icon-NAME"></use></svg>`) --
  // base.html's inline sprite (_icons_sprite.html) is already on every
  // page, so referencing a symbol by id here needs no separate asset.
  function iconSvg(name) {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';
  }

  async function render() {
    const root = document.getElementById("offline-local-data");
    if (!root || !("indexedDB" in window)) return;

    const [tasks, events, lastSynced, outboxCount] = await Promise.all([
      window.CCOfflineDB.getAllTasks(),
      window.CCOfflineDB.getAllEvents(),
      window.CCOfflineDB.getLastSyncedAt(),
      window.CCOfflineDB.getOutboxCount(),
    ]);

    // Slice 4 bailed out here entirely for a device that had never synced,
    // leaving the static "nothing to load" empty state as the only thing
    // shown. Slice 5 can no longer do that unconditionally -- a device
    // that has never been online at all must still be able to create its
    // very first task offline, and the add-task form below is the only
    // place that happens. Always render the task section (with the form);
    // only the *events* section still has nothing to show without a prior
    // pull, since there is no offline way to create one yet.
    const emptyState = document.getElementById("offline-empty-state");
    if (emptyState) emptyState.style.display = "none";

    const openTasks = tasks
      .filter((t) => t.status !== "completed")
      .sort((a, b) => (a.due_at || "9999").localeCompare(b.due_at || "9999"));

    const upcomingEvents = events
      .slice()
      .sort((a, b) => (a.start_at || "9999").localeCompare(b.start_at || "9999"))
      .slice(0, 10);

    const parts = [];
    parts.push('<div class="offline-synced-at">Last synced from this device: ' + (lastSynced ? fmtWhen(lastSynced) : "never") + "</div>");
    if (outboxCount > 0) {
      // Honest about what this slice does and doesn't do yet: the write
      // is safe and durable locally, but nothing pushes it anywhere until
      // slice 6's sync engine exists.
      parts.push(
        '<div class="offline-pending-note">' +
          outboxCount +
          (outboxCount === 1 ? " local change" : " local changes") +
          " saved on this device, waiting for sync support to send " +
          (outboxCount === 1 ? "it" : "them") +
          " elsewhere.</div>"
      );
    }

    parts.push('<h2 class="offline-section-title">Tasks (' + openTasks.length + ")</h2>");
    parts.push(
      '<form id="offline-add-task-form" class="offline-add-task-form">' +
        '<input type="text" name="title" placeholder="New task" required maxlength="200">' +
        '<input type="date" name="due_date">' +
        '<button type="submit" class="btn primary">' +
        iconSvg("plus") +
        " Add</button></form>"
    );
    if (openTasks.length === 0) {
      parts.push('<div class="empty-state">No open tasks in the local mirror.</div>');
    } else {
      // Reuses .checklist/.checklist-row/.checklist-check/.checklist-
      // delete -- the same row shape task_detail.html's own checklist
      // widget already establishes for "title + done-toggle + delete" --
      // rather than inventing a second interactive-row style.
      parts.push('<div class="checklist">');
      for (const t of openTasks) {
        parts.push(
          '<div class="checklist-row" data-task-row="' + escapeHtml(t.uid) + '">' +
            '<button type="button" class="checklist-check" data-offline-complete="' + escapeHtml(t.uid) + '" title="Mark done">' +
            iconSvg("square") +
            "</button>" +
            '<span class="checklist-text">' +
            escapeHtml(t.title || "(untitled)") +
            (t.due_at ? ' <span class="search-result-subtitle">due ' + escapeHtml(fmtWhen(t.due_at)) + "</span>" : "") +
            "</span>" +
            '<button type="button" class="checklist-delete btn ghost" data-offline-delete="' + escapeHtml(t.uid) + '" title="Delete task">' +
            iconSvg("trash") +
            "</button></div>"
        );
      }
      parts.push("</div>");
    }

    parts.push('<h2 class="offline-section-title">Events (' + upcomingEvents.length + ")</h2>");
    if (upcomingEvents.length === 0) {
      parts.push('<div class="empty-state">No events in the local mirror.</div>');
    } else {
      parts.push('<div class="checklist">');
      for (const e of upcomingEvents) {
        parts.push(
          '<div class="checklist-row"><span class="checklist-text">' +
            escapeHtml(e.title || "(untitled)") +
            (e.start_at ? ' <span class="search-result-subtitle">' + escapeHtml(fmtWhen(e.start_at)) + "</span>" : "") +
            "</span></div>"
        );
      }
      parts.push("</div>");
    }

    root.innerHTML = parts.join("\n");
  }

  // Delegated on `root` itself, which survives every re-render (only its
  // innerHTML is replaced) -- attached once, not re-bound per render, per
  // the button/form elements inside it being recreated from scratch each
  // time.
  function wireWriteHandlers() {
    const root = document.getElementById("offline-local-data");
    if (!root || !window.CCOfflineWrite) return;

    root.addEventListener("submit", async (event) => {
      const form = event.target.closest("#offline-add-task-form");
      if (!form) return;
      event.preventDefault();
      const title = form.elements.title.value.trim();
      if (!title) return;
      const dueDate = form.elements.due_date.value;
      const fields = { title };
      if (dueDate) fields.due_at = dueDate + "T00:00:00";
      form.querySelector('button[type="submit"]').disabled = true;
      await window.CCOfflineWrite.createTask(fields);
    });

    root.addEventListener("click", async (event) => {
      const completeBtn = event.target.closest("[data-offline-complete]");
      if (completeBtn) {
        await window.CCOfflineWrite.updateTaskField(completeBtn.getAttribute("data-offline-complete"), "status", "completed");
        return;
      }
      const deleteBtn = event.target.closest("[data-offline-delete]");
      if (deleteBtn) {
        await window.CCOfflineWrite.deleteTask(deleteBtn.getAttribute("data-offline-delete"));
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireWriteHandlers();
    render();
  });
  // A pull that lands *while* /offline happens to be open (e.g. the
  // network came back mid-visit), or a local write this page's own form/
  // buttons just queued, should refresh this list immediately rather than
  // requiring a reload -- both fire the same event (offline_sync_client.js
  // / offline_write.js).
  document.addEventListener("cc-offline-sync-complete", render);
})();
