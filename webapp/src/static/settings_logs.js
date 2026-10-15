// Live log view: polls the entries the app keeps in memory and appends the new ones at the chosen level.
(function () {
  const view = document.getElementById("log-view");
  if (!view) return;
  const lines = document.getElementById("log-lines");
  const empty = document.getElementById("log-empty");
  let level = "important";
  let after = 0;
  let timer = null;

  function lineFor(entry) {
    const row = document.createElement("div");
    row.className = "log-line is-" + entry.level;
    const when = new Date(entry.time * 1000).toLocaleTimeString([], { hour12: false });
    row.textContent = `${when}  ${entry.level.toUpperCase().padEnd(8)}${entry.component}  ${entry.message}`;
    return row;
  }

  async function poll() {
    try {
      const resp = await fetch(`/settings/logs/entries?level=${encodeURIComponent(level)}&after=${after}`);
      if (!resp.ok) throw new Error("log fetch failed");
      const entries = await resp.json();
      const atBottom = lines.scrollHeight - lines.scrollTop - lines.clientHeight < 40;
      entries.forEach((entry) => {
        lines.appendChild(lineFor(entry));
        after = Math.max(after, entry.id);
      });
      while (lines.children.length > 1000) lines.removeChild(lines.firstChild);
      empty.hidden = lines.children.length > 0;
      if (atBottom) lines.scrollTop = lines.scrollHeight;
    } catch (err) {
      window.ccToast({ message: "Could not load the log", variant: "error" });
      clearInterval(timer);
      timer = null;
    }
  }

  view.addEventListener("click", (e) => {
    const button = e.target.closest("[data-log-level]");
    if (!button) return;
    level = button.dataset.logLevel;
    view.querySelectorAll("[data-log-level]").forEach((b) => b.classList.toggle("active", b === button));
    lines.replaceChildren();
    after = 0;
    poll();
  });

  poll();
  timer = setInterval(poll, 2000);
})();
