// 1.8 slices 4-5 + 2026-08-18/08-19 reworks -- this file used to render
// /offline's content straight from the local IndexedDB mirror
// (offline_db.js) as a five-tab, full-app-mirroring page (Dashboard/
// Calendar/Tasks/Contacts/Notes), each tab holding read-only lists plus its
// own copy of the Quick Add builder.
//
// 2026-09-09 -- direct report against a screenshot: that page read as
// cramped (tab bar + empty-state block + form all fighting for hierarchy)
// and its "Quick Capture Syntax" preview textarea was dead weight -- it
// displayed a generated capture string for show, but submit always read the
// visual fields directly, so nothing ever parsed that text back in. Collapsed
// to a single screen: no tabs, no per-entity mirror lists, just a one-line
// sync summary and the Quick Add form. Re-adding a real offline *read*
// surface (the old mirror lists) is left for a future, separately-scoped
// pass -- this file now only reads the mirror to (a) show "last synced" /
// "N changes waiting to sync" and (b) populate the label picker, both of
// which the old render() also did as a side effect.
(function () {
  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString();
  }

  const quickAddState = { labels: [] };

  // Reads just enough of the mirror to (1) report sync status honestly and
  // (2) know which labels exist for the Quick Add label picker -- not a
  // full list render. Labels themselves still can't be *applied* to a
  // freshly created entity offline (object_label ops are commutative and
  // never flow through the field-HLC pull/write path); this only lets the
  // picker show real label names instead of an empty box.
  async function renderSummary() {
    const [tasks, events, lastSynced, outboxCount] = await Promise.all([
      window.CCOfflineDB.getAllTasks ? window.CCOfflineDB.getAllTasks() : Promise.resolve([]),
      window.CCOfflineDB.getAllEvents ? window.CCOfflineDB.getAllEvents() : Promise.resolve([]),
      window.CCOfflineDB.getLastSyncedAt ? window.CCOfflineDB.getLastSyncedAt() : Promise.resolve(null),
      window.CCOfflineDB.getOutboxCount ? window.CCOfflineDB.getOutboxCount() : Promise.resolve(0),
    ]);

    const allLabels = new Set();
    for (const t of tasks) {
      if (t.tags) t.tags.forEach((l) => allLabels.add(l));
    }
    for (const e of events) {
      if (e.tags) e.tags.forEach((l) => allLabels.add(l));
    }
    quickAddState.labels = Array.from(allLabels).sort();
    populateLabelSelect(document.getElementById("offline-task-labels"));
    populateLabelSelect(document.getElementById("offline-event-labels"));

    const summaryEl = document.getElementById("offline-sync-summary");
    if (!summaryEl) return;
    const syncedText = "Last synced from this device: " + (lastSynced ? fmtWhen(lastSynced) : "never");
    const pendingText = outboxCount > 0
      ? outboxCount + (outboxCount === 1 ? " local change" : " local changes") + " waiting to sync"
      : null;
    summaryEl.textContent = pendingText ? syncedText + " — " + pendingText : syncedText;
  }

  function populateLabelSelect(select) {
    if (!select) return;
    const previouslySelected = new Set(Array.from(select.selectedOptions || []).map((o) => o.value));
    select.innerHTML = "";
    for (const label of quickAddState.labels) {
      const opt = document.createElement("option");
      opt.value = label;
      opt.textContent = label;
      opt.selected = previouslySelected.has(label);
      select.appendChild(opt);
    }
  }

  function initializeQuickAddBuilder() {
    const builder = document.querySelector("[data-offline-quick-add]");
    if (!builder) return;
    const form = builder.querySelector("#offline-quick-add-form");
    if (!form) return;

    const entityTypeSelect = builder.querySelector("#offline-entity-type");
    const taskFields = builder.querySelector("#offline-task-fields");
    const eventFields = builder.querySelector("#offline-event-fields");
    const contactFields = builder.querySelector("#offline-contact-fields");
    const noteFields = builder.querySelector("#offline-note-fields");
    const cancelBtn = builder.querySelector("#offline-quick-add-cancel");
    const resultEl = builder.querySelector("#offline-quick-add-result");

    if (entityTypeSelect) {
      entityTypeSelect.addEventListener("change", () => {
        const type = entityTypeSelect.value;
        taskFields.hidden = type !== "task";
        eventFields.hidden = type !== "event";
        contactFields.hidden = type !== "contact";
        noteFields.hidden = type !== "note";
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        form.reset();
        if (resultEl) resultEl.textContent = "";
      });
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await handleQuickAddSubmit(builder, form, resultEl);
    });
  }

  async function handleQuickAddSubmit(builder, form, resultEl) {
    const entityTypeSelect = builder.querySelector("#offline-entity-type");
    const type = entityTypeSelect ? entityTypeSelect.value : "task";
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    try {
      let summary;
      if (type === "task") {
        const title = builder.querySelector("#offline-task-title")?.value?.trim();
        const due = builder.querySelector("#offline-task-due")?.value;
        const labels = Array.from(builder.querySelector("#offline-task-labels")?.selectedOptions || []).map((o) => o.value);
        if (!title) throw new Error("Task title is required");
        const fields = { title };
        if (due) fields.due_at = due + "T00:00:00";
        await window.CCOfflineWrite.createTask(fields);
        summary = "Task added: " + title;
        if (labels.length > 0) summary += " (labels can't be added offline)";
      } else if (type === "event") {
        const title = builder.querySelector("#offline-event-title")?.value?.trim();
        const start = builder.querySelector("#offline-event-start")?.value;
        const end = builder.querySelector("#offline-event-end")?.value;
        const allDay = builder.querySelector("#offline-event-all-day")?.checked;
        const labels = Array.from(builder.querySelector("#offline-event-labels")?.selectedOptions || []).map((o) => o.value);
        if (!title) throw new Error("Event title is required");
        if (!start) throw new Error("Event start date/time is required");
        await window.CCOfflineWrite.createEvent({
          title,
          start_at: allDay ? start.split("T")[0] + "T00:00:00" : start,
          end_at: allDay ? start.split("T")[0] + "T23:59:59" : (end || start),
          all_day: allDay ? 1 : 0,
        });
        summary = "Event added: " + title;
        if (labels.length > 0) summary += " (labels can't be added offline)";
      } else if (type === "contact") {
        const name = builder.querySelector("#offline-contact-name")?.value?.trim();
        const email = builder.querySelector("#offline-contact-email")?.value?.trim();
        const phone = builder.querySelector("#offline-contact-phone")?.value?.trim();
        if (!name) throw new Error("Contact name is required");
        await window.CCOfflineWrite.createContact({ full_name: name });
        summary = "Contact added: " + name;
        if (email || phone) summary += " (phone/email can't be added offline)";
      } else if (type === "note") {
        const content = builder.querySelector("#offline-note-content")?.value?.trim();
        if (!content) throw new Error("Note content is required");
        await window.CCOfflineWrite.createNote({ content });
        summary = "Note added";
      }

      if (resultEl) {
        resultEl.textContent = summary;
        resultEl.classList.remove("is-error");
      }
      form.reset();
      await renderSummary();
    } catch (err) {
      if (resultEl) {
        resultEl.textContent = "Couldn't save: " + err.message;
        resultEl.classList.add("is-error");
      }
    } finally {
      submitBtn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initializeQuickAddBuilder();
    renderSummary();
  });

  // A pull that lands *while* /offline happens to be open (e.g. the
  // network came back mid-visit), or a local write this page's own form
  // just queued, should refresh the sync summary/labels immediately rather
  // than requiring a reload -- both fire this same event (offline_write.js
  // / offline_sync_client.js).
  document.addEventListener("cc-offline-sync-complete", renderSummary);
})();
