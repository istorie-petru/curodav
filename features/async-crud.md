# Async CRUD: lightweight server-confirmed targeted updates

Status: **designed 2026-08-16; implemented incrementally, starting with task
CRUD.** This document is both the design and the running outcome record for
eliminating unnecessary full-page reloads after CRUD operations. It keeps the
FastAPI + Jinja2 stack: no frontend framework is introduced. All updates ride
on plain `fetch()` plus targeted DOM replacement, reusing the server-rendered
templates that already exist.

## 1. Problem

The app is server-rendered. The modal system (`static/modal.js`) already
submits create/edit forms via `fetch()` and never navigates *itself*, but on
success it calls `window.location.reload()`, and the plain-form fallbacks
(agenda widget's "Mark done", the dashboard's quick-add, inline row deletes
that outlive their undo window) bounce through full navigations or reloads.
Result: every CRUD action repaints the whole page even though the affected
region is one table, one modal, or one widget card.

What already avoids reloads, and why:

- Inline status-pill / due-date edits (`tasks_table.js`) and Kanban drag
  (`tasks_board.js`) — single-field `POST /tasks/{uid}/update-field`, targeted
  cell/column DOM updates, reload only on failure.
- List-row deletes (`app.js` `data-delete-undo`) — optimistic hide + delayed
  background `fetch`, reload only on the detail/modal form variant.
- Command palette actions — `fetch()` + toast, no reload (but the page
  underneath is left stale).
- `modal.js`'s `data-modal-keep-open` forms — re-fetch the modal's own URL and
  swap its content in place.

These are the seeds of the general pattern; the design generalizes them.

## 2. Design principles

1. **Server-rendered HTML stays the single source of truth.** The client
   never reconstructs a row, a sorted order, a paginated page, a section
   divider, or a widget card from data. After a mutation it re-fetches the
   *affected region* as an HTML fragment from the same templates that render
   the full page, and swaps it in place ("HTML over the wire" without a
   framework — the exact technique `modal.js` already uses for modal content).
2. **Mutations are server-confirmed, then re-rendered** (`fetch` → await →
   swap region). No optimistic *structural* DOM writes for operations that
   move a row between sections or pages (create, complete, delete): where the
   row belongs — sorted position, open vs. completed split, group headers,
   pagination — is computed server-side and must not be guessed client-side.
   The one existing optimistic exception stays: single-field inline edits
   (status pill color, due date), where the "move" is visible immediately and
   is exactly what the user just did.
3. **Progressive enhancement is preserved.** Every mutation endpoint keeps its
   plain-form `303 Redirect` behavior when no fetch client is present, so
   no-JS and every existing test calling the router directly behave exactly as
   before. The async path is an opt-in layer on top.
4. **Coarse regions, not per-row surgery.** Each surface owns a small number
   of region containers (the whole tasks table body; one widget card; one
   modal). Swapping a whole region is far less code than reconciling every
   dependent number (divider counts, pager state, empty-state) row by row, and
   it can never drift.

## 3. API response pattern

Two endpoint families.

### 3.1 Mutation endpoints — dual-mode JSON / redirect

The existing form-POST endpoints (`POST /tasks`, `POST /tasks/{uid}`,
`POST /tasks/{uid}/complete`, `POST /tasks/{uid}/delete`) become dual-mode:

- **Default** — no fetch header: unchanged `303 Redirect` (no-JS, plain
  forms, all existing router-function tests).
- **Fetch** — request carries `X-Requested-With: fetch` (set by the shared
  helper, `static/async_crud.js`):
  - Success: `200 {"ok": true}` — create returns `201 {"ok": true, "uid": "…"}`.
  - Failure: `400 {"error": "…"}` (validation) / `404 {"error": "task not
    found"}` — the same JSON error shape `update_field`/`bulk_action` already
    use, and existing `400` paths (`db.MultipleProjectLabelsError`) already
    raise `HTTPException(400, msg)`, which serializes to exactly this.

