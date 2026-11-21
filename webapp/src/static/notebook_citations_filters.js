/* The library's search and filter window: the Show link follows the form, and the list on the left follows it too. */
(function () {
  let timer = 0;

  function query(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  function sync(form) {
    const apply = document.getElementById("citations-filters-apply");
    const q = query(form);
    if (apply) apply.setAttribute("href", "/library" + (q ? "?" + q : ""));
    const box = document.getElementById("library-preview");
    if (!box) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      fetch(box.dataset.previewUrl + (q ? "?" + q : ""), { headers: { "X-Requested-With": "fetch" } })
        .then((r) => r.text())
        .then((html) => {
          box.innerHTML = html;
          const total = html.match(/(\d+) more/);
          const shown = (html.match(/<li>/g) || []).length;
          const count = document.getElementById("citations-filters-count");
          if (count) count.textContent = shown ? "Show " + (total ? shown + Number(total[1]) : shown) : "Show";
        });
    }, 200);
  }

  function form() {
    return document.getElementById("citations-filters-form");
  }

  document.addEventListener("change", (e) => {
    const f = e.target.form;
    if (f && f.id === "citations-filters-form") sync(f);
  });

  document.addEventListener("input", (e) => {
    const f = e.target.form;
    if (!f || f.id !== "citations-filters-form") return;
    if (e.target.id === "citations-filter-year-from") {
      const yearTo = document.getElementById("citations-filter-year-to");
      if (yearTo && !yearTo.value && e.target.value) yearTo.value = String(new Date().getFullYear());
    }
    sync(f);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.name === "q" && form() && e.target.form === form()) {
      e.preventDefault();
      window.location.href = "/library?" + query(form());
    }
  });

  new MutationObserver(() => {
    const f = form();
    if (f && !f.dataset.synced) {
      f.dataset.synced = "1";
      sync(f);
    }
  }).observe(document.body, { childList: true, subtree: true });
  if (form()) {
    form().dataset.synced = "1";
    sync(form());
  }
})();
