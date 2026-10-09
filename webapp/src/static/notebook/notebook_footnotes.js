// Footnotes (2026-10-03, direct request) -- plain editorial asides, not
// tied to the (not-yet-built) Bibliography feature. Two parts working
// together:
//
// 1. NotebookFootnote, an Editor.js Inline Tool (a different API shape
//    from the block tools in notebook_blocks.js -- render()/surround(range)/
//    checkState()/renderActions(), modeled directly on editorjs.umd.js's
//    own built-in inline Link tool, the closest upstream precedent for
//    "wrap/mark a selection, then show an editable side panel for it" --
//    read that class (search the vendored bundle for `renderActions`) if
//    this needs changing later). Inserts a `<sup class="cdx-footnote-ref"
//    data-note-id data-note>` marker right after the cursor/selection
//    (not wrapping the selected text itself -- a footnote marks a point,
//    it doesn't replace the words next to it). The note's own text lives
//    entirely in that marker's `data-note` attribute, inside whichever
//    block's own HTML content (e.g. a paragraph's `data.text`) -- it
//    round-trips through Editor.js's normal save/load/sanitize exactly
//    like `<b>`/`<i>`/`<a>` already do, so no backend changes at all were
//    needed for this feature.
//
// 2. A numbering + footer-list pass (`renderFootnoteList`), re-run on
//    every editor change and after initial load: walks the live DOM for
//    every `.cdx-footnote-ref` in document order, numbers them 1..n, and
//    rebuilds a plain `<ol>` of their note text in a footer element this
//    file creates right after the editor mount (outside Editor.js's own
//    block model entirely -- deliberately not a manual block the user
//    could drag/delete independently of the markers it describes).
(function () {
  function footnoteIcon() {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-hash"></use></svg>';
  }

  function NotebookFootnote(params) {
    this.api = params.api;
    this.button = null;
    this.textarea = null;
    this.currentMarker = null;
  }
  NotebookFootnote.isInline = true;
  NotebookFootnote.title = "Endnote";
  NotebookFootnote.sanitize = {
    sup: {
      class: "cdx-footnote-ref",
      "data-note-id": true,
      "data-note": true,
      // Added 2026-10-03 (roadmap item J, session 9a) -- see the slash-
      // command "Footnote" block below. A footnote built through that
      // flow carries its structured inputs alongside the plain `data-
      // note` text they were assembled into, so the "Edit" affordance on
      // its footer entry can reopen the same picker pre-filled for
      // regeneration, per the roadmap's "never auto-rendered, only
      // manual edit+regenerate" rule. A footnote typed the old plain way
      // simply never has these two attributes.
      "data-footnote-kind": true,
      "data-footnote-data": true,
    },
  };
  NotebookFootnote.prototype.render = function () {
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.classList.add(this.api.styles.inlineToolButton);
    this.button.innerHTML = footnoteIcon();
    return this.button;
  };
  NotebookFootnote.prototype.renderActions = function () {
    var self = this;
    this.textarea = document.createElement("textarea");
    this.textarea.placeholder = "Endnote text";
    this.textarea.className = "cdx-footnote-input";
    this.textarea.addEventListener("input", function () {
      if (!self.currentMarker) return;
      self.currentMarker.setAttribute("data-note", self.textarea.value);
      notifyMountChanged(self.currentMarker);
    });
    return this.textarea;
  };
  NotebookFootnote.prototype.surround = function (range) {
    if (!range) return;
    var existing = this.api.selection.findParentTag("SUP", "cdx-footnote-ref");
    if (existing) {
      // Cursor is already inside a footnote marker -- surround() here
      // just means "the button was clicked again," nothing to insert.
      return;
    }
    var marker = document.createElement("sup");
    marker.className = "cdx-footnote-ref";
    marker.setAttribute("data-note-id", generateId());
    marker.setAttribute("data-note", "");
    marker.contentEditable = "false";
    var insertAt = range.cloneRange();
    insertAt.collapse(false);
    insertAt.insertNode(marker);
    // Move the caret just past the newly inserted marker, matching how a
    // real footnote keeps typing flowing normally after it.
    var after = document.createRange();
    after.setStartAfter(marker);
    after.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(after);
    notifyMountChanged(marker);
  };
  NotebookFootnote.prototype.checkState = function () {
    var marker = this.api.selection.findParentTag("SUP", "cdx-footnote-ref");
    this.currentMarker = marker || null;
    if (this.button) {
      this.button.classList.toggle(
        this.api.styles.inlineToolButtonActive,
        !!marker
      );
    }
    if (this.textarea) {
      this.textarea.value = marker ? marker.getAttribute("data-note") : "";
    }
    return !!marker;
  };

  function generateId() {
    return "fn" + Math.random().toString(36).slice(2, 10);
  }

  function notifyMountChanged(node) {
    var mount = node.closest ? node.closest("#notebook-editor") : null;
    if (!mount) return;
    renderFootnoteList(mount);
    mount.dispatchEvent(new CustomEvent("notebook-footnote-change"));
  }

  function footerFor(mount) {
    var footer = document.getElementById("notebook-footnotes");
    if (!footer) {
      footer = document.createElement("div");
      footer.id = "notebook-footnotes";
      footer.className = "cdx-footnote-footer";
      footer.hidden = true;
      // 2026-10-04 (Settings > Notebook's "sidebar" layout option) --
      // notebook_document.html renders a plain empty slot,
      // #notebook-footnotes-sidebar-slot, inside the sidebar's own new
      // Endnotes tab when that layout is active; this is the one place
      // that decides where the live footer actually lives, so every
      // other function in this file (which all just read/write
      // #notebook-footnotes by id) needs no layout-awareness of its own.
      // Falls back to the original "last child of the scrollable editor
      // mount" placement whenever that slot doesn't exist (the default
      // "stacked" layout, where Endnotes already reads right after the
      // body in one column -- see that template's own header comment).
      var sidebarSlot = document.getElementById("notebook-footnotes-sidebar-slot");
      if (sidebarSlot) {
        sidebarSlot.appendChild(footer);
      } else {
        // Appended as the mount's own last child, not a sibling after it
        // -- #notebook-editor is the page's one scrollable region
        // (main-shell-body, notebook_document.html's own comment); a
        // sibling placed after it would sit outside that scroll area and
        // get clipped by main.main-shell's overflow:hidden instead.
        // Editor.js only ever touches its own internal wrapper node
        // inside this holder, so an extra plain child here survives
        // every re-render/autosave untouched.
        mount.appendChild(footer);
      }
    }
    return footer;
  }

  // Rebuilds numbering/membership every call (same "walk the live DOM, re-
  // run on change" shape as before), but no longer wipes the whole footer
  // each time -- #notebook-footnotes is now editable (direct request,
  // "footnotes should be editable inside notebook-footnotes block"), and
  // a full innerHTML="" rebuild on every keystroke would blow away the
  // caret position inside whichever <li> the user is mid-edit on. Existing
  // <li> elements (matched by their `fn-<id>` id, same ids as before) are
  // reused and left untouched while focused; only their text is kept in
  // sync with the marker's `data-note` when focus is elsewhere.
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
      // Editor.js's own MutationObserver watches the whole redactor
      // (childList/subtree/characterData/attributes) to drive its change
      // detection -- `mark` lives inside a real block's contenteditable,
      // so an unconditional write here on every call would retrigger that
      // observer -> onChange -> this function -> another write, forever
      // (confirmed live: unthrottled PUT .../content calls, "Unsaved
      // changes" never settling). Only write when the value would
      // actually change.
      var n = String(i + 1);
      if (mark.textContent !== n) mark.textContent = n;
      var refId = "fn-ref-" + noteId;
      if (mark.id !== refId) mark.id = refId;
      seenIds[noteId] = true;
      var kind = mark.getAttribute("data-footnote-kind") || "";
      var li = document.getElementById("fn-" + noteId);
      if (!li) {
        li = document.createElement("li");
        li.id = "fn-" + noteId;
        if (kind) {
          // Built via the slash-menu action flow (item J, session 9a) --
          // its text is *assembled*, not hand-typed, and roadmap item J
          // is explicit that it "changes only via manual edit+regenerate
          // ... never automatically re-rendered" -- so this entry is not
          // directly contentEditable, a dedicated "Edit" button below
          // reopens the same picker instead of letting a stray keystroke
          // here drift the text out of sync with its own stored inputs.
          li.contentEditable = "false";
          li.classList.add("cdx-footnote-list-item-structured");
          // The text+button layout needs flex, but `display:flex` on the
          // <li> itself suppresses its own numbered ::marker (confirmed
          // live -- the structured entry's "1." vanished the moment this
          // was flex, while the plain-text sibling kept its own number
          // fine) -- flex lives on an inner row instead, so the <li>
          // itself stays a plain list-item and keeps its marker.
          var row = document.createElement("span");
          row.className = "cdx-footnote-structured-row";
          var textSpan = document.createElement("span");
          textSpan.className = "cdx-footnote-text";
          row.appendChild(textSpan);
          var editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "cdx-footnote-edit-btn";
          editBtn.textContent = "Edit";
          editBtn.addEventListener("click", function () {
            openFootnoteEditPicker(li);
          });
          row.appendChild(editBtn);
          li.appendChild(row);
        } else {
          li.contentEditable = "true";
          li.spellcheck = false;
          li.textContent = mark.getAttribute("data-note") || "";
        }
      }
      if (list.children[i] !== li) {
        list.insertBefore(li, list.children[i] || null);
      }
      var noteText = mark.getAttribute("data-note") || "";
      if (kind) {
        var span = li.querySelector(".cdx-footnote-text");
        if (span && span.textContent !== noteText) span.textContent = noteText;
      } else if (document.activeElement !== li) {
        if (li.textContent !== noteText) li.textContent = noteText;
      }
    });
    Array.prototype.slice.call(list.children).forEach(function (li) {
      if (!seenIds[li.id.slice(3)]) list.removeChild(li);
    });
  }

  // Editing a footer <li> writes straight back into its marker's
  // `data-note` attribute -- that attribute lives inside the real block
  // content (the <sup> sits inside some paragraph's own contenteditable
  // html), so this mutation is what Editor.js's own change-tracking
  // already picks up to schedule an autosave (notebook_editor.js's
  // onChange), same as editing a footnote via the inline toolbar's
  // textarea already did before this.
  document.addEventListener("input", function (e) {
    var li = e.target.closest(".cdx-footnote-list li");
    if (!li) return;
    var mark = document.getElementById("fn-ref-" + li.id.slice(3));
    if (mark) mark.setAttribute("data-note", li.textContent);
  });

  // "Treated as simple text" (direct request) -- a footnote entry is one
  // line, no nested formatting: Enter does nothing (no multi-line/no new
  // list item splitting a contenteditable <li> in two), and pasting
  // strips any rich markup down to plain text.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    if (!e.target.closest(".cdx-footnote-list li")) return;
    e.preventDefault();
  });
  document.addEventListener("paste", function (e) {
    var li = e.target.closest(".cdx-footnote-list li");
    if (!li) return;
    e.preventDefault();
    var text = (e.clipboardData || window.clipboardData).getData("text/plain");
    document.execCommand("insertText", false, text);
  });

  // Click a marker in the text to jump down to its footer entry. (Jumping
  // the other direction, footer -> marker, was dropped now that the
  // footer is itself editable -- a click there needs to place the caret,
  // not scroll the page out from under it.)
  document.addEventListener("click", function (e) {
    var mark = e.target.closest(".cdx-footnote-ref");
    if (!mark) return;
    var target = document.getElementById(
      "fn-" + mark.getAttribute("data-note-id")
    );
    if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // --------------------------------------------------------------------
  // Footnote -> endnote overhaul, session 9a (roadmap item J, 2026-10-03):
  // a slash-command block that opens an action menu, the one "Page
  // citation" action wired end to end this session (the other five --
  // ibidem/opere citato/confer/apud/passim -- are rendered disabled
  // below, scheduled for session 9b per the roadmap's own sequencing).
  // The old plain-text textarea input above (renderActions) is
  // deliberately left working alongside this -- removing it now, before
  // 9b/9c land the rest of the action list, would regress authoring
  // capability with no full replacement yet; roadmap doc has this flagged
  // as a noted deviation from item J's own bullet order, not an
  // oversight.
  // --------------------------------------------------------------------

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

  // Edit affordance on a structured footer entry (li.cdx-footnote-list-
  // item-structured) -- reopens the same citation+page picker, pre-filled
  // from the marker's own `data-footnote-data`, so regenerating is always
  // starting from the exact inputs that built the current text (roadmap:
  // "reopening the same modal pre-filled ... for re-generation").
  //
  // 2026-10-04 (floating-popover -> real-modal rewrite, same change as
  // notebook_wikilinks.js's openFloatingPicker): this used to be a small
  // `position:fixed` popover anchored to the footer entry, appended to
  // `document.body` and closed by a `document`-level `mousedown`-capture
  // listener this file owned itself. Now opens through
  // `window.CCModal.openCustom` (static/modal.js) instead, the same
  // shared overlay every other modal in the app uses -- no bespoke
  // outside-click/Escape wiring to get subtly wrong, and one less
  // anchored-popover shape in this file to maintain.
  function closeEditPicker() {
    window.CCModal.close();
  }
  // One search+results widget (a labeled input + its own dropdown), used
  // standalone for the simple kinds and twice side by side for Apud's two
  // sources -- factored out of the old single-citation-only version so
  // session 9b's extra kinds don't each re-derive the same input/debounce/
  // render wiring.
  function buildCitationSearchField(initialDisplay, onPick) {
    var field = document.createElement("div");
    field.className = "cdx-footnote-edit-field";
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Search citations...";
    input.className = "cdx-footnote-picker-input";
    input.value = initialDisplay || "";
    var results = document.createElement("ul");
    results.className = "cdx-footnote-picker-results";
    field.appendChild(input);
    field.appendChild(results);
    function runSearch() {
      searchCitations(input.value, function (items) {
        renderCitationResultsInto(results, items, function (item) {
          onPick(item);
          input.value = item.display;
          results.innerHTML = "";
        });
      });
    }
    input.addEventListener("input", debounce(runSearch, 200));
    return { el: field, input: input, runSearch: runSearch };
  }
  function buildPageField(initialPage) {
    var row = document.createElement("div");
    row.className = "cdx-footnote-picker-page-row";
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Page";
    input.className = "cdx-footnote-picker-page-input";
    input.value = initialPage || "";
    row.appendChild(input);
    return { el: row, input: input };
  }
  // Generalized for every structured kind session 9b added, not just Page
  // citation -- Ibidem has no search field at all (its citation is
  // resolved contextually, not user-picked, so only the page is editable),
  // Apud has two independent search fields instead of one, Passim has no
  // page field. Every other kind (Page citation/Confer/Opere citato)
  // shares the same single-search-plus-page shape the original version
  // already had.
  function openFootnoteEditPicker(li) {
    var mark = document.getElementById("fn-ref-" + li.id.slice(3));
    if (!mark) return;
    var kind = mark.getAttribute("data-footnote-kind");
    if (!kind) return; // plain custom notes stay contentEditable, no Edit button for them
    var stored = parseFootnoteData(mark);

    var wrap = document.createElement("div");
    wrap.className = "cdx-footnote-picker cdx-footnote-modal-picker";

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "cdx-footnote-picker-insert-btn";
    saveBtn.textContent = "Save";

    function finish(data) {
      mark.setAttribute("data-note", formatFootnoteText(kind, data));
      mark.setAttribute("data-footnote-data", JSON.stringify(data));
      var mount = mark.closest("#notebook-editor");
      if (mount) {
        renderFootnoteList(mount);
        mount.dispatchEvent(new CustomEvent("notebook-footnote-change"));
      }
      closeEditPicker();
    }

    var firstFocusEl;
    if (kind === "ibidem") {
      var ibidemLabel = document.createElement("div");
      ibidemLabel.className = "cdx-footnote-picker-page-label";
      ibidemLabel.textContent = stored.citation ? "Ibid. — " + stored.citation.display : "Ibid.";
      wrap.appendChild(ibidemLabel);
      var ibidemPage = buildPageField(stored.page);
      wrap.appendChild(ibidemPage.el);
      wrap.appendChild(saveBtn);
      saveBtn.addEventListener("click", function () {
        finish({ citation: stored.citation, page: ibidemPage.input.value.trim() });
      });
      firstFocusEl = ibidemPage.input;
    } else if (kind === "apud") {
      var original = stored.citations ? stored.citations.original : null;
      var secondary = stored.citations ? stored.citations.secondary : null;
      var originalField = buildCitationSearchField(original ? original.display : "", function (item) {
        original = item;
      });
      var secondaryField = buildCitationSearchField(secondary ? secondary.display : "", function (item) {
        secondary = item;
      });
      var apudPage = buildPageField(stored.page);
      wrap.appendChild(originalField.el);
      wrap.appendChild(secondaryField.el);
      wrap.appendChild(apudPage.el);
      wrap.appendChild(saveBtn);
      saveBtn.addEventListener("click", function () {
        if (!original || !secondary) return;
        finish({ citations: { original: original, secondary: secondary }, page: apudPage.input.value.trim() });
      });
      firstFocusEl = originalField.input;
      originalField.runSearch();
      secondaryField.runSearch();
    } else {
      // page_citation, confer, opere_citato, passim
      var citation = stored.citation || null;
      var searchField = buildCitationSearchField(citation ? citation.display : "", function (item) {
        citation = item;
      });
      wrap.appendChild(searchField.el);
      var showsPage = kind !== "passim";
      var pageField = showsPage ? buildPageField(stored.page) : null;
      if (pageField) wrap.appendChild(pageField.el);
      wrap.appendChild(saveBtn);
      saveBtn.addEventListener("click", function () {
        if (!citation) return;
        finish({ citation: citation, page: pageField ? pageField.input.value.trim() : "" });
      });
      firstFocusEl = searchField.input;
      searchField.runSearch();
    }

    window.CCModal.openCustom({
      title: "Edit endnote",
      bodyNode: wrap,
    });
    firstFocusEl.focus();
  }

  // The slash-command block itself. Same shape as notebook_wikilinks.js's
  // NotebookWikilinkBlock (a placeholder block tool whose render() is a
  // picker UI, replaced by a plain paragraph containing the real marker
  // once something is picked) -- but with an extra first step, the action
  // menu, since a footnote has six different ways to build its text
  // instead of wikilink's one. Each step re-renders into the same wrap
  // node (no re-running Editor.js's own render()) since there's no public
  // "re-render this block" API short of delete+insert, which would also
  // lose focus/scroll position mid-flow.
  // "Custom note" (2026-10-03, direct clarification) -- citations are not
  // the only reason to drop a footnote; a plain editorial aside ("the
  // analysis here could be read two ways...") is just as real a case and
  // needs to stay a first-class action in this same menu, not something
  // only reachable through the old inline-toolbar textarea. Listed first
  // since it's the more generic/common case. Its result has no
  // `data-footnote-kind` at all (same marker shape the old inline tool's
  // `surround()` already produces), so the footer entry it creates is
  // plain `contentEditable`, exactly like every footnote made the old
  // way -- no Edit-button/regenerate machinery, because there is nothing
  // structured to regenerate from.
  // Session 9b (2026-10-03): all five remaining actions wired. Each
  // button sets `this.action` and picks the first step for that action's
  // own flow -- most share the generic search->page shape, but Ibidem
  // (no search at all, resolved contextually) and Apud (two searches, not
  // one) and Passim (no page at all) each need their own entry point.
  var FOOTNOTE_ACTIONS = [
    { key: "custom_note", label: "Custom note", enabled: true },
    { key: "page_citation", label: "Page citation", enabled: true },
    { key: "ibidem", label: "Ibidem", enabled: true },
    { key: "opere_citato", label: "Opere citato", enabled: true },
    { key: "confer", label: "Confer", enabled: true },
    { key: "apud", label: "Apud", enabled: true },
    { key: "passim", label: "Passim", enabled: true },
  ];
  function NotebookFootnoteBlock(params) {
    this.api = params.api;
    this.wrap = null;
    this.picked = false;
    this.step = "menu";
    this.action = null;
    this.selectedCitation = null; // single-citation kinds, and Apud's "original"
    this.selectedSecondaryCitation = null; // Apud only -- the "found quoted in" source
    this.ibidemCitation = null; // Ibidem only -- resolved from the previous citation-bearing marker, never user-picked
  }
  NotebookFootnoteBlock.toolbox = { title: "Endnote", icon: footnoteIcon() };
  NotebookFootnoteBlock.prototype.render = function () {
    this.wrap = document.createElement("div");
    this.wrap.className = "cdx-footnote-action-block";
    this.renderStep();
    var self = this;
    this.wrap.addEventListener("keydown", function (e) {
      if (e.key === "Escape") self.cancel();
    });
    return this.wrap;
  };
  NotebookFootnoteBlock.prototype.renderStep = function () {
    this.wrap.innerHTML = "";
    if (this.step === "menu") this.renderMenu();
    else if (this.step === "custom") this.renderCustomStep();
    else if (this.step === "search") this.renderSearch();
    else if (this.step === "search2") this.renderSearch2();
    else if (this.step === "page") this.renderPageStep();
    else if (this.step === "ibidem_page") this.renderIbidemPage();
    else if (this.step === "ibidem_none") this.renderIbidemNone();
  };
  NotebookFootnoteBlock.prototype.renderMenu = function () {
    var self = this;
    var menu = document.createElement("div");
    menu.className = "cdx-footnote-action-menu";
    FOOTNOTE_ACTIONS.forEach(function (action) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cdx-footnote-action-btn";
      btn.textContent = action.label;
      if (!action.enabled) {
        btn.disabled = true;
        btn.title = "Coming in a later session";
      } else {
        btn.addEventListener("click", function () {
          self.action = action.key;
          if (action.key === "custom_note") {
            self.step = "custom";
          } else if (action.key === "ibidem") {
            // Resolved immediately, not picked by the user -- Ibidem means
            // "whatever the previous footnote cited," so there's nothing
            // to search for.
            var prev = findPreviousCitationData(self.wrap);
            if (prev) {
              self.ibidemCitation = prev;
              self.step = "ibidem_page";
            } else {
              self.step = "ibidem_none";
            }
          } else {
            self.step = "search";
          }
          self.renderStep();
        });
      }
      menu.appendChild(btn);
    });
    this.wrap.appendChild(menu);
    var hint = document.createElement("div");
    hint.className = "cdx-footnote-action-hint";
    hint.textContent = "Esc to cancel";
    this.wrap.appendChild(hint);
  };
  NotebookFootnoteBlock.prototype.renderCustomStep = function () {
    var self = this;
    var wrap = document.createElement("div");
    wrap.className = "cdx-footnote-custom-note";
    var textarea = document.createElement("textarea");
    textarea.placeholder = "Endnote text (Esc to cancel)";
    textarea.className = "cdx-footnote-input";
    var insertBtn = document.createElement("button");
    insertBtn.type = "button";
    insertBtn.className = "cdx-footnote-picker-insert-btn";
    insertBtn.textContent = "Insert";
    insertBtn.addEventListener("click", function () {
      self.insertCustomNote(textarea.value.trim());
    });
    wrap.appendChild(textarea);
    wrap.appendChild(insertBtn);
    this.wrap.appendChild(wrap);
    setTimeout(function () {
      textarea.focus();
    }, 0);
  };
  // Shared first search step for every action except Custom note/Ibidem.
  // Opere citato filters results down to citations already used somewhere
  // earlier in this document (`collectUsedCitationUids`); Passim skips the
  // page step entirely (inserts straight from the pick); Apud moves on to
  // a second search (`search2`) for its secondary source instead of the
  // page step.
  NotebookFootnoteBlock.prototype.renderSearch = function () {
    var self = this;
    var pickerWrap = document.createElement("div");
    pickerWrap.className = "cdx-footnote-picker";
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder =
      (this.action === "apud" ? "Search the original/quoted source..." : "Search citations...") + " (Esc to cancel)";
    input.className = "cdx-footnote-picker-input";
    var results = document.createElement("ul");
    results.className = "cdx-footnote-picker-results";
    pickerWrap.appendChild(input);
    pickerWrap.appendChild(results);
    this.wrap.appendChild(pickerWrap);
    function runSearch() {
      searchCitations(input.value, function (items) {
        if (self.action === "opere_citato") {
          var used = collectUsedCitationUids(self.wrap);
          items = items.filter(function (item) {
            return used[item.uid];
          });
        }
        renderCitationResultsInto(results, items, function (item) {
          self.selectedCitation = item;
          if (self.action === "apud") self.step = "search2";
          else if (self.action === "passim") {
            self.insertFootnote();
            return;
          } else self.step = "page";
          self.renderStep();
        });
      });
    }
    input.addEventListener("input", debounce(runSearch, 200));
    setTimeout(function () {
      input.focus();
      runSearch();
    }, 0);
  };
  // Apud's second search -- the source the quotation was actually read
  // in, picked after the original/quoted source above.
  NotebookFootnoteBlock.prototype.renderSearch2 = function () {
    var self = this;
    var pickerWrap = document.createElement("div");
    pickerWrap.className = "cdx-footnote-picker";
    var label = document.createElement("div");
    label.className = "cdx-footnote-picker-page-label";
    label.textContent = "Original: " + this.selectedCitation.display;
    var input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Search the source you found it quoted in... (Esc to cancel)";
    input.className = "cdx-footnote-picker-input";
    var results = document.createElement("ul");
    results.className = "cdx-footnote-picker-results";
    pickerWrap.appendChild(label);
    pickerWrap.appendChild(input);
    pickerWrap.appendChild(results);
    this.wrap.appendChild(pickerWrap);
    function runSearch() {
      searchCitations(input.value, function (items) {
        renderCitationResultsInto(results, items, function (item) {
          self.selectedSecondaryCitation = item;
          self.step = "page";
          self.renderStep();
        });
      });
    }
    input.addEventListener("input", debounce(runSearch, 200));
    setTimeout(function () {
      input.focus();
      runSearch();
    }, 0);
  };
  NotebookFootnoteBlock.prototype.renderPageStep = function () {
    var self = this;
    var row = document.createElement("div");
    row.className = "cdx-footnote-picker-page-row";
    var label = document.createElement("span");
    label.className = "cdx-footnote-picker-page-label";
    label.textContent =
      this.action === "apud"
        ? this.selectedCitation.display + " / apud " + this.selectedSecondaryCitation.display
        : this.selectedCitation.display;
    var pageInput = document.createElement("input");
    pageInput.type = "text";
    pageInput.placeholder = "Page (Esc to cancel)";
    pageInput.className = "cdx-footnote-picker-page-input";
    var insertBtn = document.createElement("button");
    insertBtn.type = "button";
    insertBtn.className = "cdx-footnote-picker-insert-btn";
    insertBtn.textContent = "Insert";
    function doInsert() {
      self.insertFootnote(pageInput.value.trim());
    }
    insertBtn.addEventListener("click", doInsert);
    pageInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        doInsert();
      }
    });
    row.appendChild(label);
    row.appendChild(pageInput);
    row.appendChild(insertBtn);
    this.wrap.appendChild(row);
    setTimeout(function () {
      pageInput.focus();
    }, 0);
  };
  NotebookFootnoteBlock.prototype.renderIbidemPage = function () {
    var self = this;
    var row = document.createElement("div");
    row.className = "cdx-footnote-picker-page-row";
    var label = document.createElement("span");
    label.className = "cdx-footnote-picker-page-label";
    label.textContent = "Ibid. — " + this.ibidemCitation.display;
    var pageInput = document.createElement("input");
    pageInput.type = "text";
    pageInput.placeholder = "Page, if different (Esc to cancel)";
    pageInput.className = "cdx-footnote-picker-page-input";
    var insertBtn = document.createElement("button");
    insertBtn.type = "button";
    insertBtn.className = "cdx-footnote-picker-insert-btn";
    insertBtn.textContent = "Insert";
    function doInsert() {
      self.insertIbidem(pageInput.value.trim());
    }
    insertBtn.addEventListener("click", doInsert);
    pageInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        doInsert();
      }
    });
    row.appendChild(label);
    row.appendChild(pageInput);
    row.appendChild(insertBtn);
    this.wrap.appendChild(row);
    setTimeout(function () {
      pageInput.focus();
    }, 0);
  };
  NotebookFootnoteBlock.prototype.renderIbidemNone = function () {
    var self = this;
    var hint = document.createElement("div");
    hint.className = "cdx-footnote-action-hint";
    hint.textContent = "No previous citation in this document to refer back to.";
    this.wrap.appendChild(hint);
    var backBtn = document.createElement("button");
    backBtn.type = "button";
    backBtn.className = "cdx-footnote-action-btn";
    backBtn.textContent = "Back";
    backBtn.addEventListener("click", function () {
      self.step = "menu";
      self.renderStep();
    });
    this.wrap.appendChild(backBtn);
  };
  // `getCurrentBlockIndex()` is only as fresh as Editor.js's own click/
  // focus bookkeeping, which the action-menu's own buttons (not a real
  // contenteditable caret landing) don't reliably update -- confirmed
  // live: a block picked via mouse click through the toolbox stayed
  // marked "selected" in the DOM, yet `getCurrentBlockIndex()`-based
  // deletion silently missed it entirely (same failure mode
  // notebook_editor.js's own `isCaretAtEnd`/markdown-shortcuts comment
  // already documents -- no thrown error, just the wrong block, or none,
  // deleted). Deriving the index from this block's own wrap element
  // instead sidesteps that bookkeeping altogether.
  NotebookFootnoteBlock.prototype.ownIndex = function () {
    var block = this.api.blocks.getBlockByElement(this.wrap);
    return block ? this.api.blocks.getBlockIndex(block.id) : this.api.blocks.getCurrentBlockIndex();
  };
  // Shared by every action's final step (citation-based or plain) --
  // replaces this placeholder block with a plain paragraph containing
  // just the finished marker, same `insert`+`delete` shape
  // NotebookWikilinkBlock.pick() already established.
  NotebookFootnoteBlock.prototype.insertMarkerBlock = function (marker) {
    this.picked = true;
    var index = this.ownIndex();
    this.api.blocks.insert("paragraph", { text: marker.outerHTML + "&nbsp;" }, {}, index, true);
    this.api.blocks.delete(index + 1);
    // The inserted paragraph lives inside Editor.js's own observed
    // redactor, so `renderFootnoteList` picks it up via the normal
    // onChange -> notebookRenderFootnoteList hook (notebook_editor.js)
    // the very next tick -- no direct call needed here, same as how
    // NotebookWikilinkBlock.pick() never calls renderRelationships itself
    // either.
  };
  // Shared by every citation-bearing action except Ibidem (own method
  // below, since it never goes through `search`/`page` -- its citation is
  // resolved contextually, not stored on `this.selectedCitation`). The
  // data shape stored varies by action (`formatFootnoteText`'s own
  // dispatch already documents which): Apud stores `citations.{original,
  // secondary}` instead of a single `citation`; Passim stores no `page`
  // at all (there's no per-call page field for it to come from).
  NotebookFootnoteBlock.prototype.insertFootnote = function (page) {
    var data =
      this.action === "apud"
        ? { citations: { original: this.selectedCitation, secondary: this.selectedSecondaryCitation }, page: page }
        : this.action === "passim"
        ? { citation: this.selectedCitation }
        : { citation: this.selectedCitation, page: page };
    var marker = document.createElement("sup");
    marker.className = "cdx-footnote-ref";
    marker.setAttribute("data-note-id", generateId());
    marker.setAttribute("data-note", formatFootnoteText(this.action, data));
    marker.setAttribute("data-footnote-kind", this.action);
    marker.setAttribute("data-footnote-data", JSON.stringify(data));
    marker.contentEditable = "false";
    this.insertMarkerBlock(marker);
  };
  NotebookFootnoteBlock.prototype.insertIbidem = function (page) {
    var data = { citation: this.ibidemCitation, page: page };
    var marker = document.createElement("sup");
    marker.className = "cdx-footnote-ref";
    marker.setAttribute("data-note-id", generateId());
    marker.setAttribute("data-note", formatFootnoteText("ibidem", data));
    marker.setAttribute("data-footnote-kind", "ibidem");
    marker.setAttribute("data-footnote-data", JSON.stringify(data));
    marker.contentEditable = "false";
    this.insertMarkerBlock(marker);
  };
  // Plain editorial aside, not tied to any citation -- the marker here is
  // identical in shape to the one the old inline-toolbar's `surround()`
  // creates (no `data-footnote-kind`/`data-footnote-data` at all), so its
  // footer entry is directly `contentEditable`, same as every pre-
  // existing footnote, with no Edit-button/regenerate step (there's no
  // structured input behind free text to regenerate from).
  NotebookFootnoteBlock.prototype.insertCustomNote = function (text) {
    if (!text) return;
    var marker = document.createElement("sup");
    marker.className = "cdx-footnote-ref";
    marker.setAttribute("data-note-id", generateId());
    marker.setAttribute("data-note", text);
    marker.contentEditable = "false";
    this.insertMarkerBlock(marker);
  };
  NotebookFootnoteBlock.prototype.cancel = function () {
    if (this.picked) return;
    this.picked = true;
    this.api.blocks.delete(this.ownIndex());
  };
  NotebookFootnoteBlock.prototype.save = function () {
    return {};
  };

  window.NotebookFootnote = NotebookFootnote;
  window.NotebookFootnoteBlock = NotebookFootnoteBlock;
  window.notebookRenderFootnoteList = renderFootnoteList;
})();
