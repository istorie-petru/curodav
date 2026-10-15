(function () {
  // Classic spreadsheet-column letters (1->A, 26->Z, 27->AA...) -- Paragraph's
  // own numbering style ("uppercase letters (A, B, C...)"), extended past Z
  // the same way Excel/Sheets columns do rather than just wrapping/erroring,
  // in case a document ever has more than 26 Paragraph-level headings.
  function letterize(num) {
    var out = "";
    while (num > 0) {
      var rem = (num - 1) % 26;
      out = String.fromCharCode(65 + rem) + out;
      num = Math.floor((num - 1) / 26);
    }
    return out;
  }

  // Plain roman-numeral conversion -- Part's own numbering style. No
  // upper bound worth guarding (a document with >3999 Parts has bigger
  // problems than this function).
  function romanize(num) {
    var table = [
      [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"],
      [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"],
    ];
    var out = "";
    table.forEach(function (pair) {
      while (num >= pair[0]) {
        out += pair[1];
        num -= pair[0];
      }
    });
    return out;
  }

  // Levels 2/3/4/5 map to h.tagName "H1".."H5". `counters` is mutated in
  // place across the whole document-order walk (same object passed to
  // every call), so each level's own reset rule -- "Section resets when
  // its Chapter changes, Subsection resets when its Section changes" --
  // falls straight out of being called in document order, no separate
  // bookkeeping pass needed. Part, Chapter, and Paragraph are plain
  // document-global counters (the roadmap spec only describes Section and
  // Subsection as "scoped under" a parent; Part/Chapter/Paragraph display
  // only their own number, with no reset rule given for any of them).
  function computeLabel(counters, level) {
    switch (level) {
      case 1:
        counters.part += 1;
        return "Part " + romanize(counters.part);
      case 2:
        counters.chapter += 1;
        counters.section = 0;
        counters.subsection = 0;
        return "Chapter " + counters.chapter;
      case 3:
        counters.section += 1;
        counters.subsection = 0;
        return "Section " + counters.chapter + "." + counters.section;
      case 4:
        counters.subsection += 1;
        return "Subsection " + counters.chapter + "." + counters.section + "." + counters.subsection;
      case 5:
        counters.paragraph += 1;
        return "Paragraph " + letterize(counters.paragraph);
      default:
        return "";
    }
  }

  function renderToc(mount) {
    var nav = document.getElementById("notebook-toc");
    if (!nav) return;
    var headers = mount.querySelectorAll(".ce-header");
    nav.innerHTML = "";
    if (!headers.length) {
      nav.appendChild(window.ccEmptyState("No headings yet"));
      return;
    }
    var counters = { part: 0, chapter: 0, section: 0, subsection: 0, paragraph: 0 };
    headers.forEach(function (h, i) {
      var id = "toc-h-" + i;
      // Only write the id when it's actually changing -- this runs from
      // Editor.js's own onChange, and Editor.js's change detection reacts
      // to mutations inside the block tree, so an unconditional `h.id = id`
      // here mutates the DOM on every render, which re-triggers onChange,
      // which re-renders the Outline, forever (confirmed live: the console
      // fills with "Block «header» skipped because saved data is invalid"
      // in a tight loop). Skipping the write when the id already matches
      // keeps this idempotent.
      if (h.id !== id) h.id = id;
      var level = Number(h.tagName.slice(1));
      var label = computeLabel(counters, level);
      // Same idempotency guard as the id write above, and for the same
      // reason -- this attribute lives on the heading element itself
      // (inside Editor.js's observed redactor), not on a node outside it
      // like the sidebar <a> below.
      if (h.dataset.tocLabel !== label) h.dataset.tocLabel = label;
      // The editing view shows only the number; the word stays in the outline.
      var num = label.replace(/^[A-Za-z]+ /, "");
      if (h.dataset.tocNum !== num) h.dataset.tocNum = num;
      var a = document.createElement("a");
      a.className = "notebook-toc-item";
      a.href = "#" + id;
      a.dataset.level = String(level);
      a.dataset.tocTarget = id;
      a.textContent = label + " — " + (h.textContent || "Untitled heading");
      nav.appendChild(a);
    });
  }

  // Smooth-scroll to the heading instead of a plain hash jump -- keeps
  // the scroll contained to #notebook-editor's own scroll handling rather
  // than depending on the browser's native anchor-jump behavior finding
  // the right nested scroll container, same reasoning
  // notebook_footnotes.js's marker<->footer jump listener uses.
  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-toc-target]");
    if (!link) return;
    e.preventDefault();
    var target = document.getElementById(link.getAttribute("data-toc-target"));
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  window.notebookRenderToc = renderToc;
})();
