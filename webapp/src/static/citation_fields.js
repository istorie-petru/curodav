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
    relabel(form, type);
  }

  // Status words follow the kind (To watch, Watching, Watched), and the progress row names its unit.
  function relabel(form, type) {
    var verbs = JSON.parse(form.dataset.statusVerbs || "{}");
    var labels = JSON.parse(form.dataset.verbLabels || "{}")[verbs[type] || "read"];
    var keys = ["planned", "current", "paused", "finished", "dropped"];
    if (labels) {
      document.querySelectorAll('input[name="status"][form="citation-form"]').forEach(function (radio) {
        var i = keys.indexOf(radio.value);
        var span = radio.parentNode.querySelector("span");
        if (i >= 0 && span) span.textContent = labels[i];
        if (radio.checked) {
          var summary = radio.closest("[data-ms]").querySelector(".ms-summary");
          if (summary && span) summary.textContent = span.textContent;
        }
      });
    }
    var unit = JSON.parse(form.dataset.unitLabels || "{}")[type];
    form.querySelectorAll("[data-unit-label]").forEach(function (label) {
      label.textContent = unit && unit !== "None" ? unit : "Progress";
    });
  }

  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches('input[name="type"]')) apply();
  });
  document.addEventListener("cc-modal-content", apply);
  apply();
})();
