// First-party Editor.js blocks (2026-10-03, direct request -- "the quote
// and warning ones look bad, rework") -- NOT vendored, written against
// the plain Tool API directly (constructor({data,api,config,readOnly}),
// render()/save()/renderSettings()), same convention the built-in
// Paragraph tool uses internally (editorjs.umd.js). Replaces
// @editorjs/quote and @editorjs/warning outright (those vendor files were
// removed, see NOTICE.md) rather than wrapping/subclassing their minified
// UMD exports, which would mean patching private closures in third-party
// code to reach the new look -- these two are simple enough to own
// directly instead.
//
// Both share this app's existing 5-color tag palette (style.css's
// --tag-{blue,green,yellow,purple,red}-{fg,bg}, the same tokens Labels/
// pills use) via a `data-color` attribute + matching CSS rules in
// notebook_blocks.css -- never an inline `style=""`, this app's CSP has
// no 'unsafe-inline' for style-src and a nonce never covers attributes
// (see deps.py's `avatar-colored`/`data-style` comment for the same rule
// already established elsewhere).
(function () {
  function icon(name) {
    return (
      '<svg class="icon" aria-hidden="true"><use href="#icon-' +
      name +
      '"></use></svg>'
    );
  }

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

  // ----------------------- Quote -----------------------
  // Simple colored left bar (blockquote-style) -- deliberately no icon,
  // no boxed background, just text + an optional caption, same shape the
  // vendored @editorjs/quote block had (text/caption) minus its
  // alignment setting and quote-mark icon, which were the parts of the
  // old look that prompted the rework.

  var COLORS = ["blue", "green", "yellow", "purple", "red"];

  function colorPicker(current, onPick) {
    var wrap = el("div", "cdx-nb-color-picker");
    COLORS.forEach(function (color) {
      var btn = el("div", "cdx-settings-button nb-color-swatch", {
        "data-color": color,
        title: color.charAt(0).toUpperCase() + color.slice(1),
      });
      if (color === current) btn.classList.add("nb-color-swatch--active");
      btn.addEventListener("click", function () {
        wrap.querySelectorAll(".nb-color-swatch").forEach(function (b) {
          b.classList.remove("nb-color-swatch--active");
        });
        btn.classList.add("nb-color-swatch--active");
        onPick(color);
      });
      wrap.appendChild(btn);
    });
    return wrap;
  }

  function NotebookQuote(params) {
    this.api = params.api;
    this.readOnly = params.readOnly;
    var d = params.data || {};
    this.data = {
      text: d.text || "",
      caption: d.caption || "",
      color: COLORS.indexOf(d.color) !== -1 ? d.color : "blue",
    };
    this.wrapper = null;
  }
  NotebookQuote.toolbox = { title: "Quote", icon: icon("quote") };
  NotebookQuote.sanitize = { text: { br: true }, caption: { br: true } };
  NotebookQuote.prototype.render = function () {
    var wrapper = el("blockquote", "cdx-nb-quote", {
      "data-color": this.data.color,
    });
    var text = el("div", "cdx-nb-quote__text", {
      contenteditable: !this.readOnly,
      "data-placeholder": "Enter a quote",
    });
    text.innerHTML = this.data.text;
    var caption = el("div", "cdx-nb-quote__caption", {
      contenteditable: !this.readOnly,
      "data-placeholder": "Author, source (optional)",
    });
    caption.innerHTML = this.data.caption;
    wrapper.appendChild(text);
    wrapper.appendChild(caption);
    this.wrapper = wrapper;
    return wrapper;
  };
  NotebookQuote.prototype.save = function () {
    return {
      text: this.wrapper.querySelector(".cdx-nb-quote__text").innerHTML,
      caption: this.wrapper.querySelector(".cdx-nb-quote__caption").innerHTML,
      color: this.data.color,
    };
  };
  NotebookQuote.prototype.renderSettings = function () {
    var self = this;
    return colorPicker(this.data.color, function (color) {
      self.data.color = color;
      self.wrapper.setAttribute("data-color", color);
    });
  };

  // ----------------------- Callout -----------------------
  // Icon + tinted box, replacing @editorjs/warning's plain title/message
  // fields. "Customizable" via a type picker (not a raw color picker) --
  // each type bundles a color with a matching icon (Notion/Obsidian-
  // style callouts), so picking a type sets both at once instead of
  // requiring two separate choices.

  var CALLOUT_TYPES = {
    note: { label: "Note", color: "blue", icon: "info" },
    tip: { label: "Tip", color: "green", icon: "check-circle" },
    warning: { label: "Warning", color: "yellow", icon: "alert-triangle" },
    danger: { label: "Danger", color: "red", icon: "alert-circle" },
    important: { label: "Important", color: "purple", icon: "star" },
  };

  function NotebookCallout(params) {
    this.api = params.api;
    this.readOnly = params.readOnly;
    var d = params.data || {};
    this.data = {
      type: CALLOUT_TYPES[d.type] ? d.type : "note",
      title: d.title || "",
      message: d.message || "",
      hideTitle: !!d.hideTitle,
    };
    this.wrapper = null;
    this.iconWrap = null;
    this.titleEl = null;
  }
  NotebookCallout.toolbox = { title: "Callout", icon: icon("megaphone") };
  NotebookCallout.sanitize = { title: { br: true }, message: { br: true } };
  NotebookCallout.prototype.render = function () {
    var meta = CALLOUT_TYPES[this.data.type];
    var wrapper = el("div", "cdx-nb-callout", { "data-color": meta.color });
    var iconWrap = el("div", "cdx-nb-callout__icon");
    iconWrap.innerHTML = icon(meta.icon);
    var body = el("div", "cdx-nb-callout__body");
    var title = el("div", "cdx-nb-callout__title", {
      contenteditable: !this.readOnly,
      "data-placeholder": "Title (optional)",
    });
    title.innerHTML = this.data.title;
    title.hidden = this.data.hideTitle;
    var message = el("div", "cdx-nb-callout__message", {
      contenteditable: !this.readOnly,
      "data-placeholder": "Callout text",
    });
    message.innerHTML = this.data.message;
    body.appendChild(title);
    body.appendChild(message);
    wrapper.appendChild(iconWrap);
    wrapper.appendChild(body);
    this.wrapper = wrapper;
    this.iconWrap = iconWrap;
    this.titleEl = title;
    return wrapper;
  };
  NotebookCallout.prototype.save = function () {
    return {
      type: this.data.type,
      title: this.wrapper.querySelector(".cdx-nb-callout__title").innerHTML,
      message: this.wrapper.querySelector(".cdx-nb-callout__message")
        .innerHTML,
      hideTitle: this.data.hideTitle,
    };
  };
  NotebookCallout.prototype.renderSettings = function () {
    var self = this;
    var wrap = el("div", "cdx-nb-type-picker");
    Object.keys(CALLOUT_TYPES).forEach(function (key) {
      var meta = CALLOUT_TYPES[key];
      var btn = el("div", "cdx-settings-button nb-type-swatch", {
        "data-color": meta.color,
        title: meta.label,
      });
      btn.innerHTML = icon(meta.icon);
      if (key === self.data.type) btn.classList.add("nb-type-swatch--active");
      btn.addEventListener("click", function () {
        self.data.type = key;
        wrap.querySelectorAll(".nb-type-swatch").forEach(function (b) {
          b.classList.remove("nb-type-swatch--active");
        });
        btn.classList.add("nb-type-swatch--active");
        self.wrapper.setAttribute("data-color", meta.color);
        self.iconWrap.innerHTML = icon(meta.icon);
      });
      wrap.appendChild(btn);
    });
    var separator = el("div", "cdx-nb-settings-separator");
    var titleToggle = el(
      "div",
      "cdx-settings-button nb-title-toggle",
      { title: "Hide title" }
    );
    titleToggle.innerHTML = icon("eye");
    titleToggle.classList.toggle("nb-title-toggle--active", this.data.hideTitle);
    titleToggle.addEventListener("click", function () {
      self.data.hideTitle = !self.data.hideTitle;
      self.titleEl.hidden = self.data.hideTitle;
      titleToggle.classList.toggle("nb-title-toggle--active", self.data.hideTitle);
    });
    var outer = el("div", "cdx-nb-callout-settings");
    outer.appendChild(wrap);
    outer.appendChild(separator);
    outer.appendChild(titleToggle);
    return outer;
  };

  // ----------------------- Delimiter -----------------------
  // Replaces @editorjs/delimiter (vendored file removed, see vendor/
  // NOTICE.md) -- that tool has no data/config/renderSettings hooks at
  // all (just a static "***" mark, confirmed in its source), so adding a
  // style choice meant owning it outright rather than wrapping it.

  var DELIMITER_STYLES = {
    stars: { label: "Stars (***)" },
    line: { label: "Line" },
    dots: { label: "Dots (• • •)" },
  };

  function NotebookDelimiter(params) {
    var d = params.data || {};
    this.data = {
      style: DELIMITER_STYLES[d.style] ? d.style : "stars",
    };
    this.wrapper = null;
  }
  NotebookDelimiter.toolbox = { title: "Delimiter", icon: icon("minus") };
  NotebookDelimiter.prototype.render = function () {
    var wrapper = el("div", "cdx-nb-delimiter", {
      "data-style": this.data.style,
    });
    this.wrapper = wrapper;
    return wrapper;
  };
  NotebookDelimiter.prototype.save = function () {
    return { style: this.data.style };
  };
  NotebookDelimiter.prototype.renderSettings = function () {
    var self = this;
    var ICONS = { stars: "star", line: "minus", dots: "more" };
    return Object.keys(DELIMITER_STYLES).map(function (key) {
      return {
        icon: icon(ICONS[key]),
        title: DELIMITER_STYLES[key].label,
        isActive: self.data.style === key,
        closeOnActivate: true,
        onActivate: function () {
          self.data.style = key;
          self.wrapper.setAttribute("data-style", key);
        },
      };
    });
  };

  window.NotebookQuote = NotebookQuote;
  window.NotebookCallout = NotebookCallout;
  window.NotebookDelimiter = NotebookDelimiter;
})();
