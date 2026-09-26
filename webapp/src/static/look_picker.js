// The "Look" dropdown's trigger sync (templates/_look_picker.html,
// 2026-09-26). Picking a colour or an icon in the panel updates the
// trigger's preview (icon on a circle of the colour) and its "Colour ·
// Icon" text. Delegated on the document: the dropdown arrives inside a
// modal after this script loaded, and its panel is portaled out of the
// form while open (static/app.js), so each radio names its trigger via
// data-look-for instead of relying on the DOM tree.
(function () {
  const nice = (v) => v.charAt(0).toUpperCase() + v.slice(1).replace(/-/g, " ");

  function checked(triggerId, part) {
    const r = document.querySelector('input[data-look-for="' + triggerId + '"][data-look-part="' + part + '"]:checked');
    return r ? r.value : "";
  }

  function sync(trigger) {
    const color = checked(trigger.id, "color");
    const iconName = checked(trigger.id, "icon");
    const preview = trigger.querySelector(".look-preview");
    preview.className = "look-preview" + (color ? " habit-c-" + color : "");
    const use = preview.querySelector("use");
    if (use) {
      const glyph = iconName || trigger.dataset.defaultIcon || "tag";
      use.setAttribute("href", (use.getAttribute("href") || "").replace(/#icon-[\w-]+$/, "#icon-" + glyph));
    }
    trigger.querySelector(".look-name").textContent =
      (color ? nice(color) : trigger.dataset.noColor) + " · " + (iconName ? nice(iconName) : trigger.dataset.noIcon);
  }

  document.addEventListener("change", (e) => {
    const input = e.target;
    if (!input || !input.dataset || !input.dataset.lookFor) return;
    const trigger = document.getElementById(input.dataset.lookFor);
    if (trigger) sync(trigger);
  });
})();
