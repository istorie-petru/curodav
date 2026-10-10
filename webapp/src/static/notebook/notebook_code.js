// Code block with language-based syntax highlighting (2026-10-03, direct
// request) -- replaces @editorjs/code outright (vendor file removed, see
// vendor/NOTICE.md) since that tool is a plain textarea with no
// highlighting hooks at all. Backed by Prism.js (vendor/prism.js, MIT,
// core + a curated set of language components concatenated in their
// required dependency order -- see NOTICE.md for the exact list/order,
// required before any version bump).
//
// Technique: the classic "transparent textarea over a highlighted <pre>"
// overlay (what CodeMirror/react-simple-code-editor-style editors use
// for a real, editable, syntax-colored code box without reimplementing
// text editing) -- a real <textarea> sits on top with transparent text
// and a visible caret, so typing/selection/undo/paste all work exactly
// like a normal textarea; a <pre><code> immediately behind it, identical
// font metrics, shows Prism's colored token spans. The two are kept the
// same height by auto-growing the textarea to its scrollHeight on every
// input (avoids needing to sync independent internal scroll positions
// between the two layers).
(function () {
  var LANGUAGES = {
    plaintext: "Plain text",
    javascript: "JavaScript",
    typescript: "TypeScript",
    python: "Python",
    bash: "Bash / Shell",
    json: "JSON",
    yaml: "YAML",
    sql: "SQL",
    markup: "HTML / XML",
    css: "CSS",
    c: "C",
    cpp: "C++",
    csharp: "C#",
    java: "Java",
    go: "Go",
    rust: "Rust",
    php: "PHP",
    ruby: "Ruby",
    markdown: "Markdown",
  };

  function el(tag, cls, attrs) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) {
      for (var k in attrs) {
        if (attrs[k] != null) e.setAttribute(k, attrs[k]);
      }
    }
    return e;
  }

  function icon(name) {
    return (
      '<svg class="icon" aria-hidden="true"><use href="#icon-' +
      name +
      '"></use></svg>'
    );
  }

  function NotebookCode(params) {
    this.readOnly = params.readOnly;
    var d = params.data || {};
    this.data = {
      code: d.code || "",
      language: LANGUAGES[d.language] ? d.language : "plaintext",
    };
    this.wrapper = null;
    this.codeEl = null;
    this.textarea = null;
  }
  NotebookCode.toolbox = { title: "Code", icon: icon("code") };
  NotebookCode.prototype.highlight = function () {
    var code = this.textarea.value;
    if (this.data.language === "plaintext" || !window.Prism) {
      this.codeEl.textContent = code;
      return;
    }
    var grammar = window.Prism.languages[this.data.language];
    this.codeEl.innerHTML = grammar
      ? window.Prism.highlight(code, grammar, this.data.language)
      : code.replace(/[&<>]/g, function (c) {
          return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
        });
  };
  NotebookCode.prototype.autoGrow = function () {
    this.textarea.style.height = "auto";
    var h = Math.max(this.textarea.scrollHeight, 200) + "px";
    this.textarea.style.height = h;
    this.wrapper.style.height = h;
  };
  NotebookCode.prototype.render = function () {
    var self = this;
    var wrapper = el("div", "cdx-nb-code");
    var pre = el("pre", "cdx-nb-code__highlight");
    var codeEl = el("code", "cdx-nb-code__highlight-code language-" + this.data.language);
    pre.appendChild(codeEl);
    var textarea = el("textarea", "cdx-nb-code__textarea", {
      spellcheck: "false",
      autocapitalize: "off",
      autocomplete: "off",
      // A real `placeholder` attribute, not just data-placeholder --
      // needed purely so `:placeholder-shown` fires in CSS (see
      // notebook_code.css's own comment). The placeholder text itself is
      // never actually seen here, since the textarea's own text is
      // transparent -- "Enter code" is shown through the highlight layer
      // behind it instead (that CSS rule's own literal content string).
      placeholder: "Enter code",
    });
    textarea.value = this.data.code;
    textarea.readOnly = !!this.readOnly;
    wrapper.appendChild(pre);
    wrapper.appendChild(textarea);
    this.wrapper = wrapper;
    this.codeEl = codeEl;
    this.textarea = textarea;
    if (!this.readOnly) {
      textarea.addEventListener("input", function () {
        self.data.code = textarea.value;
        self.highlight();
        self.autoGrow();
      });
      // Tab inserts an actual tab character instead of moving focus out
      // of the code block -- a plain textarea's default Tab behavior is
      // unusable for writing code.
      textarea.addEventListener("keydown", function (e) {
        if (e.key !== "Tab") return;
        e.preventDefault();
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        textarea.value =
          textarea.value.slice(0, start) + "\t" + textarea.value.slice(end);
        textarea.selectionStart = textarea.selectionEnd = start + 1;
        self.data.code = textarea.value;
        self.highlight();
      });
    }
    this.highlight();
    // Deferred -- scrollHeight reads as 0 until the element has a real
    // layout box, which it doesn't have yet at this point in render().
    setTimeout(function () {
      self.autoGrow();
    }, 0);
    return wrapper;
  };
  NotebookCode.prototype.save = function () {
    return { code: this.textarea.value, language: this.data.language };
  };
  NotebookCode.prototype.renderSettings = function () {
    var self = this;
    return [
      {
        icon: icon("code"),
        title: "Language: " + LANGUAGES[this.data.language],
        children: {
          items: Object.keys(LANGUAGES).map(function (key) {
            return {
              title: LANGUAGES[key],
              isActive: self.data.language === key,
              closeOnActivate: true,
              onActivate: function () {
                self.data.language = key;
                self.codeEl.className = "cdx-nb-code__highlight-code language-" + key;
                self.highlight();
              },
            };
          }),
        },
      },
    ];
  };

  window.NotebookCode = NotebookCode;
})();
