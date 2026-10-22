// Browser-side timings for a few named things (see src/perf.py for the names the server accepts). Measurements are
// summed here and sent as one small report when the page is hidden or every five minutes, never one request each.
(function () {
  var LIMITS = { "editor open": 3000, "editor typing": 100, "editor change": 100, "editor save": 2000 };
  var totals = {};

  function add(name, ms) {
    if (!(name in LIMITS) || !(ms >= 0)) return;
    var t = totals[name] || (totals[name] = { count: 0, total: 0, max: 0, slow: 0 });
    t.count += 1;
    t.total += ms;
    t.max = Math.max(t.max, ms);
    if (ms > LIMITS[name]) t.slow += 1;
  }

  function send() {
    if (!Object.keys(totals).length) return;
    var body = JSON.stringify(totals);
    totals = {};
    try {
      navigator.sendBeacon("/perf/report", new Blob([body], { type: "application/json" }));
    } catch (err) {
      // Timing reports are best effort.
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") send();
  });
  window.addEventListener("pagehide", send);
  setInterval(send, 300000);
  window.ccPerf = { add: add };
})();
