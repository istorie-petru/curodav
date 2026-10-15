// The citation form shows only the fields that apply to the chosen type, and names the container field to fit.
(function () {
  function typeOf(form) {
    var checked = document.querySelector('input[name="type"][form="citation-form"]:checked') || form.querySelector('input[name="type"]:checked');
    return checked ? checked.value : "book";
  }

  function apply() {
    var form = document.getElementById("citation-form");
    if (!form) return;
    var type = typeOf(form);
    form.querySelectorAll("[data-cite-types]").forEach(function (field) {
      field.hidden = field.getAttribute("data-cite-types").split(" ").indexOf(type) === -1;
      var labels = field.getAttribute("data-cite-labels");
      if (labels) {
        labels.split(";").forEach(function (pair) {
          var kv = pair.split(":");
          if (kv[0] === type) field.querySelector("label").textContent = kv[1];
        });
      }
    });
  }

  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('input[name="type"]')) apply();
  });
  document.addEventListener("cc-modal-content", apply);
  apply();
})();
