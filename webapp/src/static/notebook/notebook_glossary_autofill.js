// Glossary Auto-fill: saves the document, attaches every glossary term found in it, and refreshes the lists.
(function () {
  var busy = false;

  async function flushSave() {
    var editor = window.notebookEditor;
    var mount = document.getElementById("notebook-editor");
    if (!editor || !mount) return;
    var data = await editor.save();
    var resp = await fetch(mount.getAttribute("data-content-url"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error("save failed");
  }

  document.addEventListener("click", async function (e) {
    var btn = e.target.closest("[data-glossary-autofill]");
    if (!btn || busy) return;
    busy = true;
    var uid = btn.getAttribute("data-glossary-autofill");
    try {
      await flushSave();
      var resp = await fetch("/notebook/" + uid + "/glossary/autofill", { method: "POST", headers: { "X-Requested-With": "fetch" } });
      if (!resp.ok) throw new Error("autofill failed");
      var result = await resp.json();
      var html = await (await fetch("/notebook/" + uid + "/glossary/list")).text();
      document.querySelectorAll("[data-glossary-list]").forEach(function (el) {
        var box = document.createElement("div");
        box.innerHTML = html;
        el.replaceWith(box.firstElementChild);
      });
      var n = result.added.length;
      var message = n ? "Added " + n + " term" + (n === 1 ? "" : "s") + (result.restored ? " (" + result.restored + " you had removed)" : "") : "No new terms found in this document";
      window.ccToast({ message: message });
    } catch (err) {
      window.ccToast({ message: "Could not auto-fill the glossary.", variant: "error" });
    } finally {
      busy = false;
    }
  });
})();
