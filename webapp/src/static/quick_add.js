(() => {
  // Merged task/event quick-add tab switch (2026-08-10) -- the dashboard
  // and label-page "+" button opens quick_add.html, which renders BOTH the
  // task and event create-forms in one modal; this script just flips
  // between them. Exposed as window.CCQuickAdd so static/modal.js's
  // wireContent() can re-run it against every freshly-injected modal
  // fragment (innerHTML injection never re-runs <script> tags, see
  // modal.js's Schedule/relations comments for the same pattern), like
  // CCWidgetPreview / CCHabitFieldToggle / etc.
  //
  // Why the tab switch is *client-side* rather than a per-tab fetch
  // (the "data-modal-get re-fetch" pattern): the two forms share nothing
  // but a handful of DB-backed option lists, and every picker involved
  // (recurrence, reminders, steppers, the Labels/Status/Priority
  // multiselects) already auto-initializes on injected content via
  // MutationObserver (see static/recurrence_picker.js, etc.). Both forms
  // are static HTML in the fragment from the start, so switching tabs is
  // just: toggle the visible panel, move the .seg-btn active state, and
  // retarget the footer Save button's `form` attribute (the footer is a
  // separate DOM element from the body -- see quick_add.html's own
  // comment on why a footer button needs `form="..."` at all).
  //
  // The init is idempotent (guarded by a data-ready flag on the panels
  // container) so a data-modal-get re-submit or a second wireContent()
  // pass doesn't double-bind the tab buttons.

  window.CCQuickAdd = {
    init(root) {
      const container = document.getElementById("quick-add-panels");
      if (!container || container.dataset.ready === "1") return;
      container.dataset.ready = "1";
      const tabs = Array.from(document.querySelectorAll("[data-quick-add-tab]"));
      const panels = Array.from(container.querySelectorAll("[data-quick-add-panel]"));
      const save = document.getElementById("quick-add-save");

      const setActive = (kind) => {
        container.dataset.active = kind;
        tabs.forEach((t) => {
          const active = t.dataset.quickAddTab === kind;
          t.classList.toggle("active", active);
          t.setAttribute("aria-selected", String(active));
        });
        panels.forEach((p) => p.classList.toggle("is-active", p.dataset.quickAddPanel === kind));
        if (save) save.setAttribute("form", kind === "event" ? "event-form" : "task-form");
      };

      tabs.forEach((t) => {
        t.addEventListener("click", () => setActive(t.dataset.quickAddTab));
      });
      setActive(container.dataset.active || "task");
    },
  };
})();
