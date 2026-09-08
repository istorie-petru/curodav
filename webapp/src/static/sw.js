// 1.8 slice 3 -- PWA shell service worker (plans/open-priority.md §
// Offline-first editing & synchronization §11 slice 3). Served at the
// root path via routers/pwa.py::service_worker (not directly off
// /static/sw.js) so its default scope is the whole app, not just /static/.
//
// 2026-09-09: the client-side "Offline Mode" feature this shell originally
// existed to support (the /offline fallback page, its Quick Add builder,
// and the local IndexedDB mirror/write/sync scripts) was purged outright,
// direct request. This file now precaches the plain app shell (the CSS/JS/
// icons every page loads, per base.html) for faster repeat loads and
// serves no offline-specific fallback -- a navigation request that fails
// with no network now just fails, the same as it would with no service
// worker installed at all. See routers/pwa.py's own header comment for the
// full removal note. This whole mechanism has been inert since before that
// removal anyway (base.html's manifest `<link>` and pwa.js's registration
// call are both commented out, per the note further down this file), so
// nothing actually using this in a browser today changed behavior.
//
// Scope of this slice, deliberately: precache the app shell (the CSS/JS/
// icons every page loads, per base.html). No sync, no IndexedDB, no
// runtime caching of dynamic server-rendered pages (Tasks/Calendar/etc.
// still require a live request -- caching their HTML here would go stale
// the moment the underlying data changes, and there is no local data layer
// to keep it honest).
//
// CACHE_NAME is bumped whenever this file's own precache list changes --
// activate's cleanup below deletes any previous cc-shell-* cache, so an
// old shell version never lingers once a new one has installed. v9
// (2026-08-17): reworked offline_sync_client.js / offline_status.js
// (sync-status toasts now fire only on real sync work), so bumping forces
// an installed PWA to re-precache the fresh scripts instead of serving a
// cached copy that still announces "Syncing…"/"Synced" on dead-server
// page loads. v10 (2026-08-18): reworked offline_status.js again (the
// in-progress "Syncing…" toast is deferred by a grace period so a fast
// small sync never flashes it). v11 (2026-08-18): the static handler now
// falls back to caches.match(request, { ignoreSearch: true }) so the
// versioned ?v= URLs every page requests can be served from the precache's
// un-versioned entries (before that, /offline-only scripts failed to load
// on a device's first offline visit). v12 (2026-08-18): added
// /static/offline_quick_capture.js to the precache list (the offline
// "Quick add" toolbar's client-side capture parser), forcing a fresh shell
// install so /offline loads it. v15 (2026-08-29): root-cause fix for a
// whole session's worth of "I edited style.css but the browser still
// shows the old look" reports (habit check-in cell CSS, several rounds).
// This wasn't a CSS bug at all -- v14's precached `/static/style.css` had
// gone stale across every one of those edits, because NOTHING bumps
// CACHE_NAME when only static/style.css itself changes (every prior bump
// here was for a *script* rewrite). The fetch handler below tries an
// exact versioned-URL match first, but falls back to `caches.match(
// request, {ignoreSearch:true})` against the precache's un-versioned
// entry the moment that exact match misses -- which, for a file that's
// never been re-fetched under a brand new `?v=` in a runtime-cached
// visit, is every single request. So every reload kept serving the
// install-time (long before today) style.css regardless of what the
// server actually returned, confirmed by curling the live server
// directly (bypasses the SW) and seeing the fix already correct there.
// Bumping CACHE_NAME is the only thing that forces a fresh precache;
// going forward, treat static/style.css changes the same as a script
// rewrite for this purpose -- bump on every edit expected to be visible
// immediately, not just JS. v16 (2026-08-29): proof the v15 lesson was
// real, not theoretical -- the very next style.css edit (suppressing
// .inline-edit-cell's text-decoration while `[data-editing]`, see that
// rule's own comment) needed this same bump to actually reach a browser.
// v17 (2026-08-29): the habit heatmap's DETAIL_WEEKS widening fix left it
// scrollable with no visible scrollbar on several platforms -- added
// `.heatmap`'s scrollbar-width/::-webkit-scrollbar rules (style.css) plus a
// new static/heatmap_scroll.js (not shell-critical -- same category as
// inline_edit.js/async_crud.js above, so not added to SHELL_ASSETS) that
// defaults the scroll position to today's end. Bumped per the v15/v16
// lesson: any style.css change needs this regardless of whether a script
// also changed. v18 (2026-08-29): superseded v17's approach per direct
// feedback ("I just never want for a scrollbar to ever be needed there") --
// both detail heatmaps now use the existing `heatmap-wide` cell-stretching
// variant instead, so there's structurally nothing to scroll; reverted
// style.css's scrollbar-visibility rules and deleted static/
// heatmap_scroll.js entirely (it's gone from disk, was never in
// SHELL_ASSETS to begin with, so nothing to remove from this list). Bumped
// because style.css changed again.
// v19 (2026-08-29): direct report ("the resize event doesn't always
// trigger, even though it should") after that same day's static/
// sidebar_tree.js fix (dispatching a synthetic `resize` on sidebar
// toggle so the dashboard masonry re-layouts). The fix itself was correct
// -- this was the v15/v16 lesson again, just for a *script* this time
// instead of style.css: the fetch handler below tries an exact
// versioned-URL match first, but for any static asset that had ALREADY
// been runtime-cached under an OLDER `?v=` (deps.py's static_url() bumps
// the query string by mtime, but the SW never revisits an entry once
// cached), the ignoreSearch fallback matches that stale cached entry
// before ever reaching the network -- so a browser with an
// already-installed PWA kept serving the pre-fix sidebar_tree.js
// regardless of the new mtime, which is exactly "doesn't always trigger"
// (only devices with no prior SW-cached copy, or a fresh install, saw the
// fix immediately). Bumping CACHE_NAME deletes the entire previous
// cc-shell-* cache on activate (both its precached AND runtime-cached
// entries), so every static asset -- precached or not -- is forced back
// through a real network fetch at least once. Also added static/
// sidebar_tree.js to SHELL_ASSETS below: it's a base.html script loaded
// on every single page (same category as app.js/modal.js, already
// precached), not a page-specific one, so it belongs in the shell rather
// than relying solely on runtime caching to ever pick it up.
// v20 (2026-08-29): style.css changed again (sidebar-header/app-name rules
// for the expanded-sidebar wordmark) -- bumped per the standing v15 lesson
// (any style.css edit needs a bump to actually reach an already-installed
// PWA), independent of this being CSS rather than a script.
// v21 (2026-08-29): style.css changed again (unified collapsed/expanded
// .tabbar/.tab-btn/.sidebar-header padding so rail icons land at the same
// inset in both states) -- bumped per the same v15 lesson.
// v22 (2026-08-29): style.css changed again (new .page-header-narrow rules,
// sidebar redesign item 13e) -- bumped per the same v15 lesson.
// v23 (2026-08-29): style.css changed again (narrow-header banner/actions-
// slot rules, folding Tasks/Contacts/Calendar's old toolbar-2row into the
// header) -- bumped per the same v15 lesson.
// v24 (2026-08-29): style.css changed again (Dashboard Header (Expanded)
// avatar overlap -- .page-banner-avatar-wrap/.avatar-hero) -- bumped per
// the same v15 lesson.
// v25 (2026-08-29): static/avatar_cropper.js generalized to also handle
// banner uploads (crop/move/aspect-ratio for all image uploads, direct
// request) and static/app.js's now-dead CCBannerUpload removed -- both are
// SHELL_ASSETS scripts, bumped per the v19 lesson (script changes need
// this too, not just style.css).
// v26 (2026-08-29): static/avatar_cropper.js changed again (smaller avatar
// output cap, WebP-with-JPEG-fallback output for every upload kind, direct
// request "convert for smaller sizes... or compress them a bit") -- bumped
// per the same v19 lesson.
// v27 (2026-08-30): static/style.css-only change (collapsed rail's
// per-item height shrunk to match the expanded rail's, and collapsed rail
// items go icon-only, no text label) -- bumped per the same v19 lesson.
// v28 (2026-08-30): static/style.css-only change, same session (collapsed
// rail's icon left-aligned to match expanded's inset instead of centered,
// active-pill switched to a full-box highlight to match) -- bumped per
// the same v19 lesson.
// v29 (2026-08-30): static/style.css-only change, same session (collapsed
// rail narrowed 80px -> 64px, its icon nudged further from the left edge
// to cut the dead space to its right) -- bumped per the same v19 lesson.
// v30 (2026-08-30): static/style.css-only change, same session (collapsed
// rail narrowed again, 64px -> 56px, trimming more of the remaining
// right-side dead space) -- bumped per the same v19 lesson.
// v31 (2026-08-30): static/style.css-only change, same session (collapsed
// rail narrowed once more, 56px -> 52px, so the active-highlight box
// reads closer to 1:1 against its 36px min-height) -- bumped per the
// same v19 lesson.
// v32 (2026-08-30): static/style.css-only change, same session (expanded
// mode's own left/right padding mismatch: sidebar-section-label's 12px
// padding stacked on top of .tabbar's own, and .tab-separator's fixed
// 40px width fell back to flush-left instead of a matching inset under
// expanded's align-items:stretch) -- bumped per the same v19 lesson.
// v33 (2026-08-30): static/style.css-only change, same session (icons
// visibly jumped left/up when toggling collapsed<->expanded, and the
// active-highlight corners had different radii between the two -- .tab-
// btn's left padding and the header/toggle's sizing are unconditional
// now, and both states' highlight uses the same --radius-sm) -- bumped
// per the same v19 lesson.
// v43 (2026-08-30): style.css changed again (new `.kanban-status-select`
// rule + dropped `.kanban-card`'s `cursor:grab`, for the rebuilt Projects
// page's click-based Kanban board, plans/STATE.md backlog item 9) --
// bumped per the same v15 lesson. static/tasks_kanban.js itself is new
// but page-specific (project_detail.html only), not added to
// SHELL_ASSETS -- same "not shell-critical" category as tasks_table.js/
// tasks_board.js above.
// v44 (2026-08-30, immediate follow-up): live bug report -- the Projects
// page's upcoming-events card overlapped the Kanban board below it. Root
// cause: it was built with `.widget-card`, which is `position:absolute`
// (the Dashboard's own JS-positioned masonry grid sets its geometry) --
// with no such JS on this plain page it had no top/left/width at all.
// New `.widget-card-static` repeats only the flattened visual treatment,
// not the positioning; style.css changed, bumped per the same v15 lesson.
// v45 (2026-09-02): direct-feedback design pass -- labels now render as
// colored/iconed pills everywhere (new `.cell-tag.cal-*` usage via
// _label_pill.html, no new classes of their own) instead of the old flat
// `tag-blue`; Unscheduled-work pills (style.css's `.unscheduled-task-*`)
// shrunk and now wrap instead of scrolling; the Kanban board's per-card
// `.kanban-status-select` is gone along with static/tasks_kanban.js
// (removed from the page entirely, was never in SHELL_ASSETS). style.css
// changed, bumped per the same v15 lesson.
// v49 (2026-09-03): the shared date+time range picker's hour selection was
// reworked after a round of mockups (direct feedback: the old scrolling/
// click-drag 24-row hour grid was "too bulky," a follow-up grid/slider/
// preset/typed-field pass was all rejected too) -- static/
// datetime_picker.js (page-specific, not itself a SHELL_ASSETS entry, but
// runtime-cached like any other static file) and style.css both changed;
// bumped per the same v15/v19 lesson so an already-installed PWA doesn't
// keep serving the old click-drag grid from its runtime cache.
// v50 (2026-09-03, same day, two direct follow-ups on the cover-banner
// baseline from v48): (1) bug fix -- the cover's floating icon badge was
// getting clipped by .detail-cover's own overflow:hidden (needed to clip
// the image/gradient fill to the rounded top corners), so the badge's
// bottom overhang -- its whole point -- was invisible; fixed by moving it
// out to a sibling .detail-cover-wrap that isn't itself clipped. (2) Work
// sessions section (task_detail.html/habit_task_detail.html) dropped its
// elevated .detail-card background in favor of .detail-plain-section (a
// hairline, same treatment the meta grid already got), plus a small
// per-row polish pass (.work-session-row). style.css + three templates
// changed, bumped per the same v15 lesson.
// v51 (2026-09-03, same day, immediate follow-up): (1) real bug fix, not
// just polish -- v48's .modal-header rewrite (padding:0, for the cover to
// bleed) had stripped the *only* margin every plain *_form.html edit
// modal's bare <h1> relied on (event_form.html "Edit event" reported
// clipped flush against the dialog's edge) -- .modal-header's original
// padding/row layout is restored, and the cover-bleed behavior moved to a
// new .detail-header-inner wrapper (negative margins matching that
// padding) used only by the 4 detail-view templates, so the other 20+
// plain-title modals go back to their original, correct layout untouched.
// (2) Work sessions' separate "Scheduled work X.Xh / Y.Yh" sub-heading
// merged into the "Work sessions" heading itself (direct feedback:
// redundant, and it was rendering a second, unwanted divider on top of
// .detail-plain-section's own -- see _task_work_allocations.html's own
// comment). style.css + all 4 detail templates + _task_work_allocations.
// html changed, bumped per the same v15 lesson.
// v52 (2026-09-03, same day, immediate follow-up: "the two lines in the
// middle of this modal") -- .detail-plain-section's own border-top is
// gone. It was always redundant: in both real call sites, whatever comes
// right before it already draws that line itself (.detail-meta-panel's
// border-bottom when it isn't :last-child, or the habit heatmap's real
// .detail-card box edge) -- so Work sessions was showing two parallel
// hairlines a margin-top gap apart instead of one. style.css changed,
// bumped per the same v15 lesson.
// v53 (2026-09-04, mobile-nav redesign, plans/STATE.md) -- the old mobile
// bottom bar (all ~8 tabbar destinations crushed into one row, direct
// report against a real install screenshot) is replaced by a 3-button
// `.mobile-tabbar` (Sidebar/Home/Search) plus a bottom-sheet drawer that
// reuses `.tabbar` itself. style.css + templates/base.html changed, plus a
// new static/mobile_nav_drawer.js (added to SHELL_ASSETS below, same
// v19 reasoning as sidebar_tree.js -- a base.html script needed on every
// page for core navigation, not a page-specific one, so it belongs in the
// shell rather than relying solely on runtime caching). Bumped per the
// v15/v16/v19 lesson: any style.css or SHELL_ASSETS-script change needs
// this regardless of how small.
// v54 (2026-09-04, same day, direct follow-up -- "implement and fix the
// other problems described in this conversation," the two gaps flagged
// but not fixed by the earlier mobile touch-equivalents audit): 1)
// `.task-row-delete` gets an `@media (hover:none)` fallback (dimmed but
// visible) since it was hover-only-reveal with no way to discover it on a
// touch device; 2) `.icon-btn` grows to 40px under `@media
// (pointer:coarse)` (was 28px, under the ~44px touch-target guideline).
// style.css changed, bumped per the same v15 lesson.
// v55 (2026-09-07, audit-fixes-2.0.md slice 4, full-app-audit-2026-09-07.md
// finding #2) -- static/modal.js gained a keyboard focus trap (Tab/Shift+Tab
// cycling within an open .modal, alongside the existing Escape handler) --
// modal.js is in SHELL_ASSETS below, bumped per the v15/v16/v19 lesson.
// v56 (2026-09-07, audit-fixes-2.0.md slice 5) -- new static/
// a11y_icon_labels.js (added to SHELL_ASSETS below, same "base.html script
// needed on every page" category as mobile_nav_drawer.js right above it),
// sets aria-label from title on icon-only controls app-wide.
// v57 (2026-09-07, audit-fixes-2.0.md slice 6) -- style.css changed
// (coarse-pointer bumps for .color-swatch-current/.heatmap-cell/
// .stepper-btn, new .skip-link rule, darkened --fg-tertiary,
// .week-overview-grid breakpoint) and base.html changed (skip-to-content
// link + #main-content id). No new files added to SHELL_ASSETS.
//
// v58 (2026-09-07, audit-fixes-2.0.md item 9): style.css changed again
// (new .card-danger utility). New template
// src/templates/_bulk_actions_bar.html added -- not in SHELL_ASSETS
// (server-rendered template, not a static asset, same reasoning as every
// other templates-only change in this file's history).
// v58 -> v59 (2026-09-07, audit-fixes-2.0.md item 12): style.css changed
// again -- raw z-index numbers in the fixed/portal overlay and nav rules
// replaced with named custom properties (--z-rail/--z-modal/--z-overlay-
// panel/etc.), same numeric values throughout, no visual change intended.
// v59 -> v60 (2026-09-07, audit-fixes-2.0.md item 11 -- CSP `'unsafe-
// inline'` elimination): style.css changed extensively (nonce/CSP-driven
// template rewrites needed a long list of new utility classes/component
// rules, see that slice's own STATE.md entry). New static/
// dynamic_styles.js added to SHELL_ASSETS below -- same "base.html script
// needed on every page" category as a11y_icon_labels.js right above it
// (the generic `data-style` -> CSSOM applier every calendar grid/detail-
// cover/progress-bar now depends on). app.js/data_maintenance.js/
// habit_checkin.js also changed (onclick/onchange elimination, force-sync
// moved into data_maintenance.js, habit-checkin-reset's initial hide
// moved into habit_checkin.js) -- app.js is already in SHELL_ASSETS below
// so its own content is covered by this same bump; data_maintenance.js/
// habit_checkin.js are page-specific (not base.html-loaded), same
// "not itself a SHELL_ASSETS entry" category datetime_picker.js's own
// v14 note already established, so neither is added here.
// v61 (2026-09-07): style.css changed again (mobile follow-up to the
// desktop-only "Calendar fit the page" pass -- new main.main-calendar
// rules under the max-width:720px block) plus calendar_day/week/month/
// fourweek.html each gained the new `main-calendar` class on main_class.
// Templates aren't shell-precached (only static/* is), so only the
// style.css half needs this bump per the v15/v16 lesson above.
// v62 (2026-09-07, same-day follow-up): style.css changed again -- direct
// report that v61 wasn't visible turned out to be a width mismatch, not a
// caching bug (the report was at a >720px window, where v61's mobile-only
// rules never applied at all) -- while investigating, also dropped Month/
// 4-Week's 2026-08-08 shrink-to-fit row logic in the >=721px block per a
// direct follow-up request for the same "widget scrolls, page doesn't"
// treatment Week/Day already had. Bumped regardless of the width mix-up,
// since the desktop block's rules did materially change.
// v63 (2026-09-07, same-day follow-up again): style.css changed again --
// v62's overflow-y:auto only covers content taller than the box; it did
// nothing for Month/4-Week when content is shorter (the actual "dead
// space" case in the original report), so added flex:1 1 0 on
// .month-week-grid in both the desktop and mobile blocks so rows grow to
// fill leftover space, same as the pre-2026-08-08 intent minus the old
// shrink-below-floor squeeze. Also switched main.main-calendar's mobile
// height from 100vh to 100dvh (direct report: widget overflowing behind
// the bottom nav bar -- the classic mobile 100vh-measures-the-largest-
// possible-viewport bug) and dropped a second, redundant
// safe-area-inset-bottom subtraction (.mobile-tabbar's own inset is
// already baked inside its fixed 64px height, not added past it).
//
// NOTE for whoever reads this next: base.html's manifest <link> and
// pwa.js's registration call are both currently commented out ("PWA
// shell -- DISABLED"), so no service worker is actually registered
// right now and this whole CACHE_NAME mechanism is inert -- bumped
// anyway to keep the log accurate for whenever the shell is re-enabled,
// per the established convention in this file, but it is NOT why a
// browser might still be showing a stale layout today. A plain browser
// HTTP cache (or an un-restarted dev server) is the more likely culprit
// until pwa.js is back in base.html.
// v64 (2026-09-07, direct request + suggestion): style.css changed again
// -- dropped main-full-width's extra margin-right:var(--space-5) (direct
// request, it left an unused strip on the right of exactly the
// full-width pages that class exists for), and folded the desktop-only
// and mobile-only "Calendar fit the page" passes (v61-v63 above) into
// one breakpoint-independent main.main-calendar ruleset, per a direct
// suggestion to look at how real apps avoid the 100vh-scrollbar problem
// instead of tuning another magic-number estimate. Removed the
// `--calendar-chrome-h` custom property entirely -- the flex-shell
// approach (lock main's own height to the viewport, let flexbox
// distribute the rest between the header and the widget) needs no
// number to estimate. See style.css's own comment on that ruleset for
// the full reasoning and a sources list.
// v65 (2026-09-07, direct report): style.css changed again -- Planner's
// "Unscheduled work" panel and the time grid below it had a 32px gap
// instead of the intended 16px. .project-calendar-layout's own flex
// `gap:16px` was stacking with each child's plain .card margin-bottom
// (also 16px, and flex gap/margin never collapse into each other) --
// zeroed margin-bottom on .project-calendar-layout's direct .card
// children only, leaving .card's own margin-bottom untouched everywhere
// else it's used in normal document flow.
// v66 (2026-09-07, direct measurement: Tasks' header bar was 58px against
// 48px everywhere else): style.css changed again -- .filter-dropdown-
// trigger's height dropped 40px -> 32px so it fits the same budget every
// other header control (icon-btn, the h2 title) already respects. Latent
// on Calendar/Contacts too (their own filter dropdowns just happened to
// be empty/absent in the account this was measured against).
// v67 (2026-09-07, direct request): style.css changed again -- extended
// the main.main-calendar flex-shell model to a new generic main.main-
// shell modifier, applied to Tasks, Contacts, Notes, Labels manage, and
// Dashboard (the pages with a clear header+scrollable-body shape,
// confirmed scope for this pass -- Settings/Search/Published lists/
// Project & Label detail held for a follow-up). Each page's own template
// also gained a `.main-shell-body` class on whichever element is its
// scrollable region (#tasks-body, #contacts-body, #notes-body,
// #modal-target on Labels manage, a new wrapper div on Dashboard around
// #dashboard-grid) -- see style.css's own comment on main.main-shell for
// the full reasoning, including why Dashboard's masonry grid (which sets
// its own JS-computed style.height) composes safely with this.
// v68 (2026-09-07, direct measurement: v66's fix still measured 50px on
// pages with the filter button and 46px on plain pages, not 48 either
// way): style.css changed again -- .page-header-narrow was missing its
// own 1px border from the height budget math (48 padding-only target
// needed 50px of auto-height to actually fit a 32px control once the
// 2px border was added back in, and 46px to fit a 28px one) --
// .page-header-narrow now sets height:48px explicitly instead of
// relying on content to add up to it. .filter-dropdown-trigger dropped
// 32px -> 30px to fit the real content budget (48 - 16 padding - 2
// border), and calendar_month.html's Month|Day .segmented switch
// (page-header-narrow-actions .segmented/.seg-btn) got a matching
// compact override -- it was the one other actions-slot control tall
// enough to get clipped by the new fixed height's overflow:hidden.
// v69 (2026-09-07, direct report): style.css changed again -- Calendar/
// Planner's .calendar-viewport (Month/4-Week/Day) and .project-calendar-
// layout (Week) both carry the plain .card class, whose margin-bottom:
// var(--space-4) sat at the very bottom of main.main-calendar's fixed-
// height flex column -- since it's the last flex child, that margin ate
// into the shell's own visible height on top of main's own bottom
// padding, reading as double the normal bottom space. Zeroed
// margin-bottom on both, scoped to being main.main-calendar's own direct
// child (`.card`'s margin-bottom is untouched everywhere else it's used).
// v73 (2026-09-08, direct request -- Labels table "check up ... it looks
// different compared to the others"): style.css changed again --
// #labels-table's own scoped 6px/12px row-padding override is gone (now
// inherits the app-wide 10px/8px `tbody td` default every other settings
// table already uses), and Labels manage dropped main-shell/
// .main-shell-body (style.css's own comment on that rule) so it scrolls
// the whole page normally like Holidays/Time Blocks/Data & Maintenance
// instead of Tasks/Contacts' fixed-viewport internal-scroll shell.
// v74 (2026-09-08, direct report -- a holiday could be saved with no dates
// at all, surfacing a raw 422 JSON blob as the error toast): style.css
// (.dtp-trigger-invalid) and static/datetime_picker.js (the document-level
// required-field submit guard) and static/modal.js (friendlyErrorMessage)
// all changed.
// v75 (2026-09-09): static/data_maintenance.js changed -- the ?note=/
// ?error= banner on Data & Maintenance now converts to a ccToast on load
// (and strips the query params) instead of just sitting there as static
// page text.
// v76 (2026-09-09, same-day follow-up): "Reset database (purge all)" moved
// from a standalone modal dialog to a confirm toast with a typed-phrase
// gate -- static/toast.js (ccConfirmSheet's new typedConfirm option) and
// static/data_maintenance.js (the trigger + fetch) both changed;
// static/style.css lost the old .dm-danger-* rules and gained
// .toast-confirm-typed/.toast-typed-input.
// v77 (2026-09-09, same-day follow-up 2): purge confirm-toast copy
// shortened, and its two buttons now stretch edge-to-edge (equal width)
// to line up with the typed-phrase input above them instead of floating
// right as a variable-width pair -- static/data_maintenance.js,
// static/style.css.
// v78 (2026-09-09, same-day follow-up 3): purge confirm-toast button
// relabeled "Permanently Delete Everything" -> "Delete Everything" ->
// just "Delete" (ccConfirmSheet's own default) -- static/
// data_maintenance.js.
// v81 (2026-09-09, direct request: "let's just remove offline mode...
// purge it"): the client-side Offline Mode feature is gone -- /offline
// dropped from SHELL_ASSETS (the route no longer exists), the six
// offline_*.js entries dropped (the files no longer exist), and the
// navigate handler's fallback to a cached /offline copy removed (a failed
// navigation now just fails, same as with no service worker at all). See
// this file's own header comment and routers/pwa.py for the full note.
// Same pass: discovered the Sync card's "Force sync" button (Settings >
// Data & Maintenance, not itself an offline_* file) only worked by calling
// window.CCOfflineSync.syncNow() -- now permanently undefined -- so it was
// removed too (data_maintenance.js, settings_data_maintenance.html) rather
// than left as a button that can only ever show an error. style.css lost
// the dead .offline-* rules those deleted templates used.
// v83 (2026-09-08, FullCalendar-parity interactions slice 2): drag-move +
// edge-resize for Month/4-Week's spanning bars, plus the pointer-follow
// drag ghost -- calendar_month_drag.js (setupBar, postReschedule, the
// elementsFromPoint-based cellAtPoint shared with setupItem) and style.css
// (.month-bar-label/-resize-handle/-resize-left/-resize-right/-ghost,
// .month-bar.dragging's opacity) both changed.
// v84 (2026-09-08, same-day bug fix, direct report): bar resize was
// unreliable -- shrinking "most of the time doesn't work", growing
// "sometimes needs N+1 to do N". Root cause: `cellAtPoint`'s
// `elementsFromPoint`-based DOM hit-test depended on the browser's own
// stacking/pointer-events resolution at a pixel still geometrically
// covered by the original, un-resized bar (only its ghost clone actually
// changes size during a resize) -- not reliable enough in practice.
// Replaced with plain rectangle-containment against the known day cells'
// own `getBoundingClientRect()`s, no DOM stacking involved.
// v86 (2026-09-09, FullCalendar-parity interactions slice 4): Week view drag
// between the "All day" row and the timed grid, both directions.
// calendar.js's setupEvent() gained an .allday-col hover/drop branch (move
// mode only); calendar_week_allday_drag.js's setupItem() gained a .time-col
// hover/drop branch (events only, not task chips). Both still POST
// /events/{uid}/reschedule, which gained an optional `all_day` field
// (routers/calendar.py) to flip the flag on a cross-boundary move -- no new
// endpoint.
// v87 (2026-09-09, FullCalendar-parity interactions slice 5): Week view no
// longer resets scroll position on an async refresh. async_calendar.js's
// refreshWeek() now captures .time-grid-wrap's scrollTop before the
// #week-grid node swap (async_crud.js's refreshRegion does a wholesale
// replaceWith, which previously discarded the user's scroll position) and
// restores it on the fresh node afterward.
//
// v88 (2026-09-09): slice 6 of the same arc -- 4-Week/Week prev/next now
// navigate via AJAX (async_calendar.js's new bindCalNav) instead of a full
// page reload, with a live date-range label in the page header
// (style.css's new .cal-nav-label, the two grid templates' updated
// markup). style.css and async_calendar.js both changed; neither is in
// SHELL_ASSETS below, but style.css is, so the bump is required either way.
const CACHE_NAME = "cc-shell-v88";

