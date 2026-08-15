// Shared async-CRUD helpers (design: features/async-crud.md). Replaces the
// "full page reload after every mutation" baseline with server-confirmed
// mutations + targeted region refreshes, loaded globally in base.html so
// every surface (Tasks, Dashboard, Calendar, ...) shares one mechanism.
//
// Conventions:
//   * A mutation endpoint returns JSON when the request carries the
//     `X-Requested-With: fetch` header (ccApi.post always sends it), and
//     its normal 303 Redirect otherwise -- so every existing plain-HTML
//     form keeps working with no JS at all (progressive enhancement).
//   * On success ccApi.post dispatches a document-level `cc-entity-changed`
//     CustomEvent (detail: {type, action, uid}). Each surface owns its own
//     region(s): a listener on that event re-fetches its region fragment
//     via ccApi.refreshRegion and swaps the DOM in place.
//   * Regions are server-rendered fragments that carry the id they belong
//     in (#tasks-body, #widget-<uid>), so refreshRegion can find its
//     container by id alone -- one source of truth, no client-side
//     re-rendering of rows.
//   * PWA/offline (1.8): _send() is the single interception point for the
//     IndexedDB outbox; wire it there, nowhere else.
(function () {
  var FETCH_HEADER = { "X-Requested-With": "fetch" };

  function uidFromUrl(url) {
    var m = String(url || "").match(/\/tasks\/([^/?]+)/);
    return m ? m[1] : undefined;
  }

  // The one place fetch is called -- swap this for the offline outbox later.
  function _send(url, method, body) {
    return fetch(url, { method: method, headers: FETCH_HEADER, body: body });
  }

  // POST a form to a mutation endpoint. Resolves with the parsed JSON body
  // on success; rejects with {message, status} on server/network errors so
  // callers can surface a ccToast and leave the form in place. Opt in to the
  // change event with opts.change = {type, action, uid}.
  function post(url, form, opts) {
    var o = opts || {};
    var body = form instanceof HTMLFormElement ? new FormData(form) : new FormData();
    var resp;
    return _send(url, "POST", body)
      .then(function (r) {
        resp = r;
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (body) {
        if (!resp.ok) {
          var err = new Error(body.error || "Request failed.");
          err.status = resp.status;
          throw err;
        }
        if (o.change) {
          var change = typeof o.change === "string" ? { type: o.change } : o.change;
          document.dispatchEvent(
            new CustomEvent("cc-entity-changed", {
              detail: {
                type: change.type,
                action: change.action || "edit",
                uid: change.uid !== undefined ? change.uid : uidFromUrl(url),
              },
            })
          );
        }
        return body;
      })
      .catch(function (err) {
        if (err && err.status) throw err;
        var netErr = new Error("Could not save -- network error. Please try again.");
        throw netErr;
      });
  }

  // Re-fetch a region fragment and swap it into its container (matched by
  // id, which the fragment itself carries). Safe no-op when the container
  // isn't on this page -- e.g. a task change while the dashboard is showing
  // only event widgets. Throws on failure so callers can fall back to a full
  // reload after a successful mutation.
  function refreshRegion(url, id) {
    var current = id ? document.getElementById(id) : null;
    if (!current) return Promise.resolve();
    current.classList.add("is-refreshing");
    return _send(url, "GET")
      .then(function (resp) {
        if (!resp.ok) throw new Error("region refresh failed");
        return resp.text();
      })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fragment = doc.body.firstElementChild;
        if (!fragment) throw new Error("empty region fragment");
        current.replaceWith(fragment);
        document.dispatchEvent(new CustomEvent("cc-region-swapped", { detail: { id: id } }));
      })
      .finally(function () {
        if (current.isConnected) current.classList.remove("is-refreshing");
      });
  }

  // Generic "mark this done" handler for forms with `data-cc-complete`
  // (dashboard widget check-offs, currently the agenda widget's rows).
  // Posts to the form's own action (POST /tasks/{uid}/complete) with the
  // fetch header and dispatches the change event; the dashboard listener
  // below (cc-entity-changed -> task widgets) owns the card refresh, so
  // there's exactly one refresh path per surface.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.matches || !form.matches("[data-cc-complete]")) return;
    e.preventDefault();
    var btn = form.querySelector("button[type='submit']");
    if (btn) {
      btn.disabled = true;
      btn.classList.add("is-loading");
    }
    post(form.action, form, { change: { type: "task", action: "complete", uid: uidFromUrl(form.action) } })
      .catch(function (err) {
        window.ccToast({ message: err.message || "Could not mark that done.", variant: "error" });
      })
      .finally(function () {
        if (btn) {
          btn.disabled = false;
          btn.classList.remove("is-loading");
        }
      });
  });

  // Dashboard / Space / Project / label pages -- the one surface-level
  // listener for task changes (design §5): re-render every task-affecting
  // widget card (data-widget-uses="tasks") from the server. Skipped in
  // edit mode, because the card fragments render edit_mode=False and a swap
  // would silently drop the drag/edit chrome until the next reload.
  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "task") return;
    var grid = document.getElementById("dashboard-grid");
    if (!grid || grid.classList.contains("is-editing")) return;
    var cards = Array.from(grid.querySelectorAll('.widget-card[data-widget-uses*="tasks"]'));
    cards.forEach(function (card) {
      if (!card.id || !card.dataset.uid) return;
      window.ccApi.refreshRegion("/dashboard/widgets/" + card.dataset.uid, card.id).catch(function () {});
    });
  });

  window.ccApi = { post: post, refreshRegion: refreshRegion };
})();
