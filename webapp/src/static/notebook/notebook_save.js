// Loads and saves a note's blocks. A save always goes through: the server keeps what it replaces in the note's history,
// so there is no revision to hold and nothing to conflict. Saves run one after another so they arrive in order.
(function () {
  var reportUrl = null;
  var chain = Promise.resolve();

  function report(what) {
    if (!reportUrl) return;
    try {
      fetch(reportUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ what: what }), keepalive: true }).catch(function () {});
    } catch (e) {}
  }

  function putOnce(url, body, keepalive) {
    return fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: body, keepalive: !!keepalive }).then(
      function (resp) {
        if (!resp.ok) {
          report("save failed: " + resp.status);
          throw new Error("save failed");
        }
        return resp;
      },
      function (err) {
        report("save failed: network");
        throw err;
      }
    );
  }

  window.NotebookSave = {
    load: function (url) {
      reportUrl = url + "/report";
      return fetch(url, { headers: { Accept: "application/json" } }).then(
        function (resp) {
          if (!resp.ok) {
            report("load failed: " + resp.status);
            throw new Error("load failed");
          }
          return resp.json();
        },
        function (err) {
          report("load failed: network");
          throw err;
        }
      );
    },
    put: function (url, body, keepalive) {
      var run = chain.then(function () { return putOnce(url, body, keepalive); });
      chain = run.catch(function () {});
      return run;
    },
  };
})();
