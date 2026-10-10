// Markdown paste for the Notebook editor: turns pasted markdown text into
// Editor.js blocks. The converter is pure (no DOM), so it also runs under
// node for tests; the paste handler at the bottom only runs in a browser.
// Feature notes: curodav-notes/documentation/features/notebook-editor.md.
(function (root) {
  function escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Inline markdown to the inline HTML the editor stores.
  function inline(text) {
    var codes = [];
    var out = escapeHtml(text).replace(/`([^`]+)`/g, function (_, code) {
      codes.push('<code class="inline-code">' + code + "</code>");
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    out = out
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/__([^_]+)__/g, "<b>$1</b>")
      .replace(/~~([^~]+)~~/g, "<s>$1</s>")
      .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<i>$2</i>")
      .replace(/(^|[^_\w])_([^_\s][^_]*?)_(?!\w)/g, "$1<i>$2</i>");
    return out.replace(/\u0000(\d+)\u0000/g, function (_, i) {
      return codes[Number(i)];
    });
  }

  var HEADING = /^(#{1,5})\s+(.*)$/;
  var BULLET = /^(\s*)([-*+])\s+(.*)$/;
  var ORDERED = /^(\s*)(\d+)[.)]\s+(.*)$/;
  var FENCE = /^```\s*([\w+-]*)\s*$/;
  var RULE = /^(-{3,}|\*{3,}|_{3,})\s*$/;
  var TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function splitRow(line) {
    return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map(function (c) {
      return inline(c.trim());
    });
  }

  // Builds nested list items from consecutive list lines.
  function buildList(lines) {
    var style = ORDERED.test(lines[0]) ? "ordered" : "unordered";
    var root = { items: [] };
    var stack = [{ indent: -1, node: root }];
    lines.forEach(function (line) {
      var m = BULLET.exec(line) || ORDERED.exec(line);
      var indent = m[1].replace(/\t/g, "  ").length;
      var item = { content: inline(m[3]), meta: {}, items: [] };
      while (stack.length > 1 && stack[stack.length - 1].indent >= indent) stack.pop();
      stack[stack.length - 1].node.items.push(item);
      stack.push({ indent: indent, node: item });
    });
    return { style: style, items: root.items };
  }

  function toBlocks(markdown) {
    var lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    var blocks = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (!line.trim()) {
        i++;
        continue;
      }
      var m = FENCE.exec(line);
      if (m) {
        var code = [];
        i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) code.push(lines[i++]);
        i++;
        blocks.push({ type: "code", data: { code: code.join("\n"), language: m[1] || "plaintext" } });
        continue;
      }
      if ((m = HEADING.exec(line))) {
        blocks.push({ type: "header", data: { text: inline(m[2].trim()), level: m[1].length } });
        i++;
        continue;
      }
      if (RULE.test(line)) {
        blocks.push({ type: "delimiter", data: { style: "stars" } });
        i++;
        continue;
      }
      if (/^>/.test(line)) {
        var quote = [];
        while (i < lines.length && /^>/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
        blocks.push({ type: "quote", data: { text: inline(quote.join(" ").trim()), caption: "", color: "blue" } });
        continue;
      }
      if (/\|/.test(line) && i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1])) {
        var rows = [splitRow(line)];
        i += 2;
        while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) rows.push(splitRow(lines[i++]));
        blocks.push({ type: "table", data: { withHeadings: true, content: rows } });
        continue;
      }
      if (BULLET.test(line) || ORDERED.test(line)) {
        var list = [];
        while (i < lines.length && (BULLET.test(lines[i]) || ORDERED.test(lines[i]))) list.push(lines[i++]);
        blocks.push({ type: "list", data: buildList(list) });
        continue;
      }
      var para = [];
      while (
        i < lines.length && lines[i].trim() && !HEADING.test(lines[i]) && !FENCE.test(lines[i]) &&
        !RULE.test(lines[i]) && !/^>/.test(lines[i]) && !BULLET.test(lines[i]) && !ORDERED.test(lines[i])
      ) {
        para.push(lines[i++].trim());
      }
      blocks.push({ type: "paragraph", data: { text: inline(para.join(" ")) } });
    }
    return blocks;
  }

  // True when the text holds anything worth converting: a block marker at
  // the start of a line, or inline markers in a multi-line paste.
  function looksLikeMarkdown(text) {
    return (
      /^(#{1,5}\s|[-*+]\s|\d+[.)]\s|>|```|\||---\s*$)/m.test(text) ||
      /\*\*[^*]+\*\*|~~[^~]+~~|`[^`]+`|\[[^\]]+\]\(https?:/.test(text)
    );
  }

  var api = { toBlocks: toBlocks, inline: inline, looksLikeMarkdown: looksLikeMarkdown };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.NotebookMarkdown = api;
})(typeof window !== "undefined" ? window : globalThis);
