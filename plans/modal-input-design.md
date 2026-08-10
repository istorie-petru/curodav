# Design: 5 reusable data-entry patterns, replacing raw text/number inputs app-wide

**Status:** ✅ Done (2026-08-07). All 5 phases implemented and verified; full suite green at 593 passed (started at 538 before this design).
**Trigger:** Screenshot of the Customize Dashboard modal ("could you rework all the modal windows, especially this one to have a cleaner, better, modern, more modular, less text inputs overall... design 5 ways to add data and use those (no text input unless it's an original string)").

## 0. Ground rule

"Original string" = free-authored prose the user is composing themselves: task/event/contact/habit **title/name**, **description/notes**, **location**, **meeting URL**, **room**, **acronym**, checklist/subtask text. These stay plain `<input type="text">`/`<textarea>`, untouched by this rework.

Everything else audited (full inventory below) is a **bounded or structured value** currently misrepresented as free text, a number, or a plain `<select>` — this design gives each of those a home in one of 5 reusable patterns, reusing existing CSS/JS building blocks rather than inventing new ones (`.segmented`, `.pill-select`, `.multiselect`, and the dormant `.color-picker`/`.icon-picker` popovers all already exist in `style.css`/`modal.js` — see the audit below).

## 1. The 5 patterns

1. **Tile/card picker** — a row of large tappable cards (icon + label), one visibly selected. For the single most important "what kind of thing" choice in a form, where there are few enough options (2-4) that showing them all beats a dropdown you have to open to see. New CSS component (`.tile-select`/`.tile-option`), built as radio-styled buttons — no-JS-safe (real `<input type="radio">` under the hood, same trick `.pill-select` and `.field-toggle` already use).
   - Applies to: widget builder's **Data source** (Calendar & Tasks / Spaces & Projects / Habits / Contacts).

2. **Segmented control** (`.segmented`/`.seg-btn`, already exists — used today only for Table/Timeline/Board view switchers) — a single-row button group for small (2-5) mutually exclusive choices where every option should stay visible without opening anything.
   - Applies to: widget builder's **View** and **Range**, task **Priority**, schedule class **Day** (7 options — acceptable as a wrapping segmented row) and **Parity**.

