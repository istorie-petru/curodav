// Inline editing for the Schedule Table view (templates/schedule_classes.html)
// -- same pattern as tasks_table.js: change a control, it saves itself via
// fetch, the row updates in place, no full-page reload on success. Two
// endpoints, matching routers/schedule.py:
//
//  - Day/Time (`.reposition-field`) POST the whole day+start_time+end_time
//    triple to /schedule/classes/{uid}/reposition -- the same endpoint the
//    Calendar view's drag-to-move already uses, since day/start/end are
//    naturally one "when is this class" unit there too, not three
//    independent fields. Changing just the Day select still needs to send
//    the row's current start/end alongside it (that's what a partial
//    payload -- day only -- would otherwise clobber to empty on the
//    server), so this reads all three controls from the same <tr> before
//    posting, not just the one that changed.
//  - Parity (`.pill-select`) POSTs only itself to
//    /schedule/classes/{uid}/update-field, same shape as the Tasks table's
//    status/priority pills.
//
// Exposed as window.CCScheduleTable.init(root), not a bare top-level IIFE
// -- the create/edit class form (schedule_class_form.html) still opens as
// a modal (data-modal) from a row's Edit link, and modal.js's
// wireContent() re-runs .init() after that content is injected the same
// way it does for every other page-level script. Schedule itself
// (schedule_classes.html) stopped being modal-openable 2026-08-08, but
// the re-init entry point stays since the modal-opened edit form can still
// land back on a freshly-reloaded table row.
(function () {
  function init(root) {
    const table = (root || document).querySelector("#schedule-table") || document.getElementById("schedule-table");
    if (!table || table.dataset.ccWired) return;
    table.dataset.ccWired = "1"; // avoid double-binding if init() runs twice on the same table

    async function post(url, body) {
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error("update failed");
        return true;
      } catch (err) {
        window.ccToast({ message: "Could not save that change. Reloading...", variant: "error", duration: 1400 });
        setTimeout(() => window.location.reload(), 1200);
        return false;
      }
    }

    table.querySelectorAll(".reposition-field").forEach((field) => {
      field.addEventListener("change", async () => {
        const uid = field.dataset.uid;
        const row = field.closest("tr");
        const day = row.querySelector('[data-field="day"]').value;
        const startTime = row.querySelector('[data-field="start_time"]').value;
        const endTime = row.querySelector('[data-field="end_time"]').value;
        if (!startTime || !endTime) return; // mid-edit / cleared -- wait for a real value
        await post(`/schedule/classes/${uid}/reposition`, { day, start_time: startTime, end_time: endTime });
      });
    });

    table.querySelectorAll("select.pill-select").forEach((select) => {
      select.addEventListener("change", async () => {
        const uid = select.dataset.uid;
        const field = select.dataset.field;
        const opt = select.options[select.selectedIndex];
        const color = opt.dataset.color || "gray";
        select.className = "pill-select pill-" + color;
        await post(`/schedule/classes/${uid}/update-field`, { field, value: opt.value });
      });
    });

  }

  window.CCScheduleTable = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
