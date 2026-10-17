// Entry edit modal: each reference is one row (citation dropdown, start page, end page); the + button adds a row from the template.
(function () {
  let counter = 0;
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest("[data-entry-ref-add]");
    if (!btn) return;
    e.preventDefault();
    const rows = document.getElementById("entry-reference-rows");
    const tmpl = document.getElementById("entry-reference-template");
    if (!rows || !tmpl) return;
    counter += 1;
    rows.insertAdjacentHTML("beforeend", tmpl.innerHTML.replaceAll("__I__", "n" + Date.now().toString(36) + counter));
  });
  // A web page reference takes an address instead of page numbers; the unused boxes are disabled so they are not submitted.
  document.addEventListener("change", (e) => {
    const radio = e.target;
    if (!radio.matches || !radio.matches('.entry-ref-row input[type="radio"]')) return;
    const row = radio.closest(".entry-ref-row");
    const web = radio.hasAttribute("data-web");
    row.querySelectorAll(".entry-ref-url").forEach((f) => { f.hidden = !web; f.querySelector("input").disabled = !web; });
    row.querySelectorAll(".entry-ref-page").forEach((f) => { f.hidden = web; f.querySelector("input").disabled = web; });
  });
})();
