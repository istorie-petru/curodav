// 1.8 slices 4-5 + 2026-08-18 rework + 2026-08-19 Offline Mode page --
// renders /offline's content straight from the local IndexedDB mirror
// (offline_db.js), no network request of its own. This is the one page in
// this slice that actually reads *and now writes* the local store -- every
// other page is untouched server-rendered HTML, per §0's "a second
// read/write path alongside the server-rendered one, not a replacement."
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
// is_work_allocation field) -- in the same agenda-style sections the
// dashboard's Agenda widget uses. "Quick add" is a single-field capture
// input (offline_quick_capture.js's parser) whose submissions go through
// CCOfflineWrite.createTask/createEvent/createContact. Labels and a task's
// scheduled time blocks are parsed but can't be applied offline (labels
// never flow through the field-HLC pull/write path, and a work allocation
// needs the server-side event_task_relations link a device op can't
// express); a contact's phone/email are dropped too (they live in child
// tables outside the sync protocol) -- each skip is reported honestly in
// the result line rather than silently ignored.
//
// 2026-08-19 -- Dedicated Offline Mode page: full tabbed interface mirroring
// the main app navigation (Dashboard, Calendar, Tasks, Contacts, Notes)
// with read/write access to the local IndexedDB mirror. Quick add is now a
// floating action button on every tab. This file now renders all five
// panels from the local mirror.
//
// 2026-08-19 (expansion) -- Merge Upcoming and Quick Add into single view:
// each panel now shows its data with an integrated visual Quick Add builder
// (entity type dropdown, label picker, date/time inputs) instead of a
// separate modal. The floating FAB and modal are removed.
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
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&", "<": "<", ">": ">", '"': """, "'": "'" }[c]));
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

  function getTodayString() {
    const now = new Date();
    return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
  }

  // Quick Add Builder state per panel
  const quickAddState = {
    currentPanel: "dashboard",
    selectedEntityType: "task",
    labels: [],
  };

  async function render() {
    const [tasks, events, contacts, notes, lastSynced, outboxCount] = await Promise.all([
      window.CCOfflineDB.getAllTasks ? window.CCOfflineDB.getAllTasks() : Promise.resolve([]),
      window.CCOfflineDB.getAllEvents ? window.CCOfflineDB.getAllEvents() : Promise.resolve([]),
      window.CCOfflineDB.getAllContacts ? window.CCOfflineDB.getAllContacts() : Promise.resolve([]),
      window.CCOfflineDB.getAllNotes ? window.CCOfflineDB.getAllNotes() : Promise.resolve([]),
      window.CCOfflineDB.getLastSyncedAt ? window.CCOfflineDB.getLastSyncedAt() : Promise.resolve(null),
      window.CCOfflineDB.getOutboxCount ? window.CCOfflineDB.getOutboxCount() : Promise.resolve(0),
    ]);

    // Collect all unique labels from tasks and events
    const allLabels = new Set();
    for (const t of tasks) {
      if (t.tags) t.tags.forEach(l => allLabels.add(l));
    }
    for (const e of events) {
      if (e.tags) e.tags.forEach(l => allLabels.add(l));
    }
    quickAddState.labels = Array.from(allLabels).sort();

    // Common header for all panels
    const syncedHtml = '<div class="offline-synced-at">Last synced from this device: ' + (lastSynced ? fmtWhen(lastSynced) : "never") + "</div>";
    const pendingHtml = outboxCount > 0
      ? '<div class="offline-pending-note">' + outboxCount + (outboxCount === 1 ? " local change" : " local changes") + " saved on this device, waiting to sync when you're back online.</div>"
      : "";

    // Dashboard Panel
    const dashboardRoot = document.getElementById("offline-dashboard");
    const dashboardEmpty = document.getElementById("offline-dashboard-empty");
    if (dashboardRoot) {
      if (dashboardEmpty) dashboardEmpty.style.display = "none";
      const openTasks = tasks.filter((t) => t.status !== "completed").length;
      const upcomingEvents = events.filter((e) => e.start_at && e.start_at.slice(0, 10) >= getTodayString()).length;
      const timetabledCount = events.filter((e) => e.is_work_allocation && e.start_at && e.start_at.slice(0, 10) >= getTodayString()).length;
      const contactCount = contacts.length;
      const noteCount = notes.length;

      let html = syncedHtml + pendingHtml;
      html += '<div class="offline-dashboard-grid">';
      html += '<div class="offline-dashboard-card"><h3>' + openTasks + '</h3><p>Open Tasks</p></div>';
      html += '<div class="offline-dashboard-card"><h3>' + upcomingEvents + '</h3><p>Upcoming Events</p></div>';
      html += '<div class="offline-dashboard-card"><h3>' + timetabledCount + '</h3><p>Timetabled Sessions</p></div>';
      html += '<div class="offline-dashboard-card"><h3>' + contactCount + '</h3><p>Contacts</p></div>';
      html += '<div class="offline-dashboard-card"><h3>' + noteCount + '</h3><p>Notes</p></div>';
      html += '</div>';

      if (openTasks === 0 && upcomingEvents === 0 && contactCount === 0 && noteCount === 0) {
        html += '<div class="empty-state">No local data yet. Use Quick Add below to get started.</div>';
      }
      dashboardRoot.innerHTML = html;
    }

    // Calendar Panel
    const calendarRoot = document.getElementById("offline-calendar");
    const calendarEmpty = document.getElementById("offline-calendar-empty");
    if (calendarRoot) {
      if (calendarEmpty) calendarEmpty.style.display = "none";
      const today = getTodayString();
      const upcomingEvents = events
        .filter((e) => !e.is_work_allocation && e.start_at && e.start_at.slice(0, 10) >= today)
        .sort(byStartAt);
      const timetabledEvents = events
        .filter((e) => e.is_work_allocation && e.start_at && e.start_at.slice(0, 10) >= today)
        .sort(byStartAt);

      let html = syncedHtml + pendingHtml;
      html += '<h2 class="offline-section-title">Upcoming Events (' + upcomingEvents.length + ")</h2>";
      if (upcomingEvents.length === 0) {
        html += '<div class="empty-state">No upcoming events in the local mirror.</div>';
      } else {
        html += '<div class="checklist">';
        for (const e of upcomingEvents) {
          html += '<div class="checklist-row"><span class="offline-event-when">' + eventWhen(e) + '</span><span class="checklist-text">' + escapeHtml(e.title || "(untitled)") + '</span></div>';
        }
        html += '</div>';
      }

      html += '<h2 class="offline-section-title">Timetabled Sessions (' + timetabledEvents.length + ")</h2>";
      if (timetabledEvents.length === 0) {
        html += '<div class="empty-state">No scheduled work sessions in the local mirror.</div>';
      } else {
        html += '<div class="checklist">';
        for (const e of timetabledEvents) {
          html += '<div class="checklist-row"><span class="offline-event-when">' + eventWhen(e) + '</span><span class="checklist-text">' + escapeHtml(e.title || "(untitled)") + '</span><span class="pill-static pill-blue">Timetabled</span></div>';
        }
        html += '</div>';
      }
      calendarRoot.innerHTML = html;
    }

    // Tasks Panel
    const tasksRoot = document.getElementById("offline-tasks");
    const tasksEmpty = document.getElementById("offline-tasks-empty");
    if (tasksRoot) {
      if (tasksEmpty) tasksEmpty.style.display = "none";
      const openTasks = tasks.filter((t) => t.status !== "completed").sort((a, b) => (a.due_at || "9999").localeCompare(b.due_at || "9999"));
      const completedTasks = tasks.filter((t) => t.status === "completed").sort((a, b) => (a.completed_at || "9999").localeCompare(b.completed_at || "9999"));

      let html = syncedHtml + pendingHtml;
      html += '<h2 class="offline-section-title">Open Tasks (' + openTasks.length + ")</h2>";
      if (openTasks.length === 0) {
        html += '<div class="empty-state">No open tasks in the local mirror.</div>';
      } else {
        html += '<div class="checklist">';
        for (const t of openTasks) {
          html += '<div class="checklist-row" data-task-row="' + escapeHtml(t.uid) + '"><button type="button" class="checklist-check" data-offline-complete="' + escapeHtml(t.uid) + '" title="Mark done">' + iconSvg("square") + '</button><span class="checklist-text">' + escapeHtml(t.title || "(untitled)") + (t.due_at ? ' <span class="search-result-subtitle">due ' + escapeHtml(fmtWhen(t.due_at)) + '</span>' : '') + '</span><button type="button" class="checklist-delete btn ghost" data-offline-delete="' + escapeHtml(t.uid) + '" title="Delete task">' + iconSvg("trash") + '</button></div>';
        }
        html += '</div>';
      }

      if (completedTasks.length > 0) {
        html += '<h2 class="offline-section-title">Completed Tasks (' + completedTasks.length + ")</h2>";
        html += '<div class="checklist">';
        for (const t of completedTasks) {
          html += '<div class="checklist-row"><span class="checklist-text">' + escapeHtml(t.title || "(untitled)") + (t.completed_at ? ' <span class="search-result-subtitle">completed ' + escapeHtml(fmtWhen(t.completed_at)) + '</span>' : '') + '</span></div>';
        }
        html += '</div>';
      }
      tasksRoot.innerHTML = html;
    }

    // Contacts Panel
    const contactsRoot = document.getElementById("offline-contacts");
    const contactsEmpty = document.getElementById("offline-contacts-empty");
    if (contactsRoot) {
      if (contactsEmpty) contactsEmpty.style.display = "none";
      let html = syncedHtml + pendingHtml;
      html += '<h2 class="offline-section-title">Contacts (' + contacts.length + ")</h2>";
      if (contacts.length === 0) {
        html += '<div class="empty-state">No contacts in the local mirror.</div>';
      } else {
        html += '<div class="checklist">';
        for (const c of contacts) {
          html += '<div class="checklist-row"><span class="checklist-text">' + escapeHtml(c.full_name || c.title || "(unnamed)") + (c.email ? ' <span class="search-result-subtitle">' + escapeHtml(c.email) + '</span>' : '') + '</span><button type="button" class="checklist-delete btn ghost" data-offline-delete-contact="' + escapeHtml(c.uid) + '" title="Delete contact">' + iconSvg("trash") + '</button></div>';
        }
        html += '</div>';
      }
      contactsRoot.innerHTML = html;
    }

    // Notes Panel
    const notesRoot = document.getElementById("offline-notes");
    const notesEmpty = document.getElementById("offline-notes-empty");
    if (notesRoot) {
      if (notesEmpty) notesEmpty.style.display = "none";
      let html = syncedHtml + pendingHtml;
      html += '<h2 class="offline-section-title">Notes (' + notes.length + ")</h2>";
      if (notes.length === 0) {
        html += '<div class="empty-state">No notes in the local mirror.</div>';
      } else {
        html += '<div class="checklist">';
        for (const n of notes) {
          const content = n.content || "";
          const preview = content.length > 100 ? content.slice(0, 100) + "..." : content;
          html += '<div class="checklist-row"><span class="checklist-text">' + escapeHtml(preview) + (n.updated_at ? ' <span class="search-result-subtitle">updated ' + escapeHtml(fmtWhen(n.updated_at)) + '</span>' : '') + '</span><button type="button" class="checklist-delete btn ghost" data-offline-delete-note="' + escapeHtml(n.uid) + '" title="Delete note">' + iconSvg("trash") + '</button></div>';
        }
        html += '</div>';
      }
      notesRoot.innerHTML = html;
    }

    // Initialize Quick Add builders for all panels
    initializeQuickAddBuilders();
  }

  function initializeQuickAddBuilders() {
    const builders = document.querySelectorAll("[data-offline-quick-add]");
    for (const builder of builders) {
      const form = builder.querySelector("#offline-quick-add-form");
      if (!form) continue;
      
      const entityTypeSelect = builder.querySelector("#offline-entity-type");
      const taskFields = builder.querySelector("#offline-task-fields");
      const eventFields = builder.querySelector("#offline-event-fields");
      const contactFields = builder.querySelector("#offline-contact-fields");
      const noteFields = builder.querySelector("#offline-note-fields");
      const labelsSelectTask = builder.querySelector("#offline-task-labels");
      const labelsSelectEvent = builder.querySelector("#offline-event-labels");
      const captureText = builder.querySelector("#offline-capture-text");
      const cancelBtn = builder.querySelector("#offline-quick-add-cancel");
      const resultEl = builder.querySelector("#offline-quick-add-result");

      // Populate label multiselects
      populateLabelSelect(labelsSelectTask);
      populateLabelSelect(labelsSelectEvent);

      // Entity type change handler
      if (entityTypeSelect) {
        entityTypeSelect.addEventListener("change", () => {
          const type = entityTypeSelect.value;
          quickAddState.selectedEntityType = type;
          // Show/hide fieldsets
          taskFields.hidden = type !== "task";
          eventFields.hidden = type !== "event";
          contactFields.hidden = type !== "contact";
          noteFields.hidden = type !== "note";
          updateCaptureText();
        });
      }

      // Input change handlers to update capture text
      const inputs = builder.querySelectorAll("input, select, textarea");
      for (const input of inputs) {
        input.addEventListener("input", updateCaptureText);
        input.addEventListener("change", updateCaptureText);
      }

      // Capture text manual edit
      if (captureText) {
        captureText.addEventListener("input", () => {
          // Allow manual editing of capture text
        });
      }

      // Cancel button
      if (cancelBtn) {
        cancelBtn.addEventListener("click", () => {
          form.reset();
          updateCaptureText();
          if (resultEl) resultEl.textContent = "";
        });
      }

      // Form submit
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        await handleQuickAddSubmit(builder, form, resultEl);
      });

      // Initial capture text
      updateCaptureText();
    }
  }

  function populateLabelSelect(select) {
    if (!select) return;
    select.innerHTML = "";
    for (const label of quickAddState.labels) {
      const opt = document.createElement("option");
      opt.value = label;
      opt.textContent = label;
      select.appendChild(opt);
    }
  }

  function updateCaptureText() {
    const builders = document.querySelectorAll("[data-offline-quick-add]");
    for (const builder of builders) {
      const entityTypeSelect = builder.querySelector("#offline-entity-type");
      const captureText = builder.querySelector("#offline-capture-text");
      if (!entityTypeSelect || !captureText) continue;

      const type = entityTypeSelect.value;
      let parts = [];

      if (type === "task") {
        const title = builder.querySelector("#offline-task-title")?.value?.trim();
        const due = builder.querySelector("#offline-task-due")?.value;
        const labels = Array.from(builder.querySelector("#offline-task-labels")?.selectedOptions || []).map(o => o.value);
        if (title) parts.push("!t " + title);
        if (due) parts.push(due.split("-").reverse().join("/")); // YYYY-MM-DD -> DD/MM/YYYY (actually D/M format)
        for (const label of labels) parts.push("#" + label);
      } else if (type === "event") {
        const title = builder.querySelector("#offline-event-title")?.value?.trim();
        const start = builder.querySelector("#offline-event-start")?.value;
        const end = builder.querySelector("#offline-event-end")?.value;
        const allDay = builder.querySelector("#offline-event-all-day")?.checked;
        const labels = Array.from(builder.querySelector("#offline-event-labels")?.selectedOptions || []).map(o => o.value);
        if (title) parts.push("!e " + title);
        if (start) {
          const datePart = start.split("T")[0];
          const timePart = start.split("T")[1];
          if (!allDay && timePart) {
            parts.push(datePart.split("-").reverse().join("/") + " " + timePart);
          } else {
            parts.push(datePart.split("-").reverse().join("/"));
          }
        }
        if (end && !allDay) {
          const endTime = end.split("T")[1];
          if (endTime) parts[parts.length - 1] += "-" + endTime;
        }
        for (const label of labels) parts.push("#" + label);
      } else if (type === "contact") {
        const name = builder.querySelector("#offline-contact-name")?.value?.trim();
        const email = builder.querySelector("#offline-contact-email")?.value?.trim();
        const phone = builder.querySelector("#offline-contact-phone")?.value?.trim();
        if (name) parts.push("!c " + name);
        if (email) parts.push(email);
        if (phone) parts.push(phone);
      } else if (type === "note") {
        const content = builder.querySelector("#offline-note-content")?.value?.trim();
        if (content) parts.push("!n " + content);
      }

      captureText.value = parts.join(" ");
    }
  }

  async function handleQuickAddSubmit(builder, form, resultEl) {
    const entityTypeSelect = builder.querySelector("#offline-entity-type");
    const type = entityTypeSelect?.value || quickAddState.selectedEntityType;
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    try {
      let summary;
      if (type === "task") {
        const title = builder.querySelector("#offline-task-title")?.value?.trim();
        const due = builder.querySelector("#offline-task-due")?.value;
        const labels = Array.from(builder.querySelector("#offline-task-labels")?.selectedOptions || []).map(o => o.value);
        if (!title) throw new Error("Task title is required");
        const fields = { title };
        if (due) fields.due_at = due + "T00:00:00";
        await window.CCOfflineWrite.createTask(fields);
        summary = "Task added: " + title;
        if (labels.length > 0) summary += " (labels can't be added offline)";
      } else if (type === "event") {
        const title = builder.querySelector("#offline-event-title")?.value?.trim();
        const start = builder.querySelector("#offline-event-start")?.value;
        const end = builder.querySelector("#offline-event-end")?.value;
        const allDay = builder.querySelector("#offline-event-all-day")?.checked;
        const labels = Array.from(builder.querySelector("#offline-event-labels")?.selectedOptions || []).map(o => o.value);
        if (!title) throw new Error("Event title is required");
        if (!start) throw new Error("Event start date/time is required");
        await window.CCOfflineWrite.createEvent({
          title,
          start_at: allDay ? start.split("T")[0] + "T00:00:00" : start,
          end_at: allDay ? start.split("T")[0] + "T23:59:59" : (end || start),
          all_day: allDay ? 1 : 0,
        });
        summary = "Event added: " + title;
        if (labels.length > 0) summary += " (labels can't be added offline)";
      } else if (type === "contact") {
        const name = builder.querySelector("#offline-contact-name")?.value?.trim();
        const email = builder.querySelector("#offline-contact-email")?.value?.trim();
        const phone = builder.querySelector("#offline-contact-phone")?.value?.trim();
        if (!name) throw new Error("Contact name is required");
        await window.CCOfflineWrite.createContact({ full_name: name });
        summary = "Contact added: " + name;
        if (email || phone) summary += " (phone/email can't be added offline)";
      } else if (type === "note") {
        const content = builder.querySelector("#offline-note-content")?.value?.trim();
        if (!content) throw new Error("Note content is required");
        await window.CCOfflineWrite.createNote({ content });
        summary = "Note added";
      }

      if (resultEl) {
        resultEl.textContent = summary;
        resultEl.classList.remove("is-error");
      }
      form.reset();
      updateCaptureText();
    } catch (err) {
      if (resultEl) {
        resultEl.textContent = "Couldn't save: " + err.message;
        resultEl.classList.add("is-error");
      }
    } finally {
      submitBtn.disabled = false;
    }
  }

  function wireWriteHandlers() {
    // Tasks
    const tasksRoot = document.getElementById("offline-tasks");
    if (tasksRoot) {
      tasksRoot.addEventListener("click", async (event) => {
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

    // Contacts
    const contactsRoot = document.getElementById("offline-contacts");
    if (contactsRoot) {
      contactsRoot.addEventListener("click", async (event) => {
        const deleteBtn = event.target.closest("[data-offline-delete-contact]");
        if (deleteBtn) {
          await window.CCOfflineWrite.deleteContact(deleteBtn.getAttribute("data-offline-delete-contact"));
        }
      });
    }

    // Notes
    const notesRoot = document.getElementById("offline-notes");
    if (notesRoot) {
      notesRoot.addEventListener("click", async (event) => {
        const deleteBtn = event.target.closest("[data-offline-delete-note]");
        if (deleteBtn) {
          await window.CCOfflineWrite.deleteNote(deleteBtn.getAttribute("data-offline-delete-note"));
        }
      });
    }
  }

  function wireTabs() {
    const buttons = document.querySelectorAll("[data-offline-main-tab]");
    for (const btn of buttons) {
      btn.addEventListener("click", () => {
        const kind = btn.dataset.offlineMainTab;
        for (const b of buttons) {
          const active = b.dataset.offlineMainTab === kind;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
        }
        document.querySelectorAll("[data-offline-main-panel]").forEach((panel) => {
          panel.classList.toggle("is-active", panel.dataset.offlineMainPanel === kind);
        });
        quickAddState.currentPanel = kind;
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