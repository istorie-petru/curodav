// Notes page listener (async-CRUD design, features/async-crud.md) --
// every note mutation surface (modal create/edit, form delete) dispatches
// cc-entity-changed; this refreshes the #notes-body region from the server
// instead of a full page reload. Claims the event only when the region is
// actually on this page -- otherwise the mutation's dispatcher falls back
// to a reload (the claim protocol in ccApi).
(function () {
  if (!document.getElementById("notes-body")) return;
  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "note") return;
    detail.claimed = true;
    var url =
      "/notes/regions?region=list" + (window.location.search || "");
    window.ccApi.refreshRegion(url, "notes-body").catch(function () {
      window.location.reload();
    });
  });
})();