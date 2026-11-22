/* The page reader for EPUB, MOBI, FB2, comics and PDF, drawn by the vendored foliate-js: pages, chapters, coloured highlights with
   notes, search, lookups, full screen and touch. */
import { makeBook } from "./foliate/view.js";
import { Overlayer } from "./foliate/overlayer.js";

const root = document.querySelector("[data-book-reader]");
if (root) {
  const uid = root.dataset.uid;
  // The language named for the attached file wins over the one the book file declares; both feed reading aloud and the lookups.
  const bookLanguage = () => root.dataset.language || (view.language && view.language.canonical) || "";
  const settings = JSON.parse(root.dataset.reader || "{}");
  const choices = JSON.parse(root.dataset.choices || "{}");
  const position = JSON.parse(root.dataset.position || "{}");
  const lookups = JSON.parse(root.dataset.lookups || "[]");
  const annotations = JSON.parse(root.dataset.annotations || "[]");
  const kind = root.dataset.kind || "book";
  const isPdf = kind === "pdf";
  const isComic = kind === "comic";
  const isFixed = isPdf || isComic; // pages as they are, no reflowing text
  const bookmarks = JSON.parse(root.dataset.bookmarks || "[]");
  const view = document.getElementById("book-view");
  const pop = document.getElementById("reader-pop");
  const percent = root.querySelector("[data-reader-percent]");
  const list = document.querySelector("[data-reader-annotations]");
  const empty = document.querySelector("[data-reader-annotations-empty]");
  const COLORS = { yellow: "#e0b100", orange: "#e8803a", green: "#4caf50", blue: "#3b82f6", pink: "#e05297" };
  let picked = null; // the text selected now: { doc, index, range, quote }
  let current = null; // the highlight the popover is about: its annotation
  let saveTimer = 0;
  let lastPlace = null;
  let unsaved = false;
  let selTimer = 0;

  // ---- Appearance ----
  const FONTS = { serif: "Georgia, 'Times New Roman', serif", sans: "system-ui, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif", mono: "ui-monospace, 'DejaVu Sans Mono', Menlo, monospace" };
  const THEMES = { light: ["#1d1d1f", "#ffffff"], sepia: ["#4a3b27", "#f4ecd8"], dark: ["#e6e6e6", "#2b2b2b"] };
  function palette() {
    const t = settings.theme === "app" ? (document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light") : settings.theme;
    return THEMES[t] || THEMES.light;
  }
  function styles() {
    const [fg, bg] = palette();
    const justify = settings.justify === "on";
    const hyph = settings.hyphenate === "on";
    const family = FONTS[settings.font];
    const face = family ? `html, body, p, li, blockquote, div, span, h1, h2, h3, h4, h5, h6{font-family:${family} !important;}` : "";
    return `${face}
      html{color:${fg} !important; background:${bg} !important; font-size:${settings.font_size}% !important;}
      body, p, li, blockquote, div{line-height:${settings.line_height} !important; color:${fg} !important;}
      p, li, blockquote{text-align:${justify ? "justify" : "start"} !important; hyphens:${hyph ? "auto" : "manual"} !important; -webkit-hyphens:${hyph ? "auto" : "manual"} !important;}
      a{color:inherit !important; text-decoration:underline;} img, svg{max-width:100%;}`;
  }
  function applySettings() {
    const r = view.renderer;
    if (!r) return;
    root.querySelectorAll("[data-value-of]").forEach((el) => {
      const key = el.dataset.valueOf;
      const hit = (choices[key] || []).find((c) => c[0] === settings[key]);
      el.textContent = hit ? hit[1] : settings[key];
    });
    root.querySelectorAll("[data-set]").forEach((b) => b.classList.toggle("active", settings[b.dataset.set] === b.dataset.val));
    root.querySelector(".reader-stage").style.filter = settings.brightness && settings.brightness !== "100" ? `brightness(${Number(settings.brightness) / 100})` : "";
    if (isFixed) {
      r.setAttribute("zoom", settings.pdf_zoom || "fit-page");
      root.querySelector(".reader-stage").style.background = "var(--bg-secondary)";
      return;
    }
    r.setAttribute("flow", settings.layout === "scrolled" ? "scrolled" : "paginated");
    r.setAttribute("max-column-count", settings.layout === "single" ? "1" : "2");
    r.setAttribute("gap", settings.margin + "%");
    r.setAttribute("animated", "");
    if (r.setStyles) r.setStyles(styles());
    root.querySelector(".reader-stage").style.background = palette()[1];
  }
  function persist() {
    const body = new FormData();
    Object.entries(settings).forEach(([k, v]) => body.set("reader_" + k, v));
    fetch("/settings/library/reader", { method: "POST", headers: { "X-Requested-With": "fetch" }, body });
  }
  const panel = root.querySelector("[data-reader-panel]");
  const appearance = document.querySelector("[data-reader-appearance]");
  appearance.addEventListener("click", (e) => {
    e.stopPropagation();
    panel.hidden = !panel.hidden;
    appearance.setAttribute("aria-expanded", String(!panel.hidden));
  });
  document.addEventListener("click", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && !e.target.closest("[data-reader-appearance]")) panel.hidden = true;
    if (!pop.hidden && !pop.contains(e.target) && !picked) hidePop();
  });
  panel.addEventListener("click", (e) => {
    const step = e.target.closest("[data-step]");
    const set = e.target.closest("[data-set]");
    if (step) {
      const opts = (choices[step.dataset.step] || []).map((c) => c[0]);
      const at = Math.max(0, opts.indexOf(settings[step.dataset.step]));
      settings[step.dataset.step] = opts[Math.max(0, Math.min(opts.length - 1, at + Number(step.dataset.dir)))];
    } else if (set) settings[set.dataset.set] = set.dataset.val;
    else return;
    applySettings();
    persist();
    if (isFixed && set && ["layout", "direction"].includes(set.dataset.set)) setTimeout(() => window.location.reload(), 250);
  });
  panel.addEventListener("change", (e) => {
    const t = e.target.closest("[data-toggle]");
    if (!t) return;
    settings[t.dataset.toggle] = t.checked ? "on" : "off";
    applySettings();
    persist();
  });

  function fail(message) {
    const box = root.querySelector("[data-reader-error]");
    box.textContent = message;
    box.hidden = false;
  }
  function post(path, data) {
    const body = new FormData();
    Object.entries(data).forEach(([k, v]) => body.set(k, v));
    return fetch(`/library/${uid}/${path}`, { method: "POST", headers: { "X-Requested-With": "fetch" }, body });
  }

  // ---- The sidebar ----
  function showPanel(name) {
    document.documentElement.removeAttribute("data-notebook-sidebar-collapsed");
    const option = document.querySelector(`[data-notebook-sidebar-tab="${name}"]`);
    if (option) option.click();
  }

  // Chapters
  function renderToc(items, into) {
    const ul = document.createElement("ul");
    ul.className = "reader-toc-list";
    (items || []).forEach((item) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = "#";
      a.textContent = (item.label || "").trim() || "Untitled";
      a.dataset.href = item.href || "";
      li.appendChild(a);
      if (item.subitems && item.subitems.length) renderToc(item.subitems, li);
      ul.appendChild(li);
    });
    into.appendChild(ul);
  }
  document.addEventListener("click", (e) => {
    const link = e.target.closest && e.target.closest("[data-reader-toc] a[data-href]");
    if (link) {
      e.preventDefault();
      view.goTo(link.dataset.href);
    }
  });

  // Annotations
  function colorOf(a) {
    return COLORS[a.color] || COLORS.yellow;
  }
  function renderAnnotations() {
    list.innerHTML = "";
    annotations.forEach((a) => {
      const li = document.createElement("li");
      li.dataset.uid = a.uid;
      li.style.setProperty("--mark", colorOf(a));
      const q = document.createElement("a");
      q.href = "#";
      q.className = "reader-quote";
      q.textContent = "“" + a.quote.slice(0, 160) + (a.quote.length > 160 ? "…" : "") + "”";
      q.addEventListener("click", (e) => { e.preventDefault(); goToAnnotation(a); });
      li.appendChild(q);
      const note = document.createElement("div");
      note.className = "reader-note" + (a.note ? "" : " is-empty");
      note.textContent = a.note || "Add a note";
      note.tabIndex = 0;
      note.setAttribute("role", "button");
      const edit = () => editNote(a, note);
      note.addEventListener("click", edit);
      note.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); edit(); } });
      li.appendChild(note);
      const row = document.createElement("div");
      row.className = "reader-annotation-tools";
      Object.keys(COLORS).forEach((name) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "reader-swatch reader-swatch-" + name + (a.color === name ? " is-on" : "");
        b.title = "Colour " + name;
        b.setAttribute("aria-label", "Colour " + name);
        b.addEventListener("click", () => recolor(a, name));
        row.appendChild(b);
      });
      const del = document.createElement("button");
      del.type = "button";
      del.className = "icon-btn";
      del.title = "Remove";
      del.setAttribute("aria-label", "Remove highlight");
      del.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-trash"></use></svg>';
      del.addEventListener("click", () => removeAnnotation(a));
      row.appendChild(del);
      li.appendChild(row);
      list.appendChild(li);
    });
    empty.hidden = annotations.length > 0;
  }
  function editNote(a, el) {
    const area = document.createElement("textarea");
    area.className = "reader-note-edit";
    area.rows = 3;
    area.value = a.note || "";
    area.setAttribute("aria-label", "Note");
    el.replaceWith(area);
    area.focus();
    const done = async () => {
      a.note = area.value.trim();
      await post(`annotations/${a.uid}`, { note: a.note });
      renderAnnotations();
      redraw(a);
    };
    area.addEventListener("blur", done, { once: true });
    area.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { area.value = a.note || ""; area.blur(); }
      else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) area.blur();
    });
  }
  function focusNote(a) {
    showPanel("annotations");
    const li = list.querySelector(`[data-uid="${a.uid}"]`);
    if (!li) return;
    li.scrollIntoView({ block: "nearest" });
    const note = li.querySelector(".reader-note");
    if (note) note.click();
  }
  async function recolor(a, color) {
    a.color = color;
    await post(`annotations/${a.uid}`, { color });
    renderAnnotations();
    redraw(a);
  }
  async function removeAnnotation(a) {
    await post(`annotations/${a.uid}/delete`, { section: 0 });
    annotations.splice(annotations.indexOf(a), 1);
    undraw(a);
    renderAnnotations();
    hidePop();
  }
  function goToAnnotation(a) {
    view.goTo(isPdf ? a.section : a.cfi);
  }

  // ---- Drawing highlights ----
  // EPUB and the like: foliate places each by its CFI. PDF: the page's text layer gets an overlay of its own.
  function redraw(a) {
    if (!isPdf) return view.addAnnotation({ value: a.cfi });
    drawPdfPage(a.section);
  }
  function undraw(a) {
    if (!isPdf) return view.deleteAnnotation({ value: a.cfi });
    drawPdfPage(a.section);
  }
  const pdfDocs = new Map(); // page index -> iframe document
  root.pdfDocs = pdfDocs; // read by the page's tests

  function textRange(doc, needle) {
    // The first run of the text layer's text that reads as `needle`, ignoring spaces and line breaks.
    const walker = doc.createTreeWalker(doc.querySelector(".textLayer") || doc.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let flat = "";
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = n.nodeValue;
      for (let i = 0; i < text.length; i++) {
        if (/\s/.test(text[i])) continue;
        nodes.push([n, i]);
        flat += text[i];
      }
    }
    const want = needle.replace(/\s+/g, "");
    const at = want ? flat.toLowerCase().indexOf(want.toLowerCase()) : -1;
    if (at < 0) return null;
    const range = doc.createRange();
    const [sn, so] = nodes[at];
    const [en, eo] = nodes[at + want.length - 1];
    range.setStart(sn, so);
    range.setEnd(en, eo + 1);
    return range;
  }
  function pdfOverlay(doc) {
    if (!doc.__overlay) {
      doc.__overlay = new Overlayer();
      doc.documentElement.append(doc.__overlay.element);
      doc.__marks = new Map();
    }
    return doc.__overlay;
  }
  function drawPdfPage(index) {
    const doc = pdfDocs.get(index);
    if (!doc || !doc.querySelector(".textLayer")) return;
    const ov = pdfOverlay(doc);
    [...doc.__marks.keys()].forEach((k) => { ov.remove(k); doc.__marks.delete(k); });
    annotations.filter((a) => a.section === index).forEach((a) => {
      const range = textRange(doc, a.quote);
      if (!range) return;
      ov.add(a.uid, range, Overlayer.highlight, { color: colorOf(a) });
      doc.__marks.set(a.uid, a);
    });
    if (pdfSearch.term && pdfSearch.page === index) {
      const range = textRange(doc, pdfSearch.term);
      if (range) { ov.add("search", range, Overlayer.outline, { color: "#ef4444" }); doc.__marks.set("search", null); }
    }
  }

  // ---- Selection and the popover ----
  function frameOffset(doc) {
    const frame = doc.defaultView && doc.defaultView.frameElement;
    const f = frame ? frame.getBoundingClientRect() : { left: 0, top: 0 };
    const box = root.getBoundingClientRect();
    return { x: f.left - box.left, y: f.top - box.top };
  }
  function hidePop() {
    pop.hidden = true;
    pop.querySelector("[data-reader-sources]").hidden = true;
    pop.querySelector("[data-reader-define]").hidden = true;
    picked = null;
    current = null;
  }
  function showPop(doc, range, mode) {
    const off = frameOffset(doc);
    const r = range.getBoundingClientRect();
    pop.hidden = false;
    pop.classList.toggle("is-existing", mode === "existing");
    pop.querySelector('[data-act="note"]').hidden = mode !== "existing";
    pop.querySelector('[data-act="delete"]').hidden = mode !== "existing";
    pop.querySelector("[data-reader-sources]").hidden = true;
    pop.querySelector("[data-reader-define]").hidden = true;
    const top = off.y + r.top - pop.offsetHeight - 8;
    pop.style.top = (top < 4 ? off.y + r.bottom + 8 : top) + "px";
    pop.style.left = Math.max(8, Math.min(off.x + r.left, root.clientWidth - pop.offsetWidth - 8)) + "px";
  }
  function onSelection(doc, index) {
    const sel = doc.getSelection();
    const quote = sel ? sel.toString().trim() : "";
    if (!sel || sel.isCollapsed || !quote) {
      if (picked && picked.doc === doc && !pop.matches(":hover")) hidePop();
      return;
    }
    picked = { doc, index, range: sel.getRangeAt(0), quote };
    current = null;
    showPop(doc, picked.range, "new");
  }
  function attachFrame(doc, index) {
    const later = () => { clearTimeout(selTimer); selTimer = setTimeout(() => onSelection(doc, index), 280); };
    if (!isComic) {
      doc.addEventListener("mouseup", later);
      doc.addEventListener("selectionchange", later); // a long press on a phone selects without any mouse event
    }
    doc.addEventListener("keydown", (ev) => navigate(ev));
    attachTouch(doc);
    if (isPdf) {
      pdfDocs.set(index, doc);
      doc.addEventListener("cc-render", () => { drawPdfPage(index); checkTextLayer(doc); });
      doc.addEventListener("click", (e) => {
        const ov = doc.__overlay;
        if (!ov) return;
        const [key, range] = ov.hitTest({ x: e.clientX, y: e.clientY });
        const a = annotations.find((x) => x.uid === key);
        if (a && (!picked || !picked.quote)) { current = a; picked = null; showPop(doc, range, "existing"); }
      });
    }
  }
  view.addEventListener("load", (e) => attachFrame(e.detail.doc, e.detail.index));
  // A link out of the book opens in a new tab only when it is a web or mail address; anything else (a javascript: link in a
  // hostile book, say) is ignored.
  view.addEventListener("external-link", (e) => {
    e.preventDefault();
    const href = (e.detail && e.detail.href_) || "";
    if (/^(https?:|mailto:)/i.test(href)) window.open(href, "_blank", "noopener,noreferrer");
  });

  async function create(color) {
    if (!picked) return;
    const { index, range, quote, doc } = picked;
    const cfi = isPdf ? "" : view.getCFI(index, range);
    const resp = await post("annotations", { section: index, quote, note: "", cfi, color });
    const data = await resp.json().catch(() => ({}));
    const a = { uid: data.uid, section: index, cfi, quote, note: "", color };
    annotations.push(a);
    redraw(a);
    renderAnnotations();
    const sel = doc.getSelection();
    if (sel) sel.removeAllRanges();
    hidePop();
  }
  pop.addEventListener("pointerdown", (e) => e.preventDefault());
  pop.addEventListener("click", (e) => {
    const swatch = e.target.closest("[data-color]");
    if (swatch) {
      if (current) recolor(current, swatch.dataset.color).then(hidePop);
      else create(swatch.dataset.color);
      return;
    }
    const source = e.target.closest("[data-source]");
    if (source) {
      const text = (picked ? picked.quote : current ? current.quote : "").slice(0, 200);
      window.open(source.dataset.url.replace("%s", encodeURIComponent(text)), "_blank", "noopener,noreferrer");
      return;
    }
    const act = e.target.closest("[data-act]");
    if (!act) return;
    const text = picked ? picked.quote : current ? current.quote : "";
    switch (act.dataset.act) {
      case "cite":
        navigator.clipboard.writeText("“" + text + "” " + root.dataset.cite);
        hidePop();
        break;
      case "define":
        define(text);
        break;
      case "find":
        hidePop();
        showPanel("search");
        document.querySelector("[data-reader-search-input]").value = text.slice(0, 100);
        runSearch(text.slice(0, 100));
        break;
      case "online":
        pop.querySelector("[data-reader-sources]").hidden = !pop.querySelector("[data-reader-sources]").hidden;
        break;
      case "note":
        if (current) { const a = current; hidePop(); focusNote(a); }
        break;
      case "delete":
        if (current) removeAnnotation(current);
        break;
    }
  });
  // EPUB: foliate draws the highlights and tells us when one is clicked.
  view.addEventListener("create-overlay", () => { if (!isPdf) annotations.forEach((a) => a.cfi && view.addAnnotation({ value: a.cfi })); });
  view.addEventListener("draw-annotation", (e) => {
    const { draw, annotation } = e.detail;
    if (annotation.value === ttsMark) { draw(Overlayer.underline, { color: "#3b82f6", width: 3 }); return; }
    const known = annotations.find((a) => a.cfi === annotation.value);
    draw(Overlayer.highlight, { color: known ? colorOf(known) : COLORS.yellow });
  });
  view.addEventListener("show-annotation", (e) => {
    const a = annotations.find((x) => x.cfi === e.detail.value);
    if (!a) return;
    const content = view.renderer.getContents().find((c) => c.index === e.detail.index);
    if (!content) return;
    current = a;
    picked = null;
    showPop(content.doc, e.detail.range, "existing");
  });

  // ---- Search ----
  const searchInput = document.querySelector("[data-reader-search-input]");
  const results = document.querySelector("[data-reader-results]");
  const status = document.querySelector("[data-reader-search-status]");
  const pdfSearch = { term: "", page: -1 };
  let searchRun = 0;

  function excerptNode(pre, match, post) {
    const frag = document.createDocumentFragment();
    frag.append(document.createTextNode(pre));
    const m = document.createElement("mark");
    m.textContent = match;
    frag.append(m, document.createTextNode(post));
    return frag;
  }
  function addResult(group, pre, match, post, go) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = "#";
    a.className = "reader-result";
    a.appendChild(excerptNode(pre, match, post));
    a.addEventListener("click", (e) => { e.preventDefault(); go(); });
    li.appendChild(a);
    group.appendChild(li);
  }
  function addGroup(label) {
    const li = document.createElement("li");
    li.className = "reader-result-group";
    const h = document.createElement("span");
    h.className = "reader-result-label";
    h.textContent = label;
    const ul = document.createElement("ul");
    li.append(h, ul);
    results.appendChild(li);
    return ul;
  }
  async function runSearch(query) {
    query = (query || "").trim();
    const mine = ++searchRun;
    results.innerHTML = "";
    pdfSearch.term = "";
    if (!isPdf) view.clearSearch();
    if (!query) { status.textContent = ""; return; }
    status.textContent = "Searching…";
    let count = 0;
    if (isPdf) {
      const resp = await fetch(`/library/${uid}/search?q=${encodeURIComponent(query)}&edition=${encodeURIComponent(root.dataset.edition)}&format=PDF`);
      const data = await resp.json();
      if (mine !== searchRun) return;
      data.hits.forEach((h) => {
        const m = h.snippet.match(/^(.*?)\[(.*?)\](.*)$/s) || ["", "", query, ""];
        const group = addGroup("Page " + (h.section + 1));
        addResult(group, m[1], m[2], m[3], () => { pdfSearch.term = query; pdfSearch.page = h.section; view.goTo(h.section); drawPdfPage(h.section); });
        count++;
      });
      status.textContent = data.error || (count ? count + (count === 1 ? " result" : " results") : "Nothing found");
      return;
    }
    for await (const r of view.search({ query })) {
      if (mine !== searchRun) return;
      if (r === "done") break;
      if (!r.subitems) continue;
      const group = addGroup((r.label || "").trim() || "Book");
      r.subitems.forEach(({ cfi, excerpt }) => {
        addResult(group, excerpt.pre, excerpt.match, excerpt.post, () => view.goTo(cfi));
        count++;
      });
      status.textContent = count + (count === 1 ? " result" : " results") + "…";
    }
    if (mine === searchRun) status.textContent = count ? count + (count === 1 ? " result" : " results") : "Nothing found";
  }
  document.querySelector("[data-reader-search-form]").addEventListener("submit", (e) => { e.preventDefault(); runSearch(searchInput.value); });

  // ---- Turning pages: keys, buttons, touch ----
  function navigate(ev) {
    if (ev.target.closest && ev.target.closest("input, textarea, select")) return;
    if (ev.key === "ArrowRight" || ev.key === "PageDown") { view.next(); ev.preventDefault(); }
    else if (ev.key === "ArrowLeft" || ev.key === "PageUp") { view.prev(); ev.preventDefault(); }
    else if (ev.key === "Escape" && root.classList.contains("is-fullscreen") && !document.fullscreenElement) setFullscreen(false);
  }
  document.addEventListener("keydown", navigate);
  function attachTouch(doc) {
    let start = null;
    doc.addEventListener("touchstart", (e) => {
      start = e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() } : null;
    }, { passive: true });
    doc.addEventListener("touchend", (e) => {
      if (!start || settings.layout === "scrolled") return;
      const t = e.changedTouches[0];
      const dx = t.clientX - start.x;
      const dy = t.clientY - start.y;
      const quick = Date.now() - start.t < 350;
      const picking = doc.getSelection && !doc.getSelection().isCollapsed;
      const width = doc.documentElement.clientWidth || 1;
      start = null;
      if (picking) return;
      if (Math.abs(dx) > 50 && Math.abs(dy) < 60 && Math.abs(dx) > Math.abs(dy) * 1.5) { dx < 0 ? view.next() : view.prev(); return; }
      if (quick && Math.abs(dx) < 10 && Math.abs(dy) < 10 && !e.target.closest("a[href]")) {
        // a tap near the left or right edge turns the page
        if (t.clientX < width * 0.22) view.prev();
        else if (t.clientX > width * 0.78) view.next();
      }
    }, { passive: true });
  }
  root.querySelector("[data-reader-prev]").addEventListener("click", () => view.prev());
  root.querySelector("[data-reader-next]").addEventListener("click", () => view.next());
  const backBtn = root.querySelector("[data-reader-back]");
  backBtn.addEventListener("click", () => view.history.back());

  // ---- Full screen ----
  const fsBtn = root.querySelector("[data-reader-fullscreen]");
  const sideBtn = root.querySelector("[data-reader-side]");
  let sidebarWas = false;
  function setFullscreen(on) {
    root.classList.toggle("is-fullscreen", on);
    document.documentElement.toggleAttribute("data-reader-fullscreen", on);
    fsBtn.setAttribute("aria-pressed", String(on));
    fsBtn.title = fsBtn.ariaLabel = on ? "Leave full screen" : "Full screen";
    fsBtn.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-' + (on ? "minimize-2" : "maximize-2") + '"></use></svg>';
    sideBtn.hidden = !on;
    if (on) {
      sidebarWas = document.documentElement.hasAttribute("data-notebook-sidebar-collapsed");
      document.documentElement.setAttribute("data-notebook-sidebar-collapsed", "1");
    } else if (!sidebarWas) {
      document.documentElement.removeAttribute("data-notebook-sidebar-collapsed");
    }
    if (on && document.documentElement.requestFullscreen && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
  }
  fsBtn.addEventListener("click", () => setFullscreen(!root.classList.contains("is-fullscreen")));
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && root.classList.contains("is-fullscreen")) setFullscreen(false); });
  sideBtn.addEventListener("click", () => {
    const html = document.documentElement;
    if (html.hasAttribute("data-notebook-sidebar-collapsed")) html.removeAttribute("data-notebook-sidebar-collapsed");
    else html.setAttribute("data-notebook-sidebar-collapsed", "1");
  });

  // ---- The progress bar ----
  const bar = root.querySelector("[data-reader-progress]");
  const fill = root.querySelector("[data-reader-fill]");
  const thumb = root.querySelector("[data-reader-thumb]");
  const tip = root.querySelector("[data-reader-tip]");
  let dragging = false;
  function paint(f) {
    const pct = Math.round(f * 1000) / 10;
    fill.style.width = pct + "%";
    thumb.style.left = pct + "%";
    percent.textContent = Math.round(f * 100) + "%";
    bar.setAttribute("aria-valuenow", String(Math.round(f * 100)));
  }
  function fractionAt(ev) {
    const r = bar.getBoundingClientRect();
    return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
  }
  bar.addEventListener("pointerdown", (ev) => { dragging = true; bar.setPointerCapture(ev.pointerId); paint(fractionAt(ev)); });
  bar.addEventListener("pointermove", (ev) => {
    const f = fractionAt(ev);
    if (dragging) paint(f);
    tip.hidden = false;
    tip.style.left = f * 100 + "%";
    tip.textContent = Math.round(f * 100) + "%";
  });
  bar.addEventListener("pointerleave", () => { tip.hidden = true; });
  bar.addEventListener("pointerup", (ev) => { if (dragging) { dragging = false; view.goToFraction(fractionAt(ev)); } });
  bar.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowRight") { view.next(); ev.preventDefault(); }
    else if (ev.key === "ArrowLeft") { view.prev(); ev.preventDefault(); }
  });
  view.history && view.history.addEventListener("index-change", () => { backBtn.disabled = !view.history.canGoBack; });
  view.addEventListener("relocate", (e) => {
    const d = e.detail;
    if (!dragging) paint(d.fraction || 0);
    if (isFixed && d.section) root.querySelector("[data-reader-page]").textContent = "Page " + (d.section.current + 1) + " of " + d.section.total;
    lastPlace = { cfi: d.cfi || "", fraction: d.fraction || 0 };
    unsaved = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(savePlace, 700);
  });
  // Where the reader stopped is saved at once when the page is left, so coming back opens on the same page.
  function savePlace() {
    if (!unsaved || !lastPlace) return;
    unsaved = false;
    const body = new FormData();
    body.set("cfi", lastPlace.cfi);
    body.set("fraction", String(lastPlace.fraction));
    if (!(navigator.sendBeacon && navigator.sendBeacon(`/library/${uid}/reading-position`, body))) post("reading-position", lastPlace);
  }
  window.addEventListener("pagehide", savePlace);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") savePlace(); });
  function ticks() {
    const box = root.querySelector("[data-reader-ticks]");
    box.innerHTML = "";
    try {
      (view.getSectionFractions() || []).slice(1).forEach((f) => {
        const t = document.createElement("span");
        t.style.left = f * 100 + "%";
        box.appendChild(t);
      });
    } catch (e) { /* no sections to mark */ }
  }

  // ---- Bookmarks ----
  const bmList = document.querySelector("[data-reader-bookmarks]");
  const bmEmpty = document.querySelector("[data-reader-bookmarks-empty]");
  function renderBookmarks() {
    bmList.innerHTML = "";
    bookmarks.forEach((b) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = "#";
      a.className = "reader-quote";
      a.textContent = b.label || "Bookmark";
      a.addEventListener("click", (e) => { e.preventDefault(); view.goTo(b.cfi || b.section); });
      const pct = document.createElement("span");
      pct.className = "muted";
      pct.textContent = Math.round(b.fraction * 100) + "%";
      const del = document.createElement("button");
      del.type = "button";
      del.className = "icon-btn";
      del.title = "Remove";
      del.setAttribute("aria-label", "Remove bookmark");
      del.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-trash"></use></svg>';
      del.addEventListener("click", async () => {
        await post(`bookmarks/${b.uid}/delete`, {});
        bookmarks.splice(bookmarks.indexOf(b), 1);
        renderBookmarks();
      });
      li.append(a, pct, del);
      bmList.appendChild(li);
    });
    bmEmpty.hidden = bookmarks.length > 0;
  }
  root.querySelector("[data-reader-bookmark]").addEventListener("click", async () => {
    const loc = view.lastLocation || {};
    const label = (loc.tocItem && loc.tocItem.label ? loc.tocItem.label.trim() : "") || (isFixed && loc.section ? "Page " + (loc.section.current + 1) : "Bookmark");
    const data = { section: loc.section ? loc.section.current : 0, cfi: loc.cfi || "", label, fraction: loc.fraction || 0 };
    const resp = await post("bookmarks", data);
    const made = await resp.json().catch(() => ({}));
    bookmarks.push(Object.assign({ uid: made.uid }, data));
    bookmarks.sort((a, b) => a.fraction - b.fraction);
    renderBookmarks();
    if (window.ccToast) window.ccToast({ message: "Bookmarked: " + label, title: "Bookmark", icon: "bookmark" });
  });

  // ---- Define ----
  const defineBox = pop.querySelector("[data-reader-define]");
  async function define(text) {
    defineBox.hidden = false;
    defineBox.textContent = "Looking it up…";
    const lang = bookLanguage() || "en";
    try {
      const resp = await fetch(`/library/define?q=${encodeURIComponent(text.slice(0, 80))}&lang=${encodeURIComponent(lang)}`);
      const d = await resp.json();
      defineBox.textContent = "";
      if (!d.source) { defineBox.textContent = "Nothing found for “" + d.title + "”"; return; }
      const head = document.createElement("strong");
      head.textContent = d.title;
      defineBox.appendChild(head);
      if (d.summary) {
        const p = document.createElement("p");
        p.textContent = d.summary;
        defineBox.appendChild(p);
      }
      d.entries.forEach((en) => {
        const p = document.createElement("p");
        const pos = document.createElement("em");
        pos.textContent = en.pos ? en.pos + ": " : "";
        p.append(pos, document.createTextNode(en.defs.join("; ")));
        defineBox.appendChild(p);
      });
      const src = document.createElement("a");
      src.href = d.url || "#";
      src.target = "_blank";
      src.rel = "noopener noreferrer";
      src.textContent = d.source;
      defineBox.appendChild(src);
    } catch (e) {
      defineBox.textContent = "The lookup could not be made";
    }
  }

  // ---- Read aloud ----
  const speakBtn = root.querySelector("[data-reader-speak]");
  let speaking = false;
  let ttsMark = null;
  // Speech: the browser's own voices when it has any, else the server reads each sentence (espeak-ng) and the page plays it.
  let engine = null;
  // The server's audio plays through Web Audio: the context is started inside the click on the speaker button, which browsers
  // count as permission to play, so sentences fetched later (after awaits) still play. A plain <audio> element can be refused
  // by the autoplay rules at that point.
  let audioCtx = null;
  let currentSource = null;
  const keepUtterances = []; // Chrome drops the end event of an utterance nothing holds on to
  async function pickEngine() {
    // The server's voice (Piper, or espeak-ng) unless the reader settings ask for the browser's own voices.
    if (settings.voice !== "browser" || !("speechSynthesis" in window)) return "server";
    if (!window.speechSynthesis.getVoices().length) {
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 1500);
        window.speechSynthesis.addEventListener("voiceschanged", () => { clearTimeout(t); resolve(); }, { once: true });
      });
    }
    return window.speechSynthesis.getVoices().length ? "browser" : "server";
  }
  function stopSpeaking() {
    speaking = false;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (currentSource) { try { currentSource.stop(); } catch (e) { /* already stopped */ } currentSource = null; }
    if (ttsMark && !isPdf) view.deleteAnnotation({ value: ttsMark });
    ttsMark = null;
    if (speakBtn) { speakBtn.setAttribute("aria-pressed", "false"); speakBtn.classList.remove("is-on"); }
  }
  async function sayServer(text, lang) {
    // true when read, "server" when the server cannot read aloud, "play" when this browser would not play the sound
    let resp;
    try { resp = await fetch(voiceUrl(text, lang)); } catch (e) { return "server"; }
    if (!resp.ok) return "server";
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") await audioCtx.resume();
      const buffer = await audioCtx.decodeAudioData(await resp.arrayBuffer());
      if (!speaking) return true;
      return await new Promise((resolve) => {
        const src = audioCtx.createBufferSource();
        src.buffer = buffer;
        src.connect(audioCtx.destination);
        currentSource = src;
        src.onended = () => { if (currentSource === src) currentSource = null; resolve(true); };
        src.start();
      });
    } catch (e) {
      return "play";
    }
  }
  function sayBrowser(text, lang) {
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      if (lang) u.lang = lang;
      keepUtterances.push(u);
      if (keepUtterances.length > 20) keepUtterances.shift();
      u.onend = () => resolve(true);
      u.onerror = (e) => {
        if (e.error === "synthesis-failed" || e.error === "synthesis-unavailable" || e.error === "voice-unavailable") engine = "server";
        resolve(e.error === "interrupted" || e.error === "canceled");
      };
      window.speechSynthesis.speak(u);
    });
  }
  function voiceUrl(text, lang) {
    return `/library/tts?lang=${encodeURIComponent(lang || "en")}&text=${encodeURIComponent(text.slice(0, 1000))}`;
  }
  // The next sentence is asked for while this one plays, so the server's voice runs on without gaps.
  function prefetch(text, lang) {
    fetch(voiceUrl(text, lang)).catch(() => {});
  }
  async function say(text, lang) {
    if (!speaking || !text.trim()) return;
    if (!engine) engine = await pickEngine();
    if (engine === "browser") {
      if (await sayBrowser(text, lang) || !speaking) return;
      engine = "server";
    }
    const done = await sayServer(text, lang);
    if (done === true || !speaking) return;
    stopSpeaking();
    if (window.ccToast) window.ccToast({ variant: "error", message: done === "server"
      ? "The server cannot read aloud: install espeak-ng, or Piper with 'curodav-ctl install --voice'"
      : "This browser would not play the reading; check that the page is allowed to play sound" });
  }
  function chunks(text) {
    // Sentences, joined up to a few hundred characters, so a long page is read in pieces that can be stopped.
    const parts = text.replace(/\s+/g, " ").match(/[^.!?…]+[.!?…]*["'”’)]*\s*/g) || [];
    const out = [];
    let cur = "";
    parts.forEach((p) => {
      if ((cur + p).length > 300 && cur) { out.push(cur.trim()); cur = ""; }
      cur += p;
    });
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  function ssmlParts(ssml) {
    // The sentences of one block, each with the mark that locates it in the page.
    const doc = new DOMParser().parseFromString(ssml, "application/xml");
    const parts = [];
    let mark = null;
    let text = "";
    const flush = () => { if (text.trim()) parts.push({ mark, text: text.trim() }); text = ""; };
    const walk = (n) => {
      n.childNodes.forEach((c) => {
        if (c.nodeType === 3) text += c.nodeValue;
        else if (c.nodeType === 1 && c.localName === "mark") { flush(); mark = c.getAttribute("name"); }
        else if (c.nodeType === 1) walk(c);
      });
    };
    walk(doc.documentElement);
    flush();
    return parts;
  }
  function markRange(range) {
    // The sentence being read is underlined, and the page turns to it when it starts on the next page.
    const content = view.renderer.getContents()[0];
    if (!content) return;
    if (ttsMark) view.deleteAnnotation({ value: ttsMark });
    ttsMark = view.getCFI(content.index, range);
    view.addAnnotation({ value: ttsMark });
    view.renderer.scrollToAnchor(range, true);
  }
  async function readBook() {
    await view.initTTS("sentence", markRange);
    const here = view.lastLocation && view.lastLocation.range;
    let ssml = here ? view.tts.from(here) : view.tts.start();
    while (speaking) {
      if (!ssml) {
        await view.next();
        await new Promise((r) => setTimeout(r, 400));
        await view.initTTS("sentence", markRange);
        ssml = view.tts.start();
        if (!ssml) break;
      }
      const lang = bookLanguage() || "";
      const parts = ssmlParts(ssml);
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        if (!speaking) return;
        if (engine === "server" && parts[i + 1]) prefetch(parts[i + 1].text, lang);
        if (part.mark !== null) view.tts.setMark(part.mark);
        await say(part.text, lang);
      }
      ssml = view.tts.next();
    }
  }
  async function readPdf() {
    // A PDF has no flowing text: each page's text layer is read, then the next page opens.
    while (speaking) {
      const loc = view.lastLocation;
      const idx = loc && loc.section ? loc.section.current : 0;
      let doc = pdfDocs.get(idx);
      let tries = 0;
      while (speaking && (!doc || !doc.querySelector(".textLayer span")) && tries++ < 20) {
        await new Promise((r) => setTimeout(r, 250));
        doc = pdfDocs.get(idx);
      }
      if (!speaking) return;
      const text = doc && doc.querySelector(".textLayer") ? doc.querySelector(".textLayer").innerText : "";
      for (const part of chunks(text)) { if (!speaking) return; await say(part, bookLanguage() || ""); }
      if (!speaking) return;
      const before = idx;
      await view.next();
      await new Promise((r) => setTimeout(r, 900));
      const now = view.lastLocation && view.lastLocation.section ? view.lastLocation.section.current : before;
      if (now === before) break;
    }
  }
  if (speakBtn) speakBtn.addEventListener("click", async () => {
    if (speaking) { stopSpeaking(); return; }
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtx.resume();
    } catch (e) { /* no Web Audio: the browser's own voices are the only way */ }
    speaking = true;
    speakBtn.setAttribute("aria-pressed", "true");
    speakBtn.classList.add("is-on");
    try { await (isPdf ? readPdf() : readBook()); } catch (e) { console.error(e); }
    stopSpeaking();
  });
  window.addEventListener("pagehide", () => window.speechSynthesis && window.speechSynthesis.cancel());

  // ---- A PDF with no text: offer OCR ----
  const ocrBar = root.querySelector("[data-reader-ocr]");
  const seenPages = { empty: 0, text: 0 };
  function checkTextLayer(doc) {
    if (!isPdf || !ocrBar || seenPages.text) return;
    if (doc.querySelectorAll(".textLayer span").length) { seenPages.text++; ocrBar.hidden = true; return; }
    if (++seenPages.empty >= 2) {
      ocrBar.hidden = false;
      if (root.dataset.ocr !== "true") ocrBar.querySelector("button").hidden = true;
    }
  }
  if (ocrBar) ocrBar.querySelector("[data-reader-ocr-start]").addEventListener("click", async () => {
    const url = `/library/editions/${root.dataset.edition}/ocr`;
    const started = await (await fetch(url, { method: "POST", headers: { "X-Requested-With": "fetch" } })).json();
    if (!started.available) { if (window.ccToast) window.ccToast({ message: started.message, variant: "error" }); return; }
    ocrBar.hidden = true;
    const toast = window.ccToast ? window.ccToast({ title: "Making it searchable", message: "Reading the pages, this can take a while", icon: "scan-text", persistent: true, progress: null }) : null;
    const poll = async () => {
      const s = await (await fetch(url)).json();
      if (s.state === "running") return setTimeout(poll, 3000);
      if (toast) toast.set({ title: s.state === "done" ? "Searchable" : "Could not read it", message: s.message, variant: s.state === "done" ? "default" : "error", progress: false });
      if (s.state === "done") setTimeout(() => window.location.reload(), 1200);
    };
    setTimeout(poll, 3000);
  });


  // ---- Reading time, for the statistics: counted only while the page is shown and the reader has done something in the last minute ----
  let lastActive = Date.now();
  let pending = 0;
  const touch = () => { lastActive = Date.now(); };
  ["keydown", "pointerdown", "wheel", "touchstart"].forEach((n) => document.addEventListener(n, touch, { passive: true }));
  view.addEventListener("relocate", touch);
  view.addEventListener("load", (e) => { ["pointerdown", "keydown", "touchstart", "wheel"].forEach((n) => e.detail.doc.addEventListener(n, touch, { passive: true })); });
  function sendTime() {
    if (pending < 1) return;
    const body = new FormData();
    body.set("seconds", String(Math.round(pending)));
    pending = 0;
    if (!(navigator.sendBeacon && navigator.sendBeacon(`/library/${uid}/reading-time`, body))) fetch(`/library/${uid}/reading-time`, { method: "POST", body, keepalive: true });
  }
  setInterval(() => {
    if (document.visibilityState === "visible" && (speaking || Date.now() - lastActive < 60000)) pending += 5;
    if (pending >= 30) sendTime();
  }, 5000);
  window.addEventListener("pagehide", sendTime);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") sendTime(); });

  renderAnnotations();
  renderBookmarks();
  (async () => {
    try {
      const waiting = root.dataset.file.includes("/converted");
      if (waiting) fail("Preparing the book, the first time can take a minute…");
      const resp = await fetch(root.dataset.file);
      if (!resp.ok) {
        const info = await resp.json().catch(() => ({}));
        throw new Error(info.detail || "The book file could not be loaded");
      }
      root.querySelector("[data-reader-error]").hidden = true;
      const blob = await resp.blob();
      const file = new File([blob], root.dataset.fileName || "book.epub", { type: blob.type });
      if (isFixed) {
        // Two pages side by side with the first page alone and centred; the One page layout shows a page at a time.
        // Manga reads right to left unless the setting says otherwise.
        const book = await makeBook(file);
        const single = settings.layout === "single" || book.sections.length < 3;
        book.rendition = Object.assign({}, book.rendition, { spread: single ? "none" : "auto" });
        if (!single) book.sections[0].pageSpread = "center";
        if (isComic) {
          const rtl = settings.direction === "rtl" || (settings.direction === "auto" && root.dataset.manga === "true");
          book.dir = rtl ? "rtl" : "ltr";
        }
        await view.open(book);
      } else {
        await view.open(file);
      }
      applySettings();
      const toc = document.querySelector("[data-reader-toc]");
      if (view.book && view.book.toc && view.book.toc.length) renderToc(view.book.toc, toc);
      else toc.textContent = "No chapters in this book";
      await view.init({ lastLocation: position.cfi && !position.cfi.startsWith("section:") ? position.cfi : null });
      ticks();
      paint(position.fraction || 0);
    } catch (err) {
      console.error(err);
      fail("This book could not be opened in the reader. " + (err && err.message ? err.message : ""));
    }
  })();
}
