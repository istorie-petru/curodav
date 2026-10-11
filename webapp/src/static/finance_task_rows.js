// Pending transactions rows in the task edit form (templates/_task_transactions.html): a row added from the template
// gets its own key so each Tags dropdown posts under its own name, and the Type choice decides which accounts the
// row asks for.
(function () {
  let counter = 0;

  function rekey(row) {
    counter += 1;
    const token = "n" + counter;
    row.querySelectorAll("*").forEach(function (el) {
      ["name", "id", "for", "data-ms-name"].forEach(function (attr) {
        const value = el.getAttribute(attr);
        if (value && value.indexOf("tmpl") !== -1) el.setAttribute(attr, value.replace(/tmpl/g, token));
      });
    });
    const key = row.querySelector('input[name="pt_key"]');
    if (key) key.value = token;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const rows = document.getElementById("pending-tx-rows");
    if (!rows) return;
    new MutationObserver(function (changes) {
      changes.forEach(function (change) {
        change.addedNodes.forEach(function (node) {
          if (node.nodeType === 1 && node.matches(".pending-tx-edit")) rekey(node);
        });
      });
    }).observe(rows, { childList: true });
  });

  document.addEventListener("change", function (e) {
    const radio = e.target;
    if (!radio.matches || !radio.matches(".contact-type-radio") || radio.dataset.proxyName !== "pt_type") return;
    const proxy = document.getElementById(radio.dataset.proxyTarget);
    const row = proxy && proxy.closest(".pending-tx-edit");
    if (row) row.dataset.type = radio.value.toLowerCase();
  });
})();
