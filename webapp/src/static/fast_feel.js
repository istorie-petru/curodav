// Fast-feel helpers. ccPrefetch fetches a modal's HTML when a pointer hovers or touches its trigger, so the click
// has the page waiting. ccBusy shows a thin progress bar, but only for waits longer than 150 ms so quick
// responses never flash. Cached pages live for 10 s and are dropped on any change or form submit.
(function () {
  const TTL = 10000;
  const HOVER_DELAY = 65;
  const BUSY_DELAY = 150;
  const SKIP = /\/(logout|download|export)|\.md(\?|$)/i;
  const cache = new Map();
  let hoverTimer = null;

  function sameOriginPath(url) {
    try {
      const u = new URL(url, window.location.href);
      return u.origin === window.location.origin ? u.pathname + u.search : null;
    } catch (err) {
      return null;
    }
  }

  function save(path) {
    const entry = { at: Date.now(), text: fetch(path).then((resp) => (resp.ok ? resp.text() : Promise.reject(new Error("not ok")))) };
    entry.text.catch(() => cache.delete(path));
    cache.set(path, entry);
    return entry;
  }

  function warm(url) {
    const path = sameOriginPath(url);
    if (!path || SKIP.test(path) || (navigator.connection && navigator.connection.saveData)) return;
    const entry = cache.get(path);
    if (entry && Date.now() - entry.at < TTL) return;
    save(path);
  }

  // The HTML for url: the warmed copy when it is still fresh (used once), otherwise a normal fetch.
  function text(url) {
    const path = sameOriginPath(url);
    const entry = path && cache.get(path);
    if (entry && Date.now() - entry.at < TTL) {
      cache.delete(path);
      return entry.text.catch(() => fetch(url).then((resp) => resp.text()));
    }
    return fetch(url).then((resp) => resp.text());
  }

  function target(el) {
    const trigger = el && el.closest ? el.closest("[data-modal]") : null;
    if (!trigger) return null;
    return trigger.getAttribute("data-modal") || trigger.getAttribute("href");
  }

  document.addEventListener("pointerover", (e) => {
    if (e.pointerType !== "mouse") return;
    const url = target(e.target);
    if (!url) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => warm(url), HOVER_DELAY);
  });
  document.addEventListener("pointerout", (e) => {
    if (e.pointerType === "mouse" && target(e.target)) clearTimeout(hoverTimer);
  });
  document.addEventListener("touchstart", (e) => {
    const url = target(e.target);
    if (url) warm(url);
  }, { passive: true });
  ["cc-entity-changed", "submit"].forEach((name) => document.addEventListener(name, () => cache.clear(), true));

  let bar = null;
  let waiting = 0;
  let showTimer = null;

  function begin() {
    waiting += 1;
    if (waiting === 1) {
      showTimer = setTimeout(() => {
        if (!bar) {
          bar = document.createElement("div");
          bar.className = "cc-progress";
          bar.setAttribute("aria-hidden", "true");
          document.body.appendChild(bar);
        }
        bar.classList.add("is-active");
      }, BUSY_DELAY);
    }
    let done = false;
    return function end() {
      if (done) return;
      done = true;
      waiting = Math.max(0, waiting - 1);
      if (waiting === 0) {
        clearTimeout(showTimer);
        if (bar) bar.classList.remove("is-active");
      }
    };
  }

  window.ccPrefetch = { warm: warm, text: text };
  window.ccBusy = { begin: begin };
})();
