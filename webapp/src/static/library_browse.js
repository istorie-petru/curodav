/* The Library page shows as many entries as fit the window, without a scrollbar, and the pager under them swaps pages in place. */
(function () {
  var box = document.getElementById("library-results");
  if (!box) return;
  var timer = 0;
  var loading = false;

  function results() {
    return document.getElementById("library-results");
  }

  function query(offset, limit) {
    var params = new URLSearchParams(window.location.search);
    ["offset", "limit", "fragment"].forEach(function (k) { params.delete(k); });
    params.set("offset", String(offset));
    params.set("limit", String(limit));
    return params;
  }

  function load(offset, limit) {
    if (loading) return;
    loading = true;
    var params = query(offset, limit);
    params.set("fragment", "1");
    fetch("/library?" + params.toString(), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var holder = document.createElement("div");
        holder.innerHTML = html;
        var fresh = holder.querySelector("#library-results");
        if (fresh) results().replaceWith(fresh);
        var shown = query(offset, limit);
        shown.delete("limit");
        if (!offset) shown.delete("offset");
        var qs = shown.toString();
        history.replaceState(null, "", "/library" + (qs ? "?" + qs : ""));
      })
      .finally(function () { loading = false; });
  }

  // How many entries fit between the top of the list and the bottom of the window, leaving room for the pager.
  function capacity() {
    var el = results();
    var layout = el.dataset.layout;
    var top = el.getBoundingClientRect().top;
    var bar = document.querySelector(".mobile-tabbar");
    var below = bar && bar.offsetParent ? bar.offsetHeight : 0;
    var main = el.closest("main");
    var pad = main ? parseFloat(getComputedStyle(main).paddingBottom) || 0 : 0;
    var pager = el.querySelector(".library-pager");
    var room = window.innerHeight - top - below - pad - (pager ? pager.offsetHeight : 44) - 6;
    if (layout === "grid") {
      var cards = el.querySelectorAll(".media-card");
      if (!cards.length) return 0;
      var first = cards[0];
      var perRow = 0;
      for (var i = 0; i < cards.length && cards[i].offsetTop === first.offsetTop; i++) perRow++;
      var grid = el.querySelector(".media-grid");
      var gap = parseFloat(getComputedStyle(grid).rowGap) || 12;
      var cardRows = Math.max(1, Math.floor((room + gap) / (first.offsetHeight + gap)));
      return Math.max(perRow, perRow * cardRows);
    }
    var rows = el.querySelectorAll("tbody tr");
    var head = el.querySelector("thead");
    if (!rows.length) return 0;
    var tallest = 0;
    rows.forEach(function (r) { tallest = Math.max(tallest, r.offsetHeight); });
    return Math.max(4, Math.floor((room - (head ? head.offsetHeight : 0) - 8) / tallest));
  }

  function fit() {
    var el = results();
    var n = capacity();
    if (!n) return;
    var limit = Number(el.dataset.limit);
    var total = Number(el.dataset.total);
    var cookie = "library_per_page_" + el.dataset.layout;
    document.cookie = cookie + "=" + n + "; path=/library; max-age=31536000; samesite=lax";
    if (n === limit) return;
    if (n > limit && limit >= total) return;
    var offset = Math.floor(Number(el.dataset.offset) / n) * n;
    load(offset, n);
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-library-page]");
    if (!btn || btn.disabled) return;
    var el = results();
    var limit = Number(el.dataset.limit);
    var offset = Number(el.dataset.offset) + (btn.dataset.libraryPage === "next" ? limit : -limit);
    load(Math.max(0, offset), limit);
  });

  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(fit, 250);
  });
  if (document.readyState === "complete") fit();
  else window.addEventListener("load", fit);
})();
