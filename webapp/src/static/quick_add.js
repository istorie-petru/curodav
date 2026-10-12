(() => {
  // Sidebar "Add new" modal (templates/quick_add.html): every data type has its own form panel, and the
  // type dropdown beside each panel's title switches between them (the dropdown in a panel always shows
  // that panel's own kind). Exposed as window.CCQuickAdd so static/modal.js's wireContent() can re-run
  // it on every injected modal fragment; guarded so a second pass does not bind twice.
  const FORM_IDS = { task: "task-form", event: "event-form", contact: "contact-form", label: "label-form", transaction: "finance-transaction-form", note: "notebook-new-form" };

  window.CCQuickAdd = {
    init() {
      const container = document.getElementById("quick-add-panels");
      if (!container || container.dataset.ready === "1") return;
      container.dataset.ready = "1";
      const panels = Array.from(container.querySelectorAll("[data-quick-add-panel]"));
      const save = document.getElementById("quick-add-save");

      const setActive = (kind) => {
        container.dataset.active = kind;
        panels.forEach((p) => p.classList.toggle("is-active", p.dataset.quickAddPanel === kind));
        if (save) save.setAttribute("form", FORM_IDS[kind] || "task-form");
      };

      container.addEventListener("change", (e) => {
        const radio = e.target;
        if (!radio.matches || !radio.matches("input[data-quick-add-tab]") || radio.dataset.restoring) return;
        const kind = radio.dataset.quickAddTab;
        const from = container.dataset.active;
        setActive(kind);
        // Put the panel just left back on its own kind, so returning to it shows the right label.
        const own = container.querySelector('[data-quick-add-panel="' + from + '"] input[data-quick-add-tab="' + from + '"]');
        if (own && !own.checked) {
          own.dataset.restoring = "1";
          own.checked = true;
          own.dispatchEvent(new Event("change", { bubbles: true }));
          delete own.dataset.restoring;
        }
      });
      setActive(container.dataset.active || "task");
    },
  };
})();
