// Notebook table model: the pure part of the table tool (no DOM). Formulas, structure changes,
// sorting, paste parsing and export. It also runs under node, which is how it is tested.
// Feature notes: curodav-notes/documentation/features/notebook-tables.md.
(function (root) {
  var ERR = { REF: "#REF!", DIV: "#DIV/0!", NAME: "#NAME?", VALUE: "#VALUE!", PARSE: "#ERR", CYCLE: "#CYCLE" };

  function colName(index) {
    var name = "";
    for (var n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
    return name;
  }

  function colIndex(letters) {
    var n = 0;
    for (var i = 0; i < letters.length; i++) n = n * 26 + (letters.charCodeAt(i) - 64);
    return n - 1;
  }

  function parseRef(text) {
    var m = /^([A-Z]{1,3})(\d+)$/.exec(text);
    return m ? { r: Number(m[2]) - 1, c: colIndex(m[1]) } : null;
  }

  function refText(r, c) {
    return colName(c) + (r + 1);
  }

  function stripHtml(html) {
    return String(html == null ? "" : html)
      .replace(/<br\s*\/?>/gi, " ")
      .replace(/<[^>]*>/g, "")
      .replace(/&nbsp;/g, " ")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&")
      .trim();
  }

  // A formula is stored as plain text starting with "="; text wrapped in markup is also accepted.
  function plainFormula(raw) {
    if (typeof raw !== "string") return null;
    var t = raw.trim();
    // Saved text is HTML-escaped by the editor, so "&", "<" and ">" in a formula come back escaped.
    if (t.charAt(0) === "=") return t.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&amp;/g, "&");
    var stripped = stripHtml(raw);
    return stripped.charAt(0) === "=" ? stripped : null;
  }

  function isFormula(raw) {
    return plainFormula(raw) !== null;
  }

  function formulaText(raw) {
    return plainFormula(raw).slice(1);
  }

  function toNumber(text) {
    if (text === "") return null;
    var cleaned = text.replace(/[\s ]/g, "").replace(/,(?=\d{3}(\D|$))/g, "");
    if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?%?$/i.test(cleaned)) return null;
    var pct = cleaned.charAt(cleaned.length - 1) === "%";
    var n = Number(pct ? cleaned.slice(0, -1) : cleaned);
    return pct ? n / 100 : n;
  }

  // ---- Formula tokenizer, parser and evaluator -------------------------------
  function tokenize(src) {
    var tokens = [];
    var re = /\s*(?:(\d+\.?\d*|\.\d+)|"((?:[^"]|"")*)"|([A-Za-z_][A-Za-z_0-9]*)|(<>|<=|>=|.))/g;
    var m;
    while ((m = re.exec(src)) && m[0] !== "") {
      if (m[1] !== undefined) tokens.push({ t: "num", v: Number(m[1]) });
      else if (m[2] !== undefined) tokens.push({ t: "str", v: m[2].replace(/""/g, '"') });
      else if (m[3] !== undefined) tokens.push({ t: "id", v: m[3].toUpperCase() });
      else if (/\S/.test(m[4])) tokens.push({ t: "op", v: m[4] });
    }
    return tokens;
  }

  function FormulaError(code) {
    this.code = code;
  }

  function parse(src) {
    var tokens = tokenize(src);
    var pos = 0;
    function peek() { return tokens[pos]; }
    function next() { return tokens[pos++]; }
    function isOp(v) { var t = peek(); return t && t.t === "op" && t.v === v; }
    function fail() { throw new FormulaError(ERR.PARSE); }

    function expr() {
      var node = concat();
      while (isOp("=") || isOp("<") || isOp(">") || isOp("<=") || isOp(">=") || isOp("<>")) {
        node = { k: "bin", op: next().v, a: node, b: concat() };
      }
      return node;
    }
    function concat() {
      var node = sum();
      while (isOp("&")) node = { k: "bin", op: next().v, a: node, b: sum() };
      return node;
    }
    function sum() {
      var node = term();
      while (isOp("+") || isOp("-")) node = { k: "bin", op: next().v, a: node, b: term() };
      return node;
    }
    function term() {
      var node = unary();
      while (isOp("*") || isOp("/")) node = { k: "bin", op: next().v, a: node, b: unary() };
      return node;
    }
    function unary() {
      if (isOp("-")) { next(); return { k: "neg", a: unary() }; }
      if (isOp("+")) { next(); return unary(); }
      return primary();
    }
    function primary() {
      var t = next();
      if (!t) fail();
      if (t.t === "num") return { k: "num", v: t.v };
      if (t.t === "str") return { k: "str", v: t.v };
      if (t.t === "op" && t.v === "(") {
        var inner = expr();
        if (!isOp(")")) fail();
        next();
        return inner;
      }
      if (t.t === "id") {
        if (isOp("(")) {
          next();
          var args = [];
          if (!isOp(")")) {
            args.push(expr());
            while (isOp(",")) { next(); args.push(expr()); }
          }
          if (!isOp(")")) fail();
          next();
          return { k: "call", name: t.v, args: args };
        }
        if (t.v === "ABOVE" || t.v === "LEFT") return { k: "run", dir: t.v };
        var ref = parseRef(t.v);
        if (!ref) throw new FormulaError(ERR.NAME);
        if (isOp(":")) {
          next();
          var end = next();
          var endRef = end && end.t === "id" ? parseRef(end.v) : null;
          if (!endRef) fail();
          return { k: "range", from: ref, to: endRef };
        }
        return { k: "ref", r: ref.r, c: ref.c };
      }
      return fail();
    }
    var tree = expr();
    if (pos < tokens.length) fail();
    return tree;
  }

  // `grid` is the raw content; `merges` lists {r, c, rs, cs}. Returns a matrix of
  // {v, text, err}: v is a number or string, text the display text, err an error code.
  function evaluate(grid, merges) {
    var rows = grid.length;
    var cols = rows ? Math.max.apply(null, grid.map(function (row) { return row.length; })) : 0;
    var cache = {};
    var visiting = {};
    var covered = coveredMap(merges || []);

    function raw(r, c) {
      return grid[r] && grid[r][c] != null ? grid[r][c] : "";
    }

    function cell(r, c) {
      if (r < 0 || c < 0 || r >= rows || c >= cols) throw new FormulaError(ERR.REF);
      var key = r + "," + c;
      if (covered[key]) return { v: "", text: "", err: null };
      if (cache[key]) return cache[key];
      if (visiting[key]) throw new FormulaError(ERR.CYCLE);
      var out;
      if (isFormula(raw(r, c))) {
        visiting[key] = true;
        try {
          var value = run(parse(formulaText(raw(r, c))), r, c);
          out = { v: value, text: formatValue(value), err: null };
        } catch (e) {
          if (!(e instanceof FormulaError)) throw e;
          out = { v: "", text: e.code, err: e.code };
        }
        delete visiting[key];
      } else {
        var text = stripHtml(raw(r, c));
        var n = toNumber(text);
        out = { v: n === null ? text : n, text: text, err: null };
      }
      cache[key] = out;
      return out;
    }

    function value(r, c) {
      var cellValue = cell(r, c);
      if (cellValue.err) throw new FormulaError(cellValue.err);
      return cellValue.v;
    }

    function numbersIn(node, r, c) {
      var out = [];
      function add(rr, cc) {
        var v = value(rr, cc);
        if (typeof v === "number") out.push(v);
      }
      if (node.k === "range") {
        var r1 = Math.min(node.from.r, node.to.r), r2 = Math.max(node.from.r, node.to.r);
        var c1 = Math.min(node.from.c, node.to.c), c2 = Math.max(node.from.c, node.to.c);
        for (var rr = r1; rr <= r2; rr++) for (var cc = c1; cc <= c2; cc++) add(rr, cc);
      } else if (node.k === "run") {
        var dr = node.dir === "ABOVE" ? -1 : 0, dc = node.dir === "LEFT" ? -1 : 0;
        for (var y = r + dr, x = c + dc; y >= 0 && x >= 0; y += dr, x += dc) {
          if (covered[y + "," + x]) continue;
          var v = value(y, x);
          if (typeof v !== "number") break;
          out.push(v);
        }
      } else {
        var one = run(node, r, c);
        if (typeof one === "number") out.push(one);
      }
      return out;
    }

    function run(node, r, c) {
      switch (node.k) {
        case "num": return node.v;
        case "str": return node.v;
        case "ref": return value(node.r, node.c);
        case "neg": return -num(run(node.a, r, c));
        case "bin": {
          if (node.op === "&") return text(run(node.a, r, c)) + text(run(node.b, r, c));
          if (COMPARE[node.op]) return COMPARE[node.op](compare(run(node.a, r, c), run(node.b, r, c)));
          var a = num(run(node.a, r, c)), b = num(run(node.b, r, c));
          if (node.op === "+") return a + b;
          if (node.op === "-") return a - b;
          if (node.op === "*") return a * b;
          if (b === 0) throw new FormulaError(ERR.DIV);
          return a / b;
        }
        case "range":
        case "run": throw new FormulaError(ERR.VALUE);
        case "call": return call(node, r, c);
      }
      throw new FormulaError(ERR.PARSE);
    }

    function num(v) {
      if (typeof v === "number") return v;
      if (typeof v === "boolean") return v ? 1 : 0;
      if (v === "") return 0;
      throw new FormulaError(ERR.VALUE);
    }

    function text(v) {
      return typeof v === "string" ? v : formatValue(v);
    }

    // Numbers sort before text, text compares without regard to case, as in a spreadsheet.
    function compare(a, b) {
      if (a === "" && typeof b === "number") a = 0;
      if (b === "" && typeof a === "number") b = 0;
      var ta = typeof a, tb = typeof b;
      if (ta !== tb) return ta === "string" ? 1 : tb === "string" ? -1 : 0;
      if (ta === "string") {
        var x = a.toLowerCase(), y = b.toLowerCase();
        return x < y ? -1 : x > y ? 1 : 0;
      }
      return a - b;
    }

    function truth(v) {
      if (typeof v === "boolean") return v;
      if (typeof v === "number") return v !== 0;
      throw new FormulaError(ERR.VALUE);
    }

    function call(node, r, c) {
      var name = node.name;
      if (name === "IF") {
        if (node.args.length < 2 || node.args.length > 3) throw new FormulaError(ERR.PARSE);
        if (truth(run(node.args[0], r, c))) return run(node.args[1], r, c);
        return node.args[2] ? run(node.args[2], r, c) : "";
      }
      if (name === "AND" || name === "OR") {
        if (!node.args.length) throw new FormulaError(ERR.PARSE);
        var flags = node.args.map(function (arg) { return truth(run(arg, r, c)); });
        return name === "AND" ? flags.every(Boolean) : flags.some(Boolean);
      }
      if (name === "NOT") {
        if (node.args.length !== 1) throw new FormulaError(ERR.PARSE);
        return !truth(run(node.args[0], r, c));
      }
      if (name === "ROUND") {
        if (!node.args.length || node.args.length > 2) throw new FormulaError(ERR.PARSE);
        var x = num(run(node.args[0], r, c));
        var digits = node.args[1] ? num(run(node.args[1], r, c)) : 0;
        var f = Math.pow(10, digits);
        return Math.round(x * f) / f;
      }
      if (["SUM", "AVERAGE", "MIN", "MAX", "COUNT"].indexOf(name) === -1) throw new FormulaError(ERR.NAME);
      var values = [];
      node.args.forEach(function (arg) {
        values = values.concat(numbersIn(arg, r, c));
      });
      if (name === "COUNT") return values.length;
      if (name === "SUM") return values.reduce(function (s, v) { return s + v; }, 0);
      if (!values.length) {
        if (name === "AVERAGE") throw new FormulaError(ERR.DIV);
        return 0;
      }
      if (name === "AVERAGE") return values.reduce(function (s, v) { return s + v; }, 0) / values.length;
      return name === "MIN" ? Math.min.apply(null, values) : Math.max.apply(null, values);
    }

    var result = [];
    for (var r = 0; r < rows; r++) {
      result.push([]);
      for (var c = 0; c < cols; c++) result[r].push(cell(r, c));
    }
    return result;
  }

  function formatValue(v) {
    if (typeof v === "number") return String(Number(v.toFixed(10)));
    if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
    return String(v);
  }

  var COMPARE = {
    "=": function (c) { return c === 0; },
    "<>": function (c) { return c !== 0; },
    "<": function (c) { return c < 0; },
    ">": function (c) { return c > 0; },
    "<=": function (c) { return c <= 0; },
    ">=": function (c) { return c >= 0; },
  };

  // ---- Merges ------------------------------------------------------------------
  function coveredMap(merges) {
    var map = {};
    merges.forEach(function (m) {
      for (var r = m.r; r < m.r + m.rs; r++) {
        for (var c = m.c; c < m.c + m.cs; c++) if (r !== m.r || c !== m.c) map[r + "," + c] = true;
      }
    });
    return map;
  }

  function mergeAt(merges, r, c) {
    for (var i = 0; i < merges.length; i++) if (merges[i].r === r && merges[i].c === c) return merges[i];
    return null;
  }

  function overlaps(m, r1, c1, r2, c2) {
    return !(m.r + m.rs - 1 < r1 || m.r > r2 || m.c + m.cs - 1 < c1 || m.c > c2);
  }

  // Merges the rectangle; any merge it touches is absorbed into it.
  function merge(merges, r1, c1, r2, c2) {
    if (r1 === r2 && c1 === c2) return merges;
    var kept = merges.filter(function (m) { return !overlaps(m, r1, c1, r2, c2); });
    kept.push({ r: r1, c: c1, rs: r2 - r1 + 1, cs: c2 - c1 + 1 });
    return kept;
  }

  function split(merges, r1, c1, r2, c2) {
    return merges.filter(function (m) { return !overlaps(m, r1, c1, r2, c2); });
  }

  // ---- Structure changes (rows and columns) ----------------------------------------
  function shiftRefs(formula, axis, index, delta) {
    // Quoted text is left alone; only the parts between quotes hold references.
    return formula.split(/("(?:[^"]|"")*")/).map(function (part, i) {
      return i % 2 ? part : shiftPlain(part, axis, index, delta);
    }).join("");
  }

  function shiftPlain(formula, axis, index, delta) {
    return formula.replace(/([A-Z]{1,3}\d+)(?::([A-Z]{1,3}\d+))?(?!\w|\()/g, function (whole, a, b) {
      function move(ref) {
        var p = parseRef(ref);
        if (!p) return ref;
        var v = axis === "row" ? p.r : p.c;
        if (delta > 0) {
          if (v >= index) v += delta;
        } else if (v === index) {
          return null;
        } else if (v > index) {
          v += delta;
        }
        return axis === "row" ? refText(v, p.c) : refText(p.r, v);
      }
      var first = move(a);
      if (!b) return first === null ? "#REF!" : first;
      var second = move(b);
      if (first === null && second === null) return "#REF!";
      if (first === null) first = a;
      return first + ":" + (second === null ? b : second);
    });
  }

  function adjustFormulas(grid, axis, index, delta) {
    return grid.map(function (row) {
      return row.map(function (raw) {
        if (!isFormula(raw)) return raw;
        return "=" + shiftRefs(formulaText(raw), axis, index, delta);
      });
    });
  }

  function emptyRow(cols) {
    var row = [];
    for (var i = 0; i < cols; i++) row.push("");
    return row;
  }

  function colCount(grid) {
    return grid.reduce(function (n, row) { return Math.max(n, row.length); }, 0);
  }

  function shiftMerges(merges, axis, index, delta) {
    var out = [];
    merges.forEach(function (m) {
      var start = axis === "row" ? m.r : m.c;
      var span = axis === "row" ? m.rs : m.cs;
      var end = start + span - 1;
      if (delta > 0) {
        if (index <= start) start += delta;
        else if (index <= end) span += delta;
      } else if (index < start) {
        start -= 1;
      } else if (index <= end) {
        span -= 1;
        if (span < 1) return;
      }
      var next = { r: m.r, c: m.c, rs: m.rs, cs: m.cs };
      if (axis === "row") { next.r = start; next.rs = span; } else { next.c = start; next.cs = span; }
      if (next.rs * next.cs > 1) out.push(next);
    });
    return out;
  }

  // `model` is {content, merges, align, colors}; `align` is keyed by column, `colors` by "r,c".
  function insertRow(model, at) {
    var content = adjustFormulas(model.content, "row", at, 1);
    content.splice(at, 0, emptyRow(colCount(content)));
    var colors = {};
    Object.keys(model.colors || {}).forEach(function (k) {
      var p = k.split(",").map(Number);
      colors[(p[0] >= at ? p[0] + 1 : p[0]) + "," + p[1]] = model.colors[k];
    });
    return { content: content, merges: shiftMerges(model.merges || [], "row", at, 1), align: model.align || {}, colors: colors };
  }

  function deleteRow(model, at) {
    if (model.content.length <= 1) return model;
    var content = adjustFormulas(model.content, "row", at, -1);
    content.splice(at, 1);
    var colors = {};
    Object.keys(model.colors || {}).forEach(function (k) {
      var p = k.split(",").map(Number);
      if (p[0] === at) return;
      colors[(p[0] > at ? p[0] - 1 : p[0]) + "," + p[1]] = model.colors[k];
    });
    return { content: content, merges: shiftMerges(model.merges || [], "row", at, -1), align: model.align || {}, colors: colors };
  }

  function insertCol(model, at) {
    var content = adjustFormulas(model.content, "col", at, 1).map(function (row) {
      var copy = row.slice();
      copy.splice(at, 0, "");
      return copy;
    });
    var align = {};
    Object.keys(model.align || {}).forEach(function (k) {
      var c = Number(k);
      align[c >= at ? c + 1 : c] = model.align[k];
    });
    var colors = {};
    Object.keys(model.colors || {}).forEach(function (k) {
      var p = k.split(",").map(Number);
      colors[p[0] + "," + (p[1] >= at ? p[1] + 1 : p[1])] = model.colors[k];
    });
    return { content: content, merges: shiftMerges(model.merges || [], "col", at, 1), align: align, colors: colors };
  }

  function deleteCol(model, at) {
    if (colCount(model.content) <= 1) return model;
    var content = adjustFormulas(model.content, "col", at, -1).map(function (row) {
      var copy = row.slice();
      copy.splice(at, 1);
      return copy;
    });
    var align = {};
    Object.keys(model.align || {}).forEach(function (k) {
      var c = Number(k);
      if (c === at) return;
      align[c > at ? c - 1 : c] = model.align[k];
    });
    var colors = {};
    Object.keys(model.colors || {}).forEach(function (k) {
      var p = k.split(",").map(Number);
      if (p[1] === at) return;
      colors[p[0] + "," + (p[1] > at ? p[1] - 1 : p[1])] = model.colors[k];
    });
    return { content: content, merges: shiftMerges(model.merges || [], "col", at, -1), align: align, colors: colors };
  }

  // ---- Columns: numbers, alignment, sorting -----------------------------------------
  function isNumericColumn(values, col, firstRow) {
    var seen = 0;
    for (var r = firstRow; r < values.length; r++) {
      var cell = values[r][col];
      if (!cell || cell.text === "") continue;
      if (typeof cell.v !== "number") return false;
      seen++;
    }
    return seen > 0;
  }

  // Row order after sorting body rows (from `firstRow` on) by one column; empty cells go last.
  function sortedOrder(values, col, dir, firstRow) {
    var order = [];
    for (var r = firstRow; r < values.length; r++) order.push(r);
    var sign = dir === "desc" ? -1 : 1;
    order.sort(function (a, b) {
      var x = values[a][col], y = values[b][col];
      var xe = !x || x.text === "", ye = !y || y.text === "";
      if (xe || ye) return xe === ye ? a - b : xe ? 1 : -1;
      var cmp = typeof x.v === "number" && typeof y.v === "number"
        ? x.v - y.v
        : String(x.text).localeCompare(String(y.text), undefined, { numeric: true, sensitivity: "base" });
      return cmp * sign || a - b;
    });
    var all = [];
    for (var h = 0; h < firstRow; h++) all.push(h);
    return all.concat(order);
  }

  function canSort(model) {
    var hasFormula = model.content.some(function (row) { return row.some(isFormula); });
    return !hasFormula && !(model.merges && model.merges.length);
  }

  // ---- Paste and export ---------------------------------------------------------------
  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function tsvToGrid(text) {
    var lines = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "").split("\n");
    return lines.map(function (line) {
      return line.split("\t").map(function (cell) {
        var t = cell.replace(/^"([\s\S]*)"$/, "$1").trim();
        return t.charAt(0) === "=" ? t : escapeHtml(t);
      });
    });
  }

  function looksLikeTsv(text) {
    return /\t/.test(text) || /\n.+/.test(text.replace(/\n+$/, ""));
  }

  var MD_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function markdownTableToGrid(text) {
    var lines = text.replace(/\r\n?/g, "\n").split("\n").filter(function (l) { return l.trim(); });
    if (lines.length < 2 || !/\|/.test(lines[0]) || !MD_SEPARATOR.test(lines[1])) return null;
    function cells(line) {
      return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map(function (c) {
        var t = c.trim();
        return t.charAt(0) === "=" ? t : escapeHtml(t);
      });
    }
    var rows = [cells(lines[0])].concat(lines.slice(2).map(cells));
    return rows;
  }

  function plainRows(values) {
    return values.map(function (row) {
      return row.map(function (cell) { return cell ? cell.text : ""; });
    });
  }

  function toMarkdown(values) {
    var rows = plainRows(values).map(function (row) {
      return row.map(function (t) { return t.replace(/\|/g, "\\|"); });
    });
    if (!rows.length) return "";
    var width = rows[0].length;
    var line = function (row) { return "| " + row.join(" | ") + " |"; };
    var sep = "|" + new Array(width + 1).join(" --- |");
    return [line(rows[0]), sep].concat(rows.slice(1).map(line)).join("\n");
  }

  function toCsv(values) {
    return plainRows(values).map(function (row) {
      return row.map(function (t) {
        return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
      }).join(",");
    }).join("\n");
  }

  var api = {
    ERR: ERR, colName: colName, parseRef: parseRef, refText: refText, stripHtml: stripHtml, isFormula: isFormula,
    formulaText: formulaText, toNumber: toNumber, evaluate: evaluate, formatValue: formatValue,
    coveredMap: coveredMap, mergeAt: mergeAt, merge: merge, split: split, shiftRefs: shiftRefs,
    insertRow: insertRow, deleteRow: deleteRow, insertCol: insertCol, deleteCol: deleteCol,
    isNumericColumn: isNumericColumn, sortedOrder: sortedOrder, canSort: canSort, colCount: colCount,
    tsvToGrid: tsvToGrid, looksLikeTsv: looksLikeTsv, markdownTableToGrid: markdownTableToGrid,
    toMarkdown: toMarkdown, toCsv: toCsv,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.NotebookTableModel = api;
})(typeof window !== "undefined" ? window : globalThis);