const SHELL_ASSETS = [
  "/static/manifest.webmanifest",
  "/static/style.css",
  "/static/toast.js",
  "/static/app.js",
  "/static/sidebar_tree.js",
  "/static/mobile_nav_drawer.js",
  "/static/a11y_icon_labels.js",
  "/static/dynamic_styles.js",
  "/static/modal.js",
  "/static/tag_input.js",
  "/static/recurrence_picker.js",
  "/static/reminders_picker.js",
  "/static/stepper.js",
  "/static/dashboard_widget_preview.js",
  "/static/avatar_cropper.js",
  "/static/task_habit_field_toggle.js",
  "/static/event_format_toggle.js",
  "/static/command_palette.js",
  "/static/quick_add.js",
  "/static/pwa.js",
  "/static/favicon-16.png",
  "/static/favicon-32.png",
  "/static/apple-touch-icon.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      // Take over immediately on first install instead of waiting for
      // every open tab to close -- this app has no in-page "update
      // available, reload?" prompt (out of scope for this slice), so the
      // alternative is a stale worker sitting idle until the user
      // happens to close and reopen the tab themselves.
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("cc-shell-") && key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Only ever intervene for this app's own GETs -- cross-origin requests
  // (none today, but future-proofing) and non-GET writes (every task/
  // event/contact mutation in this app is a plain form POST, per
  // features/architecture.md) always go straight to the network
  // untouched.
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    // Network-first for real page loads: this app's pages are server-
    // rendered from live SQLite state (main.py's own comment on why
    // full-page HTTP caching is deliberately avoided), so a page that
    // *can* reach the network must never be served a stale cached copy.
    // 2026-09-09: this used to fall back to a cached copy of /offline on a
    // genuine network failure -- that page (and the whole client-side
    // Offline Mode feature) was purged, direct request, so a failed
    // navigation now just fails, the same as it would with no service
    // worker installed at all.
    event.respondWith(fetch(request));
    return;
  }

  if (new URL(request.url).pathname.startsWith("/static/")) {
    // Cache-first for static assets: every static URL this app renders
    // is already cache-busted with a `?v=<mtime>` query string
    // (deps.py's static_url()) whenever the underlying file changes, so
    // the plain un-versioned path cached here can never silently serve
    // stale content under a *new* version's URL -- a changed file simply
    // gets requested under a different URL than the one already cached.
    // Falls back to the network (and refreshes the cache entry) for
    // anything not in the precache list above.
    //
    // 2026-08-18 -- `ignoreSearch` fallback: pages request these assets
    // with the `?v=` suffix, and `caches.match` never matches that against
    // the precached un-versioned entry, so the precache only actually
    // served anything for assets the runtime path had ALSO cached under
    // their versioned URL during a controlled online visit. (Originally
    // motivated by /offline-only scripts that were never requested by a
    // normal page visit and so never runtime-cached -- those scripts and
    // that page are gone now, 2026-09-09, but the general staleness gap
    // this fallback closes is still real for any precached-but-not-yet-
    // runtime-cached asset, see v41 below.) The versioned-exact match is
    // tried first (a runtime-cached copy is the freshest thing the SW
    // knows); the ignoreSearch match against the un-versioned precache
    // entry is the fallback.
    //
    // v41 (2026-08-30): root-cause fix for the actual bug behind every one
    // of the v15-v33 "I edited a file, the browser still shows the old
    // version" reports -- this wasn't just a "forgot to bump CACHE_NAME"
    // problem, the fallback ORDER was wrong. The old code tried the exact
    // versioned match, and on a miss went straight to the ignoreSearch
    // precache/runtime-cache match -- BEFORE ever trying the network. Once
    // any old version of a file had been cached (either precached
    // unversioned at install, or runtime-cached under a previous `?v=`),
    // ignoreSearch always matched it by path, so a new `?v=` request was
    // served that stale entry directly and NEVER reached the network --
    // even while fully online. That's exactly the reported symptom: a hard
    // refresh works (it bypasses the SW entirely), but a normal navigation
    // to another page re-requests the asset through the SW and gets the
    // stale ignoreSearch hit again. Fixed by trying the network *before*
    // the ignoreSearch fallback: an exact cache hit is still served
    // instantly (fast path for a version already fetched), but any miss
    // now goes to the network first and only falls back to the stale
    // ignoreSearch precache entry if that fetch itself fails (genuinely
    // offline) -- which is what the ignoreSearch fallback was actually
    // meant for (see the 2026-08-18 note above).
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request)
            .then((response) => {
              const copy = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
              return response;
            })
            .catch(() => caches.match(request, { ignoreSearch: true }))
      )
    );
  }
  // Everything else (JSON APIs, non-precached GETs) is left alone --
  // default browser network handling, no caching.
});
