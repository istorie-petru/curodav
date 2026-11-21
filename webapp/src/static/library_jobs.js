/* The Calibre maintenance jobs: starting one opens a toast that stays, with a progress bar, until the job is done. */
(function () {
  var URL = "/settings/library/books/job";
  var toast = null;
  var timer = 0;

  function fraction(s) {
    return s.total ? s.done / s.total : null;
  }

  function show(s) {
    var opts = { title: s.label || "Library", message: s.message || "Working…", icon: "refresh-cw", progress: fraction(s) };
    if (toast && toast.isAlive() && toast.set(opts)) return;
    toast = window.ccToast(Object.assign({ persistent: true, className: "toast-job" }, opts));
  }

  function finish(s) {
    var failed = s.state === "failed";
    var opts = { title: (s.label || "Library") + (failed ? " failed" : " done"), message: s.message || "", icon: failed ? "alert-circle" : "check-circle", variant: failed ? "error" : "default", progress: false };
    if (toast && toast.isAlive() && toast.set(opts)) {
      var t = toast;
      setTimeout(function () { t.dismiss(); }, failed ? 15000 : 8000);
    } else {
      window.ccToast(Object.assign({ duration: failed ? 15000 : 8000 }, opts));
    }
    toast = null;
    setButtons(false);
  }

  function setButtons(busy) {
    document.querySelectorAll("form[data-job-form] button").forEach(function (b) { b.disabled = busy; });
  }

  function poll() {
    clearTimeout(timer);
    fetch(URL, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s.state === "running") {
          show(s);
          setButtons(true);
          timer = setTimeout(poll, 900);
        } else if (toast) {
          finish(s);
        } else {
          setButtons(false);
        }
      })
      .catch(function () { timer = setTimeout(poll, 3000); });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target.closest && e.target.closest("form[data-job-form]");
    if (!form) return;
    e.preventDefault();
    e.stopPropagation();
    var start = function () {
      fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" }, body: new FormData(form) })
        .then(function (r) { return r.json(); })
        .then(function (s) {
          show(Object.assign({ message: "Starting…" }, s, { state: "running" }));
          setButtons(true);
          timer = setTimeout(poll, 600);
        })
        .catch(function () { window.ccToast({ message: "Could not start that", variant: "error" }); });
    };
    var sheet = form.getAttribute("data-confirm-sheet");
    if (sheet && window.ccConfirmSheet) window.ccConfirmSheet({ message: sheet, confirmLabel: "Run", onConfirm: start });
    else start();
  }, true);

  // The Ratings window shows the criteria as soon as Advanced rating is switched on.
  document.addEventListener("change", function (e) {
    if (!e.target.matches || !e.target.matches("#ratings-advanced")) return;
    document.querySelectorAll("[data-advanced-only]").forEach(function (el) { el.hidden = !e.target.checked; });
  });

  // A job started earlier (or from another page) keeps its toast when this page opens.
  document.addEventListener("DOMContentLoaded", function () {
    if (document.querySelector("form[data-job-form]")) poll();
  });
})();
