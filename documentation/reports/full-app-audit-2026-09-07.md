# Full-app audit — 2026-09-07

Read-only audit, run as five parallel scoped passes (code quality/dead code,
security, UX/accessibility/mobile, performance, UI consistency) rather than
one full read-through, to keep it cheap. No code was changed. Two of the
higher-severity claims below (modal focus trap, `_attach_tags` N+1) were
independently spot-checked against the source and confirmed; the rest are
as reported by each pass — worth a quick look at the cited line before
acting, per this repo's own "verify before trusting a claim" convention.

This is a findings list, not a roadmap. Folding any of these into
`documentation/plans/open.md` / `open-priority.md` as an actual slice is
a separate decision — nothing here was added to those files.

## Priority findings (do these first if you do nothing else)

1. **N+1 queries on every list render — `db.py:1415` `_attach_tags`.**
   Every `list_events`/`list_tasks`/`list_contacts`/`list_notes` call
   fetches labels one row at a time via `list_labels_for_object` inside a
   per-row loop (call sites: db.py:1539, 1903, 1917, 1992, 2002, 2087,
   2378, 2395, 2542, 2601, 2656, 2707, 3074, 3384). Confirmed by reading
   the function directly. Contacts compound this further —
   `_attach_contact_phones_emails` (db.py:3038-3042) adds 5 more per-row
   queries (phones/emails/websites/addresses/social_profiles), so a
   contacts-list render costs the base query plus 6 extra queries per row.
   Hits the hottest pages in the app: dashboard, month/4-week calendar,
   tasks table, contacts list. Fix: batch-fetch `object_labels` (and the
   contact child tables) for the whole result set in one
   `WHERE object_id IN (...)` query, group in Python, or use a JOIN with
   `GROUP_CONCAT`.

2. **Modals have no keyboard focus trap — `static/modal.js`.** Confirmed:
   the only keydown handling in the file (line 557) is Escape-to-close;
   there is no Tab/Shift+Tab cycling to keep focus inside an open dialog.
   A keyboard user can Tab out of an open modal into the page behind it —
   a WCAG 2.1.2/2.4.3 violation and the one accessibility finding rated
   high rather than medium. Fix: add first/last-focusable-element cycling
   alongside the existing Escape handler.

3. **CSP allows `unsafe-inline` for script-src and style-src —
   `security_headers.py:52-62`.** Present but the main practical XSS
   mitigation (blocking inline `<script>`/inline handlers) is disabled.
   Already acknowledged as a tradeoff in the code's own docstring, so this
   is a "confirm it's still an acceptable tradeoff" item, not a surprise.
   Fix: migrate to nonce-based CSP incrementally.