3. **Swatch-grid popover** (`.color-picker`/`.icon-picker`, already fully built in CSS + `modal.js`'s `wireSwatchPickers`, portalled through `#color-popover`/`#icon-popover` in `base.html` — currently wired to **zero** templates, orphaned since the pre-rework calendars/projects pages that used it were deleted). Revive as-is, no new component needed.
   - Applies to: habit **color** + **icon**, label **color** + **icon** (`labels_manage.html` per-row edit, `label_detail.html`'s inline edit form) — replacing plain `<select>`s (color) and a free-text emoji field / plain-text icon-name `<select>` (icon) with an actual visual grid drawn from the same icon sprite used everywhere else.

4. **Chip multiselect** (`_widget_list_multiselect.html`'s checkbox-dropdown-with-summary pattern, already used for widget task-list/calendar filters — generalize into a shared partial usable outside the widget builder). Checkbox list in a popover, selected items shown as removable chips/pills on the trigger.
   - Applies to: every **Labels/tags** field currently a text input + `<datalist>` — task_form, event_form, contact_form, habit_form, widget builder/edit form, tasks_list.html's bulk-tag input. This is the single most-repeated offender in the whole audit (7 occurrences of the same text+datalist pattern for what is, in every case, picking from an already-known, already-finite label vocabulary).

5. **Stepper** — a number field flanked by −/+ buttons, native `<input type="number">` underneath (no-JS still works, min/step preserved). New small CSS+JS component (`.stepper`/`.stepper-btn`), generic over any bounded numeric field.
   - Applies to: widget builder's **Limit**, habit **Daily target**, schedule class **Credits**, schedule settings **Credits needed**, habit log-entry **value**.

Native `<select>` stays exactly as-is for anything with potentially many options (Project, task-list/calendar single-pickers, "merge into" targets) — a dropdown is still the right tool once cardinality goes much past ~6; these 5 patterns are for the specific cases the audit found misrepresented as text/number/opened-to-see dropdowns.

## 2. Full field-by-field mapping (from the audit)

| Template | Field | Today | Becomes |
|---|---|---|---|
| `_widget_builder_fields.html` / `_widget_edit_form.html` | Data source | `<select>` | Tile picker |
| same | View | `<select>` | Segmented (options filtered by source via existing `data-source` JS, unchanged) |
| same | Range | `<select>` | Segmented (shown/hidden by existing `data-has-range` JS, unchanged) |
| same | Limit | number input | Stepper |
| same | Labels (tags) | text + datalist | Chip multiselect |
| `task_form.html` | Priority | `<select>` | Segmented |
| `task_form.html` | Labels | text + datalist | Chip multiselect |
| `event_form.html` | Labels | text + datalist | Chip multiselect |
| `contact_form.html` | Labels | text + datalist | Chip multiselect |
| `habit_form.html` | Color | `<select>` | Swatch-grid popover |
| `habit_form.html` | Icon | free-text emoji input | Swatch-grid popover |
| `habit_form.html` | Daily target | number input | Stepper |
| `habit_form.html` | Labels | text + datalist | Chip multiselect |
| `habit_detail.html` | Log value | number input | Stepper |
| `labels_manage.html` | Color (per row) | `<select>` | Swatch-grid popover |
| `label_detail.html` | Color | `<select>` | Swatch-grid popover |
| `label_detail.html` | Icon | `<select>` (text names) | Swatch-grid popover |
| `schedule_class_form.html` | Credits | number input | Stepper |
| `schedule_class_form.html` | Day | `<select>` | Segmented |
| `schedule_class_form.html` | Parity | `<select>` | Segmented |
| `schedule_class_form.html` | Class type | free-text input | Segmented + "Other" text fallback (kept free-entry since new course types genuinely appear — see §3) |
| `schedule_settings.html` | Credits needed | number input | Stepper |
| `tasks_list.html` | Bulk-tag input | text + datalist | Chip multiselect |

Everything else in the earlier audit (title/description/name/notes/location/meeting URL/room/acronym/checklist text, all native date/time/datetime-local/email/file inputs, all already-good `<select>`s not listed above, existing `.field-toggle-group` checkbox groups) is unchanged.

## 3. One judgment call, flagged rather than silently decided

**Class type** (`schedule_class_form.html`) is presented as free text today ("Course, Seminar, Lab...") but is bounded *in practice* for most users — however unlike Color/Icon/Priority, its domain isn't fixed by this app, it's whatever course types a given school uses. Pure segmented-control would silently block a legitimate new value. Resolution: segmented control pre-populated with the values already seen across this user's existing classes (queried, not hardcoded) plus a "+ Other" option that reveals a small text fallback — same `:has()` progressive-disclosure trick already used for this form's professor-select/new-professor-name toggle, so no new JS pattern needed either.

## 4. Implementation phases

1. **Phase A — Customize/Add-widget modal** (explicitly called out in the request): tile picker for Data source, segmented for View/Range, stepper for Limit, chip multiselect for Labels. This is the flagship example the screenshot showed.
2. **Phase B — Chip multiselect everywhere**: generalize `_widget_list_multiselect.html` into a shared partial, apply to task/event/contact/habit Labels fields + tasks_list.html's bulk-tag input.
3. **Phase C — Swatch-grid revival**: wire the dormant color/icon pickers into habit_form, labels_manage, label_detail.
4. **Phase D — Steppers**: habit daily target, habit log value, schedule class credits, schedule settings credits needed (widget Limit already covered in Phase A).
5. **Phase E — Segmented controls elsewhere**: task priority, schedule class day/parity/class-type.

Each phase: implement, update/add tests per the standing house rule, run the full suite green, before starting the next phase.
