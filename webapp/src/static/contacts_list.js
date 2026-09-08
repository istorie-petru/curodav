// Contacts page listener (async-CRUD design, features/async-crud.md) --
// every contact mutation surface (modal create/edit, detail delete)
// dispatches cc-entity-changed; this refreshes the #contacts-body region
// from the server instead of a full page reload. Claims the event only
// when the region is actually on this page -- otherwise the mutation's
// dispatcher falls back to a reload (the claim protocol in ccApi).
(function () {
  if (!document.getElementById("contacts-body")) return;
  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "contact") return;
    detail.claimed = true;
    var url =
      "/contacts/regions?region=list" + (window.location.search || "");
    window.ccApi.refreshRegion(url, "contacts-body").catch(function () {
      window.location.reload();
    });
  });
})();