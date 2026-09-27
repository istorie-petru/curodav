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

  // 2026-09-27 (Settings > Appearance's Accent color, `show_icon=false` --
  // see _look_picker.html's own comment): a colour-only trigger has no
  // `[data-look-part="icon"]` radios anywhere, checked or not -- this is
  // how sync() tells "no icon picked yet" (iconName === "", still show
  // "· No icon") apart from "there is no icon half of this control at
  // all" (omit the "· ..." entirely, and don't try to recolor a `<use>`
  // that was never rendered into the preview).
  function hasIconPart(triggerId) {
    return !!document.querySelector('input[data-look-for="' + triggerId + '"][data-look-part="icon"]');
  }

  function sync(trigger) {
    const color = checked(trigger.id, "color");
    const preview = trigger.querySelector(".look-preview");
    // 2026-09-27 (Settings > Appearance's Accent color, `dot_var_prefix` --
    // see _look_picker.html's own comment): the swatch/preview colour used
    // to come from a per-colour `habit-c-*` class, always the label/habit
    // palette. Two different palettes now share this one control (the
    // label/habit `--cal-accent-*` vars, or Accent color's own
    // `--accent-preset-*` vars), so the server renders which prefix to use
    // as `data-dot-var-prefix` and this sets the shared `--habit-accent`
    // custom property directly instead of toggling a hardcoded class.
    const prefix = trigger.dataset.dotVarPrefix || "cal-accent-";
    if (color) preview.style.setProperty("--habit-accent", "var(--" + prefix + color + ")");
    else preview.style.removeProperty("--habit-accent");
    const colorText = color ? nice(color) : trigger.dataset.noColor;
    if (!hasIconPart(trigger.id)) {
      trigger.querySelector(".look-name").textContent = colorText;
      return;
    }
    const iconName = checked(trigger.id, "icon");
    const use = preview.querySelector("use");
    if (use) {
      const glyph = iconName || trigger.dataset.defaultIcon || "tag";
      use.setAttribute("href", (use.getAttribute("href") || "").replace(/#icon-[\w-]+$/, "#icon-" + glyph));
    }
    trigger.querySelector(".look-name").textContent = colorText + " · " + (iconName ? nice(iconName) : trigger.dataset.noIcon);
  }

  document.addEventListener("change", (e) => {
    const input = e.target;
    if (!input || !input.dataset || !input.dataset.lookFor) return;
    const trigger = document.getElementById(input.dataset.lookFor);
    if (trigger) sync(trigger);
  });
})();
