// Universal command surface (1.2 side work, plans/open.md § Universal
// command surface) -- one shared picker overlay backing two independent
// invocation modes:
//
//   - Global mode: Ctrl-K / Cmd-K from anywhere, the tabbar's Search
//     entry, or /search's own input (search.html) -- searches tasks/
//     events/contacts by title/description/label (routers/search.py's
//     GET /api/search) and navigates to whichever result you pick
//     (CCModal.open -- the same mechanism every `data-modal` link in the
//     app already uses).
//   - Relation-picker mode: any `[data-relations-picker]` trigger (the
//     Relations card's "Add a related event/task..." button,
//     _task_relations.html/_event_relations.html) -- the overlay opens
//     pre-scoped to `GET /api/search?for_task=<uid>` (or `for_event`),
//     which applies the app's one relation rule server-side (share >=1
//     label, not already linked -- see routers/search.py's api_search).
//     Picking a result -- or typing a title and choosing "Create new" --
//     fills the sibling `.relations-hidden-form` and submits it; the POST
//     targets and the defensive `_shares_label` re-check on submit
//     (routers/tasks.py's add_task_relation, routers/calendar.py's
//     add_event_relation) are unchanged from the old <select>-based flow
//     this replaces.
//
// Both modes share one overlay (#command-palette-overlay, base.html) --
// one query implementation, one keyboard-nav implementation, one set of
// result-rendering rules, not two independent search UIs. It's a portal
// like #modal-overlay/#color-popover (see base.html's own comments on
// those): it must render on top of an already-open modal, since a
// relations-picker trigger lives inside modal-body, so it can't be a
// modal-body descendant or .modal-body's overflow:auto would clip it.
//
// Entry points are delegated at the document level (see the two
// document.addEventListener("click"/"keydown") calls at the bottom)
// rather than wired per-element the way e.g. relations_picker.js used to
// -- a relations-picker trigger is frequently injected via modal.js's
// innerHTML swap, which never runs <script> tags, and delegation means
// this file needs no wireContent()-style re-init hook at all.
(function () {
  const overlay = document.getElementById("command-palette-overlay");
  const input = document.getElementById("command-palette-input");
  const resultsEl = document.getElementById("command-palette-results");
  const closeBtn = document.getElementById("command-palette-close");
  if (!overlay || !input || !resultsEl) return;

  let mode = "global"; // "global" | "relation"
  let relationCtx = null; // {forTask, forEvent, label, hiddenForm} when mode === "relation"
  let activeIndex = -1;
  let fetchToken = 0;
  let debounceTimer = null;

  const TYPE_ICON = { task: "check-square", event: "calendar", contact: "user" };

  function iconMarkup(name) {
    return '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function open(opts) {
    opts = opts || {};
    mode = opts.forTask || opts.forEvent ? "relation" : "global";
    relationCtx = mode === "relation" ? opts : null;
    input.value = "";
    input.placeholder = mode === "relation"
      ? "Add a related " + (opts.label || "item") + "…"
      : "Search tasks, events, contacts…";
    activeIndex = -1;
    overlay.classList.add("is-open");
    document.body.classList.add("command-palette-open");
    window.setTimeout(function () {
      input.focus();
    }, 0);
    runQuery("");
  }

  function close() {
    overlay.classList.remove("is-open");
    document.body.classList.remove("command-palette-open");
    mode = "global";
    relationCtx = null;
  }

  function runQuery(q) {
    const token = ++fetchToken;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    params.set("limit", "20");
    if (mode === "relation" && relationCtx) {
      if (relationCtx.forTask) params.set("for_task", relationCtx.forTask);
      if (relationCtx.forEvent) params.set("for_event", relationCtx.forEvent);
    }
    fetch("/api/search?" + params.toString())
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (token !== fetchToken) return; // a newer keystroke's query already landed
        render(q, data.results || [], data);
      })
      .catch(function () {
        if (token !== fetchToken) return;
        render(q, [], {});
      });
  }

  function render(q, items, data) {
    resultsEl.innerHTML = "";
    const rows = items.map(function (item, i) {
      return { kind: "result", item: item, index: i };
    });
    if (mode === "relation" && q) {
      rows.push({ kind: "create", index: rows.length, title: q });
    }

    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "command-palette-empty";
      if (mode === "relation" && data && data.no_labels) {
        empty.textContent = "Add a label to relate " + (relationCtx.label || "items") + ".";
      } else if (q) {
        empty.textContent = "No results.";
      } else {
        empty.textContent = mode === "relation"
          ? "Type to search, or enter a title to create a new " + (relationCtx.label || "item") + "."
          : "Type to search across tasks, events, and contacts.";
      }
      resultsEl.appendChild(empty);
      activeIndex = -1;
      return;
    }

    rows.forEach(function (row) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "command-palette-row";
      if (row.kind === "create") {
        el.innerHTML =
          iconMarkup("plus") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">Create new ' +
          escapeHtml(relationCtx.label || "item") + ': "' + escapeHtml(row.title) + '"</span></span>';
        el.addEventListener("click", function () {
          submitRelation("__new__", row.title);
        });
      } else {
        const r = row.item;
        el.innerHTML =
          iconMarkup(TYPE_ICON[r.type] || "file") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">' +
          escapeHtml(r.title) + '</span><span class="command-palette-row-subtitle">' +
          escapeHtml(r.subtitle || "") + "</span></span>";
        el.addEventListener("click", function () {
          selectResult(r);
        });
      }
      resultsEl.appendChild(el);
    });
    activeIndex = 0;
    highlightActive();
  }

  function highlightActive() {
    Array.from(resultsEl.children).forEach(function (el, i) {
      el.classList.toggle("is-active", i === activeIndex);
    });
  }

  function moveActive(delta) {
    const count = resultsEl.children.length;
    if (!count) return;
    activeIndex = (activeIndex + delta + count) % count;
    highlightActive();
    const el = resultsEl.children[activeIndex];
    if (el) el.scrollIntoView({ block: "nearest" });
  }

  function activateCurrent() {
    const el = resultsEl.children[activeIndex];
    if (el) el.click();
  }

  function selectResult(r) {
    if (mode === "relation") {
      submitRelation(r.uid, "");
      return;
    }
    close();
    const url = r.type === "task" ? "/tasks/" + r.uid : r.type === "event" ? "/events/" + r.uid : "/contacts/" + r.uid;
    if (window.CCModal) {
      window.CCModal.open(url);
    } else {
      window.location.href = url;
    }
  }

  function submitRelation(targetUid, newTitle) {
    if (!relationCtx || !relationCtx.hiddenForm) return;
    const form = relationCtx.hiddenForm;
    const targetInput = form.querySelector('input[name="target_uid"]');
    const titleInput = form.querySelector('input[name="new_title"]');
    if (targetInput) targetInput.value = targetUid;
    if (titleInput) titleInput.value = newTitle;
    close();
    form.requestSubmit();
  }

  input.addEventListener("input", function () {
    window.clearTimeout(debounceTimer);
    const q = input.value.trim();
    debounceTimer = window.setTimeout(function () {
      runQuery(q);
    }, 150);
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveActive(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveActive(-1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      activateCurrent();
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  });

  if (closeBtn) closeBtn.addEventListener("click", close);
  // Backdrop click closes, same convention as static/modal.js's own
  // overlay (only when the click lands on the scrim itself, not the panel).
  overlay.addEventListener("mousedown", function (e) {
    if (e.target === overlay) close();
  });

  document.addEventListener("keydown", function (e) {
    const combo = (e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K");
    if (!combo) return;
    e.preventDefault();
    if (overlay.classList.contains("is-open")) close();
    else open({});
  });

  document.addEventListener("click", function (e) {
    const relTrigger = e.target.closest("[data-relations-picker]");
    if (relTrigger) {
      e.preventDefault();
      const forTask = relTrigger.getAttribute("data-for-task") || "";
      const forEvent = relTrigger.getAttribute("data-for-event") || "";
      const label = relTrigger.getAttribute("data-relations-label") || "item";
      // The hidden submit form is rendered as this button's sibling
      // (one add-row = one trigger button + one hidden form, see
      // _task_relations.html/_event_relations.html) inside the same
      // .relations-group -- matched by DOM adjacency, not an id lookup,
      // since a page can in principle render more than one Relations card.
      const group = relTrigger.closest(".relations-group");
      const hiddenForm = group ? group.querySelector(".relations-hidden-form") : null;
      if (!hiddenForm) return;
      open({
        forTask: forTask || undefined,
        forEvent: forEvent || undefined,
        label: label,
        hiddenForm: hiddenForm,
      });
      return;
    }
    const openTrigger = e.target.closest("[data-command-palette-open]");
    if (openTrigger) {
      e.preventDefault();
      open({});
    }
  });

  window.CCCommandPalette = { open: open, close: close };
})();
