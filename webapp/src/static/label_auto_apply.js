// Picking a project in an item's modal also checks that project's auto
// labels in the Labels field, with no refresh. Add only: nothing is removed.
(function () {
  document.addEventListener("change", async (e) => {
    const radio = e.target;
    if (!(radio instanceof HTMLInputElement) || radio.type !== "radio" || radio.name !== "project" || !radio.value) return;
    let names = [];
    try {
      const resp = await fetch("/settings/labels/" + encodeURIComponent(radio.value) + "/auto-labels");
      if (!resp.ok) return;
      names = await resp.json();
    } catch (err) {
      return;
    }
    const scope = radio.form || radio.closest("form") || document;
    names.forEach((name) => {
      const box = Array.from(scope.querySelectorAll('input[name="tags_labels"]')).find((i) => i.value === name);
      if (box && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  });
})();
