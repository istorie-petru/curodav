// Universal command surface (1.2 side work, plans/open.md § Universal
// command surface) -- one shared picker overlay backing three independent
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
//   - Label mode: entered from a global-mode result row's own "Add
//     label" action button (see buildActions below), never opened
//     directly -- searches routers/search.py's GET /api/labels (every
//     label already in use, filtered live) and assigns the picked (or
//     freshly typed) label to that one result via
//     POST /api/entities/<type>/<uid>/labels. This is the "Command
//     palette actions" follow-up (plans/open.md): the overlay was
//     search-and-navigate only before; result rows now also carry
//     Complete/Add label/Delete actions (global mode only -- relation
//     mode's rows exist to be picked as a link target, not acted on), and
//     global mode itself gained "Create task/event: '<query>'" rows,
//     mirroring the "Create new" row relation mode already had. Additive
//     throughout: the query layer, /api/search, and the relations-picker
//     wiring below are all unchanged.
//
// All three modes share one overlay (#command-palette-overlay, base.html)
// -- one query implementation, one keyboard-nav implementation, one set of
// result-rendering rules, not three independent UIs. It's a portal like
// #modal-overlay/#color-popover (see base.html's own comments on those):
// it must render on top of an already-open modal, since a
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

  let mode = "global"; // "global" | "relation" | "label"
  let relationCtx = null; // {forTask, forEvent, label, hiddenForm} when mode === "relation"
  let labelCtx = null; // {type, uid, title} when mode === "label"
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

  function toast(opts) {
    if (window.ccToast) window.ccToast(opts);
  }

  function open(opts) {
    opts = opts || {};
    mode = opts.forTask || opts.forEvent ? "relation" : "global";
    relationCtx = mode === "relation" ? opts : null;
    labelCtx = null;
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
    labelCtx = null;
  }

  // Label mode is entered from within an already-open overlay (a result
  // row's "Add label" action), not through the same open() entry points
  // above -- it keeps the overlay open and just retargets the query.
  function enterLabelMode(r) {
    mode = "label";
    labelCtx = { type: r.type, uid: r.uid, title: r.title };
    input.value = "";
    input.placeholder = 'Add a label to "' + r.title + '"…';
    activeIndex = -1;
    window.setTimeout(function () {
      input.focus();
    }, 0);
    runQuery("");
  }

  function runQuery(q) {
    const token = ++fetchToken;
    if (mode === "label") {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      params.set("limit", "20");
      fetch("/api/labels?" + params.toString())
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (token !== fetchToken) return;
          render(q, data.labels || [], data);
        })
        .catch(function () {
          if (token !== fetchToken) return;
          render(q, [], {});
        });
      return;
    }
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

  function buildRows(q, items) {
    if (mode === "label") {
      const rows = items.map(function (name, i) {
        return { kind: "label-option", name: name, index: i };
      });
      const exact = q && items.some(function (n) {
        return n.toLowerCase() === q.toLowerCase();
      });
      if (q && !exact) rows.push({ kind: "label-create", name: q, index: rows.length });
      return rows;
    }
    const rows = items.map(function (item, i) {
      return { kind: "result", item: item, index: i };
    });
    if (mode === "relation" && q) {
      rows.push({ kind: "create", index: rows.length, title: q });
    }
    if (mode === "global" && q) {
      rows.push({ kind: "create-task", index: rows.length, title: q });
      rows.push({ kind: "create-event", index: rows.length + 1, title: q });
    }
    return rows;
  }

  function emptyMessage(q, data) {
    if (mode === "label") {
      return q ? "" : "Type to search existing labels, or enter a new one.";
    }
    if (mode === "relation" && data && data.no_labels) {
      return "Add a label to relate " + (relationCtx.label || "items") + ".";
    }
    if (q) return "No results.";
    return mode === "relation"
      ? "Type to search, or enter a title to create a new " + (relationCtx.label || "item") + "."
      : "Type to search across tasks, events, and contacts.";
  }

  function render(q, items, data) {
    resultsEl.innerHTML = "";
    const rows = buildRows(q, items);

    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "command-palette-empty";
      empty.textContent = emptyMessage(q, data);
      resultsEl.appendChild(empty);
      activeIndex = -1;
      return;
    }

    rows.forEach(function (row) {
      const el = document.createElement("div");
      el.className = "command-palette-row";

      if (row.kind === "create") {
        el.innerHTML =
          iconMarkup("plus") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">Create new ' +
          escapeHtml(relationCtx.label || "item") + ': "' + escapeHtml(row.title) + '"</span></span>';
        el.addEventListener("click", function () {
          submitRelation("__new__", row.title);
        });
      } else if (row.kind === "create-task" || row.kind === "create-event") {
        const typeLabel = row.kind === "create-task" ? "task" : "event";
        el.innerHTML =
          iconMarkup("plus") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">Create ' +
          typeLabel + ': "' + escapeHtml(row.title) + '"</span></span>';
        el.addEventListener("click", function () {
          createEntity(typeLabel, row.title);
        });
      } else if (row.kind === "label-option" || row.kind === "label-create") {
        const isCreate = row.kind === "label-create";
        el.innerHTML =
          iconMarkup("tag") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">' +
          (isCreate ? 'Add new label: "' + escapeHtml(row.name) + '"' : escapeHtml(row.name)) +
          "</span></span>";
        el.addEventListener("click", function () {
          assignLabel(row.name);
        });
      } else {
        const r = row.item;
        const main = document.createElement("button");
        main.type = "button";
        main.className = "command-palette-row-main";
        main.innerHTML =
          iconMarkup(TYPE_ICON[r.type] || "file") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">' +
          escapeHtml(r.title) + '</span><span class="command-palette-row-subtitle">' +
          escapeHtml(r.subtitle || "") + "</span></span>";
        main.addEventListener("click", function () {
          selectResult(r);
        });
        el.appendChild(main);
        if (mode === "global") el.appendChild(buildActions(r));
      }
      resultsEl.appendChild(el);
    });
    activeIndex = 0;
    highlightActive();
  }

  // Global-mode-only per-row actions (open.md § Command palette actions):
  // Mark done (tasks, not already done), Add label (any type -- switches
  // the overlay into label mode above), Delete (any type, destructive --
  // confirmed via the same window.ccConfirmSheet every other destructive
  // action in the app uses, static/modal.js's own convention). Relation
  // mode's rows stay action-free -- they exist to be picked as a link
  // target, and a stray Delete button in that context would be a real
  // footgun (Relations picker rows render exactly one click away from a
  // destructive action with no relation-specific context in the row).
  function buildActions(r) {
    const wrap = document.createElement("div");
    wrap.className = "command-palette-row-actions";
    const defs = [];
    if (r.type === "task" && r.status !== "done") {
      defs.push({ icon: "check-square", label: "Mark done", danger: false, run: function () { completeTask(r); } });
    }
    defs.push({ icon: "tag", label: "Add label", danger: false, run: function () { enterLabelMode(r); } });
    defs.push({ icon: "trash", label: "Delete", danger: true, run: function (btn) { deleteEntity(r, btn); } });
    defs.forEach(function (d) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "command-palette-action" + (d.danger ? " is-danger" : "");
      btn.title = d.label;
      btn.setAttribute("aria-label", d.label);
      btn.innerHTML = iconMarkup(d.icon);
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        d.run(btn);
      });
      wrap.appendChild(btn);
    });
    return wrap;
  }

  function entityUrl(r) {
    return r.type === "task" ? "/tasks/" + r.uid : r.type === "event" ? "/events/" + r.uid : "/contacts/" + r.uid;
  }

  function deleteUrl(r) {
    return entityUrl(r) + "/delete";
  }

  function completeTask(r) {
    fetch("/tasks/" + r.uid + "/complete", { method: "POST" })
      .then(function (resp) {
        if (!resp.ok) throw new Error("failed");
        toast({ message: 'Marked "' + r.title + '" done.' });
        close();
      })
      .catch(function () {
        toast({ message: "Could not mark that task done.", variant: "error" });
      });
  }

  function deleteEntity(r, anchorBtn) {
    if (!window.ccConfirmSheet) return;
    window.ccConfirmSheet({
      anchor: anchorBtn,
      message: 'Delete "' + r.title + '"? This cannot be undone.',
      onConfirm: function () {
        fetch(deleteUrl(r), { method: "POST" })
          .then(function (resp) {
            if (!resp.ok) throw new Error("failed");
            toast({ message: 'Deleted "' + r.title + '".' });
            close();
          })
          .catch(function () {
            toast({ message: "Could not delete that item.", variant: "error" });
          });
      },
    });
  }

  function assignLabel(name) {
    if (!labelCtx) return;
    const ctx = labelCtx;
    fetch("/api/entities/" + ctx.type + "/" + ctx.uid + "/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: name }),
    })
      .then(async function (resp) {
        if (!resp.ok) {
          const data = await resp.json().catch(function () {
            return {};
          });
          throw new Error(data.error || "failed");
        }
        toast({ message: 'Added label "' + name + '" to "' + ctx.title + '".' });
        close();
      })
      .catch(function (err) {
        toast({ message: err.message || "Could not add that label.", variant: "error" });
      });
  }

  function createEntity(typeLabel, title) {
    close();
    const url = (typeLabel === "task" ? "/tasks/new" : "/events/new") + "?title=" + encodeURIComponent(title);
    if (window.CCModal) {
      window.CCModal.open(url);
    } else {
      window.location.href = url;
    }
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
    // A "result" row's clickable surface is the nested .command-palette-
    // row-main button (see render() above), not the outer row itself --
    // Enter should trigger the same thing a plain click on the row does,
    // so it targets that inner button when present rather than the row's
    // own (actionless, for "result" rows) click.
    const el = resultsEl.children[activeIndex];
    if (!el) return;
    const main = el.querySelector(".command-palette-row-main");
    (main || el).click();
  }

  function selectResult(r) {
    if (mode === "relation") {
      submitRelation(r.uid, "");
      return;
    }
    close();
    const url = entityUrl(r);
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
      // Label mode backs out to the global results it was entered from
      // rather than closing the whole overlay -- it's one step down from
      // global mode (entered via a row's own action button, not a fresh
      // Ctrl-K), so Escape should feel like "back", not "quit".
      if (mode === "label") {
        mode = "global";
        labelCtx = null;
        input.value = "";
        input.placeholder = "Search tasks, events, contacts…";
        runQuery("");
      } else {
        close();
      }
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
