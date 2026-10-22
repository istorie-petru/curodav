// New modal (templates/quick_add.html): the right column lists what comes next, or the matches for the search
// box (GET /quick/next). 
(function () {
  let timer = null;
  let controller = null;

  async function load(box) {
    const list = document.getElementById("qa-next-list");
    if (!list) return;
    if (controller) controller.abort();
    controller = new AbortController();
    const end = window.ccBusy ? window.ccBusy.begin() : null;
    try {
      const resp = await fetch("/quick/next?q=" + encodeURIComponent(box.value.trim()), { signal: controller.signal });
      if (resp.ok) list.innerHTML = await resp.text();
      const title = document.getElementById("qa-side-title");
      if (title) title.textContent = box.value.trim() ? "Matches" : "Coming up";
    } catch (err) {
      if (err.name !== "AbortError") list.classList.add("is-stale");
    } finally {
      if (end) end();
    }
  }

  document.addEventListener("input", (e) => {
    const box = e.target;
    if (!box.matches || !box.matches("[data-qa-search]")) return;
    clearTimeout(timer);
    timer = setTimeout(() => load(box), 120);
  });
})();
