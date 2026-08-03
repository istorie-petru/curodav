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
// -- 2026-08-01, Schedule became a modal opened from Calendar
// (_calendar_nav.html), and a modal's content is injected via
// `body.innerHTML = ...` (modal.js), which never executes embedded
// <script> tags and never re-runs a script that already finished loading
// on the *original* page (Calendar's own extra_scripts doesn't include
// this file at all). Loading this file globally (base.html) plus calling
// .init() again from modal.js's wireContent() after every injection is
// what makes it work both as a normal full-page view AND inside the
// modal -- same "listeners have to be reattached to fresh DOM nodes"
// problem wireContent() already solves for color pickers and forms.
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

    initDensity(table, root);
  }

  // Compact density (2026-08-01, "a lot of classes, easily viewed") --
  // localStorage-persisted, same "pure per-device display preference"
  // category as the Timeline view's gutter width (timeline.js), not
  // something the server needs to know about. Scoped to whichever table
  // was just wired (not a bare getElementById) so this also works
  // correctly when re-run inside the modal.
  const DENSITY_KEY = "commandCenterWeb.scheduleTableDensity";
  function initDensity(table, root) {
    const toggle = (root || document).querySelector("#schedule-density-toggle") || document.getElementById("schedule-density-toggle");
    if (!toggle || toggle.dataset.ccWired) return;
    toggle.dataset.ccWired = "1";

    function apply(on) {
      table.classList.toggle("is-compact", on);
      toggle.classList.toggle("active", on);
    }
    apply(localStorage.getItem(DENSITY_KEY) === "1");

    toggle.addEventListener("click", () => {
      const on = !table.classList.contains("is-compact");
      apply(on);
      localStorage.setItem(DENSITY_KEY, on ? "1" : "0");
    });
  }

  window.CCScheduleTable = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
