# State

Single source of truth for "where are we right now." Read this file — and
only this file — at the start of a session working toward 2.0. Don't re-read
`roadmap.md` / `open-priority.md` / `open.md` in full; they're expanded specs
for reference, not session-start context. Update this file at the end of every
session, right before the final commit of that session.

Trimmed 2026-09-03: "Right now" had grown to ~4,400 lines of accumulated
session-by-session history instead of a current-position summary. Entries
older than the day of the trim were deleted outright (direct request, not
archived elsewhere) — full detail for anything cut is still recoverable via
`git log -p -- documentation/plans/STATE.md` (or `plans/STATE.md` in commits
before the docs move) if a past decision needs re-litigating. Keep "Right
now" short going forward: this file's whole value is being cheap to read at
session start.

## Right now

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 4, the modal keyboard
  focus trap (`documentation/reports/full-app-audit-2026-09-07.md` finding
  #2, the one accessibility finding rated high -- WCAG 2.1.2/2.4.3, a
  keyboard user could Tab straight out of an open modal into the page
  behind it). `static/modal.js` previously had only an Escape handler
  (line 557); added `trapTabKey`, wired into the same document-level
  `keydown` listener, alongside a new `getFocusableElements`/
  `FOCUSABLE_SELECTOR` helper. Queries `#modal-dialog` (the persistent
  wrapper element -- see `stabilizeHeight`'s own comment on why this is
  the stable element to query, not `#modal-body`, since content underneath
  it gets swapped by `refreshModalContent`/navigation) fresh on every
  Tab keypress rather than caching a focusable list at open time, so it
  stays correct across those swaps. Shift+Tab off the first focusable (or
  from outside the dialog entirely) wraps to last; Tab off the last (or
  from outside) wraps to first; a modal with zero focusable elements
  (rare, but not provably impossible) sends focus to the dialog itself
  instead of doing nothing -- needed `tabindex="-1"` added to
  `#modal-dialog` in `base.html` (JS-focusable fallback target, not in the
  natural tab order).

  `sw.js` CACHE_NAME bumped v54 -> v55 (`modal.js` is in `SHELL_ASSETS`),
  `test_pwa_shell.py`'s pin updated. No existing test exercises modal
  keyboard behavior (this suite has no JS-execution harness, per this
  file's own recurring note) -- grepped `tests/` for `focus.trap`/`Tab`/
  `modal.js` first, the only hits were `test_pwa_shell.py`'s precache-list
  assertion, already updated. Full suite: all 84 non-live test files
  green, run as one file-per-background-process batch inside a single
  bash call (16 cores available this session, so per-file parallelism
  finished well under the 45s per-call cap instead of needing pre-built
  chunk files -- `test_caldav_bridge_live.py` excluded as always).

  **Next slice** (per `audit-fixes-2.0.md`'s order): #5, icon-button
  accessible names -- an `aria-label` fallback keyed off each element's
  existing `title`, touching `_task_row.html:144`, `_habit_row.html:115`,
  `labels_manage.html:75`, `_labels_table_body.html:28`,
  `settings_holidays.html:61`, `settings_time_blocks.html:63,125`, and the
  widget/picker/relation-row templates the audit report lists. Mechanical,
  many touch points, low risk.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 3, the N+1 query fix
  flagged as the highest-impact single fix in the whole audit report
  (`documentation/reports/full-app-audit-2026-09-07.md` finding #1).
  `db.py:1415` `_attach_tags` and `db.py:3030` `_attach_contact_phones_
  emails` were each called once per row inside every `list_*`/`_search_*`
  function (14 call sites: `list_events`, `list_tasks_*` x3, `related_
  tasks_for_event`, `related_events_for_task`, `work_allocations_for_task`,
  `list_tasks_by_labels`, `list_events_by_labels`, `_search_tasks`,
  `_search_events`, `_search_contacts`, `_search_notes`, `list_contacts`,
  `list_notes`) -- each contact row alone cost the base query plus 6 extra
  per-row queries (tags + 5 child tables: phones/emails/websites/
  addresses/social_profiles).

  Fixed with two new batch helpers, `_attach_tags_bulk` and `_attach_
  contact_phones_emails_bulk` (both right next to their per-row
  originals), each running one `SELECT ... WHERE ... IN (...)` for the
  whole result set and grouping rows by uid in Python instead of querying
  per row. Every one of the 14 call sites above now decodes its rows into
  plain dicts first (`_row_to_dict`), batch-attaches tags (and phones/
  emails for contacts) once, then does whatever per-row shaping it used to
  do (search's `out.append({...})`, `list_contacts`'s photo-version
  backfill) over the already-tagged dicts. The single-row `get_event`/
  `get_task`/`get_contact`/`get_note`-style functions were deliberately
  left calling the original per-row `_attach_tags`/`_attach_contact_
  phones_emails` -- one row has no N+1 to fix, and a bulk query of size 1
  would just be the same query with extra ceremony.

  No schema change, no row-shape change (each dict still gets the same
  `tags`/`phones`/`emails`/etc. keys attached, just computed via a
  different query shape) -- existing tests cover this as-is, no test
  changes needed. Pure Python change, isolated to db.py, no template/CSS/
  JS touched -- no `sw.js` bump needed. Full suite: 1970 passed, run as 12
  parallel background chunks within one call (this sandbox's own /tmp-
  and background-process-don't-persist-between-bash-calls limitation, same
  as every other multi-chunk session this file documents -- build the file
  list, split, launch, and `wait` all inside one call), `test_caldav_
  bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #4, the modal
  keyboard focus trap (`static/modal.js` -- Tab/Shift+Tab cycling within
  an open `.modal`).

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 2, "silent-
  misconfiguration guards" (two independent fixes, `documentation/reports/
  full-app-audit-2026-09-07.md` findings #4 and the `config.py:69` Radicale
  one). Both diverged from the doc's original one-line sketch once actually
  implemented -- see `audit-fixes-2.0.md`'s own entry for the reasoning,
  summarized here:

  1. **Non-loopback exposure warning** (`src/auth.py`). The finding asked
     for a startup-time check, but the ASGI app is never told what host
     uvicorn bound to (systemd's `--host 0.0.0.0`, `main.py::main()`'s own
     hardcoded `0.0.0.0`, and a bare `uvicorn` CLI invocation all bypass
     any config this app owns) -- there is no "at startup" hook with that
     information. Landed as a request-time check instead:
     `AuthMiddleware._warn_if_exposed`, called from the existing `elif not
     self._configured(...)` branch (the exact "deploy_mode == local, no
     account configured, i.e. auth is genuinely off" branch, so no new DB
     read), reads the real local socket address off `scope["server"]` --
     for a listener bound to `0.0.0.0`, that's the actual interface a
     connection arrived on, not the literal string `"0.0.0.0"` -- and logs
     a `logger.warning` once per process the first time that address isn't
     loopback (`127.0.0.1`/`::1`/`localhost`, new `_is_loopback_host`
     helper), cached on `app.state._cc_exposure_warned` the same way
     `_configured` caches its own answer.
  2. **Radicale devpass fail-startup** (`src/config.py` +
     `src/main.py`). The finding's literal phrasing ("fail startup in
     production mode if creds are still at the dev default") would have
     broken every existing standalone production deploy that doesn't run
     Radicale at all -- the common case, since `scripts/curodav-ctl`'s env
     template ships `CC_RADICALE_*` commented out, which means the
     devuser/devpass fallback is what a perfectly correctly-configured
     no-Radicale production install already runs with today, silently and
     harmlessly (there's nothing real behind that URL, so the credentials
     never actually authenticate anywhere). An unconditional check would
     have failed all of those too -- directly contradicting this doc's own
     "no behavior change for a correctly-configured deploy" framing. Landed
     gated on the bridge actually connecting: `main.py`'s lifespan (the
     existing Radicale-optional `try`/`except`, which must never raise for
     an unreachable server) gained an `else` branch that runs only after
     `CalDavBridge(settings)` succeeds -- if `deploy_mode == "production"`
     and the now-live connection is still authenticated with the exact
     devuser/devpass pair (new `config.uses_default_radicale_credentials`,
     checked against the *effective* settings, i.e. after
     `apply_persisted_radicale_overrides`, so a /setup-entered password
     that happens to literally be "devpass" is still caught), it raises
     `RuntimeError` -- deliberately allowed to propagate and fail the whole
     lifespan startup, unlike the broad `except Exception` right above it.
     A standalone/no-Radicale production deploy (bridge stays `None`) never
     reaches this branch at all, so it boots exactly as before.

  New tests: `test_auth.py::TestIsLoopbackHost` (6 cases),
  `TestAuthMiddlewareExposureWarning` (4 cases -- loopback silent,
  non-loopback warns once via `caplog`, auth-enabled silent, forced-/setup
  production silent), `TestUsesDefaultRadicaleCredentials` (4 cases). The
  `main.py` lifespan wiring itself has no test harness in this suite (no
  `test_main.py` exists) -- verified instead with two ad hoc scripts (not
  added to the suite, same convention this file has used before for
  lifespan-adjacent checks): one confirms the `RuntimeError` actually fires
  end-to-end with a stubbed always-connects `CalDavBridge`, the other
  confirms an unreachable-Radicale stub still boots clean. Pure Python
  change (`auth.py`, `config.py`, `main.py`), no template/CSS/JS touched --
  no `sw.js` bump needed. Full suite: 1970 passed, run as 12 parallel
  chunks within one call (this sandbox doesn't persist `/tmp` or
  background processes *between* bash calls this session, unlike some
  prior sessions -- chunking + backgrounding + `wait` all had to happen
  inside one call), `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #3, the `_attach_tags`/
  `_attach_contact_phones_emails` N+1 query fix -- flagged as the
  highest-impact single fix in the whole audit.

- **Shipped:** 2026-09-07 -- a Cowork full-app audit (code quality, security,
  UX/accessibility/mobile, performance, UI consistency) ran this same day;
  findings are in `documentation/reports/full-app-audit-2026-09-07.md`, and
  the fix order before 2.0 is `documentation/plans/audit-fixes-2.0.md`
  (linked from `roadmap.md`'s 2.0 section). This entry is **slice 1 of
  that list**: session revocation.

  **Bug (well, gap) fixed:** sessions were stateless 30-day signed cookies
  with no revocation path at all -- changing the login password (Settings
  > General or first-run /setup) didn't invalidate any cookie already
  issued under the old password, so a stolen cookie (or the just-replaced
  password's own session) stayed valid for up to 30 more days regardless.
  Fixed by reusing the exact mechanism `routers/settings.py::purge_all`
  already had for this (drop the auto-generated session-signing secret,
  which lives in `app_meta`, so every cookie's HMAC stops verifying) and
  generalizing it to a second trigger: new `auth.rotate_session_secret`
  is now called from both `routers/auth.py::setup_submit` and
  `routers/settings.py::change_login_password`, right where each already
  mints its own fresh cookie for the current browser -- so the account
  owner's own session survives (re-signed under the new secret) while
  every other outstanding session, and a stolen cookie, immediately stops
  working. A no-op when `CC_AUTH_SECRET` is set (operator-fixed, not in
  `app_meta` -- see the function's own docstring for the equivalent
  operator action there). Both call sites also update
  `app.state._cc_auth_secret` in the same request (the in-process cache
  `AuthMiddleware` reads), matching what `purge_all` already had to do --
  without it, the very redirect the password-change response issues would
  have looked unauthenticated to itself.

  New tests: `test_auth.py::TestRotateSessionSecret` (4 cases: persists a
  new secret, an old token stops verifying against the rotated one, no-op
  when `CC_AUTH_SECRET` is fixed, repeated calls produce different
  secrets) plus `TestSetupSubmit::test_persists_a_session_secret_and_
  caches_it_on_app_state`; `test_settings_login_password.py` gained
  `test_rotates_session_secret_so_old_sessions_are_revoked` (end-to-end:
  a pre-change token fails against the post-change secret, the response's
  own new cookie succeeds, `app.state` agrees) and `test_env_fixed_secret_
  is_not_rotated`. Pure Python change (auth.py + the two router files),
  no template/CSS/JS touched -- no `sw.js` bump needed. Full suite: 1955
  passed, run as 12 chunks of ~7 files each (this sandbox's own
  background-process-per-bash-call limitation meant even smaller per-call
  chunks than usual were needed this session -- some individual test
  files, e.g. `test_offline_sync.py`, take ~20s alone here, apparently
  slow disk I/O in this particular sandbox rather than anything about the
  test itself), `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #2, the two
  silent-misconfiguration guards (unauthenticated local mode exposed
  publicly; the dev Radicale password fallback in production).

- **Shipped:** Direct follow-up, same day (2026-09-04), immediately after
  the mobile-nav redesign below -- "also implement and fix the other
  problems described in this conversation," the two touch-target gaps the
  earlier Cowork audit flagged but deliberately left unfixed (audit-only
  was the scope at the time):
  1. **`.task-row-delete` (Tasks/Habits table row delete button) had no
     touch fallback.** It's hover-reveal-only (`tr:hover`/
     `tr:focus-within`, opacity not display, so it stays a real focusable
     target) -- fine for keyboard/mouse, but a touch device has no
     reliable `:hover` state and there was no way to reach `:focus-within`
     either (tapping the row's title link navigates away instead of just
     focusing it), so the button was tappable but practically invisible on
     a phone. Added `@media (hover:none){ .task-row-delete{opacity:.55;} }`
     -- feature-detects the input mechanism rather than screen width (also
     covers a touch-primary tablet at a wide viewport), dimmed rather than
     full-opacity so it still reads as secondary the way hover-reveal
     signals on desktop.
  2. **`.icon-btn` (modal close, calendar nav arrows, etc.) was 28px,
     under the ~44px touch-target guideline** (Apple HIG / Material
     Design) -- fine for a mouse, tight for a finger. Added
     `@media (pointer:coarse){ .icon-btn{width:40px; height:40px;} }` --
     real box growth (not a padding-only/pseudo-element hit-area trick),
     scoped to the base rule only; more specific overrides further down
     (`.cropper-rotate-group .icon-btn`'s 32px compact toolbar, etc.) are
     untouched, each would need its own layout check before growing.
  `sw.js` CACHE_NAME bumped v53 -> v54 (style.css changed), `test_pwa_
  shell.py`'s pin updated. Neither class is referenced by any existing
  test (grepped `tests/` first). Full suite: 1948 passed across 5
  foreground chunks (same count as the mobile-nav slice right below --
  no tests added this round, just two CSS fixes),
  `test_caldav_bridge_live.py` excluded as always.

- **Shipped:** Direct request, 2026-09-04 -- mobile navigation redesign,
  reached via a Cowork mobile-touch/nav audit (no code changes -- Pointer
  Events/`touch-action:none` already covered every drag interaction, only
  gap found was `.task-row-delete`'s hover-only reveal, not fixed here)
  followed by a real install screenshot: the old `@media (max-width:720px)`
  treatment packed all ~8 rail destinations (Home/Calendar/Planner/Tasks/
  Contacts/Search/Settings/+New) into one crushed 64px row, exactly what
  the screenshot showed. Pushed back once on the user's own 3-item
  proposal (Calendar/Tasks dropping to two-tap access) before building --
  they confirmed the minimal version anyway, so this isn't a compromise,
  it's what was asked for after the tradeoff was surfaced.
  1. **New persistent `.mobile-tabbar`** (`templates/base.html`) -- exactly
     3 buttons fixed to the bottom edge: a Sidebar toggle
     (`#mobile-nav-toggle`), Home, Search. Desktop-hidden entirely (style.
     css scopes it to `max-width:720px`); `.tabbar` (the rail) renders
     normally above that width and this bar never displays.
  2. **`.tabbar` itself becomes a bottom-sheet drawer below 720px** --
     same rail markup desktop uses, not a trimmed copy (explicit decision:
     "mirrors the desktop expanded sidebar's content, not a subset"), so
     Spaces/Projects/tree-toggles -- hidden outright in the old mobile
     block -- are un-hidden and given the same row layout
     `html[data-sidebar-expanded]` uses on desktop (duplicated into the
     mobile media query since that ruleset itself is guarded to
     `@media (min-width:721px)` and never fires at phone widths). Hidden
     below the viewport by default (`transform:translateY(110%)`), toggled
     via `html[data-mobile-nav-open]` (new `static/mobile_nav_drawer.js`).
     Rows are 44px min-height (not desktop-expanded's 36px) for a real
     touch-target floor. `#mobile-nav-handle` gives it the same drag-to-
     dismiss grab handle `#modal-handle` (static/modal.js) already uses,
     same Pointer Events pattern, same ~90px dismiss threshold -- one
     visual/interaction convention for both bottom sheets in the app, not
     two. `#mobile-nav-scrim` darkens behind it, tap to close, stopping
     short of `.mobile-tabbar` (`bottom:64px`, not 0) so Home/Search/the
     toggle stay reachable while the drawer is open.
  3. Caught and fixed before commit: the "hide these three elements above
     the mobile breakpoint" default rule was accidentally placed *after*
     the `@media (max-width:720px)` block in style.css -- since both share
     equal specificity, source order (not media-query nesting) decides the
     winner when both apply, so it was clobbering the mobile-only
     `display:` overrides at every width including mobile ones. Moved
     before the block instead.
  `sw.js` CACHE_NAME bumped v52 -> v53 (new `static/mobile_nav_drawer.js`
  added to SHELL_ASSETS -- same "base.html script needed on every page"
  category as `sidebar_tree.js` -- plus style.css/base.html changed),
  `test_pwa_shell.py`'s pin updated. No existing test asserts the old
  mobile markup/CSS shape (this suite has no JS/CSS rendering harness, per
  this file's own recurring note) -- `test_sidebar_tree.py`/
  `test_nav_and_deactivation.py` (assert `.tabbar`'s inner markup, which
  is unchanged -- only wrapped differently at mobile widths) re-run clean.
  Full suite: 1948 passed across 5 foreground chunks (this sandbox's
  background-process-per-bash-call limitation, `test_caldav_bridge_live.py`
  excluded as always).

  **Not done, flagged not fixed:** an unrelated, large *pre-existing*
  staged-but-uncommitted change was found sitting in this repo's index at
  session start (`git status --short` before any edit here) -- a docs
  reorg (`plans/`/`features/`/root guide `.md` files moved under
  `documentation/`), deploy script removal, new `.github/workflows/`.
  Not this session's work, not touched or folded into this commit --
  committed only this slice's own files (`git commit -- <paths>`, a
  partial commit that leaves the rest of the index staged and alone).
  Whoever owns that restructuring still needs to commit or discard it
  separately.

- **Bug fix:** Direct report, 2026-09-04 -- "two events overlap in the week
  view, I move one via mouse but they still show half width... they should
  go to normal width when the event is moved and there is no overlap."
  Root cause: overlap layout (`left_pct`/`width_pct` lane widths) is
  computed entirely server-side by `grid_layout.layout_day` and baked into
  the rendered HTML once; `static/calendar.js`'s `.time-event` drag/resize
  handler (`setupEvent`'s `end()`) only ever moved `top`/`height` live and,
  on a successful save, patched just the `.te-time` label text -- it never
  triggered a re-layout of the column, so both the dragged event and
  whatever it used to overlap with stayed at their pre-drag width until an
  actual page load. Every *other* calendar drag path already goes through
  the app's async-CRUD convention (`window.ccApi.dispatchChange` ->
  `cc-entity-changed` -> `async_calendar.js`'s region refresh, which
  re-runs `layout_day`): month/day-cell drag (`calendar_month_drag.js`),
  all-day-row drag (`calendar_week_allday_drag.js`), work-allocation drag
  (`project_calendar.js`), modal edits (`modal.js`) -- `calendar.js`'s own
  handler was the one holdout patching DOM by hand instead. Fixed by
  making it follow the same convention: `end()`'s success handler now
  calls `dispatchChange({type:"event", action:"move", uid})` instead of
  patching `.te-time` (that patch, and the now-dead `minutesToDisplayTime`
  12h/24h helper it alone used, are removed -- the region refresh
  re-renders the label server-side instead).

  Patched a second hole found while fixing the first: Day view
  (`calendar_day.html`) had no async-CRUD region at all -- unlike Week's
  `#week-grid`, there was nothing for `dispatchChange` to refresh, so a
  Day-view drag would have kept going stale even after the `calendar.js`
  fix. Added the same region Week/Month/4-Week already have: split Day's
  grid markup into `_calendar_day_grid.html` (`id="day-grid"`), added a
  `_day_view_context` helper (`routers/calendar.py`, mirroring
  `_week_view_context`/`_four_week_view_context`) shared by the full page
  and a new `region == "day"` branch on `GET /calendar/regions`, and gave
  `async_calendar.js` a `refreshDay`/`dayEl` branch (re-binds via the same
  `CCWeekGrid.init()` Week uses -- Day never loads
  project_calendar.js/CCWeekAllDayDrag/CCUnscheduledPanel, so only that
  one re-bind applies). `calendar_day.html` now also loads
  `async_calendar.js`.

  Pure JS/Python/template change -- `calendar.js`/`async_calendar.js`
  aren't in `sw.js`'s `SHELL_ASSETS` precache list (page-specific scripts,
  not part of the global app shell), so no `sw.js` CACHE_NAME bump needed.
  Full suite: 1953 (1 pre-existing, unrelated failure --
  `test_dashboard_router.py::TestAgendaWidgetAllUpcoming::
  test_todays_earlier_events_still_count_as_upcoming` is UTC-now-vs-local-
  date sensitive and tripped over the calendar rolling from 09-03 to
  09-04 mid-session; not touched by this change, pre-existing per its own
  2026-09-03 changelog entry above).

- **Bug fix:** Direct report, same day (2026-09-03) -- "the data is not put
  in the today widget or the upcoming correctly." Real, reproduced bug in
  `routers/dashboard.py::_render_agenda`'s `next_30_days`/`all_upcoming`
  branch: it compared an event's full `start_at` timestamp against
  `datetime.now().isoformat()` (wall-clock precision), so any event whose
  clock time on *today's own date* was earlier than the moment the page
  rendered (midnight, or any earlier hour) got silently dropped from
  "Upcoming" -- exactly the screenshot's symptom, three real events on
  today's date, all missing, jumping straight to +3/+7-day events instead.
  Fixed to a pure date-level comparison (`start_at[:10] >= today_iso`),
  matching the convention every other boundary in this same function
  already uses (the Tasks branch two lines up, the `range == "today"`
  branch's own `[:10] == today_iso`) and matching routers/calendar.py's
  month/week/day views, which only ever reason in whole days. New
  regression test (`test_dashboard_router.py::TestAgendaWidgetAllUpcoming
  ::test_todays_earlier_events_still_count_as_upcoming`) seeds an event
  earlier today, one an hour from now, and one yesterday -- only yesterday
  should drop. Pure Python fix, no template/CSS/JS touched -- no `sw.js`
  bump needed. Full suite: 1953 passed.

  Separate follow-up, same day, immediately after: confirmed via
  AskUserQuestion that the "Today" pane's "Nothing to show" was exactly
  the flagged design gap above (the user had already hand-fixed their own
  copy of the widget) -- direct request to change the *default* for
  future first-time seeds: "modify the default to not be overdue only,
  but be overdue, tasks and events." `_DEFAULT_STACK_MEMBER_TYPES`'s third
  member's `show` widened from `["overdue"]` to `["overdue", "tasks",
  "events"]` -- every Show section `range="today"` actually supports, so
  a fresh "Today" pane shows what its name implies. Scoped to the one-time
  seed only (`_ensure_default_widgets`/`_ensure_default_label_widgets`'s
  own app_meta flag) -- doesn't touch anyone who already has widgets,
  seeded or hand-built. 5 assertions across `test_dashboard_router.py`
  and `test_dashboard_usability_rework.py` updated for the new default
  Show list. Pure Python change, no `sw.js` bump needed. Full suite:
  1953 passed.

- **Shipped:** Direct follow-up, same day (2026-09-03), immediately on top
  of the header-clipping-fix + Work-sessions-header-merge entry right
  below ("the two lines in the middle of this modal"): the merge fixed the
  divider *between* "Work sessions" and "Scheduled work" (by deleting the
  second heading entirely), but `.detail-plain-section`'s own border-top
  was still redundant with whatever came right before it -- `.detail-meta-
  panel`'s own border-bottom (active whenever it's not `:last-child`,
  which is exactly when Work sessions follows it) or the habit heatmap's
  real `.detail-card` box edge/shadow. Two hairlines a `margin-top` gap
  apart where one already existed. Fix: `.detail-plain-section`'s
  border-top removed outright, `margin-top` alone provides the spacing --
  confirmed by rendering the real template output directly (a short ad
  hoc script, not a screenshot guess) before and after. `sw.js`
  CACHE_NAME bumped v51 -> v52, `test_pwa_shell.py`'s pin updated. Full
  suite: 1952 passed.

- **Shipped:** Direct follow-up, same day (2026-09-03), immediately on top
  of the badge-clipping-fix + Work-sessions-rework entry right below:
  1. **Real regression fix** ("edit the header so that it doesn't clip
     (margins)"), caught from a screenshot of the *edit* event modal, not
     a detail-view modal -- the v48 `.modal-header` rewrite (`padding:0`,
     so the cover banner could bleed edge-to-edge) had stripped the
     *only* margin every plain `*_form.html` edit modal's bare `<h1>`
     relied on (event/task/contact/habit/label/note/... -- 20+ templates,
     confirmed by grepping every `.modal-header` consumer, not assumed).
     `.modal-header`'s original padding + row layout is restored exactly;
     the cover-bleed behavior moved to a new `.detail-header-inner`
     wrapper (negative margins sized to match that padding exactly, both
     the desktop and mobile-breakpoint values) used only by the 4
     detail-view templates, which now wrap their `detail_cover(...)` +
     `.detail-heading-row` pair in it instead of putting them directly in
     `.modal-header`.
  2. **Work sessions header merge** (direct follow-up: "merge the Work
     sessions and the Scheduled work 1.0h / 1.0h, because it's
     redundant... don't have two dividers between the two - none is
     enough") -- the separate "Scheduled work" sub-heading
     (`.relations-group`/`.relations-group-head`, a leftover from when
     this card could hold more than one labeled group) is gone; its hours
     readout is now a second `.checklist-progress` pill on the "Work
     sessions" heading itself. This also fixed an unintended second
     divider: `.relations-group`'s own `border-top` was firing because it
     was the *second* child of the macro's output (after the `<h2>`), so
     its `:first-child` CSS exemption never actually matched -- on top of
     `.detail-plain-section`'s own top border from the earlier entry
     below, that read as two hairlines where one now suffices.
     `.relations-group`/`.relations-group-head` CSS removed as fully dead
     (its only other two consumers were already the same unreferenced
     `_task_relations.html`/`_event_relations.html` files noted in the
     `.detail-identity-dot` cleanup below).
  `sw.js` CACHE_NAME bumped v50 -> v51 (checked `git log` first, no
  concurrent commits since this session's own v50), `test_pwa_shell.py`'s
  pin updated. Full suite: 1952 passed (four parallel chunks by file).

- **Shipped:** Direct follow-up, same day (2026-09-03), two small fixes on
  top of the cover-banner baseline shipped earlier the same day:
  1. **Bug fix** ("the icon is cut by the body, not sitting on top") --
     `.detail-cover-icon` (the floating badge) used to be a child of
     `.detail-cover`, which needs `overflow:hidden` to clip the image/
     gradient fill to the cover's rounded top corners; that same
     `overflow:hidden` was clipping the badge's own bottom overhang, its
     entire reason for existing. Fixed by introducing `.detail-cover-wrap`
     (a plain, non-clipping positioning context) as the actual parent of
     both `.detail-cover` and `.detail-cover-icon`, siblings now instead
     of parent/child -- `_detail_cover.html` + style.css both changed, no
     other template changes needed (all four detail modals go through the
     one shared macro).
  2. **Work sessions rework** (direct request: "could we also rework the
     work sessions" -> clarified via AskUserQuestion -> "visual polish
     without having the background color card div"): task_detail.html's
     and habit_task_detail.html's Work sessions section dropped the
     elevated `.detail-card` wrapper for the new `.detail-plain-section`
     (a top hairline instead of a tonal box -- same "no background card"
     treatment the meta grid got in the very first 2026-09-03 session
     today) plus a `.work-session-row` modifier per row (a little more
     vertical padding than the default `.checklist-row` density, a small
     clock icon ahead of "Session N") -- purely visual, no new fields or
     endpoints. The habit heatmap card right above it on the habit-task
     page keeps its real `.detail-card` treatment, unaffected -- scoped
     to Work sessions specifically, matching how the meta-grid change was
     scoped narrowly too.
  `sw.js` CACHE_NAME bumped v49 -> v50 (picking up from another session's
  concurrent v48->v49 datetime-picker bump the same day -- this repo saw
  parallel sessions today, checked via `git log` before bumping rather than
  assuming the last value this session itself had written), `test_pwa_
  shell.py`'s pin updated. `test_detail_modals_rework.py`'s task-page
  card-count test rewritten (Work sessions was the last real `.detail-card`
  on that page; now there are zero). Full suite: 1952 passed (four
  parallel chunks by file, same convention as every other multi-file
  session this file documents).

- **Shipped:** Direct request, same day (2026-09-03) -- reworked the shared
  date+time range picker's hour selection (`_datetime_picker.html`'s
  `datetime_picker` macro / `static/datetime_picker.js`), used by the event
  create/edit modal (`_event_form_fields.html`'s Start & end field) among
  other callers. Reached via several mockup rounds (static HTML, shared as
  files, not built against real data) rather than a single guess: a first
  pass of grid/slider/preset alternatives to the old scrolling 24-row hour
  list was all rejected as "counterintuitive" (the slider drags/rounds
  imprecisely, the grids/presets don't reach every hour); a follow-up typed
  HH:MM text-field pass was rejected too, as "too much input needed"; a
  compact single-column mockup (full calendar + two small Start/End chips
  under it, no second column) landed on its "closed" state but not its
  click-to-open-a-dropdown interaction; the final round dropped the dropdown
  in favor of segmented in-place editing and was approved outright ("yes.
  this one. implement").
  1. **Range mode's panel is a single column now** (`.dtp-panel--range`,
     style.css, flex column instead of a 2-col grid) -- month calendar, then
     one `.dtp-hour-row` of two `.dtp-hour-chip`s (Start/End) underneath,
     same width as date mode's own panel. The old scrolling/click-drag
     24-row `.dtp-hour` list is gone entirely (datetime_picker.js's
     `renderHours`/`paintHours`/`pickHour`/`attachHourDrag` removed).
  2. **Each chip is a native-time-input-style segmented field** -- hour and
     minute (plus AM/PM, 12h setting only) segments, exactly one highlighted
     ("active") at a time while that chip has real focus. Arrow Up/Down nudge
     the active segment (wrapping 23→00/59→00); Arrow Left/Right move which
     segment is active; typing digits sets a value directly and
     auto-advances hour→minute after two digits (`typeDigit`); Backspace
     clears the active segment. Minutes are a real independently-tracked
     `state.startMinute`/`endMinute` now, not derived via the old
     "keep-the-original-minute-unless-hour-changes" trick the whole-hour
     click grid needed.
  3. **No Apply button anywhere (range or time mode).** Every edit -- a day
     click, a segment nudge, a typed digit -- commits straight to the hidden
     inputs immediately (`commitLive`), the same auto-commit contract `date`
     mode already had; the panel just stays open afterward since one edit is
     rarely the last one. Time mode (hours-only, no calendar -- the weekly
     Sleep/Leisure block picker) reuses the exact same chip row, gaining a
     minimal one-row header (`renderTimeHeader`) just to hold Clear.
  4. **Clear moved into the header, icon-only,** for range mode too now
     (previously only date mode had this; range/time had a text Clear in a
     footer that no longer exists) -- reuses the existing `.dtp-clear-nav`
     treatment next to the month-nav arrows, still hidden whenever `submit`
     is set.
  5. **Submit-mode callers** (event_detail.html's "Move this occurrence",
     `_task_work_allocations.html`'s per-session set-times, both
     `data-dtp-submit="1"`) lost their Apply-triggered `requestSubmit()` and
     gained a close-triggered one instead: a new `state.dirty` flag (reset
     on open, set on any real edit) means the enclosing form submits only if
     the panel is closed *after* an actual edit landed a complete value --
     opening a submit-mode picker just to look, then clicking away, no
     longer silently re-POSTs unchanged values.
  `sw.js` CACHE_NAME bumped v48 → v49 (style.css + datetime_picker.js
  changed), `test_pwa_shell.py`'s pin updated. No other tests touch this
  component's JS-rendered markup (grepped `dtp-hour`/`dtp-panel`/
  `dtp-trigger`/etc. across `tests/` first -- none), so no other test
  changes were needed. Full suite: 1952 passed (four chunks by file, same
  convention as every other multi-file session this file documents).

- **Shipped:** Direct request, same day (2026-09-03) -- "all dates should be
  displayed more minimally, with a single script that resolves all dates
  from the standard complicated format to a more human readable format.
  EVERYWHERE." Audited every template for raw ISO date/datetime display
  text (`grep` across `src/templates` for `_at`/`date_from`/`date_to`/
  `created_at`/`checked_at` references, excluding form-input `value=`
  attributes and JS `data-*` attributes, which must stay raw ISO for
  `datetime_picker.js`/drag-calc to keep working) rather than adding a new
  formatter: the app already had a "single script" for this --
  `deps.py`'s `relative_date` Jinja filter (short dates: "Today"/
  "Tomorrow"/"Yesterday"/"5 Sep"/"5 Sep 2027") and `fmt_dt` filter (full
  timestamps: "Aug 25, 2026, 8:57 PM") -- it just wasn't applied
  everywhere yet. Six templates had raw `value[:10]`/bare-field date text
  that skipped both filters; switched each to whichever of the two
  already-established filters matches the field (short date vs.
  full timestamp), no new code: `task_detail.html` (due/start),
  `event_detail.html` (start/end, occurrence-card date, "Moved to" date --
  the datetime_picker's own prefill value at line 150 left untouched, it
  needs raw ISO), `project_detail.html` (deadline/event leading date,
  Kanban card due-date tag), `settings_holidays.html` (date_from/date_to
  range), `settings_data_maintenance.html` (sync-conflict `created_at`,
  integrity `checked_at`, both `fmt_dt` to match the pre-existing
  `latest_backup.created_at | fmt_dt` on the same page). Confirmed via
  grep that calendar grid templates' `start_at`/`end_at` uses are all
  `data-start`/`data-end` JS attributes or already-filtered `fmt_time`
  calls, not raw display text -- left alone. `test_settings_holidays.py`'s
  `test_lists_existing_holidays_as_rows_with_edit_buttons` updated
  ("2026-12-20"/"2027-01-05" -> "20 Dec"/"5 Jan 2027", the new
  `relative_date` output for today = 2026-09-03). Full suite: 1952 passed
  (four parallel chunks by file). No new filter, no `sw.js` cache bump
  (server-rendered text, not a static asset).

- **Shipped:** Direct request, same day (2026-09-03), on top of the two
  view/edit-modal design follow-ups right below: after a mockup pass (4
  static HTML variants, shared as a file, not built against real data)
  exploring ways to "spice up" the bland restyled view modal, the user
  picked one outright -- "I like variant B so much I want it to be the
  baseline for all view modal windows. Implement." -- a Notion-style cover
  banner replacing the plain `.detail-identity-dot + title` header row
  across all four detail modals (event/task/contact/habit-task).
  1. **New shared `_detail_cover.html` macro** (`detail_cover(accent,
     banner, badge_html, avatar_mode=false)`), imported by all four
     detail templates. Renders a `.detail-cover` strip: a real resolved
     banner image (`.detail-cover-img`) when one exists, else a flat
     accent-color gradient fill (`.detail-cover-fill`, CSS custom prop
     `--cover-accent`) -- with a floating `.detail-cover-icon` badge
     (a small white icon card, or `.detail-cover-icon-avatar` for
     contacts, a ringed avatar with no card chrome) overlapping its
     bottom edge. Which of the two wins was a real design collision, not
     a guess -- resolved via AskUserQuestion before touching any code
     (real image wins, color is the fallback, one cover slot instead of
     stacking a color header above the pre-existing task image banner).
  2. **`db.banner_for_task` generalized to `db.banner_for_object(conn,
     object_type, obj)`** (same label > Project > Space priority chain,
     now keyed on any `object_labels` type) -- `banner_for_task` kept as
     a thin name-preserving wrapper so its own tests and both pre-existing
     call sites (task_detail, project_detail's Kanban cards) didn't need
     to change. Wired up fresh for events (`routers/calendar.py`'s
     `event_detail` -- STATE.md had flagged this exact gap, "generalizes,
     just not wired to event_detail.html yet") and contacts
     (`routers/contacts.py`'s `contact_detail`); habit-task detail reuses
     task_detail's route so it got `banner`/`status_colors` for free.
  3. **New `deps.py` global `stable_color(seed)`** -- contacts have no
     color field the way events (calendar_color) and tasks (status) do,
     so a contact's cover-fill color is deterministically derived from
     its own `uid` (md5 -> one of the same 16 `.cal-*` names
     routers/labels.py's `COLORS` uses, duplicated locally rather than
     imported to avoid a circular import with routers/labels.py).
  4. **task_detail.html's old standalone `.detail-modal-banner` body
     strip is retired** -- that resolved image now renders inside the
     new cover instead of a second, separate strip below the header.
     `.detail-identity-dot` CSS is removed too (its only other consumers,
     `_task_relations.html`/`_event_relations.html`, were already dead/
     unreferenced templates per routers/tasks.py's and routers/
     calendar.py's own "now unreferenced" comments -- confirmed via grep
     before removing, not assumed).
  `.modal-header` restructured from a single flex row to a column (cover
  above a new `.detail-heading-row` for the title) -- a global rule
  change, safe because static/modal.js's `injectModalContent` copies this
  div's *children* into the dialog's persistent `#modal-header` (which
  carries the same class/CSS), never the div's own class list, so no
  modifier class on `.modal-header` itself would have survived the
  modal-JS path; every state that differs (image vs. gradient) lives on a
  child element's class instead. Mobile breakpoint updated to match
  (shorter, unrounded cover under the bottom-sheet's drag handle).
  `sw.js` CACHE_NAME bumped v47 -> v48, `test_pwa_shell.py`'s pin updated.
  `test_detail_modals_rework.py`'s `TestIdentityMark` rewritten for the
  new markup (3 tests); `test_banners.py`'s task-detail banner tests
  updated for the new `.detail-cover-img`/`.detail-cover-fill` classes/
  location, plus 2 new tests covering the event/contact wiring. Full
  suite: 1952 passed (four parallel chunks by file, same convention as
  every other multi-file session this file documents).

- **Shipped:** Direct follow-up, same day (2026-09-03), on top of the
  Format-toggle rework right below: "make the input boxes more dense: half
  width modal windows (especially valuable for the reminders, recurrence,
  holiday calendar). The format settings should be right at the end of the
  modal, not before the reminders." Both purely a `_event_form_fields.html`
  reorder/class change, no CSS/JS touched -- the 2-column `.field-grid`
  and the `.field` (half) vs. `.field field-wide` (full row) split already
  existed (Holiday calendar was already `ms_wide=false`/half; Labels was
  already a plain half-width `.field` too):
  1. **Reminders and Recurrence dropped `field-wide`.** Each used to claim
     a full row for one short input; now plain `.field`s, so they land
     side by side in the grid the same way Holiday calendar already did.
  2. **Format (+ its Location/Meeting URL fields) moved from right after
     All day/before Labels down to the very end of the field grid, after
     Holiday calendar.** Pure reorder -- the `_has_location`/`_has_meeting`
     Jinja sets and the field's show/hide CSS (`#event-form:has(...)`,
     style.css, untouched) don't care where in the DOM the field sits.
  New field order: Title, Description, Start & end, All day, Labels,
  Reminders + Recurrence (side by side), Holiday calendar (+ Exclude Sat/
  Sun, hidden until recurring), Format (+ Location or Meeting URL,
  whichever the Format pick reveals) last. Verified with an ad hoc
  TestClient-free script (new_event_form's rendered body, not added to the
  suite -- no existing test asserts field order, confirmed by grep before
  starting) that `reminders` < `recurrence` < `holiday_calendar` <
  `event_format_in_person` by string offset, and that neither Reminders'
  nor Recurrence's own `.field` div carries `field-wide` anymore. `sw.js`
  CACHE_NAME bumped v46 -> v47 (template-only change), `test_pwa_shell.
  py`'s pin updated. Full suite: 1945 passed (four parallel chunks, same
  as the entry below), unaffected since no test asserted the old order or
  width.

- **Shipped:** Direct request, same day (2026-09-03), two view/edit-modal
  design follow-ups the user flagged as still outstanding from the
  2026-09-02 detail-modal design pass ("we have not restyled the view
  modal to not use the colored bg card div... also we have not fixed the
  CSS for some edit modal... I would prefer to move away from how the
  Format toggle looks — too cramped between icons and text, the gray, out
  of place, no clear subordination, no clear 'not one of these' state").
  Confirmed direction via AskUserQuestion (3 questions) before touching
  code:
  1. **View modals: the meta grid's wrapper is no longer an elevated
     tonal `.detail-card` with a colored left accent.** New `style.css`
     class `.detail-meta-panel` (no background/border/shadow/hover-lift,
     just a bottom hairline separating it from whatever follows) replaces
     `.detail-card` on the *meta grid specifically* in all four detail
     modals — `event_detail.html`, `task_detail.html`,
     `contact_detail.html`, `habit_task_detail.html` — including dropping
     the now-unused `style="--detail-accent: ..."` inline attribute from
     the two that had one (event/task). Scoped deliberately narrow: a
     *second*, later `.detail-card` in event/task/habit-task (the
     occurrence card, Work sessions card, habit heatmap) keeps the real
     card treatment untouched — the feedback was about the meta display
     specifically, not every card in a detail modal. Calendar-color signal
     for events still survives via the header's `.detail-identity-dot`
     and the Start value's own `.color-dot`, so nothing about "which
     color is this" was lost, just the big tinted box.
  2. **Edit modal's Format toggle (In person / Online) rebuilt on the
     existing tile/card picker pattern** (`.tile-select`/`.tile-option`,
     already used by the widget builder's Data source field) instead of
     the cramped `.segmented`/`.seg-btn` pill row — `_event_form_fields.
     html`, three equal cards now, icon above label, obvious selected
     look (border + tint) vs. a plain neutral outline unselected. Added a
     third, explicit **None** option (`id="event_format_none"`, value
     `none`) — "neither Location nor Meeting URL set" used to be an
     implicit state (both radios simply unchecked, including on every
     brand-new event); it's now a real, visibly-selected third choice,
     checked whenever `_has_location`/`_has_meeting` are both false. Kept
     the original `event_format_in_person`/`event_format_online` ids and
     the `event-format-segmented` wrapper class in place (just added
     `tile-select` alongside) specifically so existing tests and
     `event_format_toggle.js`'s own selector didn't need touching beyond
     the one real behavior change: picking None now clears *both*
     Location and Meeting URL (previously the clear-the-other-field logic
     only ever knew about one "other" field, since None wasn't a value it
     handled).
  `sw.js` CACHE_NAME bumped v45 → v46 (style.css + templates + JS
  changed), `test_pwa_shell.py`'s pin updated. `test_detail_modals_rework.
  py` updated for the `.detail-card` → `.detail-meta-panel` rename (3
  tests asserting the literal wrapper class, 1 asserting `--detail-accent`
  presence — replaced with an assertion on the still-present
  `.color-dot`/`.detail-identity-dot`, 1 card-count test dropped from 2 to
  1 now that only the Work sessions card is a real `.detail-card` on the
  task page); `test_event_format_field.py` gained a new
  `TestFormatFieldNoneOption` class (4 tests: new-event/edit-with-neither
  check None, edit-with-location/edit-with-meeting don't). Full suite:
  1945 passed (four parallel chunks by file, same convention as every
  other multi-file session this file documents).

- **Shipped:** Direct follow-up, same day (2026-09-03), calendar drag-and-drop
  consistency + a new capability, three bundled changes from one
  conversation ("in the planner and calendar pages... there should be drag
  and drop support" -> turned out Week/4-Week/Month already had it wired,
  the actual gaps were narrower):
  1. **CSS bug: the Month/4-Week dragging chip looked like it was
     disappearing, not being picked up.** `.month-event-item.dragging,
     .month-due-task-item.dragging` was `opacity:.5; cursor:grabbing` only
     -- no shadow/outline/z-index, unlike Week's `.time-event.dragging`
     (ring outline + elevated shadow + z-index:30 + opacity:.95). Direct
     feedback: "the css is wrong... the events are not shown as dragged."
     Now both share the same ring-outline/shadow/opacity-.95 treatment
     (Month/4-Week uses z-index:5, not Week's 30 -- no tall shared
     absolutely-positioned canvas there to clear).
  2. **New: drag-and-drop for the Week view's all-day row.**
     `_calendar_week_grid.html`'s `.allday-task` items (events and
     due-date tasks) had zero drag wiring before this -- not broken, never
     built; `calendar.js` only ever binds `.time-event:not(.work-
     allocation)`, which this row's items never carry. New file
     `static/calendar_week_allday_drag.js`, modeled directly on Month/
     4-Week's own `calendar_month_drag.js`: day-shift only (no time axis,
     no resize -- multi-day span-resize is a separate unbuilt feature), same
     `/events/{uid}/reschedule` and `/tasks/{uid}/update-field` (field
     `due_at`) endpoints, same recurring-event exclusion (no `data-uid`
     rendered for a recurring event, so it stays click-only). Needed
     `data-date` added to `.allday-col` and `data-uid`/`data-start`/
     `data-end`/`data-due` added to the two `.allday-task` link kinds,
     neither of which existed before. Wired into `calendar_week.html`'s
     script block and into `async_calendar.js`'s `refreshWeek()` re-bind
     (`CCWeekAllDayDrag.init()`) so a swapped-in `#week-grid` region after
     any change gets the bindings re-attached, same pattern every other
     region-refresh hook already uses. Day view's own `.allday-task` strip
     (`calendar_day.html`) was deliberately left alone -- out of scope,
     wasn't requested.
  3. **Task due-date chips: fallback icon changed from `square` (read as
     an empty checkbox) to `alert-triangle`.** Direct feedback: "the icon
     next to tasks... should not be a checkbox, but better a warning sign
     (because that is the due date of the task)." The `default('square',
     true)` fallback (used whenever a task's own label has no configured
     icon) was one identical pattern repeated in 5 templates --
     `_calendar_week_grid.html`, `calendar_day.html`,
     `_calendar_month_grid.html`, `_calendar_fourweek_grid.html`,
     `_widget_agenda.html` -- confirmed with the user this should change
     everywhere, not just Week, since it's genuinely the same element/
     meaning in each place.
  Full suite: 1941 passed (four file-list chunks, `test_caldav_bridge_live.py`
  excluded as always -- background/nohup pytest runs don't survive between
  tool calls in this sandbox, so chunks were run as direct foreground calls
  against explicit file-list slices instead).

- **Shipped:** Direct follow-up, same day (2026-09-03), "the font in the
  tasks table is much too small, compare the two tables -- I want a much
  more standardized font." The three density-pass sizes fighting for
  attention in one row (Status chip 11px, compact Date 13px, everything
  else -- Habits' plain-text Cadence/Streak/Check-in, both tables' Labels
  pills -- inheriting whatever the page default happened to be, ~15.5px)
  are now one number: `.task-table tbody td{font-size:var(--text-
  footnote)}` (14px), with the Status chip's and Labels pill's own
  `font-size:11px` overrides dropped entirely (inherit the td's 14px) and
  a new `.task-table .dtp--compact .dtp-trigger{font-size:inherit;}`
  overriding the compact date trigger's normally-global 13px specifically
  inside this table. The Title cell keeps its own explicit larger size
  (`.task-title-cell a`, `var(--text-body)`, from the original density
  pass) -- an element's own directly-matching rule always wins over an
  inherited ancestor value regardless of the ancestor selector's
  specificity, so this one deliberate exception to the new baseline was
  safe to leave alone. Pure CSS, no markup touched -- full suite unaffected
  (1946 passed, same as before this entry).

- **Fixed two real bugs + one more design follow-up**, same day
  (2026-09-03), reported as "the setting is on, no icons show, something's
  rotten... the Tasks table doesn't match Habits (font, corner radius)...
  also I want label colors lighter/pastel, based on the chosen color":
  1. **Bug: an icon picked in the label editor never saved.**
     `label_form_modal.html` (the live "New Label"/"Edit label" modal --
     confirmed via `routers/labels.py::edit_label_modal`, which template
     actually serves the Edit button, since `label_edit_modal.html` looked
     plausible but turned out to be orphaned/unrouted) posts an `icon`
     radio (`_icon_swatch_picker.html`) into `create_label`/`update_label`
     -- neither route declared an `icon: str = Form(...)` param, so
     FastAPI silently dropped the field on every submit, and `db.
     upsert_label_config`'s own partial-update contract ("only touch what
     you're told to") meant an absent key wasn't cleared, just silently
     never changed. Confirmed end-to-end with a `Request` carrying a real
     `.app.state.settings.db_path` (the bare-`Request` harness this suite
     otherwise uses can't exercise `label_icon()`'s DB-backed path at all
     -- see the entry below) that the render side was already correct
     given a label that actually has an icon; the picker's own submit was
     the break. Fixed by declaring `icon` on both routes. New tests in
     `test_phase2_labels.py::TestIconPersistence` (create, update-new,
     update-change, "No icon" radio clears it, doesn't disturb color/
     group saved alongside it).
  2. **Bug (found while verifying #1): a standalone Habit entity's own
     labels never rendered anywhere**, icon or plain. `routers/tasks.py`'s
     `_habit_group_items` hardcoded `"tags": []` on the entity-kind branch
     instead of reading `h.get("tags")` -- `db.list_habits`'s own
     `_habit_row_to_dict` already attaches real labels via `object_labels`,
     the same mechanism every other entity type uses, so the data existed
     and was computed, just discarded one line later. A habit-*labeled
     task* right above it in the same function (`kind: "task"`,
     `t.get("tags")`) never had this bug. New test:
     `test_tasks_habits_view.py::TestHabitsViewRetired::
     test_standalone_habit_entity_carries_its_own_labels`.
  3. **Design: Tasks/Habits row pills now match each other exactly, and
     are pastel.** `_habit_row.html`'s Labels cell had no `.cell-tags`
     wrapper (only `_task_row.html`'s did), so the density pass's radius/
     font-size override (originally `.task-labels-select .cell-tag`) never
     reached it -- Habits kept the app's default 8px/13px pill next to
     Tasks' new fully-rounded 11px one. Added the same `.cell-tags` wrapper
     to `_habit_row.html`, retargeted the CSS rule to `.cell-tags
     .cell-tag` so one selector now covers both. Separately, label pills
     everywhere (`label_pill`'s `.cell-tag.cal-<color>`, not just these two
     rows) now paint with the same light/tinted `--tag-<color>-bg`/`-fg`
     pair `.tag-<color>` pills already used elsewhere in the app (all 16
     colors already had one, light AND dark theme -- nothing new to
     invent) instead of the bold saturated `--cal-bg-*`/`--cal-fg-*` pair
     built for the calendar's own filled surfaces. Scoped to `.cell-tag.cal-
     *` (2-class, beats the bare `.cal-*` rule regardless of source order)
     so calendar dots/filled-cards/timeline bars keep their original bold
     look -- only the label-pill element repaints, everywhere it's used.
  Full suite: 1946 passed (four parallel chunks, `test_caldav_bridge_live.py`
  excluded as always).

- **Shipped:** Direct follow-up, same day (2026-09-03), on top of the two
  entries right below: "labels should all look like pils and have their
  respective icons visible. also all pils should have the same rounded
  corners and text should have the same size." The quiet dot+muted-text
  Labels treatment from the density-pass entry below (`label_pill_quiet`,
  `.cell-tag-quiet`) is reverted outright, same day it shipped -- the
  Tasks/Habits row's Labels cell goes back to the original `label_pill`
  (full color fill + icon, same macro every other page's read-only tag
  display already used); `label_pill_quiet` deleted from _label_pill.html
  rather than left as dead code, its two call sites (_task_row.html/
  _habit_row.html) reverted to `label_pill`. Icon visibility itself is
  unchanged code -- gated by `_show_label_icons()` (Settings > Appearance
  > "Show icons next to labels", off by default) AND the individual
  label's own configured icon (Settings > Labels) -- neither of those
  toggles was touched this session; if a label still shows no icon after
  this, check both settings, not a code path. New this round: the Labels
  pill and the Status chip next to it now share one shape -- `.cell-tag`'s
  app-wide default (`var(--radius-sm)` 8px / `var(--text-caption)` 13px)
  never matched the Status trigger's own compact-chip override from the
  density pass (`var(--radius-pill)` fully rounded / 11px), which is what
  read as "not all pills have the same rounded corners." Fixed with a
  `.task-labels-select .cell-tag` override (radius-pill + 11px) scoped to
  this one row's Labels cell specifically -- every other page's label
  pills (task/event/contact detail, project Kanban, widget builder) keep
  the app's normal 8px/13px look untouched. Full suite: 1940 passed (four
  parallel chunks). Verified the reverted markup directly (bare-Request
  script, same harness limitation as always -- no real `request.app`, so
  `_label_color`/`_label_icon`'s broad except silently falls back to
  default color/no icon in that harness specifically; not evidence of a
  real bug, just untestable outside a live ASGI request the way this
  suite is structured) -- confirmed `.task-labels-select .cell-tag` with
  the new radius/font-size lands, `label_pill`'s icon-conditional markup
  is back in place.

- **Shipped:** Direct follow-up, same day (2026-09-03): "don't repeat
  column headers, say them once. don't group tasks by label anymore, make
  one single big table. also I want the white card background div back."
  Three changes on top of the design pass right below:
  1. **One flat table, one header.** `_tasks_body.html`'s per-group
     `.card`+`<table>`+`<thead>` (Project/Unassigned/Completed, each
     repeating Title/Status/Date/Labels in its own header) is gone --
     collapsed into one `<table id="task-table">` inside one `.card` with
     one plain `<thead>`. `routers/tasks.py`'s `_build_task_groups`/
     `groups` context is untouched (still Project-alphabetical -> Habits
     -> Unassigned -> Completed, per `test_tasks_grouping.py`) -- the
     template just concatenates every non-Habits, non-Completed group's
     tasks into one `<tbody>` in that same order, then Completed's own
     tasks last in the same `<tbody>` (still dimmed via the existing
     `.task-row-completed` class, just no longer behind its own header).
     Habits keeps its fully separate table/header/`+` -- confirmed with the
     user this wasn't part of the "grouped by label" complaint, it's a
     different column set for a different row kind, not a label grouping.
  2. **Single "+ Task nou" add button**, replacing every per-group `+` --
     `_tasks_toolbar.html` now renders one `<a href="/tasks/new" ... class="btn
     primary" data-fab>` next to the Date filter in the page header's
     actions slot (same slot/pattern Notes' own header button uses); the
     project a new task belongs to is picked inside the create modal's own
     Labels field, same as every other path that ever set one.
  3. **White card background back** -- reverted the same session's earlier
     `.task-group-card`/`.task-table-habits` flattening override
     (`background:none`/no shadow/no hover-lift) entirely; both fall back
     to the plain `.card`+`.table-scroll` elevated look with no override.
     Moot for `.task-group-card` specifically now anyway, since (1) above
     means there's only ever one of it on the page.
  Confirmed with the user before implementing (AskUserQuestion, two
  questions): Completed tasks stay clustered at the end of the one table
  (dimmed, no header) rather than fully interleaved by date, and the
  add-task affordance is one button above the table (project picked in the
  form) rather than a per-row project column. Updated
  `test_tasks_table_habits_split.py`'s `TestGroupNameAndAddButtonInTableHeader`
  -- its three per-group-header tests asserted exactly the design being
  undone here (`>Garden (1)<`/`>Unassigned (1)<`/`>Completed (1)<` inside a
  `<thead>`), replaced with tests asserting the merged table's single
  header, that Project/Unassigned tasks actually land in the same
  `<tbody>`, that Completed still renders dimmed inline, and that exactly
  one `href="/tasks/new"` exists on the page; the Habits-table-specific
  test in the same class was untouched (that table didn't change). Full
  suite: 1940 passed (four parallel chunks, `test_caldav_bridge_live.py`
  excluded as always).

- **Shipped:** Direct request (2026-09-03), seven-point design pass on the
  Tasks table's density/hierarchy ("kill the giant empty space in every
  row... stop treating every group as a giant card... make the task name
  dominant... status should not consume an entire column... labels need to
  be less visually aggressive... put the + where it actually belongs...
  delete should be hidden until hover"). All CSS plus a handful of small
  template hooks, no column-layout rewrite, no JS changes — kept the
  existing `<table>`/`<tr>`/`<td>` structure (and its Status/Date/Labels
  `<th>`s) rather than the two-line flex-row shape the request's own
  mockups sketched, specifically so `static/tasks_table.js`'s delegated
  selectors (`closest("tr")`, `td:nth-child(2) a`, etc.) and the existing
  markup-assertion tests (`test_tasks_table_labels_status_title.py`,
  `test_tasks_table_habits_split.py`) didn't need touching:
  1. Row height: `.task-table thead th`/`tbody td` padding scoped down
     from the app's default 10-12px to 8px (same "#labels-table gets its
     own scoped override, not a bare `tbody td` rule" precedent already in
     style.css) — lands at ~44px (the trailing delete `.icon-btn` is the
     tallest cell at 28px square).
  2. Groups: `.task-group-card`/`.task-table-habits` (both also `.card` +
     `.table-scroll`) flattened — `background:none` (drops the elevated
     fill AND `.table-scroll`'s edge-fade gradients, which are painted in
     the same now-absent `--bg-elevated` and would otherwise show as stray
     tinted rectangles at the edges), `box-shadow:none`, no hover-lift. The
     header row's own 2px `border-bottom` (unchanged) is now the only
     boundary between groups.
  3. Title: `.task-title-cell a` bumped to 600 weight / `--text-body`. The
     title column's floor width dropped 140px -> 64px (140px was the
     "checkbox -> enormous whitespace -> status" gap the request pointed
     at directly — a short title like "h" was reserving room nothing used);
     the existing `:has([data-editing])` 280px floor while typing is
     untouched. Date (`.dtp--compact .dtp-trigger`) recolored to
     `--fg-secondary`, a rung below the title.
  4. Status: `.task-status-select .pill-select-trigger` padding/font
     shrunk further (2px 7px / 11px) into a small colored chip. Not a
     literal single dot — four live statuses (Active/Completed/Archived/
     Paused) need to stay distinguishable without opening the menu, which
     the request's own fallback wording ("if you have multiple states, use
     a tiny status indicator... clicking it opens the state menu") already
     allows for.
  5. Labels: new `_label_pill.html::label_pill_quiet(tag)` macro — a small
     `.color-dot` (reused as-is, just painted via the label's own
     `.cal-<color>` class for its `background`) plus plain muted text,
     replacing the old bold filled `.cell-tag` pill in the Tasks/Habits
     row's *closed-state* display only (`_task_row.html`, `_habit_row.html`).
     The Labels dropdown *panel* options still render the original
     `label_pill` (full color) — the request's own carve-out for "when
     labels are an important filtering mechanism." Every other `label_pill`
     caller (task/event/contact detail, project Kanban, widget builder)
     untouched.
  6. Header `+`: `.task-add-btn`/`.task-add-btn-label` — icon stays
     icon-only at rest, a `max-width:0`-collapsed "Add task"/"Add habit"
     label expands in on hover/focus instead of a bare glyph alone at the
     end of a header row.
  7. Delete: `.task-row-delete{opacity:0}`, revealed on `tr:hover` OR
     `tr:focus-within` (not `display`/`visibility`, so it stays a real
     focusable target for keyboard tabbing — `:focus-within` reveals it the
     moment focus reaches it, before a sighted keyboard user needs to see
     it) — new `.task-row-actions`/`.task-row-delete` classes on the
     trailing `<td>`/button in both `_task_row.html` and `_habit_row.html`.
  Deliberately NOT built: the mockups' ⋮ Edit/Duplicate/Move/Delete menu —
  Edit and Delete already exist (open the row, delete icon), but Duplicate
  and Move have no backend support at all (no duplicate-task endpoint, no
  per-row move-to-list action outside the bulk-actions bar), so inventing
  menu items for features that don't exist would be worse than the plain
  hover-reveal delete this ships instead. Also not built: using the
  bulk-select checkbox itself as a one-click "mark complete" toggle (the
  mockups' `□`/`✓` idea) — that checkbox is the bulk-selection control
  (`static/tasks_table.js`'s whole shift-click/drag-paint/bulk-actions-bar
  system keys off it); overloading it with a second, conflicting meaning
  would break bulk-select outright, not simplify the row. Status stays its
  own compact control instead (item 4 above).
  Verified: full suite passed (four parallel chunks by test-file, this
  environment's background-process-per-bash-call limitation meant a single
  bash call had to launch all four AND `wait` on them together rather than
  polling separately — 1939 passed, 0 failed, `test_caldav_bridge_live.py`
  excluded as always). Also spot-checked the rendered `/tasks` HTML
  directly (a seeded in-memory-DB script, not added to the suite) to
  confirm `label_pill_quiet`'s markup and the new hover/`+`-label classes
  actually land where expected — the Python test suite has no JS/CSS
  harness (per this file's own recurring note), so the seven points above
  are validated by source/markup inspection, not a computed-style
  assertion.

## How to run a session (slice discipline)

1. Read this file. That's the whole session-start cost.
2. Pick **one** slice — one roadmap bullet, sized to ship standalone (the
   roadmap docs already size sections this way; if a section still feels big,
   split it into a smaller committable piece rather than attempting it whole).
3. Before writing code, open only the specific section of `open-priority.md`
   or `open.md` the slice belongs to (use grep/section headers, not a full
   read) — the docs are long because they cover nine releases, not because one
   slice needs all of it.
4. Implement, then run the affected test file(s) directly
   (`pytest tests/test_x.py -q`), not the full suite, while iterating.
5. Before calling the slice done: run the full suite once
   (`cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q`), commit
   with a message following the existing `Released X.Y — ...` / descriptive
   style, bump `pyproject.toml` version if the slice completes a release.
6. Update the "Right now" section above with the new position. Update
   `roadmap.md`'s table row and the relevant doc section (strike through /
   mark resolved, matching how `1.1`/`1.2` were closed out) in the same
   commit. Remove the finished section from `open-priority.md`/`open.md` and
   summarize the shipped outcome in `features/`, per each doc's own "How open
   work gets tracked" footer.
7. Stop. Don't chain multiple slices in one session unless they're trivially
   small (a doc-only correction, a one-line fix) — bigger sessions cost more
   tokens per slice and make the commit history harder to audit, not easier.

## Cheap verification, every session

```bash
git status --short                                    # catch uncommitted WIP from a prior session
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q   # full suite, ~11s, 921+ tests
```

Run both before assuming a clean starting point — WIP has been left
uncommitted before (1.2 sat complete-and-passing but uncommitted until a
session checked `git status`).

## Where the detail actually lives (read on demand, not up front)

| Need | File | Read |
|---|---|---|
| Full release order / dependencies | `plans/roadmap.md` | the one table + the current release's subsection only |
| Rework spec (projects, schedule, views, sync) | `plans/open-priority.md` | the one `##` section for the current slice |
| App-local/low-priority spec | `plans/open.md` | the one `##` section for the current slice |
| Data model / layering rules | `features/architecture.md` | before touching schema or a new entity type |
| What's shipped, for cross-reference | `features/README.md` + linked docs | only if the slice touches an existing surface |
| Why something was cut, versioning history | `plans/abandoned.md` | rarely — only if reopening a past decision |

## Notes for future sessions

- Test env: `.venv/bin/python` at repo root, run from `webapp/` with
  `PYTHONPATH=src`. The system `python3` (3.14) is not the project venv.
- Git identity in this repo: `istorie.petru <126282015+istorie-petru@users.noreply.github.com>`.
- Commit message convention: `Released X.Y — <summary>` for a release-closing
  commit (see `git log`); plain descriptive messages for side-work-only or
  partial slices that don't close a release.
