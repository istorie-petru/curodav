// Live log view: polls the entries the app keeps in memory and groups
// identical ones into thin cards (title, count, copy). A card opens to the
// full text; the category buttons show exactly that category.
(function () {
  const view = document.getElementById("log-view");
  if (!view) return;
  const lines = document.getElementById("log-lines");
  const empty = document.getElementById("log-empty");
  let level = "important";
  let after = 0;
  let timer = null;
  const cards = new Map();

  function icon(name) {
    return `<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
  }

  function clock(entry) {
    return new Date(entry.time * 1000).toLocaleTimeString([], { hour12: false });
  }

  function fullText(card) {
    return `${card.dataset.last}  ${card.dataset.level.toUpperCase()}  ${card.dataset.component}\n${card.dataset.message}`;
  }

  function build(entry, key) {
    const card = document.createElement("div");
    card.className = "log-card is-" + entry.level;
    card.dataset.key = key;
    card.innerHTML =
      '<div class="log-card-head">' +
      '<button type="button" class="log-card-toggle" aria-expanded="false">' +
      '<span class="log-card-title"></span>' +
      '<span class="log-card-meta"><span class="log-card-component"></span><span class="log-card-time"></span></span>' +
      "</button>" +
      '<span class="log-card-count cell-tag"></span>' +
      '<button type="button" class="icon-btn log-card-copy" title="Copy" aria-label="Copy">' + icon("copy") + "</button>" +
      "</div>" +
      '<pre class="log-card-body" hidden></pre>';
    card.querySelector(".log-card-title").textContent = entry.message.split("\n")[0];
    card.querySelector(".log-card-component").textContent = entry.component;
    card.dataset.level = entry.level;
    card.dataset.component = entry.component;
    card.dataset.message = entry.message;
    card.dataset.count = "0";
    return card;
  }

  function add(entry) {
    const key = entry.level + "|" + entry.component + "|" + entry.message.split("\n")[0];
    let card = cards.get(key);
    if (!card) {
      card = build(entry, key);
      cards.set(key, card);
    }
    card.dataset.count = String(Number(card.dataset.count) + 1);
    card.dataset.last = clock(entry);
    card.dataset.message = entry.message;
    card.querySelector(".log-card-body").textContent = entry.message;
    card.querySelector(".log-card-time").textContent = clock(entry);
    const count = card.querySelector(".log-card-count");
    count.textContent = "×" + card.dataset.count;
    count.hidden = card.dataset.count === "1";
    lines.prepend(card);
  }

  async function poll() {
    try {
      const resp = await fetch(`/settings/logs/entries?level=${encodeURIComponent(level)}&after=${after}`);
      if (!resp.ok) throw new Error("log fetch failed");
      const entries = await resp.json();
      entries.forEach((entry) => {
        add(entry);
        after = Math.max(after, entry.id);
      });
      while (lines.children.length > 300) {
        const last = lines.lastElementChild;
        cards.delete(last.dataset.key);
        last.remove();
      }
      empty.hidden = lines.children.length > 0;
    } catch (err) {
      window.ccToast({ message: "Could not load the log", variant: "error" });
      clearInterval(timer);
      timer = null;
    }
  }

  view.addEventListener("click", (e) => {
    const button = e.target.closest("[data-log-level]");
    if (button) {
      level = button.dataset.logLevel;
      view.querySelectorAll("[data-log-level]").forEach((b) => b.classList.toggle("active", b === button));
      lines.replaceChildren();
      cards.clear();
      after = 0;
      poll();
      return;
    }
    const copy = e.target.closest(".log-card-copy");
    if (copy) {
      const text = fullText(copy.closest(".log-card"));
      navigator.clipboard.writeText(text).then(
        () => window.ccToast({ message: "Copied", variant: "success" }),
        () => window.ccToast({ message: "Could not copy", variant: "error" })
      );
      return;
    }
    const toggle = e.target.closest(".log-card-toggle");
    if (toggle) {
      const body = toggle.closest(".log-card").querySelector(".log-card-body");
      body.hidden = !body.hidden;
      toggle.setAttribute("aria-expanded", String(!body.hidden));
    }
  });

  poll();
  timer = setInterval(poll, 2000);
})();
