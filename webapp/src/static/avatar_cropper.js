// Visual crop/move/aspect-ratio tool for every image upload in this app
// (contact photos, the profile-picture row, and -- 2026-08-29, direct
// request "add the ability to crop, move, aspect ratio modal window after
// all image uploads" -- Home/label and the global Page header banner too).
// Originally contact-photo-only (2026-08-08 direct feedback: "uploading an
// image should allow for cropping and resizing it in a visual manner");
// generalized rather than forked into a second near-identical file, since
// the whole editor (drag-to-move, resize handles, ratio presets, rotation,
// canvas-based crop-and-scale-down output) is identical between an avatar
// and a banner -- only the *defaults* (starting ratio preset, output size
// cap, output filename) differ, and those are driven off which CSS class
// wired the input, not a second copy of this file.
//
// Intercepts the file input's own change event, shows a full-screen editor
// (free-form draggable/resizable crop box, Free/Square/4:3/16:9/Banner
// (5:1) aspect presets, 90-degree rotation), and on Apply replaces the
// input's file with the cropped/rotated/resized JPEG via DataTransfer --
// the form still posts a plain file input exactly as before (`name="photo"`
// for avatars, `name="banner_file"` for banners), no backend change needed
// either way (routers/settings.py's/contacts.py's/banners.py's upload
// routes never resized/cropped server-side to begin with -- they just
// store whatever bytes arrive). If that form carries `data-autosubmit`
// (settings_general.html's profile-picture row, which has no Save button
// of its own) OR the input is a banner upload (banner_editor.html's own
// upload form isn't marked data-autosubmit, but always auto-submitted on
// file selection even before this editor existed -- see the removed
// CCBannerUpload.onFile in app.js this replaces), Apply submits the form
// immediately.
//
// A self-contained overlay (own backdrop, own DOM, built at runtime), not
// a reuse of #modal-overlay/#modal-dialog (base.html) -- contact_form.html
// (and banner_editor.html) are themselves already rendered *inside* that
// modal system when opened from Contacts/a page's edit-mode toolbar, so
// this needs to layer on top of an already-open modal rather than replace
// it.
//
// Exposed as window.CCAvatarCropper.init(root), same re-init-after-inject
// convention as CCScheduleTable/CCScheduleGrid -- see modal.js's
// wireContent() comment (which already calls this for every injected
// modal, so banner_editor.html needed no wiring changes of its own beyond
// swapping which CSS class its file input carries). Cancelling or closing
// the editor clears the file input back to empty (no half-applied state).
(function () {
  const RATIOS = { free: null, square: 1, "4:3": 4 / 3, "16:9": 16 / 9, banner: 5 };
  const RATIO_LABELS = { free: "Free", square: "Square", "4:3": "4:3", "16:9": "16:9", banner: "Banner (5:1)" };
  const STAGE_MAX = 480; // px, the editor's on-screen canvas box

  // Per-`kind` defaults -- everything that varies between "cropping an
  // avatar" and "cropping a banner." `kind` is derived from which
  // selector matched the input (see KINDS below), never guessed from the
  // image itself, so behavior is deterministic per upload surface.
  const KIND_CONFIG = {
    avatar: {
      maxOutput: 640, // px, either dimension -- plenty for an avatar circle
      defaultRatio: "free", // unchanged from this file's original, avatar-only behavior
      outputName: "avatar.jpg",
      alwaysSubmit: false, // gated behind the form's own data-autosubmit, as before
    },
    banner: {
      maxOutput: 2400, // px, matches the old CCBannerUpload's own "long edge" cap
      defaultRatio: "banner", // 5:1, matching banner_editor.html's own guidance text
      outputName: "banner.jpg",
      alwaysSubmit: true, // banner_editor.html's upload form always auto-submitted on file selection, even before this editor existed
    },
  };
  // Selector -> kind, checked in order -- .avatar-upload-input keeps its
  // original meaning (contact photo, profile picture); .banner-upload-input
  // is the 2026-08-29 addition (banner_editor.html, both Home/label
  // banners and the global Page header banner -- all three share this one
  // template/route/CSS class already, see routers/banners.py's own
  // "one scope value, same route" design).
  const KINDS = [
    { selector: ".avatar-upload-input", kind: "avatar" },
    { selector: ".banner-upload-input", kind: "banner" },
  ];

  function init(root) {
    KINDS.forEach(({ selector, kind }) => {
      (root || document).querySelectorAll(selector).forEach((input) => {
        if (input.dataset.ccCropperWired) return;
        input.dataset.ccCropperWired = "1";
        input.addEventListener("change", () => {
          const file = input.files && input.files[0];
          if (!file) return;
          openEditor(file, input, kind);
        });
      });
    });
  }

  function openEditor(file, input, kind) {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => buildEditor(img, file.type, input, kind);
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  function buildEditor(img, mimeType, input, kind) {
    const config = KIND_CONFIG[kind] || KIND_CONFIG.avatar;
    const state = {
      rotation: 0, // 0 | 90 | 180 | 270
      ratio: RATIOS[config.defaultRatio], // null = free, else a number (w/h)
      // Box is in *display* (on-screen canvas) pixel space, top-left origin.
      box: { x: 0, y: 0, w: 0, h: 0 },
      naturalCanvas: document.createElement("canvas"), // full-res, current rotation
      scale: 1, // display px per natural px
    };

    // Ratio presets rendered in a fixed order regardless of kind (Free/
    // Square/4:3/16:9/Banner) -- same reasoning as offering Square/4:3/
    // 16:9 on an avatar crop already did before banners existed: extra
    // presets are harmless, and a single shared list is simpler than
    // branching the toolbar's own markup per kind. Only which one starts
    // `.active` (config.defaultRatio) actually varies.
    const ratioButtons = Object.keys(RATIOS)
      .map((key) => `<button type="button" class="seg-btn${key === config.defaultRatio ? " active" : ""}" data-ratio="${key}">${RATIO_LABELS[key]}</button>`)
      .join("");

    const overlay = document.createElement("div");
    overlay.className = "cropper-overlay";
    overlay.innerHTML = `
      <div class="cropper-panel">
        <div class="cropper-header">
          <h2>Adjust image</h2>
          <button type="button" class="icon-btn" data-cropper-close aria-label="Close">${useIcon("x")}</button>
        </div>
        <div class="cropper-stage">
          <canvas class="cropper-canvas"></canvas>
          <div class="cropper-box">
            <div class="cropper-box-handle" data-handle="n"></div>
            <div class="cropper-box-handle" data-handle="ne"></div>
            <div class="cropper-box-handle" data-handle="e"></div>
            <div class="cropper-box-handle" data-handle="se"></div>
            <div class="cropper-box-handle" data-handle="s"></div>
            <div class="cropper-box-handle" data-handle="sw"></div>
            <div class="cropper-box-handle" data-handle="w"></div>
            <div class="cropper-box-handle" data-handle="nw"></div>
          </div>
        </div>
        <div class="cropper-toolbar">
          <div class="segmented cropper-ratio-group">${ratioButtons}</div>
          <div class="cropper-rotate-group">
            <button type="button" class="icon-btn" data-rotate="-90" title="Rotate left" aria-label="Rotate left">&#8634;</button>
            <button type="button" class="icon-btn" data-rotate="90" title="Rotate right" aria-label="Rotate right">&#8635;</button>
          </div>
        </div>
        <div class="cropper-footer">
          <button type="button" class="btn ghost" data-cropper-cancel>Cancel</button>
          <button type="button" class="btn primary" data-cropper-apply>Apply</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    // rAF, not immediate -- lets the freshly-appended element get its
    // layout/paint before the opacity/transform transition (style.css)
    // runs, same "one frame of undropped '.is-open'" pattern modal.js uses.
    requestAnimationFrame(() => overlay.classList.add("is-open"));

    const canvas = overlay.querySelector(".cropper-canvas");
    const ctx = canvas.getContext("2d");
    const stage = overlay.querySelector(".cropper-stage");
    const boxEl = overlay.querySelector(".cropper-box");

    function renderRotatedSource() {
      const swap = state.rotation === 90 || state.rotation === 270;
      const nw = swap ? img.naturalHeight : img.naturalWidth;
      const nh = swap ? img.naturalWidth : img.naturalHeight;
      const nc = state.naturalCanvas;
      nc.width = nw;
      nc.height = nh;
      const nctx = nc.getContext("2d");
      nctx.save();
      nctx.translate(nw / 2, nh / 2);
      nctx.rotate((state.rotation * Math.PI) / 180);
      nctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
      nctx.restore();
    }

    function renderDisplay() {
      const nc = state.naturalCanvas;
      const fit = Math.min(STAGE_MAX / nc.width, STAGE_MAX / nc.height, 1);
      canvas.width = Math.round(nc.width * fit);
      canvas.height = Math.round(nc.height * fit);
      state.scale = canvas.width / nc.width;
      ctx.drawImage(nc, 0, 0, canvas.width, canvas.height);
      stage.style.width = canvas.width + "px";
      stage.style.height = canvas.height + "px";
    }

    function defaultBox() {
      const w = canvas.width;
      const h = canvas.height;
      let bw = w * 0.8;
      let bh = h * 0.8;
      if (state.ratio) {
        if (bw / bh > state.ratio) bw = bh * state.ratio;
        else bh = bw / state.ratio;
      }
      state.box = { x: (w - bw) / 2, y: (h - bh) / 2, w: bw, h: bh };
      paintBox();
    }

    function clampBox() {
      const b = state.box;
      b.w = Math.min(b.w, canvas.width);
      b.h = Math.min(b.h, canvas.height);
      b.x = Math.max(0, Math.min(b.x, canvas.width - b.w));
      b.y = Math.max(0, Math.min(b.y, canvas.height - b.h));
    }

    function paintBox() {
      clampBox();
      const b = state.box;
      boxEl.style.left = b.x + "px";
      boxEl.style.top = b.y + "px";
      boxEl.style.width = b.w + "px";
      boxEl.style.height = b.h + "px";
    }

    function rotate(delta) {
      state.rotation = ((state.rotation + delta) % 360 + 360) % 360;
      renderRotatedSource();
      renderDisplay();
      defaultBox(); // resetting the box on rotate is simpler and more
                     // predictable than trying to remap an arbitrary
                     // rectangle through a 90-degree axis swap
    }

    function setRatio(key) {
      overlay.querySelectorAll("[data-ratio]").forEach((b) => b.classList.toggle("active", b.dataset.ratio === key));
      state.ratio = RATIOS[key];
      if (state.ratio) {
        // Re-fit the current box to the new ratio around its own center
        // rather than resetting position -- keeps whatever the user was
        // already framing roughly in place.
        const b = state.box;
        const cx = b.x + b.w / 2;
        const cy = b.y + b.h / 2;
        let bw = b.w;
        let bh = bw / state.ratio;
        if (bh > canvas.height) {
          bh = canvas.height;
          bw = bh * state.ratio;
        }
        state.box = { x: cx - bw / 2, y: cy - bh / 2, w: bw, h: bh };
        paintBox();
      }
    }

    // --- Drag to move, drag handles to resize -----------------------------
    let drag = null; // { mode: 'move'|'nw'|'n'|..., startX, startY, startBox }

    function pointerDown(mode, e) {
      e.preventDefault();
      const p = pointFromEvent(e);
      drag = { mode, startX: p.x, startY: p.y, startBox: { ...state.box } };
      window.addEventListener("pointermove", pointerMove);
      window.addEventListener("pointerup", pointerUp);
    }

    function pointFromEvent(e) {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function pointerMove(e) {
      if (!drag) return;
      const p = pointFromEvent(e);
      const dx = p.x - drag.startX;
      const dy = p.y - drag.startY;
      const sb = drag.startBox;
      let b = { ...sb };

      if (drag.mode === "move") {
        b.x = sb.x + dx;
        b.y = sb.y + dy;
      } else {
        // Resize from whichever edge(s) the handle represents. Each edge
        // moves independently; a locked ratio recomputes height from the
        // new width after every edge adjustment (width is treated as the
        // driving dimension for simplicity/consistency across handles).
        if (drag.mode.includes("e")) b.w = sb.w + dx;
        if (drag.mode.includes("s")) b.h = sb.h + dy;
        if (drag.mode.includes("w")) {
          b.x = sb.x + dx;
          b.w = sb.w - dx;
        }
        if (drag.mode.includes("n")) {
          b.y = sb.y + dy;
          b.h = sb.h - dy;
        }
        if (b.w < 24) b.w = 24;
        if (b.h < 24) b.h = 24;
        if (state.ratio) {
          if (drag.mode === "n" || drag.mode === "s") {
            b.w = b.h * state.ratio;
          } else {
            b.h = b.w / state.ratio;
          }
          // Re-anchor the edge(s) that shouldn't have moved when the
          // opposite dimension got recomputed for the ratio lock.
          if (drag.mode.includes("w")) b.x = sb.x + sb.w - b.w;
          if (drag.mode.includes("n")) b.y = sb.y + sb.h - b.h;
        }
      }
      state.box = b;
      paintBox();
    }

    function pointerUp() {
      drag = null;
      window.removeEventListener("pointermove", pointerMove);
      window.removeEventListener("pointerup", pointerUp);
    }

    boxEl.addEventListener("pointerdown", (e) => {
      if (e.target.dataset.handle) return; // handled by its own listener below
      pointerDown("move", e);
    });
    overlay.querySelectorAll(".cropper-box-handle").forEach((h) => {
      h.addEventListener("pointerdown", (e) => pointerDown(h.dataset.handle, e));
    });

    // --- Toolbar -------------------------------------------------------
    overlay.querySelectorAll("[data-ratio]").forEach((b) => {
      b.addEventListener("click", () => setRatio(b.dataset.ratio));
    });
    overlay.querySelectorAll("[data-rotate]").forEach((b) => {
      b.addEventListener("click", () => rotate(parseInt(b.dataset.rotate, 10)));
    });

    function closeEditor(clearInput) {
      overlay.classList.remove("is-open");
      setTimeout(() => overlay.remove(), 160);
      if (clearInput) input.value = "";
    }
    overlay.querySelector("[data-cropper-close]").addEventListener("click", () => closeEditor(true));
    overlay.querySelector("[data-cropper-cancel]").addEventListener("click", () => closeEditor(true));
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeEditor(true);
    });

    overlay.querySelector("[data-cropper-apply]").addEventListener("click", () => {
      const b = state.box;
      // Map the display-space box back to the (rotated) natural-resolution
      // source so the output isn't limited to the on-screen stage size.
      const sx = b.x / state.scale;
      const sy = b.y / state.scale;
      const sw = b.w / state.scale;
      const sh = b.h / state.scale;

      const outScale = Math.min(1, config.maxOutput / sw, config.maxOutput / sh);
      const out = document.createElement("canvas");
      out.width = Math.max(1, Math.round(sw * outScale));
      out.height = Math.max(1, Math.round(sh * outScale));
      const octx = out.getContext("2d");
      octx.drawImage(state.naturalCanvas, sx, sy, sw, sh, 0, 0, out.width, out.height);

      out.toBlob(
        (blob) => {
          if (!blob) return;
          const croppedFile = new File([blob], config.outputName, { type: "image/jpeg" });
          const dt = new DataTransfer();
          dt.items.add(croppedFile);
          input.files = dt.files;
          updatePreview(input, out.toDataURL("image/jpeg", 0.9));
          closeEditor(false);
          const form = input.form;
          if (form && (config.alwaysSubmit || form.hasAttribute("data-autosubmit"))) form.requestSubmit();
        },
        "image/jpeg",
        0.88
      );
    });

    renderRotatedSource();
    renderDisplay();
    defaultBox();
  }

  function updatePreview(input, dataUrl) {
    const wrap = input.closest(".avatar-upload");
    if (!wrap) return;
    let img = wrap.querySelector("img.avatar-circle");
    if (!img) {
      const placeholder = wrap.querySelector(".avatar-circle");
      img = document.createElement("img");
      img.className = placeholder ? placeholder.className : "avatar-circle avatar-large";
      img.alt = "";
      if (placeholder) placeholder.replaceWith(img);
      else wrap.insertBefore(img, wrap.firstChild);
    }
    img.src = dataUrl;
  }

  // Minimal inline-SVG helper -- this overlay is built at runtime, not
  // server-rendered, so it can't call the Jinja `icon()` global. Reuses
  // the same sprite (templates/_icons_sprite.html, included once in
  // base.html) via <use>, exactly like every server-rendered icon does.
  function useIcon(name) {
    return `<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
  }

  window.CCAvatarCropper = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
