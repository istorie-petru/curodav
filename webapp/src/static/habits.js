// Habits pages listener (async-CRUD design, features/async-crud.md):
//   * cc-entity-changed (habit) -> refresh this page's own region
//     (#habits-body on /habits, #habit-detail-body on /habits/{uid}) from
//     the server instead of a full reload. Claims the event only when a
//     region is actually on this page (the claim protocol in ccApi).
//   * Plain-page forms on the habits pages -- the archive/unarchive
//     buttons, the backfill ("Log entry") form, and the heatmap cells
//     (data-cc-change="habit" or .heatmap-cell-form with a /habits/ action)
//     -- submit through ccApi.post + the change event instead of the
//     native 303 redirect, so the region above re-renders. Forms already
//     handled by another handler (modal.js's own submit path, app.js's
//     delete/undo handlers) arrive with defaultPrevented set and are
//     skipped.
(function () {
  var regionEl = document.getElementById("habits-body") || document.getElementById("habit-detail-body");
  if (!regionEl) return;
  var isDetail = !!document.getElementById("habit-detail-body");
  var regionUrl = isDetail
    ? "/habits/regions?region=detail&uid=" + encodeURIComponent(regionEl.dataset.uid || "")
    : "/habits/regions?region=list";

  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "habit") return;
    detail.claimed = true;
    window.ccApi.refreshRegion(regionUrl, regionEl.id).catch(function () {
      window.location.reload();
    });
  });

  function submitAsync(form) {
    var btn = form.querySelector("button[type='submit']");
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-loading");
    }
    window.ccApi
      .post(form.action, form)
      .then(function () {
        window.ccApi.dispatchChange({
          type: form.getAttribute("data-cc-change") || "habit",
          action: form.getAttribute("data-cc-action") || "checkin",
        });
      })
      .catch(function (err) {
        window.ccToast({ message: err.message || "Could not save.", variant: "error" });
      })
      .finally(function () {
        if (btn) {
          btn.disabled = false;
          btn.classList.remove("is-loading");
        }
      });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.matches) return;
    if (e.defaultPrevented) return;
    if (form.closest && form.closest("#modal-overlay")) return;
    var isHeatmapCell = form.matches(".heatmap-cell-form") && String(form.action || "").indexOf("/habits/") !== -1;
    if (!isHeatmapCell && !form.matches("[data-cc-change]")) return;
    e.preventDefault();
    submitAsync(form);
  });
})();