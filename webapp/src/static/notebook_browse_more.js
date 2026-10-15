// Browse page: the Load more button fetches the next page of rows and
// appends it, so the open selection and scroll position stay put.
(function () {
  document.addEventListener("click", async function (e) {
    const btn = e.target.closest("#notebook-load-more");
    if (!btn) return;
    e.preventDefault();
    const url = btn.dataset.rowsUrl + "&offset=" + encodeURIComponent(btn.dataset.nextOffset);
    btn.setAttribute("aria-busy", "true");
    try {
      const resp = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
      if (!resp.ok) throw new Error("load failed");
      const data = await resp.json();
      document.getElementById("notebook-rows").insertAdjacentHTML("beforeend", data.html);
      if (data.has_more) {
        btn.dataset.nextOffset = data.next_offset;
        btn.removeAttribute("aria-busy");
      } else {
        btn.closest(".notebook-load-more").remove();
      }
    } catch (err) {
      btn.removeAttribute("aria-busy");
      window.ccToast({ message: "Could not load more documents.", variant: "error" });
    }
  });
})();
