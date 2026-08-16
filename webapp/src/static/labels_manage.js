// Labels manage page async-CRUD listener (features/async-crud.md): after a
// label edit/merge (modal forms carry data-cc-change="label", modal.js
// dispatches), re-render the #labels-body region from the server instead
// of a full reload, then re-run the client-side search init on the fresh
// markup. Claims the event only when the region is on this page (the
// ccApi.claimed protocol); refresh failure falls back to a reload.
(function () {
  if (!document.getElementById("labels-body")) return;

  function refresh() {
    return window.ccApi.refreshRegion("/labels/regions?region=list", "labels-body").then(function () {
      if (window.CCLabelSearch) window.CCLabelSearch.init();
    });
  }

  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "label") return;
    detail.claimed = true;
    refresh().catch(function () {
      window.location.reload();
    });
  });
})();