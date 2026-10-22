(() => {
  // Sidebar "Add new" modal (templates/quick_add.html): every data type has its own form panel, and the
  // type dropdown beside each panel's title switches between them (the dropdown in a panel always shows
  // that panel's own kind). Exposed as window.CCQuickAdd so static/modal.js's wireContent() can re-run
  // it on every injected modal fragment.
  //
  // The change listener lives on `document`, not on the panels: an open dropdown panel is moved out of the modal
  // into #multiselect-portal, so its radios fire `change` outside the panels container.
  const FORM_IDS = { task: "task-form", event: "event-form", contact: "contact-form", label: "label-form", transaction: "finance-transaction-form", note: "notebook-new-form" };

  function setActive(container, kind) {
    container.dataset.active = kind;
    container.querySelectorAll("[data-quick-add-panel]").forEach((p) => p.classList.toggle("is-active", p.dataset.quickAddPanel === kind));
    const save = document.getElementById("quick-add-save");
    if (save) save.setAttribute("form", FORM_IDS[kind] || "task-form");
  }

  function onChange(e) {
    const radio = e.target;
    if (!radio.matches || !radio.matches("input[data-quick-add-tab]") || radio.dataset.restoring) return;
    const container = document.getElementById("quick-add-panels");
    if (!container) return;
    const from = container.dataset.active;
    setActive(container, radio.dataset.quickAddTab);
    // Put the panel just left back on its own kind, so returning to it shows the right label.
    const own = container.querySelector('[data-quick-add-panel="' + from + '"] input[data-quick-add-tab="' + from + '"]');
    if (own && !own.checked) {
      own.dataset.restoring = "1";
      own.checked = true;
      own.dispatchEvent(new Event("change", { bubbles: true }));
      delete own.dataset.restoring;
    }
  }

  function markSearchBoxes() {
    document.querySelectorAll('.quick-add-panel input[name="title"]').forEach((box) => box.setAttribute("data-qa-search", "1"));
  }

  function setKind(kind) {
    const container = document.getElementById("quick-add-panels");
    if (!container) return;
    const from = container.querySelector(".quick-add-panel.is-active input[data-qa-search]");
    const text = from ? from.value : "";
    document.querySelectorAll("[data-qa-kind-btn]").forEach((b) => b.classList.toggle("is-active", b.dataset.qaKindBtn === kind));
    setActive(container, kind);
    const to = container.querySelector(".quick-add-panel.is-active input[data-qa-search]");
    if (to) {
      if (text && !to.value) to.value = text;
      to.focus();
    }
  }

  function onClick(e) {
    const t = e.target.closest && e.target.closest("[data-qa-kind-btn]");
    if (t) setKind(t.dataset.qaKindBtn);
  }

  let bound = false;
  window.CCQuickAdd = {
    onChange,
    init() {
      if (!bound) {
        bound = true;
        document.addEventListener("change", onChange);
        document.addEventListener("click", onClick);
      }
      markSearchBoxes();
      const container = document.getElementById("quick-add-panels");
      if (container) setActive(container, container.dataset.active || "task");
    },
  };
})();
