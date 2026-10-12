// Grays out every calendar/planner item that already ended, judged against the current time
// (the server only knows whole past days). Re-runs every minute and after a region refresh.
(function () {
  var SELECTOR = ".time-event, .month-event-item, .month-bar, .allday-bar, .sec-row[data-start], tr[data-start]";

  function parse(value, endOfDay) {
    if (!value) return null;
    var d = new Date(value.length === 10 ? value + (endOfDay ? "T23:59:59" : "T00:00:00") : value);
    return isNaN(d) ? null : d;
  }

  // Recurring items carry no data-start; fall back to the column date and the printed time.
  function fromText(el) {
    var col = el.closest("[data-date]");
    var time = el.querySelector(".te-time");
    if (!col || !time) return null;
    var found = time.textContent.match(/(\d{1,2}):(\d{2})\s*([AP]M)?/gi);
    if (!found) return null;
    var m = /(\d{1,2}):(\d{2})\s*([AP]M)?/i.exec(found[found.length - 1]);
    var h = Number(m[1]) % 12 + (m[3] && /p/i.test(m[3]) ? 12 : 0);
    if (!m[3]) h = Number(m[1]);
    return new Date(col.dataset.date + "T" + String(h).padStart(2, "0") + ":" + m[2] + ":00");
  }

  function mark() {
    var now = new Date();
    document.querySelectorAll(SELECTOR).forEach(function (el) {
      var end = null;
      if (el.dataset.start !== undefined) {
        var allDay = el.dataset.allDay === "1" || el.classList.contains("allday-bar") || el.classList.contains("month-bar");
        end = parse(el.dataset.end, allDay) || parse(el.dataset.start, allDay);
      } else {
        end = fromText(el);
      }
      el.classList.toggle("is-time-past", !!end && end < now);
    });
  }

  var timer = null;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(mark, 60);
  }
  new MutationObserver(function (list) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].addedNodes.length) { schedule(); return; }
    }
  }).observe(document.body, { childList: true, subtree: true });
  setInterval(mark, 60000);
  mark();
})();
