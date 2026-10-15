// The markdown rules for typing in the Notebook editor, as pure functions (no DOM) so they run under node
// for tests. notebook_editor.js applies what they return. Cases: curodav-notes/documentation/features/notebook-rework/markdown.md.
(function (root) {
  // ---- Block markers: what typing a marker at the start of a paragraph turns it into ----
  // `before` is the text before the caret in the block, `key` is "Space" or "Enter", `rest` the text after the caret.
  function blockMarker(before, key, rest) {
    var m;
    if (key === "Space") {
      if ((m = /^(#{1,5})$/.exec(before))) return { type: "header", level: m[1].length };
      if (/^[-*+]$/.test(before)) return { type: "list", style: "unordered" };
      if (/^\d+[.)]$/.test(before)) return { type: "list", style: "ordered" };
      if (before === ">") return { type: "quote" };
      if ((m = /^\[( |x|X)\]$/.exec(before))) return { type: "list", style: "checklist", checked: m[1] !== " " };
    }
    if (key === "Enter" && !(rest || "").length) {
      if (before === "```") return { type: "code" };
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(before)) return { type: "delimiter" };
    }
    return null;
  }

  // A heading changes level when `#`s are typed at its start; its level is capped at 5.
  function headingLevelMarker(before) {
    var m = /^(#{1,5})$/.exec(before);
    return m ? m[1].length : 0;
  }

  // ---- Inline markers ----
  // Each rule has a marker, the tags it makes (outermost first) and whether a space may touch it.
  var MARKS = [
    { open: "***", tags: ["b", "i"] },
    { open: "**", tags: ["b"] },
    { open: "~~", tags: ["s"] },
    { open: "*", tags: ["i"] },
    { open: "_", tags: ["i"], word: true },
    { open: "`", tags: ["code"] },
  ];

  function esc(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Called after `typed` was inserted at the caret. `before` is the text up to and including the caret,
  // `after` the text behind it. Returns {start, end, content, tags, consume} or null:
  // the span [start, end) of `before` is replaced by `content` in `tags`, and `consume` characters of `after` are removed.
  function inlineRule(before, after, typed) {
    if (typed === ")") return linkRule(before);
    for (var i = 0; i < MARKS.length; i++) {
      var mark = MARKS[i];
      var o = esc(mark.open);
      var lead = mark.word ? "(^|[^_\\w\\\\])" : "(^|[^" + esc(mark.open.charAt(0)) + "\\\\])";
      var body = "([^" + esc(mark.open.charAt(0)) + "\\s](?:[^" + esc(mark.open.charAt(0)) + "]*[^" + esc(mark.open.charAt(0)) + "\\s])?)";
      // The closing marker was just typed: opener, text and closer all sit before the caret.
      var closing = new RegExp(lead + o + body + o + "$").exec(before);
      if (closing && before.charAt(before.length - 1) === mark.open.charAt(mark.open.length - 1)) {
        if (mark.open === "*" && /\*$/.test(closing[1])) continue;
        var start = before.length - closing[0].length + closing[1].length;
        return { start: start, end: before.length, content: closing[2], tags: mark.tags, consume: 0 };
      }
      // The opening marker was just typed in front of text that already ends with its closer.
      var opened = new RegExp(lead + o + "$").exec(before);
      if (opened) {
        var m = new RegExp("^" + body + o).exec(after);
        var nextChar = after.charAt(m ? m[0].length : 0);
        if (m && !(mark.word && /\w/.test(nextChar)) && !(mark.open.length === 1 && nextChar === mark.open)) {
          return { start: before.length - mark.open.length, end: before.length, content: m[1], tags: mark.tags, consume: m[0].length };
        }
      }
    }
    return null;
  }

  function linkRule(before) {
    var m = /(^|[^\\])\[([^\]\[]+)\]\(([^()\s]+)\)$/.exec(before);
    if (!m || !/^(https?:\/\/|mailto:|\/)/i.test(m[3])) return null;
    var whole = m[0].length - m[1].length;
    return { start: before.length - whole, end: before.length, content: m[2], tags: ["a"], href: m[3], consume: 0 };
  }

  // ---- Wrapping a selection: which tag a typed marker makes, given whether the selection is already italic ----
  function selectionTag(typed, alreadyItalic) {
    if (typed === "*") return alreadyItalic ? "b" : "i";
    if (typed === "_") return "i";
    if (typed === "~") return "s";
    if (typed === "`") return "code";
    return null;
  }

  // What a conversion looked like when typed, so Backspace can bring it back.
  function typedForm(rule) {
    var open = rule.tags.length === 2 ? "***" : { b: "**", i: "*", s: "~~", code: "`" }[rule.tags[0]];
    if (rule.tags[0] === "a") return "[" + rule.content + "](" + rule.href + ")";
    return open + rule.content + open;
  }

  var api = { blockMarker: blockMarker, headingLevelMarker: headingLevelMarker, inlineRule: inlineRule, selectionTag: selectionTag, typedForm: typedForm };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.NotebookTyping = api;
})(typeof window !== "undefined" ? window : globalThis);
