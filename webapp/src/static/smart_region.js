// Smart refresh for sorted and filtered lists: a click on a `[data-smart-link]` or the submit of a
// `[data-smart-form]` (GET) fetches the same URL and swaps only the `[data-smart-region]` elements (matched by id),
// so scroll, open menus and the rest of the page stay put. `[data-smart-attrs="href"]` elements get just those
// attributes copied. Any failure falls back to a normal navigation.
(function () {
  let controller = null;

  async function refresh(url, fallback) {
    if (controller) controller.abort();
    controller = new AbortController();
    try {
      const resp = await fetch(url, { headers: { "X-Requested-With": "fetch" }, signal: controller.signal });
      if (!resp.ok) throw new Error("refresh failed");
      const next = new DOMParser().parseFromString(await resp.text(), "text/html");
      const regions = document.querySelectorAll("[data-smart-region]");
      let swapped = 0;
      regions.forEach((region) => {
        const fresh = region.id && next.getElementById(region.id);
        if (fresh) {
          region.innerHTML = fresh.innerHTML;
          swapped += 1;
        }
      });
      if (!swapped) throw new Error("no region");
      document.querySelectorAll("[data-smart-attrs]").forEach((el) => {
        const fresh = el.id && next.getElementById(el.id);
        if (!fresh) return;
        el.dataset.smartAttrs.split(",").forEach((attr) => el.setAttribute(attr, fresh.getAttribute(attr) || ""));
      });
      history.replaceState(null, "", url);
      document.dispatchEvent(new CustomEvent("cc-region-refreshed"));
    } catch (err) {
      if (err.name === "AbortError") return;
      fallback();
    }
  }

  document.addEventListener("click", function (e) {
    const link = e.target.closest("a[data-smart-link]");
    if (!link || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    e.preventDefault();
    refresh(link.href, () => { window.location.href = link.href; });
  });

  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (!form.matches || !form.matches("form[data-smart-form]")) return;
    e.preventDefault();
    const params = new URLSearchParams(new FormData(form));
    const url = new URL(form.getAttribute("action") || window.location.pathname, window.location.href);
    url.search = params.toString();
    refresh(url.toString(), () => { window.location.href = url.toString(); });
  });
})();
