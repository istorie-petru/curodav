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
// pass -- this file now only reads the mirror to show "last synced" /
// "N changes waiting to sync".
//
// 2026-09-09 follow-up -- direct report against a second screenshot: the
// Labels multiselect (populated here from the mirror's tag set) "doesn't
// work" -- correctly so, it was never wired to actually apply a label to
// the created entity (object_label ops never flow through the field-HLC
// pull/write path offline); the old code only admitted that *after*
// submit, via an "(labels can't be added offline)" footnote. Removed the
// Labels field from the template entirely rather than cosmetically fixing
// a picker that can't do its job -- this file no longer needs to read
// tasks/events for their tags at all, only the two sync-summary numbers.
(function () {
  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString();
  }

  async function renderSummary() {
    const summaryEl = document.getElementById("offline-sync-summary");
    if (!summaryEl) return;
    const [lastSynced, outboxCount] = await Promise.all([
      window.CCOfflineDB.getLastSyncedAt ? window.CCOfflineDB.getLastSyncedAt() : Promise.resolve(null),
      window.CCOfflineDB.getOutboxCount ? window.CCOfflineDB.getOutboxCount() : Promise.resolve(0),
    ]);

    const syncedText = "Last synced from this device: " + (lastSynced ? fmtWhen(lastSynced) : "never");
    const pendingText = outboxCount > 0
      ? outboxCount + (outboxCount === 1 ? " local change" : " local changes") + " waiting to sync"
      : null;
    summaryEl.textContent = pendingText ? syncedText + " — " + pendingText : syncedText;
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
        if (!title) throw new Error("Task title is required");
        const fields = { title };
        if (due) fields.due_at = due + "T00:00:00";
        await window.CCOfflineWrite.createTask(fields);
        summary = "Task added: " + title;
      } else if (type === "event") {
        const title = builder.querySelector("#offline-event-title")?.value?.trim();
        const start = builder.querySelector("#offline-event-start")?.value;
        const end = builder.querySelector("#offline-event-end")?.value;
        const allDay = builder.querySelector("#offline-event-all-day")?.checked;
        if (!title) throw new Error("Event title is required");
        if (!start) throw new Error("Event start date/time is required");
        await window.CCOfflineWrite.createEvent({
          title,
          start_at: allDay ? start.split("T")[0] + "T00:00:00" : start,
          end_at: allDay ? start.split("T")[0] + "T23:59:59" : (end || start),
          all_day: allDay ? 1 : 0,
        });
        summary = "Event added: " + title;
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
  // just queued, should refresh the sync summary immediately rather than
  // requiring a reload -- both fire this same event (offline_write.js /
  // offline_sync_client.js).
  document.addEventListener("cc-offline-sync-complete", renderSummary);
})();
