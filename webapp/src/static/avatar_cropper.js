// Visual crop/resize/rotate tool for contact photo uploads
// (templates/contact_form.html's `.avatar-upload-input`), 2026-08-08 direct
// feedback ("uploading an image should allow for cropping and resizing it
// in a visual manner"). Intercepts the file input's own change event,
// shows a full-screen editor (free-form draggable/resizable crop box,
// Free/Square/4:3/16:9 aspect presets, 90-degree rotation), and on Apply
// replaces the input's file with the cropped/rotated/resized JPEG via
// DataTransfer -- the form still posts a plain `name="photo"` file exactly
// as before, no backend change needed. If that form carries
// `data-autosubmit` (settings_general.html's profile-picture row, which
// has no Save button of its own), Apply submits the form immediately.
//
// A self-contained overlay (own backdrop, own DOM, built at runtime), not
// a reuse of #modal-overlay/#modal-dialog (base.html) -- contact_form.html
// is itself already rendered *inside* that modal system when opened from
// Contacts, so this needs to layer on top of an already-open modal rather
// than replace it.
//
// Exposed as window.CCAvatarCropper.init(root), same re-init-after-inject
// convention as CCScheduleTable/CCScheduleGrid -- see modal.js's
// wireContent() comment. Cancelling or closing the editor clears the file
// input back to empty (no half-applied state).
(function () {
  const RATIOS = { free: null, square: 1, "4:3": 4 / 3, "16:9": 16 / 9 };
  const MAX_OUTPUT = 640; // px, either dimension -- plenty for an avatar circle
  const STAGE_MAX = 480; // px, the editor's on-screen canvas box

  function init(root) {
    (root || document).querySelectorAll(".avatar-upload-input").forEach((input) => {
      if (input.dataset.ccCropperWired) return;
      input.dataset.ccCropperWired = "1";
      input.addEventListener("change", () => {
        const file = input.files && input.files[0];
        if (!file) return;
        openEditor(file, input);
      });
    });
  }

  function openEditor(file, input) {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => buildEditor(img, file.type, input);
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  function buildEditor(img, mimeType, input) {
    const state = {
      rotation: 0, // 0 | 90 | 180 | 270
      ratio: null, // null = free, else a number (w/h)
      // Box is in *display* (on-screen canvas) pixel space, top-left origin.
      box: { x: 0, y: 0, w: 0, h: 0 },
      naturalCanvas: document.createElement("canvas"), // full-res, current rotation
      scale: 1, // display px per natural px
    };

    const overlay = document.createElement("div");
    overlay.className = "cropper-overlay";
    overlay.innerHTML = `
      <div class="cropper-panel">
        <div class="cropper-header">
          <h2>Adjust photo</h2>
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
          <div class="segmented cropper-ratio-group">
            <button type="button" class="seg-btn active" data-ratio="free">Free</button>
            <button type="button" class="seg-btn" data-ratio="square">Square</button>
            <button type="button" class="seg-btn" data-ratio="4:3">4:3</button>
            <button type="button" class="seg-btn" data-ratio="16:9">16:9</button>
          </div>
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

      const outScale = Math.min(1, MAX_OUTPUT / sw, MAX_OUTPUT / sh);
      const out = document.createElement("canvas");
      out.width = Math.max(1, Math.round(sw * outScale));
      out.height = Math.max(1, Math.round(sh * outScale));
      const octx = out.getContext("2d");
      octx.drawImage(state.naturalCanvas, sx, sy, sw, sh, 0, 0, out.width, out.height);

      out.toBlob(
        (blob) => {
          if (!blob) return;
          const croppedFile = new File([blob], "avatar.jpg", { type: "image/jpeg" });
          const dt = new DataTransfer();
          dt.items.add(croppedFile);
          input.files = dt.files;
          updatePreview(input, out.toDataURL("image/jpeg", 0.9));
          closeEditor(false);
          const form = input.form;
          if (form && form.hasAttribute("data-autosubmit")) form.requestSubmit();
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
