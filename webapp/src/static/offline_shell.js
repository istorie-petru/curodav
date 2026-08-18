// 1.8 slices 4-5 + 2026-08-18 rework -- renders /offline's content
// straight from the local IndexedDB mirror (offline_db.js), no network
// request of its own. This is the one page in this slice that actually
// reads *and now writes* the local store -- every other page is untouched
// server-rendered HTML, per §0's "a second read/write path alongside the
// server-rendered one, not a replacement."
//
// Slice 4 was read-only. Slice 5 added create/complete/delete for the task
// list (offline_write.js), each going through the same §2 op + outbox path
// a real sync engine (slice 6) later flushes -- this file never talks to
// `outbox` directly, only to CCOfflineWrite's entity-level functions, and
// re-renders on the same `cc-offline-sync-complete` event a pull fires, so
// a local write and an incoming pull refresh the list identically.
//
// 2026-08-18 rework ("Quick add + Upcoming toolbar"): the page is now two
// tabs. "Upcoming" holds the mirror-read list -- Tasks (with complete/
// delete, as slice 5), Upcoming events, and Timetabled events (work-
// allocation sessions, distinguished in the mirror by the server's new
// is_work_allocation sync field) -- in the same agenda-style sections the
// dashboard's Agenda widget uses. "Quick add" is a single-field capture
// input (offline_quick_capture.js's parser) whose submissions go through
// CCOfflineWrite.createTask/createEvent/createContact. Labels and a task's
// scheduled time blocks are parsed but can't be applied offline (labels
// never flow through the field-HLC pull/write path, and a work allocation
// needs the server-side event_task_relations link a device op can't
// express); a contact's phone/email are dropped too (they live in child
// tables outside the sync protocol) -- each skip is reported honestly in
// the result line rather than silently ignored.
(function () {
  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString();
  }

  // Agenda-style leading cells: the date alone for an all-day event, the
  // date + clock for a timed one. Mirrors the widget's `start_at[:10]` +
  // `fmt_time` split (templates/_widget_agenda.html), client-side.
  function fmtDay(iso) {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? "" : d.toLocaleDateString();
  }

  function fmtClock(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function eventWhen(e) {
    if (!e.start_at) return "&mdash;";
    if (e.all_day) return escapeHtml(fmtDay(e.start_at)) + " &middot; all day";
    return escapeHtml(fmtDay(e.start_at)) + " " + escapeHtml(fmtClock(e.start_at));
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Same markup deps.py's `icon()` Jinja global renders server-side
  // (`<svg class="icon" ...><use href="#icon-NAME"></use></svg>`) --
  // base.html's inline sprite (_icons_sprite.html) is already on every
  // page, so referencing a symbol by id here needs no separate asset.
  function iconSvg(name) {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';
  }

  function byStartAt(a, b) {
    return (a.start_at || "9999").localeCompare(b.start_at || "9999");
  }

  async function render() {
    const root = document.getElementById("offline-local-data");
    if (!root || !("indexedDB" in window)) return;

    const [tasks, events, lastSynced, outboxCount] = await Promise.all([
      window.CCOfflineDB.getAllTasks(),
      window.CCOfflineDB.getAllEvents(),
      window.CCOfflineDB.getLastSyncedAt(),
      window.CCOfflineDB.getOutboxCount(),
    ]);

    const emptyState = document.getElementById("offline-empty-state");
    if (emptyState) emptyState.style.display = "none";

    // "Upcoming" = starts today or later (same interpretation as the
    // Agenda widget's Upcoming range). Work allocations are split into
    // their own section via the mirror's is_work_allocation field; an
    // undated event (no start_at) is not "upcoming" and is left out.
    // "Today" is the local calendar date (mirror start_at strings are
    // naive local ISO -- UTC would drift a day near midnight).
    const now = new Date();
    const today =
      now.getFullYear() + "-" +
      String(now.getMonth() + 1).padStart(2, "0") + "-" +
      String(now.getDate()).padStart(2, "0");
    const openTasks = tasks
      .filter((t) => t.status !== "completed")
      .sort((a, b) => (a.due_at || "9999").localeCompare(b.due_at || "9999"));
    const upcomingEvents = events
      .filter((e) => !e.is_work_allocation && e.start_at && e.start_at.slice(0, 10) >= today)
      .sort(byStartAt);
    const timetabledEvents = events
      .filter((e) => e.is_work_allocation && e.start_at && e.start_at.slice(0, 10) >= today)
      .sort(byStartAt);

    const parts = [];
    parts.push('<div class="offline-synced-at">Last synced from this device: ' + (lastSynced ? fmtWhen(lastSynced) : "never") + "</div>");
    if (outboxCount > 0) {
      parts.push(
        '<div class="offline-pending-note">' +
          outboxCount +
          (outboxCount === 1 ? " local change" : " local changes") +
          " saved on this device, waiting to sync when you're back online.</div>"
      );
    }

    parts.push('<h2 class="offline-section-title">Tasks (' + openTasks.length + ")</h2>");
    if (openTasks.length === 0) {
      parts.push('<div class="empty-state">No open tasks in the local mirror.</div>');
    } else {
      // Reuses .checklist/.checklist-row/.checklist-check/.checklist-
      // delete -- the same row shape task_detail.html's own checklist
      // widget already establishes for "title + done-toggle + delete" --
      // rather than inventing a second interactive-row style.
      parts.push('<div class="checklist">');
      for (const t of openTasks) {
        parts.push(
          '<div class="checklist-row" data-task-row="' + escapeHtml(t.uid) + '">' +
            '<button type="button" class="checklist-check" data-offline-complete="' + escapeHtml(t.uid) + '" title="Mark done">' +
            iconSvg("square") +
            "</button>" +
            '<span class="checklist-text">' +
            escapeHtml(t.title || "(untitled)") +
            (t.due_at ? ' <span class="search-result-subtitle">due ' + escapeHtml(fmtWhen(t.due_at)) + "</span>" : "") +
            "</span>" +
            '<button type="button" class="checklist-delete btn ghost" data-offline-delete="' + escapeHtml(t.uid) + '" title="Delete task">' +
            iconSvg("trash") +
            "</button></div>"
        );
      }
      parts.push("</div>");
    }

    parts.push('<h2 class="offline-section-title">Upcoming events (' + upcomingEvents.length + ")</h2>");
    if (upcomingEvents.length === 0) {
      parts.push('<div class="empty-state">No upcoming events in the local mirror.</div>');
    } else {
      parts.push('<div class="checklist">');
      for (const e of upcomingEvents) {
        parts.push(
          '<div class="checklist-row"><span class="offline-event-when">' +
            eventWhen(e) +
            "</span>" +
            '<span class="checklist-text">' +
            escapeHtml(e.title || "(untitled)") +
            "</span></div>"
        );
      }
      parts.push("</div>");
    }

    parts.push('<h2 class="offline-section-title">Timetabled events (' + timetabledEvents.length + ")</h2>");
    if (timetabledEvents.length === 0) {
      parts.push('<div class="empty-state">No scheduled work sessions in the local mirror.</div>');
    } else {
      parts.push('<div class="checklist">');
      for (const e of timetabledEvents) {
        parts.push(
          '<div class="checklist-row"><span class="offline-event-when">' +
            eventWhen(e) +
            "</span>" +
            '<span class="checklist-text">' +
            escapeHtml(e.title || "(untitled)") +
            '</span><span class="pill-static pill-blue">Timetabled</span></div>'
        );
      }
      parts.push("</div>");
    }

    root.innerHTML = parts.join("\n");
  }

  function showResult(text, isError) {
    const el = document.getElementById("offline-quick-capture-result");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("is-error", !!isError);
  }

  async function handleQuickCapture(event) {
    const form = event.target.closest("#offline-quick-capture-form");
    if (!form) return;
    event.preventDefault();
    const input = form.elements.capture;
    const text = input.value.trim();
    if (!text) return;
    if (!window.CCOfflineCapture || !window.CCOfflineWrite) {
      showResult("Quick add isn't available on this device.", true);
      return;
    }
    let parsed;
    try {
      parsed = window.CCOfflineCapture.parse(text);
    } catch (err) {
      showResult(err.message, true);
      return;
    }
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      let summary;
      if (parsed.type === "task") {
        const fields = { title: parsed.title };
        if (parsed.due_date_iso) fields.due_at = parsed.due_date_iso + "T00:00:00";
        await window.CCOfflineWrite.createTask(fields);
        summary = "Task added: " + parsed.title;
      } else if (parsed.type === "event") {
        await window.CCOfflineWrite.createEvent({
          title: parsed.title,
          start_at: parsed.start_iso,
          end_at: parsed.end_iso,
          all_day: parsed.all_day ? 1 : 0,
        });
        summary = "Event added: " + parsed.title;
      } else {
        await window.CCOfflineWrite.createContact({ full_name: parsed.title });
        summary = "Contact added: " + parsed.title;
      }
      const skipped = [];
      if (parsed.labels && parsed.labels.length > 0) skipped.push("labels can't be added offline");
      if (parsed.type === "task" && parsed.timeblocks && parsed.timeblocks.length > 0) {
        skipped.push("scheduled time blocks can't be added offline");
      }
      if (parsed.type === "contact" && (parsed.phone || parsed.email)) {
        skipped.push("phone/email can't be added offline");
      }
      if (skipped.length > 0) summary += " (" + skipped.join("; ") + ")";
      showResult(summary, false);
      input.value = "";
    } catch (err) {
      showResult("Couldn't save: " + err.message, true);
    } finally {
      button.disabled = false;
    }
  }

  // Delegated on `root` itself, which survives every re-render (only its
  // innerHTML is replaced) -- attached once, not re-bound per render, per
  // the button/form elements inside it being recreated from scratch each
  // time. The quick-capture form lives outside #offline-local-data (it's
  // static markup in the Quick add panel), so it gets its own listener.
  function wireWriteHandlers() {
    const root = document.getElementById("offline-local-data");
    if (root) {
      root.addEventListener("click", async (event) => {
        const completeBtn = event.target.closest("[data-offline-complete]");
        if (completeBtn) {
          await window.CCOfflineWrite.updateTaskField(completeBtn.getAttribute("data-offline-complete"), "status", "completed");
          return;
        }
        const deleteBtn = event.target.closest("[data-offline-delete]");
        if (deleteBtn) {
          await window.CCOfflineWrite.deleteTask(deleteBtn.getAttribute("data-offline-delete"));
        }
      });
    }
    const form = document.getElementById("offline-quick-capture-form");
    if (form) form.addEventListener("submit", handleQuickCapture);
  }

  function wireTabs() {
    const buttons = document.querySelectorAll("[data-offline-tab]");
    for (const btn of buttons) {
      btn.addEventListener("click", () => {
        const kind = btn.dataset.offlineTab;
        for (const b of buttons) {
          const active = b.dataset.offlineTab === kind;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
        }
        document.querySelectorAll("[data-offline-panel]").forEach((panel) => {
          panel.classList.toggle("is-active", panel.dataset.offlinePanel === kind);
        });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireTabs();
    wireWriteHandlers();
    render();
  });
  // A pull that lands *while* /offline happens to be open (e.g. the
  // network came back mid-visit), or a local write this page's own form/
  // buttons just queued, should refresh this list immediately rather than
  // requiring a reload -- both fire the same event (offline_sync_client.js
  // / offline_write.js).
  document.addEventListener("cc-offline-sync-complete", render);
})();
