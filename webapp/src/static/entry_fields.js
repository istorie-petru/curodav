// The entry form shows the fields of the chosen type, and hides those of the others.
(function () {
  function apply() {
    var form = document.getElementById("glossary-term-form");
    if (!form) return;
    var checked = document.querySelector('input[name="kind"][form="glossary-term-form"]:checked') || form.querySelector('input[name="kind"]:checked');
    var typed = form.querySelector('input[name="kind_new"]');
    var kind = (typed && typed.value.trim()) || (checked ? checked.value : "Term");
    form.querySelectorAll("[data-kind-fields]").forEach(function (group) {
      group.hidden = group.getAttribute("data-kind-fields") !== kind;
    });
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('input[name="kind"], input[name="kind_new"]')) apply();
  });
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches('input[name="kind_new"]')) apply();
  });
  document.addEventListener("cc-modal-content", apply);
  apply();
})();
