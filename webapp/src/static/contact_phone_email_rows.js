(function () {
  let cloneCounter = 0;

  function rewriteClonedTypePicker(root) {
    // A row can hold several pickers (a pending transaction has Type and two Accounts): each proxy and its own radios get a token.
    root.querySelectorAll(".contact-type-proxy").forEach(function (proxy) {
      cloneCounter += 1;
      const base = proxy.getAttribute("name"); // e.g. "phone_type" -- the real submitted field name, never rewritten
      const token = "c" + cloneCounter;
      const oldId = proxy.id;
      const proxyId = base + "-proxy-" + token;
      proxy.id = proxyId;
      root.querySelectorAll(".contact-type-radio").forEach(function (radio) {
        if (radio.dataset.proxyTarget !== oldId) return;
        radio.name = (radio.dataset.proxyName || base) + "__" + token;
        radio.dataset.proxyTarget = proxyId;
      });
    });
  }

  function wireContainer(container) {
    if (container.dataset.ccWired) return;
    container.dataset.ccWired = "1";

    container.addEventListener("click", function (e) {
      const addBtn = e.target.closest("[data-repeatable-add]");
      if (addBtn) {
        e.preventDefault();
        const rows = document.getElementById(addBtn.getAttribute("data-repeatable-add"));
        const tmpl = document.getElementById(addBtn.getAttribute("data-repeatable-template"));
        if (rows && tmpl && tmpl.content) {
          const clone = tmpl.content.cloneNode(true);
          rewriteClonedTypePicker(clone);
          rows.appendChild(clone);
          const newInput = rows.lastElementChild ? rows.lastElementChild.querySelector("input") : null;
          if (newInput) newInput.focus();
        }
        return;
      }
      const removeBtn = e.target.closest("[data-repeatable-remove]");
      if (removeBtn) {
        e.preventDefault();
        const row = removeBtn.closest(".contact-multi-row, [data-repeatable-row]");
        if (row) row.remove();
      }
    });
  }

  // Delegated at document level (same reasoning as static/app.js's own
  // multiselect handling) so it works for both server-rendered rows and
  // rows added later via the clone path above, and keeps working after a
  // radio's own panel gets portaled out to #multiselect-portal mid-pick.
  document.addEventListener("change", function (e) {
    if (!e.target.matches || !e.target.matches(".contact-type-radio")) return;
    const targetId = e.target.dataset.proxyTarget;
    const proxy = targetId ? document.getElementById(targetId) : null;
    if (proxy) proxy.value = e.target.value;
  });

  function init(root) {
    (root || document).querySelectorAll("[data-repeatable-rows-scope]").forEach(wireContainer);
  }

  window.CCContactPhoneEmailRows = { init };
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
  });
})();
