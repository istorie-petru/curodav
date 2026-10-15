(function () {
  document.addEventListener("click", function (e) {
    const row = e.target.closest(".notebook-browse-row");
    if (!row) return;
    if (e.defaultPrevented || e.target.closest("a, button, input, label, .col-select")) return;
    const href = row.getAttribute("data-row-href");
    if (href) window.location.href = href;
  });
})();
