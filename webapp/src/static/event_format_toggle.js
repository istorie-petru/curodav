(function () {
  function init(root) {
    (root || document).querySelectorAll(".event-format-segmented").forEach((segmented) => {
      if (segmented.dataset.ccWired) return;
      segmented.dataset.ccWired = "1";

      const form = segmented.closest("form");
      if (!form) return;

      segmented.querySelectorAll('input[type="radio"]').forEach((radio) => {
        radio.addEventListener("change", () => {
          if (!radio.checked) return;
          if (radio.value === "none") {
            ["location", "meeting_url"].forEach((name) => {
              const input = form.querySelector('[name="' + name + '"]');
              if (input) input.value = "";
            });
            return;
          }
          const otherName = radio.value === "in_person" ? "meeting_url" : "location";
          const otherInput = form.querySelector('[name="' + otherName + '"]');
          if (otherInput) otherInput.value = "";
        });
      });
    });
  }

  window.CCEventFormatToggle = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
