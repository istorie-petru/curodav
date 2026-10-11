// Loads the full Lucide library (static/icons/lucide-library.svg) into the page as hidden inline symbols named
// `icon-<name>`, next to the app's own inline sprite, so any library icon works through the same `#icon-name`
// reference. Symbols the inline sprite already defines are skipped, so the app's own choices win.
(function () {
  var src = document.currentScript && document.currentScript.dataset.src;
  if (!src) return;
  fetch(src).then(function (resp) { return resp.ok ? resp.text() : ""; }).then(function (text) {
    if (!text) return;
    var doc = new DOMParser().parseFromString(text, "image/svg+xml");
    var host = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    host.setAttribute("aria-hidden", "true");
    host.setAttribute("style", "display:none");
    doc.querySelectorAll("symbol").forEach(function (symbol) {
      var id = "icon-" + symbol.getAttribute("id");
      if (document.getElementById(id)) return;
      var copy = document.importNode(symbol, true);
      copy.setAttribute("id", id);
      host.appendChild(copy);
    });
    document.body.appendChild(host);
  }).catch(function () { /* the inline sprite alone still works */ });
})();
