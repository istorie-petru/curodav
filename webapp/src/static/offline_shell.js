// 1.8 slice 4 -- renders /offline's content straight from the local
// IndexedDB mirror (offline_db.js), no network request of its own. This
// is the one page in this slice that actually reads the local store --
// every other page is untouched server-rendered HTML, per §0's "a second
// read/write path alongside the server-rendered one, not a replacement."
//
// Read-only and deliberately partial: labels/tags aren't mirrored locally
// yet (object_label ops are commutative, §7a, and never flow through the
// field-HLC pull this slice mirrors -- see offline_db.js's own note), so
// this list shows title/due/status/time only, not a project pill the way
// the real Tasks/Calendar pages do. That's an honest scope line, not a
// bug: a fuller offline view is exactly the kind of thing a later slice
// can add once there's an outbox (slice 5) worth building a real UI atop.
(function () {
  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString();
  }

  async function render() {
    const root = document.getElementById("offline-local-data");
    if (!root || !("indexedDB" in window)) return;

    const [tasks, events, lastSynced] = await Promise.all([
      window.CCOfflineDB.getAllTasks(),
      window.CCOfflineDB.getAllEvents(),
      window.CCOfflineDB.getLastSyncedAt(),
    ]);

    if (!lastSynced) {
      // Never successfully synced from this device before (fresh
      // install, or online but the very first pull hasn't landed yet) --
      // nothing local to show. The static empty-state markup
      // offline.html itself renders already covers this case; leave it
      // alone rather than replacing it with an equally-empty "0 tasks"
      // list.
      return;
    }

    const emptyState = document.getElementById("offline-empty-state");
    if (emptyState) emptyState.style.display = "none";

    const openTasks = tasks
      .filter((t) => t.status !== "completed")
      .sort((a, b) => (a.due_at || "9999").localeCompare(b.due_at || "9999"))
      .slice(0, 10);

    const upcomingEvents = events
      .slice()
      .sort((a, b) => (a.start_at || "9999").localeCompare(b.start_at || "9999"))
      .slice(0, 10);

    const parts = [];
    parts.push('<div class="offline-synced-at">Last synced from this device: ' + fmtWhen(lastSynced) + "</div>");

    parts.push('<h2 class="offline-section-title">Tasks (' + openTasks.length + ")</h2>");
    if (openTasks.length === 0) {
      parts.push('<div class="empty-state">No open tasks in the local mirror.</div>');
    } else {
      // Reuses .checklist/.checklist-row/.checklist-text -- the same
      // plain-row list styling search.html's own results list uses
      // (style.css's own comment: "a plain .checklist") -- rather than
      // inventing a second list style for what's visually the same
      // "icon-free row of title + trailing meta" shape.
      parts.push('<div class="checklist">');
      for (const t of openTasks) {
        parts.push(
          '<div class="checklist-row"><span class="checklist-text">' +
            escapeHtml(t.title || "(untitled)") +
            (t.due_at ? ' <span class="search-result-subtitle">due ' + escapeHtml(fmtWhen(t.due_at)) + "</span>" : "") +
            "</span></div>"
        );
      }
      parts.push("</div>");
    }

    parts.push('<h2 class="offline-section-title">Events (' + upcomingEvents.length + ")</h2>");
    if (upcomingEvents.length === 0) {
      parts.push('<div class="empty-state">No events in the local mirror.</div>');
    } else {
      parts.push('<div class="checklist">');
      for (const e of upcomingEvents) {
        parts.push(
          '<div class="checklist-row"><span class="checklist-text">' +
            escapeHtml(e.title || "(untitled)") +
            (e.start_at ? ' <span class="search-result-subtitle">' + escapeHtml(fmtWhen(e.start_at)) + "</span>" : "") +
            "</span></div>"
        );
      }
      parts.push("</div>");
    }

    root.innerHTML = parts.join("\n");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  document.addEventListener("DOMContentLoaded", render);
  // A pull that lands *while* /offline happens to be open (e.g. the
  // network came back mid-visit) should refresh this list immediately
  // rather than requiring a reload.
  document.addEventListener("cc-offline-sync-complete", render);
})();
