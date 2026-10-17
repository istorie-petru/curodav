// Entry edit modal: one start/end page row per citation picked in References.
(function () {
  function row(key, name) {
    const uid = key.split(":")[1];
    const el = document.createElement("div");
    el.className = "entry-ref-row";
    el.dataset.key = key;
    el.innerHTML =
      '<span class="entry-ref-name"></span>' +
      '<div class="field"><label>From page</label><input type="text" name="refstart:' + uid + '" form="glossary-term-form"></div>' +
      '<div class="field"><label>To page</label><input type="text" name="refend:' + uid + '" form="glossary-term-form"></div>';
    el.querySelector(".entry-ref-name").textContent = name;
    return el;
  }

  function sync(box) {
    const rows = document.getElementById("entry-reference-rows");
    if (!rows) return;
    const wanted = new Map();
    document.querySelectorAll('input[name="reference_keys"]:checked').forEach((cb) => {
      const label = cb.closest("label");
      wanted.set(cb.value, label ? label.textContent.trim() : cb.value);
    });
    rows.querySelectorAll(".entry-ref-row").forEach((r) => {
      if (!wanted.has(r.dataset.key)) r.remove();
    });
    wanted.forEach((name, key) => {
      if (!rows.querySelector('.entry-ref-row[data-key="' + key + '"]')) rows.appendChild(row(key, name));
    });
  }

  document.addEventListener("change", (e) => {
    if (e.target && e.target.name === "reference_keys") sync(e.target);
  });
})();
