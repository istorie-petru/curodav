// Notebook undo (Phase I): the vendored editorjs-undo kept and extended.
// It records snapshots of the editor's saved blocks (typing is grouped by a
// short pause); this subclass changes how a snapshot is applied and where
// history lives:
//   - undo and redo update only the blocks that differ (restoring their
//     alignment tune too) and fall back to one full render when blocks were
//     added, removed or moved; scroll position is kept either way
//   - the first history entry is the document as loaded, so undoing
//     everything returns the original
//   - history is saved per document in localStorage so a reload keeps it,
//     with a step cap and a size cap
// Feature notes: curodav-notes/documentation/features/notebook-editor-undo.md.
(function () {
  var Base = window.Undo;
  if (!Base) return;

  var MAX_STEPS = 100;
  var MAX_BYTES = 1500000;
  var STORAGE_PREFIX = "commandCenterWeb.notebookUndo.";

  function fingerprint(block) {
    return JSON.stringify({ type: block.type, data: block.data, tunes: block.tunes || {} });
  }

  function sameDocument(a, b) {
    return a.length === b.length && a.every(function (block, i) {
      return fingerprint(block) === fingerprint(b[i]);
    });
  }

  function scrollParent(el) {
    for (var node = el; node && node !== document.body; node = node.parentElement) {
      var overflow = getComputedStyle(node).overflowY;
      if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight) return node;
    }
    return document.scrollingElement || document.documentElement;
  }

  function NotebookUndo(options) {
    this.uid = options.uid;
    this.mount = options.mount;
    this.persistTimer = null;
    var self = this;
    Base.call(this, {
      editor: options.editor,
      maxLength: MAX_STEPS,
      config: { debounceTimer: 400 },
      onUpdate: function () {
        self.schedulePersist();
        if (options.onUpdate) options.onUpdate();
      },
    });
  }
  NotebookUndo.prototype = Object.create(Base.prototype);
  NotebookUndo.prototype.constructor = NotebookUndo;

  // Makes the document as loaded the first history entry, then restores any
  // saved history that still ends at this exact content.
  NotebookUndo.prototype.start = function () {
    var self = this;
    return this.editor.save().then(function (data) {
      self.initialize(data.blocks);
      var saved = self.readSaved();
      if (saved && saved.stack[saved.position] && sameDocument(saved.stack[saved.position].state, data.blocks)) {
        self.stack = saved.stack;
        self.position = saved.position;
        self.initialItem = saved.stack[0];
        self.onUpdate();
      }
    });
  };

  // Records the current state as a step right now, ending any typing group.
  NotebookUndo.prototype.checkpoint = function () {
    var self = this;
    if (this.applying) return Promise.resolve();
    return this.editor.save().then(function (data) {
      if (self.editorDidUpdate(data.blocks)) self.save(data.blocks);
    });
  };

  NotebookUndo.prototype.undo = function () {
    if (!this.canUndo() || this.applying) return Promise.resolve();
    this.position -= 1;
    return this.applyEntry(this.stack[this.position]);
  };

  NotebookUndo.prototype.redo = function () {
    if (!this.canRedo() || this.applying) return Promise.resolve();
    this.position += 1;
    return this.applyEntry(this.stack[this.position]);
  };

  NotebookUndo.prototype.applyEntry = function (entry) {
    var self = this;
    var editor = this.editor;
    var scroller = scrollParent(this.mount);
    var top = scroller.scrollTop;
    this.applying = true;
    this.shouldSaveHistory = false;
    this.onUpdate();
    return editor.save().then(function (data) {
      var current = data.blocks;
      var target = entry.state;
      var sameIds = current.length === target.length && current.every(function (b, i) {
        return b.id === target[i].id;
      });
      if (!sameIds) return editor.blocks.render({ blocks: target });
      var chain = Promise.resolve();
      target.forEach(function (block, i) {
        if (fingerprint(block) !== fingerprint(current[i])) {
          chain = chain.then(function () {
            // update() merges into the block's current data, so keys the target lacks must be
            // cleared explicitly.
            var payload = Object.assign({}, block.data);
            Object.keys(current[i].data || {}).forEach(function (key) {
              if (!(key in payload)) payload[key] = undefined;
            });
            return editor.blocks.update(block.id, payload, block.tunes);
          });
        }
      });
      return chain;
    }).then(function () {
      var count = editor.blocks.getBlocksCount();
      if (count) editor.caret.setToBlock(Math.max(0, Math.min(entry.index, count - 1)), "end");
      scroller.scrollTop = top;
      // Let the mutation observer's own debounce pass before recording again.
      return new Promise(function (resolve) {
        setTimeout(function () {
          self.applying = false;
          self.shouldSaveHistory = true;
          resolve();
        }, 500);
      });
    });
  };

  NotebookUndo.prototype.readSaved = function () {
    try {
      var raw = localStorage.getItem(STORAGE_PREFIX + this.uid);
      var saved = raw && JSON.parse(raw);
      return saved && Array.isArray(saved.stack) && saved.stack.length ? saved : null;
    } catch (err) {
      return null;
    }
  };

  NotebookUndo.prototype.schedulePersist = function () {
    var self = this;
    clearTimeout(this.persistTimer);
    this.persistTimer = setTimeout(function () {
      self.persist();
    }, 600);
  };

  // Saves the history, dropping the oldest steps while it is over the size
  // cap (the first entry, the loaded document, always stays).
  NotebookUndo.prototype.persist = function () {
    if (!this.stack) return;
    var stack = this.stack.slice();
    var position = this.position;
    var json = JSON.stringify({ stack: stack, position: position });
    while (json.length > MAX_BYTES && stack.length > 2) {
      stack.splice(1, 1);
      position = Math.max(1, position - 1);
      json = JSON.stringify({ stack: stack, position: position });
    }
    try {
      localStorage.setItem(STORAGE_PREFIX + this.uid, json);
    } catch (err) {
      /* storage full or blocked: history just does not survive a reload */
    }
  };

  window.NotebookUndo = NotebookUndo;
})();