A tiny shared helper decides which response to return:

```
respond(request, redirect_url)  -> JSONResponse  when X-Requested-With: fetch
                                 -> RedirectResponse(url=redirect_url, 303) otherwise
```

Endpoints keep all their existing form parameters; only the return statement
changes. No new write endpoints are added.

### 3.2 Region fragment endpoints — GET, render one named region

Thin GET endpoints that render exactly one named region of a page. The region
markup is extracted into a partial included by *both* the full page template
and the fragment response, so there is a single source of truth.

- `GET /tasks/regions?region=table` → the `<div id="tasks-body">` fragment
  (table card **or** empty state + pager + Completed divider). It reuses the
  exact `list_tasks` computation, so the fragment reflects the same active
  filter/sort/pagination params the page is showing.
- Future regions, same shape (documented here so later slices just follow the
  recipe): calendar week grid; one board column; one dashboard widget card
  (`GET /dashboard/widgets/{uid}`); one timeline day row.

Response is plain `HTMLResponse`. The client contract for a region fragment:
it is a single element whose `id` matches the container already on the page
(e.g. `#tasks-body`); the client replaces that element in place.

## 4. Client-side update pattern

New shared script `static/async_crud.js`, loaded globally, exposing:

- `ccApi.post(url, formData, opts)` — `fetch` with `X-Requested-With: fetch`
  and the form body; parses the JSON response; throws `{message}` on non-2xx.
  After a successful mutation with `opts.change = {type, action, uid}`, it
  dispatches the cross-surface change event (§5).
- `ccApi.refreshRegion(url, selector)` — fetches a fragment URL and replaces
  the matching element in place. `selector` defaults to the region element's
  own id (derived from the fragment). No-op (safe) when the container isn't on
  this page.

The pattern at each call site is always the same three lines:

```
await ccApi.post(url, form, { change: { type: "task", action, uid } });
await ccApi.refreshRegion(regionUrl);
```

### Loading / disabled states

- During a mutation: the submit button gets `.is-loading` + `disabled`
  (`modal.js` already does this; the helper documents it as the contract).
- During a region refresh: the region container gets `.is-refreshing`
  (a short, light opacity + `pointer-events: none`, new tiny CSS class). No
  skeletons — writes are single-user-fast; the class exists so a slow moment
  reads as "working", not as a dead tap.

### Error states

- **Server rejection** (non-2xx with `{error}`): toast the server's message
  (`ccToast`, `variant: "error"`), keep the form open with the user's input
  intact, re-enable the button. This is where the existing
  `MultipleProjectLabelsError` 400 lands — the same message, no reload.
- **Network failure**: toast "Could not save — network error. Please try
  again.", UI untouched. Deliberately *not* the old reload-to-resync: there is
  nothing to resync to (the write never landed), and reloading would discard
  the user's unsaved input.
- **Region refresh failure after a successful mutation**: the write is safe on
  the server; the worst case is stale markup. Toast a short error and fall
  back to `window.location.reload()` so the page converges. (Refresh is a
  plain GET; failure here means the server is having trouble serving the very
  page the user is on.)

## 5. Cross-surface synchronization

One bus, per-surface registration — no shared global state, no coupling
between surfaces.

- After any successful task mutation, the shared helper dispatches a
  document-level `CustomEvent` `cc-entity-changed` with
  `detail: {type: "task", action, uid}`.
- Each surface registers its own listener and refreshes **only the regions it
  owns**:

| Surface | Listens for | Refreshes |
|---|---|---|
| Tasks table (`/tasks`) | `cc-entity-changed` (task) | `#tasks-body` (table + pager + divider + empty state) |
| Task detail / edit modal | `data-cc-change` on the form → `modal.js` closes and dispatches instead of reloading | underlying page's own listener reacts |
| Dashboard widgets (agenda "Mark done", etc.) | `cc-entity-changed` (task) | the affected widget card (`#widget-{uid}`), via the widget region endpoint |
| Calendar week grid, Board, Timeline, Habits | same event, registered by follow-up slices | their own regions (inline status/date edits already avoid reloads) |

