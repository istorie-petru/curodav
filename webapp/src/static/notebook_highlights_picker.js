/* The Notebook's book highlights window: the list follows the search and filters, and choosing a highlight hands it to the Quote block. */
(function () {
  var timer = 0;

  function form() {
    return document.getElementById("highlights-filters-form");
  }

  function refresh() {
    var f = form();
    var box = document.getElementById("highlights-list");
    if (!f || !box) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      var query = new URLSearchParams(new FormData(f)).toString();
      fetch(box.dataset.listUrl + (query ? "?" + query : ""), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { box.innerHTML = html; });
    }, 200);
  }

  document.addEventListener("input", function (e) {
    if (e.target.form && e.target.form.id === "highlights-filters-form") refresh();
  });
  document.addEventListener("change", function (e) {
    if (e.target.form && e.target.form.id === "highlights-filters-form") refresh();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.form && e.target.form.id === "highlights-filters-form") e.preventDefault();
  });

  document.addEventListener("click", function (e) {
    var item = e.target.closest && e.target.closest("[data-highlight-pick]");
    if (!item) return;
    document.dispatchEvent(new CustomEvent("cc-highlight-picked", {
      detail: { quote: item.dataset.quote, citation: item.dataset.citation, citationUid: item.dataset.citationUid, color: item.dataset.color },
    }));
    if (window.CCModal) window.CCModal.close();
  });
})();
