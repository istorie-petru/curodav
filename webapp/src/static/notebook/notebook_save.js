// Loads and saves a note's blocks with the revision they were read at. When the note was changed somewhere else (an
// AI edit, another tab) the server refuses the save; saving stops and a toast offers to reload the note.
(function () {
  var revision = "";
  var conflicted = false;

  function remember(resp) {
    var tag = resp.headers.get("ETag");
    if (tag) revision = tag;
  }

  function conflict() {
    conflicted = true;
    window.ccToast({
      title: "Not saved",
      message: "This note was changed somewhere else. Reload to see the latest version.",
      variant: "error",
      persistent: true,
      actions: [{ label: "Reload", onAction: function () { window.location.reload(); } }],
    });
  }

  window.NotebookSave = {
    load: function (url) {
      return fetch(url, { headers: { Accept: "application/json" } }).then(function (resp) {
        if (!resp.ok) throw new Error("load failed");
        remember(resp);
        return resp.json();
      });
    },
    put: function (url, body, keepalive) {
      if (conflicted) return Promise.resolve(null);
      var headers = { "Content-Type": "application/json" };
      if (revision) headers["If-Match"] = revision;
      return fetch(url, { method: "PUT", headers: headers, body: body, keepalive: !!keepalive }).then(function (resp) {
        if (resp.status === 409) {
          conflict();
          return null;
        }
        if (!resp.ok) throw new Error("save failed");
        remember(resp);
        return resp;
      });
    },
  };
})();