Why this cannot drift: every region re-renders from live SQLite state through
the normal page-render path. The tasks table, a dashboard widget, and a
calendar grid each recompute independently, so "synchronized" means "all
re-read the same source", not "one client copies state around".

### Modal integration (create/edit/delete)

`task_form.html`'s create and edit forms carry `data-cc-change="task"`.
`modal.js`'s success path for a non-keep-open form becomes: close the modal;
if the form has `data-cc-change`, dispatch the event (the page's listener
refreshes its region) — else reload, exactly as before (backward-compatible
for every other modal). `task_detail.html`'s Delete footer form (rendered via
`_modal_footer.html`) gets `data-cc-change="task"` too; `app.js`'s
`data-delete-undo-redirect` branch dispatches the event instead of reloading
when the form opts in.

### Command palette

Already fetch-based; it closes and toasts. It now also dispatches the change
event so the page underneath refreshes its own region instead of staying
stale — the event is the only thing added.

## 6. Offline-first PWA compatibility

The 1.8 offline architecture (IndexedDB mirror + field-HLC outbox +
`/api/sync/push|pull`) and this design are complementary, not competing:

- `ccApi.post` and region fragments are ordinary same-origin `fetch`
  requests, already covered by the service worker's fetch handling (static
  precache + network-first navigations). No `sw.js` change is needed for this
  slice.
- **The write paths are already separated by construction.** Offline writes
  queue into the outbox as field-HLC ops and reach the server through
  `/api/sync/push`; online writes hit the form endpoints directly. A
  single-write entity never goes through both, so there is no double-write or
  conflict to reconcile. The `ccApi.post` helper keeps its network call behind
  one function (`_send`) so a future slice can intercept
  `navigator.onLine === false` and route through `offline_db.js::enqueueOp`
  with the same §2 field-op shape the `/offline` page already produces — the
  tasks online CRUD UI would then *be* the offline create/edit/complete/delete
  UI, with no second implementation.
- **Region fragments are GET HTML**, which the mirror cannot serve yet (it
  stores fields, not rendered markup). A future slice can either serve them
  stale-while-revalidate or rebuild a minimal offline fragment from the mirror
  (`getAllTasks`/`getAllEvents`, the exact data `offline_shell.js` already
  reads). Neither is attempted now.
- **Redirect default kept** means the app never *requires* the fetch path —
  consistent with the app's "progressive enhancement over a real page" stance
  everywhere else.

## 7. Implementation order

Incremental, each step independently shippable:

1. **Mechanism**: `static/async_crud.js` (ccApi + refreshRegion + change
   event); `GET /tasks/regions` fragment endpoint + extract `_tasks_body.html`
   partial; `data-cc-change` handling in `modal.js`/`app.js`; tasks page
   listener. This slice: task create, edit, complete, delete — the primary
   Table surface — plus the task detail modal's delete and the dashboard
   agenda widget's "Mark done" (a task-complete surface). Board/Timeline/
   Calendar pick up the modal hook automatically once their forms opt in.
2. **Follow-up slices**: wire the change event into the Calendar week grid
   (work-allocation blocks), Board, Timeline, Habits, and the remaining
   dashboard widget types; add the widget region endpoint.
3. **Offline slice**: `ccApi.post` outbox interception + offline fragment
   strategy (see §6).

## 8. Scope boundaries (deliberately not done)

- No optimistic create/complete/delete (see principle 2).
- No client-side re-rendering of rows/lists from JSON — regions are always
  server HTML.
- No new dependency; `async_crud.js` is ~100 lines of plain JS.
- The mutation endpoints' JSON mode is additive; no existing route's default
  behavior or test changes.
