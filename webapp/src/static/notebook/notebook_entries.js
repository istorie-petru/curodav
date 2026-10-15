// Dotted links for the entries attached to a note. The names are found in the text and drawn with the
// CSS Custom Highlight API, so the stored blocks and the editor's DOM are never touched. Hovering a
// dotted name shows the entry's card; Ctrl or Cmd plus click opens its view modal.
(function () {
  var mount = document.getElementById("notebook-editor");
  if (!mount || !window.CSS || !CSS.highlights || typeof Highlight === "undefined") return;
  var uid = mount.getAttribute("data-uid");
  var entries = [];
  var pattern = null;
  var owners = {};
  var ranges = [];
  var card = null;
  var cardEntry = null;
  var hoverTimer = null;
  var cards = {};

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function build() {
    owners = {};
    var names = [];
    entries.forEach(function (e) {
      e.names.forEach(function (n) {
        var key = n.trim().toLowerCase();
        if (key && !owners[key]) {
          owners[key] = e.uid;
          names.push(n.trim());
        }
      });
    });
    names.sort(function (a, b) { return b.length - a.length; });
    pattern = names.length ? new RegExp("(^|[^\\p{L}\\p{N}_])(" + names.map(escapeRegex).join("|") + ")(?![\\p{L}\\p{N}_])", "giu") : null;
  }

  function skip(node) {
    var parent = node.parentElement;
    return !parent || parent.closest("code, pre, .cdx-code, .cdx-wikilink, data.cdx-mention, .cdx-footnote-list, .nbt-cell[data-formula], .ce-header-hidden");
  }

  function paint() {
    ranges = [];
    CSS.highlights.delete("cdx-entry-link");
    if (!pattern) return;
    var walker = document.createTreeWalker(mount, NodeFilter.SHOW_TEXT);
    var found = [];
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (skip(node) || !node.textContent.trim()) continue;
      pattern.lastIndex = 0;
      var m;
      while ((m = pattern.exec(node.textContent))) {
        var start = m.index + m[1].length;
        var range = new Range();
        range.setStart(node, start);
        range.setEnd(node, start + m[2].length);
        range.entryUid = owners[m[2].toLowerCase()];
        found.push(range);
      }
    }
    ranges = found;
    if (found.length) CSS.highlights.set("cdx-entry-link", new Highlight(...found));
  }

  var paintTimer = null;
  function schedulePaint() {
    clearTimeout(paintTimer);
    paintTimer = setTimeout(paint, 400);
  }

  function load() {
    fetch("/notebook/" + uid + "/glossary/names")
      .then(function (r) { return r.ok ? r.json() : []; })
      .catch(function () { return []; })
      .then(function (list) {
        entries = list;
        build();
        paint();
      });
  }

  function rangeAt(x, y) {
    var pos = document.caretPositionFromPoint ? document.caretPositionFromPoint(x, y) : null;
    var node, offset;
    if (pos) { node = pos.offsetNode; offset = pos.offset; }
    else if (document.caretRangeFromPoint) {
      var r = document.caretRangeFromPoint(x, y);
      if (!r) return null;
      node = r.startContainer; offset = r.startOffset;
    } else return null;
    if (!node || node.nodeType !== Node.TEXT_NODE) return null;
    for (var i = 0; i < ranges.length; i++) {
      var rg = ranges[i];
      if (rg.startContainer === node && offset >= rg.startOffset && offset <= rg.endOffset) {
        var box = rg.getBoundingClientRect();
        if (x >= box.left - 1 && x <= box.right + 1 && y >= box.top - 1 && y <= box.bottom + 1) return rg;
      }
    }
    return null;
  }

  function hideCard() {
    clearTimeout(hoverTimer);
    if (cardEntry) window.NotebookFloating.release(cardEntry);
    cardEntry = null;
    if (card) card.remove();
    card = null;
  }

  function showCard(range) {
    var entryUid = range.entryUid;
    var box = range.getBoundingClientRect();
    fetchCard(entryUid).then(function (html) {
      hideCard();
      if (!html) return;
      card = document.createElement("div");
      card.className = "cdx-entry-card-pop";
      card.innerHTML = html;
      var actions = document.createElement("div");
      actions.className = "entry-card-links";
      var off = document.createElement("button");
      off.type = "button";
      off.className = "btn ghost btn-sm";
      off.textContent = "Stop linking here";
      off.addEventListener("click", function () {
        fetch("/notebook/" + uid + "/glossary/" + entryUid + "/detach", { method: "POST" }).then(function () {
          hideCard();
          load();
        });
      });
      actions.appendChild(off);
      card.appendChild(actions);
      document.body.appendChild(card);
      cardEntry = window.NotebookFloating.open(card, function () {
        if (card) card.remove();
        card = null;
        cardEntry = null;
      });
      var width = card.offsetWidth, height = card.offsetHeight;
      var left = Math.min(Math.max(8, box.left), window.innerWidth - width - 8);
      var top = box.bottom + 6;
      if (top + height > window.innerHeight - 8) top = Math.max(8, box.top - height - 6);
      card.style.left = left + "px";
      card.style.top = top + "px";
      card.addEventListener("mouseleave", hideCard);
    });
  }

  function fetchCard(entryUid) {
    if (cards[entryUid]) return Promise.resolve(cards[entryUid]);
    return fetch("/notebook/glossary/" + entryUid + "/card")
      .then(function (r) { return r.ok ? r.text() : ""; })
      .catch(function () { return ""; })
      .then(function (html) { cards[entryUid] = html; return html; });
  }

  mount.addEventListener("mousemove", function (e) {
    var range = rangeAt(e.clientX, e.clientY);
    clearTimeout(hoverTimer);
    if (!range) {
      if (card && !card.matches(":hover")) hoverTimer = setTimeout(function () { if (card && !card.matches(":hover")) hideCard(); }, 250);
      mount.classList.remove("has-entry-hover");
      return;
    }
    mount.classList.add("has-entry-hover");
    hoverTimer = setTimeout(function () { showCard(range); }, 350);
  });
  mount.addEventListener("click", function (e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    var range = rangeAt(e.clientX, e.clientY);
    if (!range || !window.CCModal) return;
    e.preventDefault();
    window.CCModal.open("/notebook/glossary/" + range.entryUid);
  });
  new MutationObserver(schedulePaint).observe(mount, { childList: true, subtree: true, characterData: true });
  document.addEventListener("notebook-saved", function () {
    cards = {};
    load();
  });
  load();
})();
