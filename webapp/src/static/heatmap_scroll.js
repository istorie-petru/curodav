// Scrolls every GitHub-style heatmap (_habit_heatmap.html's `.heatmap`) to
// its right edge -- 2026-08-29 direct feedback on the DETAIL_WEEKS widening
// fix ("no scrollbar. and the actual entries are a priority"): once a
// heatmap's grid (53 weeks x 14px/column) is wider than the card/modal it
// sits in, `.heatmap{overflow-x:auto}` makes it scrollable, but a fresh
// scroll container starts pinned to its LEFT edge -- the oldest weeks in
// the grid, often mostly blank if the habit/task is newer than the window.
// The most relevant cells (today, and whatever real entries sit near it)
// are always at the RIGHT edge (the grid ends on `today`, per
// habit_heatmap.py's heatmap_weeks/heatmap_range), so a heatmap nobody has
// scrolled yet should default to showing that end, not the empty start of
// the year -- same convention GitHub's own contribution graph uses.
//
// This does NOT replace the container's native scrollbar (still there, and
// styled visible below in style.css rather than left to an OS's auto-hiding
// default) -- it only picks a better initial scroll position. Scrolling
// left is still how you reach the older history.
//
// Exposed as window.CCHeatmapScroll.init(root), same re-init-after-inject
// convention every other per-fragment behavior in this app follows
// (avatar_cropper.js, contact_phone_email_rows.js, etc.) -- static/modal.js
// calls it from wireContent() so both a modal's first open and an in-place
// edit<->view swap re-run it, and the `cc-region-swapped` listener below
// covers the non-modal async-CRUD region refresh path (habits.js's
// #habit-detail-body, the Tasks table's own regions).
(function () {
  function init(root) {
    (root || document).querySelectorAll(".heatmap").forEach(function (el) {
      el.scrollLeft = el.scrollWidth;
    });
  }

  window.CCHeatmapScroll = { init: init };
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("cc-region-swapped", function (e) {
    var id = e.detail && e.detail.id;
    var region = id ? document.getElementById(id) : null;
    init(region || document);
  });
})();
