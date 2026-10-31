(function () {
  const nice = (v) => v.charAt(0).toUpperCase() + v.slice(1).replace(/-/g, " ");

  function checked(triggerId, part) {
    if (part === "icon") {
      const h = document.querySelector('input[type="hidden"][data-look-for="' + triggerId + '"][data-look-part="icon"]');
      return h ? h.value : "";
    }
    const r = document.querySelector('input[data-look-for="' + triggerId + '"][data-look-part="' + part + '"]:checked');
    return r ? r.value : "";
  }

  function hasIconPart(triggerId) {
    return !!document.querySelector('input[data-look-for="' + triggerId + '"][data-look-part="icon"]');
  }

  function sync(trigger) {
    const color = checked(trigger.id, "color");
    const preview = trigger.querySelector(".look-preview");
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

  let library = null;
  function loadLibrary() {
    if (!library) {
      library = fetch(document.querySelector("script[data-categories-src]")?.dataset.categoriesSrc || "/static/icons/lucide-categories.json")
        .then((r) => (r.ok ? r.json() : { categories: [] }))
        .catch(() => ({ categories: [] }));
    }
    return library;
  }

  const svg = (name) => '<svg class="icon" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';

  function hiddenInput(id) {
    return document.querySelector('input[data-look-for="' + id + '"][data-look-part="icon"]');
  }

  function paintGrid(pane) {
    const id = pane.dataset.lookPanelFor;
    const picked = hiddenInput(id).value;
    const query = pane.querySelector(".look-icon-search").value.trim().toLowerCase();
    let names = pane._cats[pane._active] || [];
    if (query) names = Object.keys(pane._all).filter((n) => n.includes(query.replace(/\s+/g, "-")));
    const noIcon = !query && pane._active === "suggested"
      ? '<button type="button" class="look-icon' + (picked ? "" : " is-selected") + '" data-icon="" tabindex="-1" title="' + pane.dataset.noIcon + '" aria-label="' + pane.dataset.noIcon + '">' + svg(pane.dataset.defaultIcon) + "</button>"
      : "";
    pane.querySelector(".look-icon-grid").innerHTML = noIcon + names.map((n) =>
      '<button type="button" class="look-icon' + (n === picked ? " is-selected" : "") + '" data-icon="' + n + '" tabindex="-1" title="' + nice(n) + '" aria-label="' + nice(n) + '">' + svg(n) + "</button>").join("");
    // One Tab stop for the whole grid (the picked icon, else the first); the arrows move inside it.
    const stop = pane.querySelector(".look-icon.is-selected") || pane.querySelector(".look-icon");
    if (stop) stop.tabIndex = 0;
  }

  function paintCats(pane) {
    pane.querySelector(".look-cats").innerHTML = pane._titles.map(([key, title]) =>
      '<button type="button" class="look-cat' + (key === pane._active && !pane.querySelector(".look-icon-search").value ? " is-active" : "") + '" data-cat="' + key + '" tabindex="' + (key === pane._active ? "0" : "-1") + '">' + title + "</button>").join("");
  }

  function buildPane(pane) {
    if (pane._built) return;
    pane._built = true;
    loadLibrary().then((data) => {
      const curated = pane.dataset.curated ? pane.dataset.curated.split(",") : [];
      pane._cats = { suggested: curated };
      pane._titles = curated.length ? [["suggested", "Suggested"]] : [];
      pane._all = {};
      data.categories.forEach((c) => {
        pane._cats[c.key] = c.icons;
        pane._titles.push([c.key, c.title]);
        c.icons.forEach((n) => { pane._all[n] = true; });
      });
      curated.forEach((n) => { pane._all[n] = true; });
      const picked = hiddenInput(pane.dataset.lookPanelFor).value;
      const home = data.categories.find((c) => c.icons.includes(picked));
      pane._active = curated.length ? "suggested" : (home ? home.key : (data.categories[0] || {}).key);
      if (picked && curated.length && !curated.includes(picked) && home) pane._active = home.key;
      paintCats(pane);
      paintGrid(pane);
      const sel = pane.querySelector(".look-icon.is-selected");
      if (sel) sel.scrollIntoView({ block: "nearest" });
    });
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest && e.target.closest(".look-trigger");
    if (trigger) {
      const pane = document.querySelector('.look-icons-pane[data-look-panel-for="' + trigger.id + '"]');
      if (pane) buildPane(pane);
      return;
    }
    const cat = e.target.closest && e.target.closest(".look-cat");
    if (cat) {
      const pane = cat.closest(".look-icons-pane");
      pane._active = cat.dataset.cat;
      pane.querySelector(".look-icon-search").value = "";
      paintCats(pane);
      paintGrid(pane);
      pane.querySelector(".look-icon-grid").scrollTop = 0;
      if (e.detail === 0) pane.querySelector('.look-cat[tabindex="0"]')?.focus();
      return;
    }
    const cell = e.target.closest && e.target.closest(".look-icon");
    if (cell) {
      const pane = cell.closest(".look-icons-pane");
      const input = hiddenInput(pane.dataset.lookPanelFor);
      input.value = cell.dataset.icon;
      pane.querySelectorAll(".look-icon.is-selected").forEach((b) => b.classList.remove("is-selected"));
      cell.classList.add("is-selected");
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });

  document.addEventListener("input", (e) => {
    if (!e.target.matches || !e.target.matches(".look-icon-search")) return;
    const pane = e.target.closest(".look-icons-pane");
    if (!pane._built) return;
    paintCats(pane);
    paintGrid(pane);
  });

  // The category list is one Tab stop; Up and Down move through it and Enter opens one.
  document.addEventListener("keydown", (e) => {
    const cat = e.target.closest && e.target.closest(".look-cat");
    if (!cat || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    e.stopPropagation();
    const next = e.key === "ArrowDown" ? cat.nextElementSibling : cat.previousElementSibling;
    if (!next) return;
    cat.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
  }, true);

  // Arrows move through the icon grid by cell and by row.
  document.addEventListener("keydown", (e) => {
    const cell = e.target.closest && e.target.closest(".look-icon");
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (!cell || !(step || e.key === "ArrowUp" || e.key === "ArrowDown")) return;
    e.preventDefault();
    e.stopPropagation();
    const cells = Array.from(cell.parentElement.querySelectorAll(".look-icon"));
    const i = cells.indexOf(cell);
    const perRow = Math.max(1, cells.filter((c) => c.offsetTop === cells[0].offsetTop).length);
    const target = cells[i + (step || (e.key === "ArrowDown" ? perRow : -perRow))];
    if (!target) return;
    cell.tabIndex = -1;
    target.tabIndex = 0;
    target.focus();
  }, true);

  // Enter in the search box must not submit the form behind the panel.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches && e.target.matches(".look-icon-search")) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  document.addEventListener("change", (e) => {
    const input = e.target;
    if (!input || !input.dataset || !input.dataset.lookFor) return;
    const trigger = document.getElementById(input.dataset.lookFor);
    if (trigger) sync(trigger);
  });
})();
