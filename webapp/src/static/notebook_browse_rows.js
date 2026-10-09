// Browse page's full-row click (_notebook_browse_list.html, 2026-10-02) --
// a row can't be a real `<a>` wrapping its own title link and the trailing
// "Edit properties" pencil (`<a>` inside `<a>` is invalid HTML and
// unpredictable to click), so `.notebook-browse-row` carries its target as
// `data-row-href` instead, and this delegated click listener navigates
// there UNLESS the click landed on an element that already does its own
// thing (the title link, the pencil, or anything inside either). Delegated
// on the document (not a per-row listener) -- same reasoning every other
// click-delegate script in this app uses: this page's rows are plain
// server-rendered HTML, never re-rendered client-side, so there's nothing
// to re-wire on navigation/filter changes (each filter pick is a real GET
// reload), but delegation is still the simplest correct way to cover every
// row with one listener instead of one per row.
(function () {
  document.addEventListener("click", function (e) {
    const row = e.target.closest(".notebook-browse-row");
    if (!row) return;
    if (e.target.closest("a, button")) return;
    const href = row.getAttribute("data-row-href");
    if (href) window.location.href = href;
  });
})();
