// Search contents: preview what a replace would touch, then replace only in the ticked documents.
(function () {
  function root(from) {
    return from.closest("[data-notebook-find]");
  }

  function params(scope, extra) {
    var data = new URLSearchParams();
    data.set("q", scope.querySelector('[name="q"]').value);
    if (extra) data.set("replacement", scope.querySelector('[name="replacement"]').value);
    ["case", "whole"].forEach(function (name) {
      data.set(name, scope.querySelector('[name="' + name + '"]').checked ? "true" : "false");
    });
    return data;
  }

  async function preview(scope) {
    var resp = await fetch("/notebook/find/preview?" + params(scope).toString());
    scope.querySelector("[data-find-results]").innerHTML = await resp.text();
    scope.querySelector("[data-find-apply]").disabled = !scope.querySelector("[data-find-hits]");
  }

  async function apply(scope) {
    var data = params(scope, true);
    scope.querySelectorAll('[data-find-hits] input[name="uids"]:checked').forEach(function (box) {
      data.append("uids", box.value);
    });
    if (!data.getAll("uids").length) {
      window.ccToast({ message: "Tick at least one document.", variant: "error" });
      return;
    }
    var resp = await fetch("/notebook/find/replace", { method: "POST", headers: { "X-Requested-With": "fetch" }, body: data });
    if (!resp.ok) {
      window.ccToast({ message: "Could not replace.", variant: "error" });
      return;
    }
    var result = await resp.json();
    var s = result.documents === 1 ? "" : "s";
    var message = "Replaced " + result.replacements + " in " + result.documents + " document" + s;
    if (result.warn) window.ccToast({ message: message + ". Open them to check the changes.", variant: "warning" });
    else window.ccToast({ message: message });
    await preview(scope);
  }

  document.addEventListener("click", function (e) {
    var previewBtn = e.target.closest("[data-find-preview]");
    if (previewBtn) preview(root(previewBtn));
    var applyBtn = e.target.closest("[data-find-apply]");
    if (applyBtn && !applyBtn.disabled) apply(root(applyBtn));
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !e.target.matches("[data-notebook-find] input[type=text]")) return;
    e.preventDefault();
    preview(root(e.target));
  });

  document.addEventListener("input", function (e) {
    var scope = e.target.closest && e.target.closest("[data-notebook-find]");
    if (scope) scope.querySelector("[data-find-apply]").disabled = true;
  });
})();
