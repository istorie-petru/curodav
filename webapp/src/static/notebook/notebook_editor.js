// Notebook Editor mode mount (curodav-notes/documentation/plans/
// architecture-notes-module-2026-09-29.md §3) -- initializes Editor.js on
// #notebook-editor, loads content_json via GET .../content, autosaves via
// PUT .../content (the one JSON-in/out exception documented in
// routers/notebook.py). No custom Curodav blocks yet (post-MVP) -- only
// Editor.js's own header/list/quote/code tools, same plain-global UMD
// pattern as every vendored script here (no bundler in this app).
(function () {
  var mount = document.getElementById("notebook-editor");
  if (!mount || !window.EditorJS) return;

  var status = document.getElementById("notebook-save-status");
  var contentUrl = mount.getAttribute("data-content-url");
  var saveTimer = null;

  function setStatus(state, text) {
    if (!status) return;
    status.setAttribute("data-state", state);
    status.textContent = text;
  }

  function save(editor) {
    editor
      .save()
      .then(function (data) {
        setStatus("saving", "Saving...");
        return fetch(contentUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
      })
      .then(function (resp) {
        if (!resp.ok) throw new Error("save failed");
        setStatus("saved", "Saved");
      })
      .catch(function () {
        setStatus("error", "Could not save");
      });
  }

  function scheduleSave(editor) {
    setStatus("pending", "Unsaved changes...");
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      save(editor);
    }, 1500);
  }

  fetch(contentUrl, { headers: { Accept: "application/json" } })
    .then(function (resp) {
      if (!resp.ok) throw new Error("load failed");
      return resp.json();
    })
    .catch(function () {
      return { blocks: [] };
    })
    .then(function (initialData) {
      var editor = new window.EditorJS({
        holder: mount,
        data: initialData,
        tools: {
          header: window.Header,
          list: { class: window.EditorjsList, inlineToolbar: true },
          quote: window.Quote,
          code: window.CodeTool,
        },
        onChange: function () {
          scheduleSave(editor);
        },
      });
      mount.addEventListener(
        "blur",
        function () {
          if (saveTimer) {
            clearTimeout(saveTimer);
            saveTimer = null;
            save(editor);
          }
        },
        true
      );
    });
})();