4. **Local deploy mode is unauthenticated by default —
   `auth.py:143-146,384-389`.** By design ("no login unless
   `CC_DEPLOY_MODE=production` or an account already exists"), but a
   self-hoster who exposes the port without reading the docs gets an
   open app. Fix: log loudly at startup if bound to a non-loopback address
   with auth disabled.

## Code quality / dead code

Scope: `routers/*.py`, `db.py`, `deps.py`. Overall this slice of the
codebase was unusually clean — no bare `except:`, no TODO/FIXME/HACK
markers, and error handling was consistently deliberate (the two
`except Exception` blocks found in `published_lists.py:112,124` are
documented best-effort background paths, not sloppiness).

- `db.py:3444-3457` `find_contact_by_name` — fully dead, zero callers.
  Low severity; delete or wire into the auto-link feature it was written
  for but never connected to.
- `db.py:3428-3431` `list_task_label_names` — dead wrapper around
  `list_object_label_names(conn, "task")`; no caller uses it. Low
  severity, delete.
- `templates/_labels_body.html` — 71-line file, never imported or
  included anywhere; superseded by `_labels_table_body.html`, which is
  genuinely used. Medium severity (safe to delete, but confirm nothing
  references it by dynamic name first).
- `templates/_task_heatmap.html` — header comment claims it's used by
  `task_detail.html`, but there's no include and no "heatmap" string
  there at all. This could be a stale comment or a silently-dropped
  feature (a recurring-task heatmap that used to render and no longer
  does) — worth actually checking the live page before deleting the file,
  since the second case is a regression, not dead code.
- `templates/_widget_add_form.html` — referenced only in a comment,
  superseded by `_modal_widget_customize.html`. Low severity.
- `templates/_task_relations.html`, `_event_relations.html`,
  `label_edit_modal.html` — confirmed still present and still orphaned,
  matching what STATE.md already flagged in past sessions. Low severity,
  straightforward deletions once someone gets to it. (These three also
  still contain the retired `.relations-group`/`.detail-identity-dot`
  classes per the UI-consistency pass below — another reason to just
  delete the files rather than leave them as stale reference material.)

## Security

Scope: `auth.py`, `security_headers.py`, `config.py`, `deps.py`, `db.py`'s
query construction, `pyproject.toml`. Overall auth.py is well-built for
its stated single-user/trusted-network threat model — PBKDF2 at 260k
iterations, constant-time comparisons, fail-closed CSRF via Origin/Referer
checks, in-memory rate limiting, HttpOnly/SameSite=Lax cookies. No SQL
injection was found (all dynamic SQL in `db.py` builds table/column names
from fixed internal constants, never request input — checked 8 call
sites). No hardcoded secrets, no path traversal in image handling.

- Sessions are stateless HMAC cookies with **no server-side revocation**
  and a 30-day expiry (`auth.py:104-109`) — a stolen cookie or a password
  change doesn't invalidate tokens already issued. Medium severity. Fix:
  add a per-account session-epoch stamp, checked on read and bumped on
  password change.
- CSP `unsafe-inline` — see priority list above.
- Local deploy mode open by default — see priority list above.
- `config.py:69` — dev Radicale password (`"devpass"`) ships as a
  fallback when env vars are unset; only reachable if a real deploy
  forgets to set `CC_RADICALE_URL`/`CC_RADICALE_PASSWORD`. Low severity.
  Fix: fail startup in production mode if creds are still at the dev
  default.
- Login rate limiting is in-memory, per-process, keyed by IP only — resets
  on restart, no cross-process shared state. Low severity given the
  stated single-user threat model; worth documenting explicitly as an
  accepted tradeoff rather than an oversight.
- `pyproject.toml` dependencies are lower-bounded only (`fastapi>=0.115`,
  `uvicorn>=0.32`, `httpx>=0.27`, `caldav>=1.3`, etc.), no upper bound
  shown in the file itself. Low severity if a lockfile pins exact
  versions elsewhere (not checked) — worth confirming one exists.

## UX / accessibility / mobile

Scope: `templates/*.html`, `static/style.css`. The 2026-09-04 mobile-nav
redesign and its two touch-target fixes (`.task-row-delete`,
`.icon-btn`) were confirmed still in place and were not re-flagged.

- Focus trap missing in modals — see priority list above (rated high,
  the only high-severity item in this category).
- Icon-only buttons relying on `title` alone with no `aria-label`, spread
  across many files: row-delete buttons in `_task_row.html:144` /
  `_habit_row.html:115`; Edit/Delete links in `labels_manage.html:75`,
  `_labels_table_body.html:28`, `settings_holidays.html:61`,
  `settings_time_blocks.html:63,125`; and a longer tail across widget/
  picker/relation-row templates (`_widget_habit_checkin.html`,
  `_widget_items.html`, `_calendar_week_grid.html`,
  `_icon_swatch_picker.html`, `_color_swatch_picker.html`,
  `_task_work_allocations.html`, and the two dead relations templates
  above). Medium severity, repeated pattern — worth fixing once via a
  shared macro default (`aria-label` falling back to `title`) rather than
  patching each site by hand.
- `.color-swatch-current` (style.css:4085-4088, 20×20px) and
  `.heatmap-cell` (style.css:4398-4401, 11×11px) have no
  `@media(pointer:coarse)` size bump, unlike `.icon-btn`'s existing fix.
  Medium severity — the heatmap cells are a daily-use check-in control on
  mobile at an 11px tap target.
- `.stepper-btn` (style.css:2649-2654, 30px wide) has no coarse-pointer
  override, and every usage (`_task_form_fields.html:158/160`,
  `habit_form.html:74/76`, `_widget_builder_fields.html`,
  `_widget_edit_form.html`, `_habit_detail_body.html:53/55`) sets
  `tabindex="-1"`, removing it from the keyboard tab order with no
  documented alternative keyboard path. Medium severity — both a touch-
  target and a keyboard-access gap on the same control.
- No skip-to-content link anywhere in `templates/` — keyboard/
  screen-reader users tab through the full sidebar on every page load.
  Medium severity, one-line fix in `base.html`.
- `--fg-tertiary:#8e8e93` (light theme, style.css:51,183) used for 12px
  text in several places (`.week-overview-day-label`,
  `.heatmap-empty`) — contrast ≈3.3:1, below WCAG AA's 4.5:1 for normal
  text. Medium severity.
- `.week-overview-grid` (style.css:5033) uses a `700px` breakpoint while
  the rest of the app standardizes on 720/721px (~20 uses) — a 20px dead
  zone where this one widget's layout disagrees with its siblings. Low
  severity.

## Performance

Scope: `db.py`, `grid_layout.py`, `recurrence_expand.py`,
`derived_state.py`, `habit_heatmap.py`, `templates/base.html`, `static/`.
No missing-index issues found — every frequently-filtered column
(`events.start_at`, `tasks.status`/`due_at`, `object_labels` composite
keys, `habit_entries(habit_uid,date)`, etc.) already has one.

- N+1 on every list render — see priority list above (the one high-
  severity performance finding).
- `recurrence_expand.expand_events` is recomputed from scratch on every
  calendar/dashboard render (call sites in `routers/calendar.py:430,603,
  677,965` and `routers/dashboard.py:256,699`), with no caching layer
  anywhere in the codebase (`lru_cache`/memoization only exists in
  unrelated settings/auth code). Medium severity — fine at current data
  volumes, worth watching if recurring-event counts or the dashboard's
  2-year lookahead window grow.
- `grid_layout.layout_day`/`pack_overlaps` similarly recomputed per
  request with no caching. Low-medium severity — cheap algorithm, unlikely
  to be the actual bottleneck.
- `habit_heatmap.heatmap_weeks` recomputes up to 224 days per request on
  every habit-detail open. Low severity, bounded and small.
- `templates/base.html:503-604` loads 24 `<script>` tags with no `defer`/
  `async` on any of them. Medium severity, cheap fix — add `defer` to the
  scripts that don't need to run inline-immediately.
- `static/style.css` is 348KB (6027 lines), one monolithic file on every
  page load. Low severity for a single-tenant personal app — it's a
  one-time cached cost (already cache-busted via `sw.js` version bumps),
  not a per-request one.

## UI consistency (modals, dropdowns, cards, settings)

Scope: `templates/*.html`, focused on modal/dropdown/card patterns and
the settings pages. The shared `detail_cover()` macro is adopted
consistently across all four detail modals with no drift, and the
settings modal-edit forms (`holiday_edit_modal.html`,
`time_block_edit_modal.html`, `label_edit_modal.html`) share one
identical structure worth treating as the template for any future
settings sub-resource modal. `.icon-btn` is the sole icon-button class
app-wide, no competing variants.

- `settings_holidays.html` / `settings_time_blocks.html` don't match the
  `.settings-group` + `.section-label` heading pattern that
  `settings_general.html`, `settings_appearance.html`, and
  `settings_data_maintenance.html` all share — they use a bare `<h1>` and
  inline-styled sub-headings instead. Medium severity — visibly
  inconsistent heading style between settings pages users navigate
  between directly. Fix: wrap their sections in the same
  `.settings-group`/`.section-label` pattern the other three pages use.
- `settings_data_maintenance.html`'s `.status-card`/`.action-menu`
  three-dot dropdown is a one-off pattern not reused anywhere else in the
  app (every other row-actions UI uses `.multiselect` or plain
  `.icon-btn` rows). Low-medium severity — not wrong, just a second
  "action menu" implementation to maintain if a second consumer ever
  appears.
- Two dropdown/multiselect implementations coexist:
  `_widget_list_multiselect.html` (the actual engine, ~20 consumers) and
  `_filter_dropdown.html` (a thin class-renaming wrapper on top of the
  same engine). Low severity, not a real duplicate, but worth confirming
  both class names are still needed.
- `settings_data_maintenance.html`'s "Needs attention" card uses an
  inline `style="background:...;border:..."` override instead of a
  semantic modifier class — the only inline-border override found
  app-wide. Low severity; promote to a `.card-danger`/`.card-tinted`
  utility class if this tinted-card need comes up again.
- The bulk-actions bar markup (`.bulk-actions-bar`/`.bulk-count`) is
  copy-pasted verbatim across `settings_holidays.html`,
  `settings_time_blocks.html` (twice), and `labels_manage.html` rather
  than shared as one include. Low severity — each is a documented
  independent `CCBulkSelect` instance and works correctly, but three-plus
  copies is a drift risk if the bar's structure changes later.
- `_task_relations.html`/`_event_relations.html` (already flagged as dead
  code above) still contain the retired `.relations-group`,
  `.relations-group-head`, and `.detail-identity-dot` classes whose CSS
  was deliberately removed per STATE.md. No live effect since nothing
  includes these files, but another reason to just delete them. No other
  stray references to retired classes (`label_pill_quiet`,
  `.task-group-card`'s old background override) were found — those
  cleanups are complete everywhere else.

## Not covered / caveats

- No live browser rendering was done (no screenshot/computed-style
  checks) — contrast and touch-target findings above are from reading
  CSS values, not measuring rendered output.
- Dependency CVE exposure wasn't checked against a live vulnerability
  database (no internet access in the audit passes) — the pyproject.toml
  finding is about version-pinning hygiene, not a confirmed vulnerability.
- Each pass sampled and grepped rather than reading every file in its
  scope end-to-end (explicit instruction, to keep the audit affordable) —
  treat this as a strong first pass, not an exhaustive line-by-line
  review.
