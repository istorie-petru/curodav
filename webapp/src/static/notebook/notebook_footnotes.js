// Endnotes for the Notebook editor. An endnote is a <sup class="cdx-footnote-ref"> marker in the
// text; its body lives in the marker's `data-note` attribute (sanitized rich text, or plain
// generated text). The numbered endnote list at the end of the document is rebuilt from the markers
// on every change, and is where every endnote is edited. Creation is only from the inline toolbar.
// Feature notes: curodav-notes/documentation/features/notebook-citations-glossary.md.
(function () {
  function footnoteIcon() {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-hash"></use></svg>';
  }

  function NotebookFootnote(params) {
    this.api = params.api;
    this.button = null;
  }
  NotebookFootnote.isInline = true;
  NotebookFootnote.title = "Endnote";
  NotebookFootnote.sanitize = {
    sup: {
      class: "cdx-footnote-ref",
      "data-note-id": true,
      "data-note": true,
      "data-footnote-kind": true,
      "data-footnote-data": true,
    },
  };
  NotebookFootnote.prototype.render = function () {
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.classList.add(this.api.styles.inlineToolButton);
    this.button.title = "Endnote";
    this.button.setAttribute("aria-label", "Endnote");
    this.button.innerHTML = footnoteIcon();
    return this.button;
  };
  // Inserts the marker (the number) after the selection and moves the caret to its entry in the
  // endnote list; on an existing marker it just jumps to that entry.
  NotebookFootnote.prototype.surround = function (range) {
    if (!range) return;
    var existing = this.api.selection.findParentTag("SUP", "cdx-footnote-ref");
    var marker = existing;
    if (!marker) {
      marker = document.createElement("sup");
      marker.className = "cdx-footnote-ref";
      marker.setAttribute("data-note-id", generateId());
      marker.setAttribute("data-note", "");
      marker.contentEditable = "false";
      var insertAt = range.cloneRange();
      insertAt.collapse(false);
      insertAt.insertNode(marker);
      var after = document.createRange();
      after.setStartAfter(marker);
      after.collapse(true);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(after);
    }
    var mount = marker.closest("#notebook-editor");
    if (mount) {
      renderFootnoteList(mount);
      mount.dispatchEvent(new CustomEvent("notebook-footnote-change"));
      focusEntry(marker.getAttribute("data-note-id"));
    }
  };
  NotebookFootnote.prototype.checkState = function () {
    var marker = this.api.selection.findParentTag("SUP", "cdx-footnote-ref");
    if (this.button) this.button.classList.toggle(this.api.styles.inlineToolButtonActive, !!marker);
    return !!marker;
  };

  function focusEntry(noteId) {
    var li = document.getElementById("fn-" + noteId);
    if (!li) return;
    var body = li.querySelector(".cdx-footnote-text[contenteditable=true]");
    var field = body || li.querySelector(".cdx-footnote-menu-btn");
    if (!field) return;
    setTimeout(function () {
      field.focus();
      if (body) {
        var r = document.createRange();
        r.selectNodeContents(body);
        r.collapse(false);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(r);
      }
      li.scrollIntoView({ block: "nearest" });
    }, 0);
  }

  function generateId() {
    return "fn" + Math.random().toString(36).slice(2, 10);
  }

  function footerFor(mount) {
    var footer = document.getElementById("notebook-footnotes");
    if (!footer) {
      footer = document.createElement("div");
      footer.id = "notebook-footnotes";
      footer.className = "cdx-footnote-footer";
      footer.hidden = true;
      // The mount's own last child: it scrolls with the document and survives Editor.js re-renders.
      mount.appendChild(footer);
    }
    return footer;
  }

  // ---- Rich text bodies ------------------------------------------------
  var NOTE_TAGS = { B: 1, STRONG: 1, I: 1, EM: 1, U: 1, S: 1, CODE: 1, SUB: 1, SUP: 1, A: 1, BR: 1 };

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Keeps basic inline formatting and links only; everything else becomes its text.
  function sanitizeNoteHtml(html) {
    var box = document.createElement("div");
    box.innerHTML = html;
    (function clean(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === Node.TEXT_NODE) return;
        if (child.nodeType !== Node.ELEMENT_NODE) {
          node.removeChild(child);
          return;
        }
        clean(child);
        if (!NOTE_TAGS[child.tagName]) {
          while (child.firstChild) node.insertBefore(child.firstChild, child);
          node.removeChild(child);
          return;
        }
        var href = child.tagName === "A" ? child.getAttribute("href") || "" : "";
        Array.prototype.slice.call(child.attributes).forEach(function (attr) {
          child.removeAttribute(attr.name);
        });
        if (href && /^(https?:|mailto:)/i.test(href)) {
          child.setAttribute("href", href);
          child.setAttribute("rel", "noopener noreferrer");
        }
      });
    })(box);
    return box.innerHTML;
  }

  // Numbers the markers and rebuilds the entry list at the end of the document. Existing entries
  // are reused (and left alone while focused) so typing in one never loses the caret.
  function renderFootnoteList(mount) {
    var footer = footerFor(mount);
    var marks = mount.querySelectorAll(".cdx-footnote-ref");
    if (!marks.length) {
      footer.hidden = true;
      footer.innerHTML = "";
      return;
    }
    footer.hidden = false;
    var heading = footer.querySelector(".cdx-footnote-footer__heading");
    if (!heading) {
      heading = document.createElement("div");
      heading.className = "cdx-footnote-footer__heading";
      heading.textContent = "Endnotes";
      footer.appendChild(heading);
    }
    var list = footer.querySelector(".cdx-footnote-list");
    if (!list) {
      list = document.createElement("ol");
      list.className = "cdx-footnote-list";
      footer.appendChild(list);
    }
    var seenIds = {};
    marks.forEach(function (mark, i) {
      var noteId = mark.getAttribute("data-note-id");
      // Editor.js watches this subtree, so write only when a value really changes.
      var n = String(i + 1);
      if (mark.textContent !== n) mark.textContent = n;
      var refId = "fn-ref-" + noteId;
      if (mark.id !== refId) mark.id = refId;
      seenIds[noteId] = true;
      var kind = mark.getAttribute("data-footnote-kind") || "";
      var li = document.getElementById("fn-" + noteId);
      if (li && li.classList.contains("cdx-footnote-list-item-structured") !== !!kind) {
        li.remove();
        li = null;
      }
      if (!li) {
        li = document.createElement("li");
        li.id = "fn-" + noteId;
        var row = document.createElement("span");
        row.className = "cdx-footnote-structured-row";
        var body = document.createElement("span");
        body.className = "cdx-footnote-text";
        if (kind) {
          // A generated endnote is automatic: it changes only through the entry menu.
          li.classList.add("cdx-footnote-list-item-structured");
        } else {
          body.contentEditable = "true";
          body.spellcheck = false;
        }
        row.appendChild(body);
        row.appendChild(buildEntryMenuButton(li));
        li.appendChild(row);
      }
      if (list.children[i] !== li) {
        list.insertBefore(li, list.children[i] || null);
      }
      var noteText = mark.getAttribute("data-note") || "";
      var body = li.querySelector(".cdx-footnote-text");
      if (kind) {
        if (body.textContent !== noteText) body.textContent = noteText;
      } else if (document.activeElement !== body) {
        var html = sanitizeNoteHtml(noteText);
        if (body.innerHTML !== html) body.innerHTML = html;
      }
    });
    Array.prototype.slice.call(list.children).forEach(function (li) {
      if (!seenIds[li.id.slice(3)]) list.removeChild(li);
    });
  }

  // Typing in a manual entry writes sanitized rich text back into its marker.
  document.addEventListener("input", function (e) {
    var body = e.target.closest && e.target.closest(".cdx-footnote-list li .cdx-footnote-text[contenteditable=true]");
    if (!body) return;
    var mark = document.getElementById("fn-ref-" + body.closest("li").id.slice(3));
    if (!mark) return;
    var html = sanitizeNoteHtml(body.innerHTML);
    if (mark.getAttribute("data-note") !== html) mark.setAttribute("data-note", html);
  });

  function inEntryBody(target) {
    return target.closest && target.closest(".cdx-footnote-list li .cdx-footnote-text[contenteditable=true]");
  }

  // One paragraph per entry; bold, italic and underline by shortcut.
  document.addEventListener("keydown", function (e) {
    if (!inEntryBody(e.target)) return;
    if (e.key === "Enter") {
      e.preventDefault();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey) {
      var command = { b: "bold", i: "italic", u: "underline" }[e.key.toLowerCase()];
      if (command) {
        e.preventDefault();
        document.execCommand(command);
      }
    }
  });

  document.addEventListener("paste", function (e) {
    if (!inEntryBody(e.target)) return;
    e.preventDefault();
    var data = e.clipboardData || window.clipboardData;
    var html = data.getData("text/html");
    if (html) document.execCommand("insertHTML", false, sanitizeNoteHtml(html).replace(/<br\s*\/?>/g, " "));
    else document.execCommand("insertText", false, data.getData("text/plain").replace(/\s*\n\s*/g, " "));
  });

  // Click a marker in the text to jump down to its entry.
  document.addEventListener("click", function (e) {
    var mark = e.target.closest(".cdx-footnote-ref");
    if (!mark) return;
    var target = document.getElementById("fn-" + mark.getAttribute("data-note-id"));
    if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  function debounce(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, ms);
    };
  }

  function searchCitations(query, cb) {
    var url = "/notebook/citations/search?q=" + encodeURIComponent(query || "");
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.ok ? resp.json() : [];
      })
      .catch(function () {
        return [];
      })
      .then(cb);
  }

  function renderCitationResultsInto(ul, items, onPick) {
    ul.innerHTML = "";
    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "cdx-footnote-picker-empty";
      empty.textContent = "No matching citations";
      ul.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "cdx-footnote-picker-result";
      li.textContent = item.display;
      li.addEventListener("click", function () {
        onPick(item);
      });
      ul.appendChild(li);
    });
  }

  // One hardcoded Chicago-inspired note format (roadmap item J2, resolved
  // 2026-10-03: "ship one hardcoded format now ... don't build a format
  // selector yet"). Natural author-name order ("First Last", not the
  // bibliography's "Last, F." -- Chicago's own note/bibliography-entry
  // distinction), title quoted for a journal article, plain otherwise (no
  // italics available in plain footnote text), year in parens, page last.
  // Deliberately simple: this is the one format v1 ships, not a template
  // engine -- see J2's own "knobs identified for when this is built"
  // list for what a second format would eventually need to vary.
  function formatCitationAuthorsNatural(authors) {
    var parts = (authors || []).map(function (a) {
      var family = (a.family || "").trim();
      var given = (a.given || "").trim();
      return (given ? given + " " : "") + family;
    }).filter(Boolean);
    if (parts.length <= 1) return parts[0] || "";
    if (parts.length === 2) return parts[0] + " and " + parts[1];
    return parts.slice(0, -1).join(", ") + ", and " + parts[parts.length - 1];
  }
  function formatCitationTitlePart(citation) {
    var title = (citation.title || "").trim() || "Untitled";
    return citation.type === "article-journal" ? '"' + title + '"' : title;
  }
  function formatPageCitationText(citation, page) {
    var bits = [];
    var authors = formatCitationAuthorsNatural(citation.authors);
    if (authors) bits.push(authors);
    bits.push(formatCitationTitlePart(citation));
    var tail = citation.year ? "(" + citation.year + ")" : "";
    var head = bits.join(", ");
    var text = tail ? head + " " + tail : head;
    if (page) text += ", " + page;
    return text + ".";
  }
  // Session 9b (2026-10-03) -- the remaining five actions, same one-
  // hardcoded-format rule as J2 ("ship one format, no selector yet").
  // Each is a distinct, named Latin convention with its own wording, not
  // a parameterized variant of `formatPageCitationText` -- Confer is the
  // one exception (literally the same body, just "Cf. " prefixed), kept
  // as a thin wrapper rather than re-deriving the author/title/year
  // assembly a second time.
  function formatConferText(citation, page) {
    return "Cf. " + formatPageCitationText(citation, page);
  }
  // Chicago's own short-form repeat citation: author + "op. cit." + page,
  // no title at all (the full citation was already given earlier in the
  // document -- that's the whole point of op. cit.). Page is genuinely
  // optional here (same reasoning as Ibidem below) since a document might
  // reference the same source's general argument without a specific page.
  function formatOpereCitatoText(citation, page) {
    var authors = formatCitationAuthorsNatural(citation.authors) || formatCitationTitlePart(citation);
    return page ? authors + ", op. cit., " + page + "." : authors + ", op. cit.";
  }
  // "Ibid." refers to whatever the immediately preceding footnote cited --
  // the citation itself is never named again, only the page (if it
  // differs from the previous note's own page; same-page "Ibid." alone is
  // also valid Chicago and is exactly what an empty `page` produces here).
  function formatIbidemText(page) {
    return page ? "Ibid., " + page + "." : "Ibid.";
  }
  // Apud ("in the work of") -- the one action that genuinely needs two
  // sources, not one: the original work being quoted, and the secondary
  // work it was actually found/read in (2026-10-03, confirmed with Peter
  // via AskUserQuestion before building -- "Two citations" over a single-
  // citation-plus-wording variant). No page on the original (its own
  // locator isn't knowable from the secondary source alone); page applies
  // to the secondary, where the quotation was actually read.
  function formatApudText(original, secondary, page) {
    var originalBits = [];
    var originalAuthors = formatCitationAuthorsNatural(original.authors);
    if (originalAuthors) originalBits.push(originalAuthors);
    originalBits.push(formatCitationTitlePart(original));
    var secondaryText = formatPageCitationText(secondary, page);
    return originalBits.join(", ") + ", apud " + secondaryText;
  }
  // One dispatch point so both insertion and the Edit/regenerate picker
  // assemble text the same way for a given kind, rather than each having
  // its own copy of this branch.
  function formatFootnoteText(kind, data) {
    if (kind === "confer") return formatConferText(data.citation, data.page);
    if (kind === "opere_citato") return formatOpereCitatoText(data.citation, data.page);
    if (kind === "passim") return formatPageCitationText(data.citation, "passim");
    if (kind === "ibidem") return formatIbidemText(data.page);
    if (kind === "apud") return formatApudText(data.citations.original, data.citations.secondary, data.page);
    return formatPageCitationText(data.citation, data.page); // page_citation, the default shape
  }
  // The single-citation kinds Ibidem can refer back to -- deliberately
  // excludes `apud` (a two-source note; "Ibid. of an apud" is ill-defined
  // enough that this just skips past it to the nearest single-citation
  // note instead, a documented judgment call, not an oversight) and
  // `custom_note`/plain footnotes (nothing citation-shaped to refer to).
  var IBIDEM_SOURCE_KINDS = { page_citation: true, confer: true, opere_citato: true, passim: true, ibidem: true };
  // Walks every citation-bearing marker in the whole mount (not just this
  // block's own paragraph) in document order, same "walk the live DOM"
  // convention `renderFootnoteList`/`renderRelationships` already use, and
  // returns the nearest one that precedes `beforeEl` -- used by Ibidem to
  // find "the previous citation" and by Opere citato to scope its search
  // to citations already used somewhere in this document.
  function citationMarkersBefore(beforeEl) {
    var mount = beforeEl.closest("#notebook-editor");
    if (!mount) return [];
    var marks = mount.querySelectorAll(".cdx-footnote-ref[data-footnote-kind]");
    var result = [];
    marks.forEach(function (mark) {
      if (mark.compareDocumentPosition(beforeEl) & Node.DOCUMENT_POSITION_FOLLOWING) {
        result.push(mark);
      }
    });
    return result;
  }
  function parseFootnoteData(mark) {
    try {
      return JSON.parse(mark.getAttribute("data-footnote-data") || "{}");
    } catch (e) {
      return {};
    }
  }
  function findPreviousCitationData(beforeEl) {
    var marks = citationMarkersBefore(beforeEl);
    for (var i = marks.length - 1; i >= 0; i--) {
      var kind = marks[i].getAttribute("data-footnote-kind");
      if (IBIDEM_SOURCE_KINDS[kind]) return parseFootnoteData(marks[i]).citation || null;
    }
    return null;
  }
  function collectUsedCitationUids(beforeEl) {
    var uids = {};
    citationMarkersBefore(beforeEl).forEach(function (mark) {
      var data = parseFootnoteData(mark);
      if (data.citation) uids[data.citation.uid] = true;
      if (data.citations) {
        if (data.citations.original) uids[data.citations.original.uid] = true;
        if (data.citations.secondary) uids[data.citations.secondary.uid] = true;
      }
    });
    return uids;
  }

  // ---- Per-entry menu and the generate-citation modal -------------------
  var CITATION_KINDS = [
    { key: "page_citation", label: "Page citation" },
    { key: "ibidem", label: "Ibidem" },
    { key: "opere_citato", label: "Opere citato" },
    { key: "confer", label: "Confer" },
    { key: "apud", label: "Apud" },
    { key: "passim", label: "Passim" },
  ];

  function markFor(li) {
    return document.getElementById("fn-ref-" + li.id.slice(3));
  }

  function refresh(mark) {
    var mount = mark.closest("#notebook-editor");
    if (!mount) return;
    renderFootnoteList(mount);
    mount.dispatchEvent(new CustomEvent("notebook-footnote-change"));
  }

  function closeEntryMenu() {
    var open = document.querySelector(".cdx-footnote-menu");
    if (!open) return;
    if (open._entry) window.NotebookFloating.release(open._entry);
    open.remove();
  }

  function buildEntryMenuButton(li) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cdx-footnote-menu-btn";
    btn.title = "Endnote actions";
    btn.setAttribute("aria-label", "Endnote actions");
    btn.setAttribute("aria-haspopup", "menu");
    btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-more"></use></svg>';
    btn.addEventListener("click", function () {
      var already = document.querySelector(".cdx-footnote-menu");
      closeEntryMenu();
      if (already && already.dataset.for === li.id) return;
      openEntryMenu(li, btn);
    });
    return btn;
  }

  // A manual entry offers Generate citation; a generated one offers Regenerate and Remove.
  function openEntryMenu(li, anchor) {
    var mark = markFor(li);
    if (!mark) return;
    var generated = !!mark.getAttribute("data-footnote-kind");
    var menu = document.createElement("div");
    menu.className = "cdx-footnote-menu";
    menu.setAttribute("role", "menu");
    menu.dataset.for = li.id;
    var items = generated
      ? [["Regenerate", function () { openCitationModal(li); }], ["Remove generation", function () { removeGeneration(mark); }]]
      : [["Generate citation", function () { openCitationModal(li); }]];
    items.forEach(function (item) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.textContent = item[0];
      b.addEventListener("click", function () {
        closeEntryMenu();
        item[1]();
      });
      menu.appendChild(b);
    });
    var rect = anchor.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = rect.bottom + 4 + "px";
    menu.style.left = Math.max(8, rect.right - 180) + "px";
    document.body.appendChild(menu);
    menu._entry = window.NotebookFloating.open(menu, function () { menu.remove(); }, null, anchor);
  }

  // Back to manual editing: the generated text stays as the entry's text.
  function removeGeneration(mark) {
    mark.setAttribute("data-note", escapeHtml(mark.getAttribute("data-note") || ""));
    mark.removeAttribute("data-footnote-kind");
    mark.removeAttribute("data-footnote-data");
    refresh(mark);
  }

  function buildCitationSearchField(initialDisplay, onPick, filterItems) {
    var field = document.createElement("div");
    field.className = "cdx-footnote-edit-field";
    var input = document.createElement("input");
    input.type = "text";
    input.setAttribute("aria-label", "Search citations");
    input.className = "cdx-footnote-picker-input";
    input.value = initialDisplay || "";
    var results = document.createElement("ul");
    results.className = "cdx-footnote-picker-results";
    field.appendChild(input);
    field.appendChild(results);
    function runSearch() {
      searchCitations(input.value, function (items) {
        renderCitationResultsInto(results, filterItems ? filterItems(items) : items, function (item) {
          onPick(item);
          input.value = item.display;
          results.innerHTML = "";
        });
      });
    }
    input.addEventListener("input", debounce(runSearch, 200));
    return { el: field, input: input, runSearch: runSearch };
  }

  function buildPageField(initialPage, label) {
    var row = document.createElement("div");
    row.className = "cdx-footnote-picker-page-row";
    var input = document.createElement("input");
    input.type = "text";
    input.setAttribute("aria-label", label || "Page");
    input.className = "cdx-footnote-picker-page-input";
    input.value = initialPage || "";
    row.appendChild(input);
    return { el: row, input: input };
  }

  function fieldLabel(text) {
    var el = document.createElement("div");
    el.className = "cdx-footnote-picker-page-label";
    el.textContent = text;
    return el;
  }

  // One modal for generating or regenerating: pick the citation type, then its citations and page.
  function openCitationModal(li) {
    var mark = markFor(li);
    if (!mark) return;
    var current = mark.getAttribute("data-footnote-kind") || "";
    var stored = parseFootnoteData(mark);
    var kind = current || "page_citation";

    var wrap = document.createElement("div");
    wrap.className = "cdx-footnote-picker cdx-footnote-modal-picker";
    var kinds = document.createElement("div");
    kinds.className = "cdx-footnote-kinds";
    var fields = document.createElement("div");
    fields.className = "cdx-footnote-kind-fields";
    wrap.appendChild(kinds);
    wrap.appendChild(fields);

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "cdx-footnote-picker-insert-btn";
    saveBtn.textContent = current ? "Regenerate" : "Generate";

    function finish(data) {
      mark.setAttribute("data-note", formatFootnoteText(kind, data));
      mark.setAttribute("data-footnote-kind", kind);
      mark.setAttribute("data-footnote-data", JSON.stringify(data));
      refresh(mark);
      window.CCModal.close();
    }

    function renderKind() {
      kinds.innerHTML = "";
      CITATION_KINDS.forEach(function (k) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "cdx-footnote-kind-btn" + (k.key === kind ? " is-active" : "");
        b.textContent = k.label;
        b.addEventListener("click", function () {
          kind = k.key;
          renderKind();
        });
        kinds.appendChild(b);
      });
      fields.innerHTML = "";
      var same = current === kind ? stored : {};
      var focusEl = null;
      var collect = null;

      if (kind === "ibidem") {
        var previous = same.citation || findPreviousCitationData(mark);
        if (!previous) {
          fields.appendChild(fieldLabel("There is no earlier citation in this document to refer back to."));
          collect = function () { return null; };
        } else {
          fields.appendChild(fieldLabel("Ibid. — " + previous.display));
          var ibidemPage = buildPageField(same.page, "Page, if different");
          fields.appendChild(ibidemPage.el);
          focusEl = ibidemPage.input;
          collect = function () { return { citation: previous, page: ibidemPage.input.value.trim() }; };
        }
      } else if (kind === "apud") {
        var original = same.citations ? same.citations.original : null;
        var secondary = same.citations ? same.citations.secondary : null;
        fields.appendChild(fieldLabel("Original source"));
        var first = buildCitationSearchField(original ? original.display : "", function (item) { original = item; });
        fields.appendChild(first.el);
        fields.appendChild(fieldLabel("Found quoted in"));
        var second = buildCitationSearchField(secondary ? secondary.display : "", function (item) { secondary = item; });
        fields.appendChild(second.el);
        fields.appendChild(fieldLabel("Page"));
        var apudPage = buildPageField(same.page);
        fields.appendChild(apudPage.el);
        focusEl = first.input;
        first.runSearch();
        second.runSearch();
        collect = function () {
          if (!original || !secondary) return null;
          return { citations: { original: original, secondary: secondary }, page: apudPage.input.value.trim() };
        };
      } else {
        var citation = same.citation || null;
        var restrict = kind === "opere_citato"
          ? function (items) {
              var used = collectUsedCitationUids(mark);
              return items.filter(function (item) { return used[item.uid]; });
            }
          : null;
        fields.appendChild(fieldLabel("Citation"));
        var search = buildCitationSearchField(citation ? citation.display : "", function (item) { citation = item; }, restrict);
        fields.appendChild(search.el);
        var pageField = null;
        if (kind !== "passim") {
          fields.appendChild(fieldLabel("Page"));
          pageField = buildPageField(same.page);
          fields.appendChild(pageField.el);
        }
        focusEl = search.input;
        search.runSearch();
        collect = function () {
          if (!citation) return null;
          return kind === "passim" ? { citation: citation } : { citation: citation, page: pageField.input.value.trim() };
        };
      }
      fields.appendChild(saveBtn);
      saveBtn.onclick = function () {
        var data = collect();
        if (data) finish(data);
      };
      if (focusEl) setTimeout(function () { focusEl.focus(); }, 0);
    }

    renderKind();
    window.CCModal.openCustom({ title: current ? "Regenerate citation" : "Generate citation", bodyNode: wrap });
  }

  window.NotebookFootnote = NotebookFootnote;
  window.notebookRenderFootnoteList = renderFootnoteList;
})();
