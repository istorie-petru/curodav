// Universal command surface (1.2 side work, plans/open.md § Universal
// command surface) -- one shared picker overlay backing two independent
// invocation modes:
//
//   - Global mode: Ctrl-K / Cmd-K from anywhere, the tabbar's Search
//     entry, or /search's own input (search.html) -- searches tasks/
//     events/contacts by title/description/label (routers/search.py's
//     GET /api/search) and navigates to whichever result you pick
//     (CCModal.open -- the same mechanism every `data-modal` link in the
//     app already uses). Global mode's own result rows also carry a
//     Mark-done action (tasks only, not already done -- see buildActions
//     below), and the input itself doubles as "Create task/event:
//     '<query>'" once you've typed a title (open.md § Command palette
//     actions).
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
// A third mode, Label mode (entered from a result row's own "Add label"
// action, searching routers/search.py's now-removed GET /api/labels),
// existed from the original "Command palette actions" follow-up
// (plans/open.md) through 2026-09-24 -- removed that day (direct
// request, "search window simplification": "remove the Add label and
// Delete buttons from the search window") along with its one entry point
// and the two backend endpoints that existed only to serve it. See
// buildActions below for what result-row actions remain.
//
// Two further additions, direct feedback (2026-08-15), both layered on top
// of global mode rather than new modes of their own:
//
//   - Page navigation: global-mode results can now include the app's own
//     pages (Dashboard/Calendar/Tasks/Contacts/Notes/Settings, every
//     Space), computed server-side (routers/search.py's `_matching_pages`)
//     and tagged `type: "page"` -- picking one is a plain navigation
//     (`window.location.href`), not `CCModal.open`, and it carries no
//     action buttons (buildActions skips `type === "page"` entirely).
//   - Quick Capture (plans/quick-capture.md): typing a standalone `!t`/
//     `!e`/`!c` token (`!n` note removed 2026-09-24, see CAPTURE_MARKER_RE's
//     own comment) anywhere in the global-mode input switches the results
//     panel from search results to a single live-parsed preview row, fed by
//     `GET /api/quick-capture/preview` instead of `/api/search` for as
//     long as a marker is present. Enter posts the raw text to
//     `POST /api/quick-capture`, which does the actual parse + create.
//     This is genuinely a sub-state of global mode, not a fourth `mode`
//     value -- `captureState.active` gates it, checked first in the
//     input-debounce and Enter-key handlers below, falling through to the
//     ordinary /api/search path the instant the marker is edited away.
//
// All three modes (plus the two global-mode additions above) share one
// overlay (#command-palette-overlay, base.html) -- one query
// implementation, one keyboard-nav implementation, one set of
// result-rendering rules, not several independent UIs. It's a portal like
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
  const filtersEl = document.getElementById("command-palette-filters");
  const editModeMenuItem = document.getElementById("command-palette-edit-mode-item");
  if (!overlay || !input || !resultsEl) return;

  let mode = "global"; // "global" | "relation"
  let relationCtx = null; // {forTask, forEvent, label, hiddenForm} when mode === "relation"
  let typeFilter = ""; // "" | "task" | "event" | "contact" -- global mode only, see filter pills below
  let activeIndex = -1;
  let fetchToken = 0;
  let debounceTimer = null;
  // Result rows actually eligible for keyboard navigation, in display
  // order -- excludes .command-palette-group-header elements (date-group
  // dividers, global mode only), which are rendered as resultsEl children
  // too but aren't selectable. Recomputed at the end of every render().
  let currentRowEls = [];

  // Date-grouped results (direct feedback, 2026-09-12: mockup of a
  // redesigned search overlay grouping by Overdue/This week/Later) --
  // global mode's result rows carry a `date` field now (routers/
  // search.py's _picker_result: a task's due_at, an event's start_at,
  // null for contacts/notes/pages). Bucketed client-side rather than by
  // the server so the grouping stays purely a display concern -- the
  // underlying /api/search ordering and relevance ranking are untouched.
  //
  // "overdue" vs "past" (2026-09-24 direct request, "search window
  // simplification": "events can't be overdue, they just pass, so an
  // event's status label needs its own wording distinct from a task's
  // 'Overdue'") -- a past-due task keeps "Overdue" (a real unmet
  // obligation), a past event gets its own neutral "Past" bucket/header
  // instead of being lumped under the same word. Split by type rather
  // than reworded in place, since the two can both appear in the same
  // grouped list and need genuinely separate headers, not one shared one.
  const BUCKET_ORDER = ["overdue", "past", "week", "later", "nodate"];
  const BUCKET_LABEL = { overdue: "Overdue", past: "Past", week: "This week", later: "Later", nodate: "No date" };

  const BARE_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

  function dateBucket(dateStr, type) {
    if (!dateStr) return "nodate";
    // A bare "YYYY-MM-DD" (a task's due_at, always date-only -- see
    // routers/tasks.py's `due_at: str = Form("")`, straight from a plain
    // date input) is parsed by `new Date()` as UTC midnight per the ES
    // spec, while a full datetime like an event's start_at (no
    // timezone suffix) parses as local time -- feeding the bare form
    // through the same `new Date(dateStr)` call rolls it back to the
    // previous local day in any timezone west of UTC, misbucketing a
    // task due "today" as Overdue. Parsed as local calendar-date
    // components instead so it lines up with `startOfToday` below,
    // which is also local.
    const d = BARE_DATE_RE.test(dateStr)
      ? new Date(Number(dateStr.slice(0, 4)), Number(dateStr.slice(5, 7)) - 1, Number(dateStr.slice(8, 10)))
      : new Date(dateStr);
    if (isNaN(d.getTime())) return "nodate";
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diffDays = Math.floor((d.getTime() - startOfToday.getTime()) / 86400000);
    if (diffDays < 0) return type === "event" ? "past" : "overdue";
    if (diffDays <= 6) return "week";
    return "later";
  }

  // Filter pills only make sense in global mode's plain search results --
  // relation mode has its own narrower purpose, and Quick Capture's single
  // preview row isn't a list to filter or navigate.
  function updatePanelsVisibility() {
    const show = mode === "global" && !captureState.active;
    if (filtersEl) filtersEl.style.display = show ? "" : "none";
  }
  // Quick Capture sub-state (global mode only) -- {active, text}. `text`
  // is the exact raw input the last preview was fetched for, re-sent
  // verbatim to POST /api/quick-capture on Enter so the server parses the
  // same string the preview was computed from.
  const captureState = { active: false, text: "" };
  // "n" (note) dropped 2026-09-24 (direct request, "remove or hide Notes
  // from the app's HTML" -- hide, not delete; src/quick_capture.py's
  // MARKER_TYPES/_MARKER_RE made the matching server-side change). Typing
  // "!n ..." now just falls through to a plain search query instead of
  // triggering a capture preview that would 400 on submit.
  const CAPTURE_MARKER_RE = /(^|\s)!(t|e|c)(\s|$)/;
  const CAPTURE_TYPE_LABEL = { task: "Task", event: "Event", contact: "Contact", note: "Note" };
  const CAPTURE_ICON = { task: "check-square", event: "calendar", contact: "user", note: "file-text" };

  const TYPE_ICON = { task: "check-square", event: "calendar", contact: "user", note: "file-text", page: "layout" };

  // "Turn on/off Edit mode" (2026-09-13, direct request: "a way to
  // activate edit mode with the help of the command palette") -- a
  // virtual, client-only row alongside global mode's "Create task/
  // event: ..." rows above (buildRows), not a real /api/search result:
  // there's nothing to search for server-side, this just surfaces an
  // app-wide setting (Settings > Appearance's own toggle, routers/
  // settings.py's set_edit_mode) as a quick action. Current on/off state
  // comes from body[data-edit-mode] (deps.py's edit_mode_enabled()
  // Jinja global, threaded onto every page via base.html), so this works
  // the same everywhere the palette itself works, not just on pages that
  // render the widget grid.
  function editModeOn() {
    return document.body.getAttribute("data-edit-mode") === "1";
  }

  function toggleEditMode() {
    const turningOn = !editModeOn();
    fetch("/settings/edit-mode", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
      body: "enabled=" + (turningOn ? "1" : ""),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("failed");
        close();
        toast({ title: "Edit mode " + (turningOn ? "on" : "off") });
        // The current page may render the widget grid (Dashboard/Space/
        // Project/Label) with its edit controls baked into server-
        // rendered HTML (routers/dashboard.py's widget_page_context) --
        // simplest way to pick that up immediately, everywhere the
        // palette can be opened from, is a full reload rather than
        // trying to detect "does this page support edit mode" client-
        // side. A page that doesn't render the grid just reloads with
        // no visible change beyond the toast already shown.
        window.location.reload();
      })
      .catch(function () {
        toast({ message: "Could not change Edit mode.", variant: "error" });
      });
  }

  // Explicit menu action (2026-09-24, "search window simplification"
  // direct request: "Add explicit menu actions beyond search itself --
  // Edit mode toggle...") -- the .action-menu item in the input row
  // (base.html) alongside the typed "edit mode" row above; its label is
  // the one piece render() can't own (it's static markup, not a result
  // row rebuilt on every keystroke), so it's refreshed once per open()
  // instead, same "read body[data-edit-mode] fresh" approach editModeOn()
  // already uses everywhere else.
  function updateEditModeMenuItem() {
    if (!editModeMenuItem) return;
    editModeMenuItem.innerHTML = iconMarkup("edit") + " Turn " + (editModeOn() ? "off" : "on") + " Edit mode";
  }

  if (editModeMenuItem) editModeMenuItem.addEventListener("click", toggleEditMode);

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
    captureState.active = false;
    typeFilter = "";
    setActivePill("");
    input.value = "";
    input.placeholder = mode === "relation"
      ? "Add a related " + (opts.label || "item") + "…"
      : "Search tasks, events, contacts… (or !t/!e/!c/!n to capture)";
    activeIndex = -1;
    overlay.classList.add("is-open");
    document.body.classList.add("command-palette-open");
    updatePanelsVisibility();
    updateEditModeMenuItem();
    // Skip the auto-focus below the mobile breakpoint (same 720px cutoff
    // style.css's own mobile blocks use) -- focusing a text input pops
    // the on-screen keyboard immediately on phones, covering half the
    // overlay before the person has even looked at it. Desktop keeps the
    // immediate focus (no keyboard to summon, and it's the whole point of
    // a keyboard-driven Ctrl-K palette).
    if (!window.matchMedia || !window.matchMedia("(max-width:720px)").matches) {
      window.setTimeout(function () {
        input.focus();
      }, 0);
    }
    runQuery("");
  }

  function close() {
    overlay.classList.remove("is-open");
    document.body.classList.remove("command-palette-open");
    mode = "global";
    relationCtx = null;
    captureState.active = false;
  }

  function setActivePill(value) {
    if (!filtersEl) return;
    Array.from(filtersEl.children).forEach(function (btn) {
      btn.classList.toggle("is-active", (btn.getAttribute("data-type-filter") || "") === value);
    });
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
    if (mode === "global" && typeFilter) params.set("types", typeFilter);
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
    const rows = items.map(function (item, i) {
      return { kind: "result", item: item, index: i };
    });
    if (mode === "relation" && q) {
      rows.push({ kind: "create", index: rows.length, title: q });
    }
    if (mode === "global" && q && "edit mode".indexOf(q.toLowerCase()) !== -1) {
      rows.push({ kind: "toggle-edit-mode", index: rows.length });
    }
    if (mode === "global" && q) {
      rows.push({ kind: "create-task", index: rows.length, title: q });
      rows.push({ kind: "create-event", index: rows.length + 1, title: q });
    }
    return rows;
  }

  function emptyMessage(q, data) {
    if (mode === "relation" && data && data.no_labels) {
      return "Add a label to relate " + (relationCtx.label || "items") + ".";
    }
    if (q) return "No results.";
    return mode === "relation"
      ? "Type to search, or enter a title to create a new " + (relationCtx.label || "item") + "."
      : "Type to search across tasks, events, and contacts.";
  }

  function runCapturePreview(rawText) {
    const token = ++fetchToken;
    fetch("/api/quick-capture/preview?text=" + encodeURIComponent(rawText))
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (token !== fetchToken) return;
        renderCapturePreview(rawText, data);
      })
      .catch(function () {
        if (token !== fetchToken) return;
        renderCapturePreview(rawText, { ok: false, error: "Could not parse that." });
      });
  }

  function captureSummary(data) {
    const parts = [];
    if (data.type === "task") {
      if (data.due_date) parts.push("due " + data.due_date);
      if (data.timeblock_count) parts.push(data.timeblock_count + " timeblock" + (data.timeblock_count === 1 ? "" : "s"));
    } else if (data.type === "event") {
      if (data.all_day && data.start) parts.push(data.start.slice(0, 10) + " (all day)");
      else if (data.start) parts.push(data.start.replace("T", " ").slice(0, 16) + (data.end ? "–" + data.end.slice(11, 16) : ""));
    } else if (data.type === "contact") {
      if (data.phone) parts.push(data.phone);
      if (data.email) parts.push(data.email);
    }
    if (data.labels && data.labels.length) parts.push(data.labels.map(function (l) { return "#" + l; }).join(" "));
    return parts.join(" · ");
  }

  function renderCapturePreview(rawText, data) {
    captureState.active = true;
    captureState.text = rawText;
    updatePanelsVisibility();
    resultsEl.innerHTML = "";
    const row = document.createElement("div");
    row.className = "command-palette-row command-palette-capture-row";
    if (!data || !data.ok) {
      row.innerHTML =
        iconMarkup("zap") +
        '<span class="command-palette-row-text"><span class="command-palette-row-title">' +
        escapeHtml((data && data.error) || "Keep typing…") + "</span></span>";
    } else {
      row.innerHTML =
        iconMarkup(CAPTURE_ICON[data.type] || "zap") +
        '<span class="command-palette-row-text"><span class="command-palette-row-title">' +
        (CAPTURE_TYPE_LABEL[data.type] || "Item") + ": " + escapeHtml(data.title || "") +
        '</span><span class="command-palette-row-subtitle">' +
        escapeHtml(captureSummary(data)) + (captureSummary(data) ? " — " : "") + "Enter to create</span></span>";
    }
    resultsEl.appendChild(row);
    activeIndex = -1;
  }

  function submitCapture() {
    if (!captureState.active || !captureState.text) return;
    const text = captureState.text;
    fetch("/api/quick-capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    })
      .then(async function (resp) {
        const data = await resp.json().catch(function () {
          return {};
        });
        if (!resp.ok) throw new Error(data.error || "Could not capture that.");
        toast({ title: (CAPTURE_TYPE_LABEL[data.type] || "Item") + " created", message: '"' + (data.title || "") + '"' });
        // async-CRUD (features/async-crud.md): the page underneath should
        // refresh its own region for the created entity instead of staying
        // stale -- this is the only thing the palette adds to the flow (it
        // already closed + toasted on its own).
        if (data.type && window.ccApi && window.ccApi.dispatchChange) {
          window.ccApi.dispatchChange({ type: data.type, action: "create" });
        }
        close();
      })
      .catch(function (err) {
        toast({ message: err.message || "Could not capture that.", variant: "error" });
      });
  }

  // Global mode only: reorders `rows` (buildRows' output) into date
  // buckets and splices in {kind: "header"} marker rows ahead of each
  // bucket's first item -- "create-task"/"create-event" rows (no `date`
  // of their own, they're the typed query, not a result) are left where
  // buildRows put them, after every real result, ungrouped. Relation/
  // label mode results skip this entirely (their own rows.forEach branch
  // never checks row.kind === "header", so returning `rows` unchanged is
  // enough to leave that behavior exactly as it was).
  function groupRowsByDate(rows) {
    if (mode !== "global") return rows;
    const resultRows = rows.filter(function (r) { return r.kind === "result"; });
    const otherRows = rows.filter(function (r) { return r.kind !== "result"; });
    if (!resultRows.length) return rows;
    const buckets = {};
    BUCKET_ORDER.forEach(function (b) { buckets[b] = []; });
    resultRows.forEach(function (r) {
      buckets[dateBucket(r.item.date, r.item.type)].push(r);
    });
    const grouped = [];
    BUCKET_ORDER.forEach(function (b) {
      if (!buckets[b].length) return;
      grouped.push({ kind: "header", label: BUCKET_LABEL[b] });
      grouped.push.apply(grouped, buckets[b]);
    });
    return grouped.concat(otherRows);
  }

  function render(q, items, data) {
    captureState.active = false;
    updatePanelsVisibility();
    resultsEl.innerHTML = "";
    const rows = groupRowsByDate(buildRows(q, items));

    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "command-palette-empty";
      empty.textContent = emptyMessage(q, data);
      resultsEl.appendChild(empty);
      activeIndex = -1;
      currentRowEls = [];
      return;
    }

    rows.forEach(function (row) {
      if (row.kind === "header") {
        const header = document.createElement("div");
        header.className = "command-palette-group-header";
        header.textContent = row.label;
        resultsEl.appendChild(header);
        return;
      }
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
      } else if (row.kind === "toggle-edit-mode") {
        const turningOn = !editModeOn();
        el.innerHTML =
          iconMarkup("edit") +
          '<span class="command-palette-row-text"><span class="command-palette-row-title">Turn ' +
          (turningOn ? "on" : "off") + " Edit mode</span></span>";
        el.addEventListener("click", function () {
          toggleEditMode();
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
        if (mode === "global" && r.type !== "page") {
          const actions = buildActions(r);
          if (actions) el.appendChild(actions);
        }
      }
      resultsEl.appendChild(el);
    });
    currentRowEls = Array.from(resultsEl.children).filter(function (el) {
      return el.classList.contains("command-palette-row");
    });
    activeIndex = currentRowEls.length ? 0 : -1;
    highlightActive();
  }

  // Global-mode-only per-row action (open.md § Command palette actions):
  // Mark done, tasks only, not already done. Add label/Delete (any type)
  // removed 2026-09-24 (direct request, "search window simplification":
  // "remove the Add label and Delete buttons from the search window") --
  // see this file's own top-of-file comment for what came out with them.
  // Relation mode's rows stay action-free -- they exist to be picked as a
  // link target, not acted on. Returns null (no actions row at all) when
  // there's nothing to show, e.g. an already-done task or any event/
  // contact row -- Mark done is the only action left, and it's task-only.
  function buildActions(r) {
    const defs = [];
    if (r.type === "task" && r.status !== "done") {
      defs.push({ icon: "check-square", label: "Mark done", danger: false, run: function () { completeTask(r); } });
    }
    if (!defs.length) return null;
    const wrap = document.createElement("div");
    wrap.className = "command-palette-row-actions";
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
    if (r.type === "page") return r.url;
    if (r.type === "task") return "/tasks/" + r.uid;
    if (r.type === "event") return "/events/" + r.uid;
    if (r.type === "note") return "/notes/" + r.uid + "/edit"; // notes have no separate view page
    return "/contacts/" + r.uid;
  }

  function completeTask(r) {
    fetch("/tasks/" + r.uid + "/complete", { method: "POST", headers: { "X-Requested-With": "fetch" } })
      .then(function (resp) {
        if (!resp.ok) throw new Error("failed");
        toast({ title: "Task done", message: '"' + r.title + '"' });
        close();
        // async-CRUD (features/async-crud.md): tell the page underneath to
        // refresh its own regions instead of leaving it stale.
        document.dispatchEvent(
          new CustomEvent("cc-entity-changed", { detail: { type: "task", action: "complete", uid: r.uid } })
        );
      })
      .catch(function () {
        toast({ message: "Could not mark that task done.", variant: "error" });
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
    currentRowEls.forEach(function (el, i) {
      el.classList.toggle("is-active", i === activeIndex);
    });
  }

  function moveActive(delta) {
    const count = currentRowEls.length;
    if (!count) return;
    activeIndex = (activeIndex + delta + count) % count;
    highlightActive();
    const el = currentRowEls[activeIndex];
    if (el) el.scrollIntoView({ block: "nearest" });
  }

  function activateCurrent() {
    // A "result" row's clickable surface is the nested .command-palette-
    // row-main button (see render() above), not the outer row itself --
    // Enter should trigger the same thing a plain click on the row does,
    // so it targets that inner button when present rather than the row's
    // own (actionless, for "result" rows) click.
    const el = currentRowEls[activeIndex];
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
    if (r.type === "page") {
      // A page replaces the whole view, unlike an entity's detail modal
      // layered over whatever page you were already on -- plain
      // navigation, not CCModal.open.
      window.location.href = r.url;
      return;
    }
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
    const raw = input.value;
    const q = raw.trim();
    debounceTimer = window.setTimeout(function () {
      // Quick Capture (plans/quick-capture.md) -- a standalone !t/!e/!c
      // token anywhere in global mode's input switches from search to a
      // live capture preview instead. Checked fresh on every keystroke, so
      // editing the marker away falls straight back to runQuery's normal
      // /api/search path (render() itself resets captureState.active).
      if (mode === "global" && CAPTURE_MARKER_RE.test(raw)) {
        runCapturePreview(raw);
      } else {
        runQuery(q);
      }
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
      if (captureState.active) {
        submitCapture();
      } else {
        activateCurrent();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  });

  // Type filter pills (global mode only) -- clicking a pill sets the
  // active type and re-runs the current query with /api/search's
  // existing `types` param (runQuery above), rather than filtering the
  // already-fetched page of results client-side, so a filtered view
  // still gets a full page of that one type instead of whatever fraction
  // of the unfiltered 20-result page happened to match.
  if (filtersEl) {
    filtersEl.addEventListener("click", function (e) {
      const btn = e.target.closest(".command-palette-pill");
      if (!btn || mode !== "global") return;
      typeFilter = btn.getAttribute("data-type-filter") || "";
      setActivePill(typeFilter);
      runQuery(input.value.trim());
    });
  }

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
