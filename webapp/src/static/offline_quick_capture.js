// 2026-08-18 -- the /offline "Quick add" toolbar's single-field capture
// input, parsed entirely client-side (no server to preview against when
// offline). This is a faithful JS port of src/quick_capture.py's grammar
// (plans/quick-capture.md), sharing its token rules so the same sentence
// means the same thing online and offline:
//
//   - An entity marker -- `!t` (task), `!e` (event), `!c` (contact) --
//     selects the type. May appear anywhere; the first marker-looking
//     token wins. `!n` (note) is deliberately rejected: notes aren't part
//     of the sync pool (only task/event/contact are mirrored), so there's
//     no offline write path for one.
//   - `#label` tokens are labels, extracted independently of type. Labels
//     aren't mirrored to a device (object_label ops are commutative, §7a,
//     and never flow through the field-HLC pull/write path), so the shell
//     that calls this parser can't apply them offline -- the parser still
//     extracts them (and strips them from the title, exactly like the
//     Python original) so the shell can honestly report what it skipped.
//   - Dates are `D/M/YYYY` or `D/M` (year inferred: the next occurrence
//     on or after today, per the spec's own short-form examples).
//   - Time ranges are `H:MM-H:MM`.
//   - Every recognized token is whitespace-delimited -- nothing glued to
//     adjacent text is recognized, same as the Python parser.
//
// Exposed as window.CCOfflineCapture.parse(text) -> {type, title, labels,
// due_date_iso, timeblocks, start_iso, end_iso, all_day, phone, email} --
// the same shape as the Python ParsedCapture, so a task's timeblocks are
// still parsed and stripped from the title even though the offline write
// path can't create them (a work allocation needs the server-side
// event_task_relations link, which a device op has no way to express).
// Throws an Error with a user-facing message on any invalid input.
(function () {
  var MARKER_TYPES = { t: "task", e: "event", c: "contact", n: "note" };
  var MARKER_RE = /^!([tecn])$/;
  var LABEL_RE = /^#([^\s#]+)$/;
  var DATE_FULL_RE = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/;
  var DATE_SHORT_RE = /^(\d{1,2})\/(\d{1,2})$/;
  var TIME_RANGE_RE = /^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$/;
  var EMAIL_RE = /^[\w.+-]+@[\w-]+\.[\w.-]+$/;
  var PHONE_RE = /^\+\d{6,15}$/;

  function todayTuple() {
    var d = new Date();
    return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() };
  }

  // Validate by round-tripping through a real Date and checking every
  // component survived -- same guarantee as Python's date() raising on an
  // impossible day (e.g. 2/30).
  function makeDate(y, m, d) {
    var dt = new Date(y, m - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) {
      throw new Error("'" + d + "/" + m + "' isn't a valid date.");
    }
    return { y: y, m: m, d: d };
  }

  function cmpDate(a, b) {
    if (a.y !== b.y) return a.y - b.y;
    if (a.m !== b.m) return a.m - b.m;
    return a.d - b.d;
  }

  function resolveDate(day, month, year, today) {
    if (year !== null) return makeDate(year, month, day);
    // Short form -- the next occurrence of this day/month on or after
    // today: this year unless it has already passed, then next year.
    var candidate = makeDate(today.y, month, day);
    if (cmpDate(candidate, today) < 0) {
      candidate = makeDate(today.y + 1, month, day);
    }
    return candidate;
  }

  function dateIso(d) {
    return (
      d.y + "-" + String(d.m).padStart(2, "0") + "-" + String(d.d).padStart(2, "0")
    );
  }

  function parseDateToken(tok, today) {
    var m = DATE_FULL_RE.exec(tok);
    if (m) {
      return resolveDate(parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10), today);
    }
    m = DATE_SHORT_RE.exec(tok);
    if (m) {
      return resolveDate(parseInt(m[1], 10), parseInt(m[2], 10), null, today);
    }
    return null;
  }

  function parseTimeRangeToken(tok) {
    var m = TIME_RANGE_RE.exec(tok);
    if (!m) return null;
    var h1 = parseInt(m[1], 10), min1 = m[2], h2 = parseInt(m[3], 10), min2 = m[4];
    if (h1 > 23 || h2 > 23 || parseInt(min1, 10) > 59 || parseInt(min2, 10) > 59) {
      throw new Error("'" + tok + "' isn't a valid time range.");
    }
    return { start: String(h1).padStart(2, "0") + ":" + min1, end: String(h2).padStart(2, "0") + ":" + min2 };
  }

  function extractLabels(tokens) {
    var labels = [];
    var consumed = {};
    for (var i = 0; i < tokens.length; i++) {
      var m = LABEL_RE.exec(tokens[i]);
      if (m) {
        labels.push(m[1]);
        consumed[i] = true;
      }
    }
    return { labels: labels, consumed: consumed };
  }

  function parseTask(tokens, today) {
    var labelsInfo = extractLabels(tokens);
    var consumed = labelsInfo.consumed;
    var timeblocks = [];
    var dueDate = null;
    var i = 0;
    while (i < tokens.length) {
      if (consumed[i]) { i += 1; continue; }
      var d = parseDateToken(tokens[i], today);
      if (d !== null) {
        var nxt = i + 1 < tokens.length ? tokens[i + 1] : null;
        var tr = nxt !== null ? parseTimeRangeToken(nxt) : null;
        if (tr !== null) {
          timeblocks.push({ date_iso: dateIso(d), start: tr.start, end: tr.end });
          consumed[i] = true;
          consumed[i + 1] = true;
          i += 2;
          continue;
        }
        consumed[i] = true;
        if (dueDate === null) dueDate = d;
      }
      i += 1;
    }
    var title = joinUnconsumed(tokens, consumed);
    return {
      type: "task",
      title: title,
      labels: labelsInfo.labels,
      due_date_iso: dueDate !== null ? dateIso(dueDate) : null,
      timeblocks: timeblocks,
    };
  }

  function parseEvent(tokens, today) {
    var labelsInfo = extractLabels(tokens);
    var consumed = labelsInfo.consumed;
    var startDate = null;
    var times = null;
    var i = 0;
    while (i < tokens.length) {
      if (consumed[i]) { i += 1; continue; }
      if (startDate === null) {
        var d = parseDateToken(tokens[i], today);
        if (d !== null) {
          startDate = d;
          consumed[i] = true;
          var nxt = i + 1 < tokens.length ? tokens[i + 1] : null;
          var tr = nxt !== null ? parseTimeRangeToken(nxt) : null;
          if (tr !== null) {
            times = tr;
            consumed[i + 1] = true;
            i += 2;
            continue;
          }
        }
      }
      i += 1;
    }
    var title = joinUnconsumed(tokens, consumed);
    var allDay = startDate !== null && times === null;
    var startIso = null, endIso = null;
    if (startDate !== null) {
      var iso = dateIso(startDate);
      if (times !== null) {
        startIso = iso + "T" + times.start + ":00";
        endIso = iso + "T" + times.end + ":00";
      } else {
        startIso = iso + "T00:00:00";
        endIso = iso + "T23:59:00";
      }
    }
    return {
      type: "event",
      title: title,
      labels: labelsInfo.labels,
      start_iso: startIso,
      end_iso: endIso,
      all_day: allDay,
    };
  }

  function parseContact(tokens) {
    var labelsInfo = extractLabels(tokens);
    var consumed = labelsInfo.consumed;
    var phone = null, email = null;
    for (var i = 0; i < tokens.length; i++) {
      if (consumed[i]) continue;
      if (EMAIL_RE.test(tokens[i])) {
        consumed[i] = true;
        if (email === null) email = tokens[i];
      } else if (PHONE_RE.test(tokens[i])) {
        consumed[i] = true;
        if (phone === null) phone = tokens[i];
      }
    }
    var name = joinUnconsumed(tokens, consumed);
    return { type: "contact", title: name, labels: labelsInfo.labels, phone: phone, email: email };
  }

  function joinUnconsumed(tokens, consumed) {
    var kept = [];
    for (var i = 0; i < tokens.length; i++) {
      if (!consumed[i]) kept.push(tokens[i]);
    }
    return kept.join(" ").trim();
  }

  function findMarker(tokens) {
    for (var i = 0; i < tokens.length; i++) {
      var m = MARKER_RE.exec(tokens[i]);
      if (m) return { index: i, type: MARKER_TYPES[m[1]] };
    }
    throw new Error("No entity marker (!t task / !e event / !c contact) found.");
  }

  function parse(text) {
    var tokens = (text || "").split(/\s+/).filter(Boolean);
    if (tokens.length === 0) throw new Error("Nothing to capture.");
    var marker = findMarker(tokens);
    if (marker.type === "note") {
      throw new Error("Notes can't be created offline yet.");
    }
    var remaining = tokens.slice(0, marker.index).concat(tokens.slice(marker.index + 1));
    var today = todayTuple();
    var result =
      marker.type === "task" ? parseTask(remaining, today) :
      marker.type === "event" ? parseEvent(remaining, today) :
      parseContact(remaining);
    if ((marker.type === "task" || marker.type === "contact") && !result.title) {
      throw new Error(marker.type === "task" ? "A task needs a title." : "A contact needs a name.");
    }
    if (marker.type === "event" && !result.title) {
      throw new Error("An event needs a title.");
    }
    return result;
  }

  window.CCOfflineCapture = { parse: parse };
})();