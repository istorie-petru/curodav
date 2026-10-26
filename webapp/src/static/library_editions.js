// The book window's edition half (citation_edit_modal.html): choosing an edition fills the edition fields from the data
// the page carries; "Provided as" shows the link box or the PDF drop slot.
(function () {
  function root(el) {
    return el.closest && el.closest("form") && el.closest("form").querySelector("[data-library-editions]");
  }

  function setField(scope, name, value) {
    var input = scope.querySelector('[name="' + name + '"]');
    if (input) input.value = value || "";
  }

  function showSource(scope, source) {
    scope.querySelector("[data-edition-link]").hidden = source !== "link";
    scope.querySelector("[data-edition-file]").hidden = source !== "local";
  }

  function pickSource(scope, source) {
    var form = scope.closest("form");
    var radio = form.querySelector('input[name="ed_source"][value="' + source + '"]');
    if (!radio) return;
    radio.checked = true;
    radio.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillEdition(scope, uid) {
    var editions = JSON.parse(scope.dataset.editions || "[]");
    var e = editions.find(function (x) { return x.uid === uid; }) || {};
    ["edition", "year", "publisher", "place", "isbn", "doi", "url"].forEach(function (k) { setField(scope, "ed_" + k, e[k]); });
    var file = scope.querySelector('input[type="file"]');
    if (file) file.value = "";
    var zone = scope.querySelector(".upload-zone-label");
    if (zone) zone.textContent = e.source === "local" ? "Replace the PDF" : "Choose or drop a PDF";
    var state = scope.querySelector("[data-edition-file-state]");
    if (state) {
      state.textContent = "";
      if (e.source === "local" && e.file_state === "ok") {
        var a = document.createElement("a");
        a.href = "/library/editions/" + e.uid + "/file";
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = e.file_label;
        state.append("Stored: ", a);
      } else if (e.source === "local") {
        state.textContent = 'The stored PDF "' + e.file_label + '" is missing from the disk. Drop it again to restore it.';
      }
    }
    var del = scope.querySelector("[data-edition-delete]");
    if (del) {
      del.hidden = !e.uid;
      var box = del.querySelector("input");
      if (box) box.checked = false;
    }
    pickSource(scope, e.source || "none");
  }

  document.addEventListener("change", function (ev) {
    var t = ev.target;
    if (!t.matches) return;
    if (t.matches('input[name="edition_uid"]')) {
      var scope = root(t);
      if (scope) fillEdition(scope, t.value);
    } else if (t.matches('input[name="ed_source"]')) {
      var scope2 = root(t);
      if (scope2) showSource(scope2, t.value);
    } else if (t.matches(".edition-file-input")) {
      var label = t.closest(".upload-zone").querySelector(".upload-zone-label");
      if (label && t.files && t.files.length) label.textContent = t.files[0].name;
    }
  });
})();
