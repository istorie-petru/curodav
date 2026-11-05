// Find details inside the entry window: a search on the kind's source, and a chosen result fills the window's fields
// (still editable) and remembers its cover for Save. Shown beside the work through the window's split pane.
(function () {
  var timer = null;

  function form() { return document.getElementById("citation-form"); }
  function field(name) { var f = form(); return f ? f.querySelector('[name="' + name + '"]') : null; }
  function kind() {
    var checked = document.querySelector('input[name="type"][form="citation-form"]:checked') || (form() && form().querySelector('input[name="type"]:checked'));
    return checked ? checked.value : "book";
  }

  function set(name, value) {
    var el = field(name);
    if (!el || value === undefined || value === null || value === "") return;
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fill(r) {
    ["title", "subtitle", "year", "container_title", "volume", "issue", "pages", "summary", "url", "doi"].forEach(function (k) { set(k, r[k]); });
    set("ed_publisher", r.publisher);
    set("ed_isbn", r.isbn);
    set("ed_year", r.year);
    var authors = r.authors || [];
    if (authors.length) {
      set("author_family", authors[0].family);
      var given = field("author_given");
      if (given) { given.value = authors[0].given || ""; given.dispatchEvent(new Event("input", { bubbles: true })); }
      var rows = document.getElementById("citation-author-rows");
      var add = form().querySelector('[data-repeatable-add="citation-author-rows"]');
      if (rows && add) {
        rows.innerHTML = "";
        authors.slice(1).forEach(function (a) {
          add.click();
          var inputs = rows.lastElementChild ? rows.lastElementChild.querySelectorAll("input") : [];
          if (inputs[0]) inputs[0].value = a.family || "";
          if (inputs[1]) inputs[1].value = a.given || "";
        });
      }
    }
    set("found_provider", r.provider);
    set("found_id", r.id);
    set("found_cover_url", r.cover_url);
    set("found_total", r.total ? String(r.total) : "");
    var preview = form().querySelector("[data-cover-preview]");
    if (preview && r.cover_url) preview.innerHTML = '<img src="/library/lookup/cover?u=' + encodeURIComponent(r.cover_url) + '" alt="">';
  }

  function render(box, data) {
    box.innerHTML = "";
    if (data.error || !data.results.length) {
      var note = document.createElement("p");
      note.className = "muted";
      note.textContent = data.error || (data.source === "No source" ? "No source for this type, fill it in by hand" : "Nothing found");
      box.appendChild(note);
      return;
    }
    data.results.forEach(function (r) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "media-lookup-row";
      var cover = document.createElement("span");
      cover.className = "media-lookup-cover";
      if (r.cover_url) { var img = document.createElement("img"); img.loading = "lazy"; img.alt = ""; img.src = "/library/lookup/cover?u=" + encodeURIComponent(r.cover_url); cover.appendChild(img); }
      var text = document.createElement("span");
      text.className = "media-lookup-text";
      var t = document.createElement("span");
      t.className = "media-lookup-title";
      t.textContent = r.title + (r.subtitle ? ": " + r.subtitle : "");
      var s = document.createElement("span");
      s.className = "media-lookup-sub";
      s.textContent = ((r.authors || []).map(function (a) { return a.family; }).join(", ") || r.publisher || r.container_title || "") + (r.year ? " · " + r.year : "");
      text.appendChild(t); text.appendChild(s);
      row.appendChild(cover); row.appendChild(text);
      row.addEventListener("click", function () {
        fill(r);
        box.querySelectorAll(".media-lookup-row").forEach(function (x) { x.classList.toggle("is-picked", x === row); });
      });
      box.appendChild(row);
    });
  }

  function search(input) {
    var box = input.closest("[data-find]").querySelector("[data-find-results]");
    var q = input.value.trim();
    if (!q) { box.innerHTML = ""; return; }
    box.innerHTML = '<p class="muted">Searching…</p>';
    fetch("/library/lookup/results?kind=" + encodeURIComponent(kind()) + "&q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (data) { render(box, data); })
      .catch(function () { box.innerHTML = '<p class="muted">The search could not be made. Try again in a moment.</p>'; });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.matches && e.target.matches("[data-find-q]")) {
      e.preventDefault();
      clearTimeout(timer);
      search(e.target);
    }
  });
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches("[data-find-q]")) {
      clearTimeout(timer);
      timer = setTimeout(function () { search(e.target); }, 500);
    }
  });
  // A new entry starts with the title typed in the window, so Find details opens already searching for it.
  document.addEventListener("cc-modal-content", function () {
    var q = document.querySelector("[data-find-q]");
    var title = field("title");
    if (q && title && title.value && !q.value) q.value = title.value;
  });
})();
