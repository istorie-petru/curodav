// New note modal (templates/notebook_new_modal.html): choosing a template swaps in that template's
// frontmatter inputs without reopening the modal, so the typed title is kept.
(function () {
  document.addEventListener("change", async function (e) {
    if (!e.target.matches || !e.target.matches('input[name="template_uid"]')) return;
    const form = e.target.form;
    const slot = document.getElementById("notebook-new-fields");
    if (!form || !slot || !form.dataset.fieldsUrl) return;
    const res = await fetch(form.dataset.fieldsUrl + "?template=" + encodeURIComponent(e.target.value));
    if (res.ok) slot.innerHTML = await res.text();
  });
})();
