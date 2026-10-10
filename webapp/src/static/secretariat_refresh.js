// Secretariat page: after any task or habit change, re-render the lists
// from the server so a completed item stays put, shown done, for the
// check-off grace period instead of vanishing or staying stale.
(function () {
  let busy = false;

  async function refresh() {
    const region = document.getElementById("sec-region");
    if (!region || busy) return;
    busy = true;
    try {
      const resp = await fetch(window.location.href, { headers: { "X-Requested-With": "fetch" } });
      if (!resp.ok) throw new Error("refresh failed");
      const doc = new DOMParser().parseFromString(await resp.text(), "text/html");
      const fresh = doc.getElementById("sec-region");
      if (fresh) region.replaceWith(fresh);
    } catch (err) {
      window.location.reload();
    } finally {
      busy = false;
    }
  }

  document.addEventListener("cc-entity-changed", refresh);
})();
