# Changelog

All notable changes to this project are documented here, one entry per
tagged release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [4.4.5]

- Fix: the first Radicale sync no longer runs before the app opens its port. With a working Radicale and many published items it could take minutes, so the deploy health check failed and `curodav-ctl update` never finished. It now runs in the background thread alongside normal use.

## [4.4.4]

- Radicale: requests to the server time out after 15 seconds, so a hung Radicale can no longer block the background sync and delay shutdown or a deploy's health check.
- Phones: the header strip is 46px tall (was 56px, or about 72px without a banner) and always as tall as its tallest control, so a wrapping row grows instead of clipping; pages without a banner use the same single row.

## [4.4.3]

- Radicale: when the connection fails at startup (wrong credentials or server down), the background sync no longer starts or claims to run, and a rejected login logs one clear line with the URL and user instead of a traceback.
- Fix: events, tasks and contacts with `::` or other unsafe characters in their ID (birthday events) are stored under a safe file name, so Radicale accepts them.
- Fix: a repeating task with no start or due date no longer publishes an invalid repeat rule.
- Fix: in the four-week and month views, holding an event or bar for a moment lets you drag it to another day on a phone; a swipe still scrolls.

## [4.4.2]

- Repeating events: choosing "Apply changes to" comes first in the edit form, and while it says "This event" the recurrence, holiday calendar and weekend fields are locked, so saving one occurrence never changes the series. Changing the rule with "This and following" or "All events" asks for confirmation, since it rebuilds the affected events.
- Fix: changing the rule of "All events" from a later occurrence no longer deletes the earlier ones; the series keeps its first date.
- Holidays: adding, changing or removing a holiday in Settings, or changing a series' weekend or holiday settings, now updates its existing events (events moved or deleted by hand are left alone).
- Fix: extending an open-ended series no longer copies a single renamed or relocated occurrence into the new events; a day shift that would break an every-other-week rule is refused.

## [4.4.1]

- Entries: every section (the short text, each field of the kind, and each extra section) has one bibliography reference with its pages, or the page's address for a web page, shown under its text in the entry view. The general reference list stays only on entries that already have one, and the citation view still lists the entries that cite it.

## [4.4.0]

- Notebook figures: the image block is now a figure with a grid of up to 12 images in 1 to 4 columns, mouse resize and drag to reorder, a caption, source line and optional "Figure N." numbering edited in the block menu, and lazy-loaded downscaled images. Old image blocks load as one-image figures; Markdown export includes the caption.
- Notebook tables: the + button is replaced by hover strips on the bottom and right edge; column, row and block menus are compact icon toolbars with short dropdowns; columns wrap between words instead of splitting them.
- Notebook menus: the block menu uses icon rows for alignment, heading level, divider style and Duplicate, Move and Delete; the endnote menu is icon-only; the wikilink picker no longer leaves a placeholder behind.
- Timeline: a color per timeline, the line stays between the circles when dates are shown, dates share one column width.
- Editor fixes: a heading's handle sits level with its text; dividers are as tall as an empty block with spacing; menu changes on dividers, quotes, callouts and timelines now save and undo as one step.
- Entries: each reference is one row with a single-choice citation dropdown and its start and end page; a + button adds another row. A reference to a web page citation takes the page's address (http or https) instead of page numbers and shows it as a link.
- Banners: the header banner is exactly 12:1 at every desktop width (no 56 to 88px clamp); on phones it keeps a 56px minimum so the controls fit.
- Notebook images and saving: figure pictures are kept once in an image store (a 15-photo note went from 7 MB to under 300 KB and from a 6.7 second save to 0.3 seconds); entry detection is about 45 times faster; saves send nothing when nothing changed and happen when the page is left. Existing notes convert when opened.
- Notebook consistency: one nine-color palette for inline color, tables, quotes and timelines; one wikilink picker for the toolbar button, the slash command and `[[`; alignment only in the block menu; one icon-row style across notebook menus.
- Editor: the dotted drop line shown while moving a block no longer stays behind after the drop, a cancelled drag or a mouse released outside the window.
- Tests: a green run leaves no files in the temp folder.

## [4.3.1]

- Banners: the header banner is 12:1 (the crop shape), at most 88px and at least 56px tall; header icons and buttons line up and stay on one row on phones.
- Entries: each reference links to its citation and can carry a start and end page (migration 17).
- Citations: a view modal; the main author sits near the top of the edit modal, other authors at the bottom, with labelled first and last name boxes. Entry and citation view modals share one sectioned layout.

## [4.3.0]

- Mobile: the header and bottom navbar stay put on every page and only the content scrolls. Task rows and the Sleep & Leisure table no longer overflow. In the planner, a touch hold of 250 ms starts moving an event, and a swipe still scrolls.
- Settings: Taxonomy & Data is split back into Labels, Groups, Projects and Holidays pages; transaction tags moved to Finance accounts and frontmatter fields to Notebook settings, where Entry types and fields share one table card with a toolbar and view dropdown. Data & Maintenance is reorganised into Backups, Export and import, Cleanup, Connection and a Danger zone.
- Logs: one thin card per distinct message with a count and a copy button; each filter shows only its own category.
- Projects: an "Auto labels" field applies labels when the project is added to an item, live in the modal.
- Contacts: Relations shows a repeating event as one row with its rule, next date and more dates.
- Published lists: "everything" now includes habit tasks and leaves out archived and draft contacts.
- Banners: crop ratio is 12:1 and the header height follows it, between 56px and 88px.
- Terminology: one Standard / Playful setting (replaces two); playful wording now also covers empty states, some toasts and the greeting.

## [4.2.0]

- Notebook: notes now live in generated folders (by project, then label, plus Unfiled), with gradient folder icons, a Contacts-style list per folder, pinned notes on the Notebook home, and a Back button. Folders sort by date created by default. A note has at most one label and one project (migration 10 merges extras and keeps a report).
- Weekly Journal: one note per week (`2026-50`), grouped by year, with a week strip always visible.
- Entries: glossary terms became entries with an editable kind (Settings > Notebook), per-kind default fields and extra boxes, dotted links with hover cards and a view modal, and a sidebar list grouped by kind.
- Citations: more complete academic fields, a Chicago and Academia Română format setting, a folder-style list with search, filters and sort.
- Editor: `[[` and slash wikilinks with a better picker, markdown shortcuts on already-written text, a manual Timeline block (rich title and description), more spacing between blocks, better arrow keys in tables and lists, Markdown export, and note-level undo kept.
- Tasks: a compact read-only list grouped by project, then label; the status dropdown is the only inline editor. Transactions no longer have a status (all are posted).
- Fixes from the audit: one empty-state component, toasts for errors, single modal window, server-side input validation, a friendly 404 page, an error log with a live view in Settings > Logs, row menus working after in-place refreshes, and the Entries header staying on one row.

## [4.1.2]

- Fixed the Add new modal: changing the data type from its dropdown did not switch the form, because the open dropdown lives outside the modal. A test now covers it.

## [4.1.1]

- Repeating events are now real events: every occurrence is its own event in a series, so each one can be edited, moved or deleted. Edit and delete ask whether the change applies to this event, this and following, or all. Dragging an occurrence moves only that one, with a toast offering to move all future ones. Open-ended series are extended automatically each day.
- Migration 9 turns every existing repeating event (with its cancelled and moved occurrences) into a series of real events, with a copy of the database made first. Events that arrive from CalDAV or an imported file become single events.
- Planner: the unscheduled count is gone and the All day sidebar rows show a color dot and the title.
- Transactions: the ledger is plain rows (no section headings or fills), more compact, with edit icons on hover.
- Notebook: pills on the Browse page are bold; a small space after headings.

## [4.1.0]

- Transactions is now a monthly ledger: a month mover and an accounts filter in the header, then income, total income, expenses, total expenses, profit and savings. Transfers move money between accounts without appearing in the table. The Overview page, labels, groups and projects on transactions, and the other filters are gone; tags stay.
- Notebook editor: minimal rounded table grips, Alt+arrow cell moves, tables fill the writing area; distinct heading sizes, numbers only in headings and more space before them; delimiter as tall as a text line; compact popover with one font and icon size; `:` icons as inline text glyphs; typing `[` opens a ranked document picker (same project, same label, then A-Z); Markdown typed live (bold, italic, strike, code).
- Selected blocks can be deleted with Delete and dragged as a group by a grip beside the selection; dragging across list items selects the list block.
- Planner and calendar: items that have ended turn gray by the current time; the all-day row moved into the planner sidebar as a second view; fast double clicks on next and previous week no longer repeat the same week.
- Agenda rows: icon, title, and day and hour at the far right, no label pill, past items gray.
- Glossary: one-line description column, custom titled text sections per term (not shown in the sidebar), references limited to citations and searchable, editor sidebar numbered, alphabetical and clickable.
- Document properties: labels and project as two dropdowns on one row; Kind as a dropdown.
- Quick add: a Type dropdown beside the title replaces the tabs; date and template rows are full width.
- Mobile: Add new in the sidebar drawer; dropdowns and sheets no longer hide behind the bottom bar; dark colors for the installed app's system bars.
- Fixed pending transaction pickers on added rows and hid empty work sessions in the task view.

## [4.0.2]

- Removed a stray package file that was committed with 4.0.1 by mistake.

## [4.0.1]

- Finance: Duplicate on every transaction row; amounts colored; dates as "05 Apr"; the type shown as an icon left of the description; accounts as pills with a short abbreviation set in the account form, used throughout.
- Finance overview in two columns: one 6-month line chart (savings on its own right axis, income, expenses, profit; empty lines hidden), a spending pie, and an income pie when there is more than one income label. Average spending and cash runway shown when there is no income.
- Transaction tags are free-standing (no group) and carry a color and icon, chosen in the Look picker and shown as pills.
- The Look picker is a color row above a scrollable category sidebar and icon grid, covering the full Lucide library with search.
- Light theme uses soft pastel label colors; eight new colors (coral, amber, sage, sky, violet, plum, rose, sand); thin themed scrollbars everywhere.
- Fixed: the page scrollbar that came back on pages that scroll inside themselves (the icon library sheet was visible), bulk select in Taxonomy & Data, and scroll position lost on partial region refreshes.

## [4.0.0]

- Notebook templates: frontmatter cleanup, a Templates page, and a New note modal with a template picker (type, labels, project and frontmatter set at creation; also a Note tab in the sidebar New modal).
- Personal finance: accounts in Settings, transactions in quick add, overview and Transactions filters (period, label, custom range) in the header bar, CSV import, tags, and a finance export in Settings.
- Scheduled transactions: pending one-off and recurring transactions, linkable to a task, with type-dependent account rows.
- Import and export: notes as Markdown (endnotes as footnotes), finance, citations and glossary, with a supported-data table in each dialog.
- Event edit modal reworked: full-width recurrence, Format on its own row, "This occurrence" as date and time.
- Input laws applied app-wide (labels, one font size, no spinners, equal heights, switches); full Lucide icon library with a 16px minimum.
- Code health: db and dashboard router split into packages, numbered migrations, backend core tests, size-limit test.
- Notebook Browse keeps the page header title weight.

## [3.9.2]

- View modals are read-only: every part is a header with its information below it, no card styling and no editing. Event occurrences are cancelled, moved or restored from the event's edit modal.
- Work sessions are rows in the edit modal (title, hours, difficulty, start and end), saved with the form's Save; the view modal only lists them.
- Archive and Restore are one icon-only button in the edit modal's footer, and nowhere else.
- A contact carries one label and one project; contacts are grouped by label.
- Groups & Labels widget: no deadline, no progress bar; one "Attention needed" pill when a task is due this month.
- Boxes that share a row in a modal never wrap.
- The date picker stays open when you change month.

## [3.9.1]

- The event form's Format dropdown (In person, Online, None) is visible again, with Location or Meeting URL beside it.
- Recurrence Ends has an "At project's deadline" option when the chosen project has a deadline.
- The contact avatar in the view modal is 70% of the banner height with a 20% top margin.

## [3.9.0]

- Settings: every subsection is a page again (Taxonomy & Data stays), Notebook and Frontmatter are one page, the Database, Backup and Sync cards live in Data & Maintenance, and the top of Settings shows the app banner with its version and release title.
- Release commits and GitHub releases carry a short, catchy title; the Settings banner shows it.
- Icons inside pills are 1.2em.
- Notebook: the sidebar shows only the add button for its current view; the inline toolbar icons match in size; `:` opens the icon picker at once and the icons sit level with the text; block Color on text blocks colors all its text like the inline tool, with the same swatch grid; the Type column shows the type's icon, color and case.
- A dropdown with one pick shows that item's name instead of "1 selected".
- README and SECURITY brought up to date for the Notebook, Secretariat and password recovery.

## [3.8.0]

- Settings > Taxonomy & Data: labels, groups, projects and holidays in one table with a view dropdown in the header; switching swaps only the rows.
- Labels, projects and groups can be duplicated into a pre-filled create modal, and labels and projects can be archived and restored from the row.
- UI rules audit: one search component, custom dropdowns replace native selects, modal footers, core tests.
- Contact photo: the avatar in the contact modal opens the upload modal.
- Sections pages hide empty sections and no longer show New document; unscheduled work rows fit two lines.
- Secretariat section headings are larger and have no icon.
- Calendar and contacts label filters offer groups first, then labels; picking a group filters by all its labels.
- Agendas show a recurring event once, at its nearest date, with a repeat icon and a tooltip counting the remaining occurrences.
- The phone status and navigation bar colors match the page background in both themes.

## [3.7.0]

- Notebook Browse is a table with load more, bulk edit and bulk delete, and filters that toggle on and off.
- Editor: inline tools, text and background color, a More menu, markdown paste and block color and duplicate. Undo loads the saved document first, updates in place and keeps its history between sessions.
- Endnotes are created from the inline toolbar, are rich text, and each has a menu to generate a citation.
- Tables are a first-party spreadsheet-like block: merged cells, header row and column, sorting, cell colors, simple formulas (text, joining with &, comparisons, IF, AND, OR, NOT, ranges) and markdown, TSV and CSV paste and export.
- Mentions: `@` for contacts, `$` for tasks and events and `:` for icons, in text, tables and formulas.
- Glossary: an Auto-fill button attaches every term found in the document.
- Properties: each Settings > Notebook field gets an input for its type and is validated when saved.
- Search contents: find and replace across notes with a preview first, a per-note choice and a warning toast when more than five notes change.
- One rule for floating menus and bars: they close on an outside click, Escape, or when another opens.
- Password recovery: the recovery token is no longer shown in Settings. `curodav-ctl token` prints it (`--new` replaces it) and `curodav-ctl password-reset` uses it; a new password needs at least 8 characters.
- Touch devices: long-press a row to select it instead of using checkboxes, and the phone status bar follows the light and dark theme.

## [3.6.0]

- Home, groups and labels can each show as the Secretariat, Sections or a dashboard. Home defaults to the Secretariat, which hides empty sections, lists events today, tasks due today and this week on the left and other reminders on the right, shows label pills, and keeps completed tasks until the day ends.
- Work sessions have a title, an hours estimate and a difficulty. The Planner has an Unscheduled work sidebar.
- Contacts have a pseudonym, a role and an honorary title, and each published contact list chooses which name it syncs.
- Task and event details describe repeats in plain words instead of the raw rule.
- Label views list habits due today in the agenda, show eight items, and have an Archive button.
- `./run.sh skipauth` skips the login for a local run only, and refuses to start over a stale server.
- Date-dependent tests read the injected clock.

## [3.5.0]

- Settings: General, Your Profile, Notifications, Appearance, Data & Maintenance and Notebook open as modals that stay open while a setting saves. The Database, Backup and Sync status cards now sit on the main Settings page. Notebook settings split into Notebook (sidebar layout) and Frontmatter (custom fields).
- Bulk select: buttons are icon-only with tooltips, and an Edit button changes the same fields on every selected row (tasks: status, dates, repeat, labels; contacts: label, organization, title; labels: color).
- Habits and Contacts share one section heading; cards share title, body and footer parts; amount habits use the same check button as other habits and show their count in the row.
- Contacts field: type a new name to create a contact straight from a task or event.
- Password recovery: Settings shows a recovery token, and `curodav-ctl password-reset` (or `scripts/password_reset.py`) resets the login with it. Local dev builds can clear the stored login with `--dev-clear`.
- Tests: files renamed by feature, rules about assets and templates moved to core tests, and tests that asserted on CSS, script or template text removed.

## [3.4.0]

- Shared interface components: round radio and square checkbox, named input
  components for every form control, one empty-state component, one pill
  look, a shared drag-and-drop upload zone, and icon-only header buttons
  with tooltips. Placeholder text is gone from forms (search boxes use a
  magnifier icon instead); the contact form's address parts have labels.
- Dropdowns: search turns on automatically above seven items, and a long
  dropdown that can add items merges search and add-new into one box.
- Modals keep a back-stack: Escape and Cancel walk back through the modals
  you opened.
- Contacts: a new contact is a hidden buffer contact from the moment the
  form opens, so its photo can be uploaded and cropped before saving; the
  photo can be re-cropped later from the upload modal. Tasks and events have
  a Contacts field, and a contact lists the tasks and events it is involved
  in.
- Event and accent colors are checked against both themes for readability;
  dark-theme fills are lighter, with dark text.
- Test suite reorganized (dashboard, auth and offline-sync areas) with new
  core tests for the interface rules.

## [3.3.0]

- Added Notebook, a new block-based note-taking module (Editor.js, vendored
  with no CDN dependency) -- a top-level nav destination with its own All
  Documents view, organized through the existing Groups/Labels system
  (not folders): a Notebook dashboard widget lists a label/group's
  documents, with a "New document" action that pre-attaches the current
  label and opens straight into the Editor. Document content autosaves;
  title and delete are plain, no-JS-required forms.
- Removed the old quick-capture `notes` feature outright (no migration --
  nothing had real data in it) -- absorbed into Notebook instead. Its
  router, table, and search/quick-capture/command-palette integration are
  gone.

## [3.2.0]

- Command palette and full search page: past events no longer clutter the
  default empty-query browsing view (`exclude_past_events`, whole-day
  cutoff) -- a real typed query still surfaces them, and the relation-
  picker mode (for_task/for_event) is untouched.
- Command palette rows and search-page results collapsed from two lines
  to one: title and subtitle now sit on a single flex row with a "·"
  separator, truncating the title first instead of always wrapping to a
  second line.
- Dropped the `.main-shell-body` `margin-bottom:6dvh` outright (and the
  Dashboard-only `--flush` modifier that had opted just Dashboard out of
  it) -- the same "veil that hides content" symptom reported for
  Dashboard on 2026-09-24 was confirmed across Tasks/Contacts/Notes/
  Habits too.
- Removed the top border between contact list sections (label groups).

## [3.1.0]

- 24 more flair ids: 18 real event-type icons (bills, delivery, doctor,
  flight, hotel, interview, online classes, party, photography, shopping,
  studying, trip, tv, video call, vote, ...), `restaurant` split out of
  `dinner` as its own id, and 8 scenery/color backgrounds (university,
  museum, mountain, sea, sky, wood, ...).
- Months and seasons are matched by an object's own due/start DATE, not
  by keyword against its name -- a new month tier (`db.MONTH_BANNER_
  SCOPES`, one tier more specific than the existing season tier) joins
  the app's existing season fallback. Both tiers now also read an
  operator's `flairs_dir` as their default photo source (drop `july.jpg`/
  `summer.jpg` in directly, same as any other flair), falling back from
  an explicit banner-editor upload on that scope.
- A task/event's own flair match now also tries its description, as a
  backstop when the title alone matches nothing usable -- title stays
  the dominant signal, description never outranks a real title match.
- New Settings > Flairs page: shows how many of the ~106 known flair ids
  currently have a photo configured, and a bulk-upload dropzone accepting
  a `.zip`, a whole folder, or several photos at once -- a zip's contents
  are smart-filtered by filename at any depth, with a result summary
  reporting anything skipped and why.

## [3.0.0]

- Habit/task "mark done" checkboxes consolidated onto one shared component:
  the Habit Check-in widget, the Agenda widget's habit and task rows, and
  the Calendar day-grid's all-day habit chips all now share the same
  toggle/quantity/avoid form markup, sizing, colors, and hover styling
  instead of four hand-rolled copies.
- A checked-off task or habit stays visible (checked, struck through) for a
  short grace period instead of disappearing the instant a widget re-fetches.
- Fixed a habit check-in not refreshing sibling Dashboard widgets that
  also showed the same habit (e.g. Habit Check-in staying stale after a
  check-in from the Agenda widget) until a full reload.
- Widget row title size/weight, checkbox sizing/hover, and the week
  strip's "today" cell fill unified across widgets.
- Unscheduled Work row tightened; the "Labels in this group" widget always
  renders as a card grid now (Groups & Labels style), with square card
  sizing and padding fixes.
- "Labels in this group" is no longer a separate, always-pinned full-width
  widget. A group's page now gets the same 25/50/25 layout Home has --
  quarter-width Today, half-width At a glance/Upcoming stack, and its own
  label list in a quarter-width third column instead.
- Edit label / Edit group are icon-only square buttons now, pinned to the
  right edge of the page header's actions row.
- Contacts/Labels bulk delete now refreshes the page's live region in
  place instead of a full reload (`CCBulkSelect`'s new `changeType`
  option, same claim protocol every other async-CRUD mutation uses).
- Tasks table label pills link to the label preview again, now that the
  Labels cell is a plain read-only cell rather than an editable dropdown
  trigger a link couldn't nest inside.
- Event markers everywhere (label preview modal, label/project Agenda
  cards) finished moving from a plain color dot to a colored `calendar`
  icon (`widget_event_dot` renamed `widget_event_icon`).
- Widget "Limit" field's default and its `0` (no limit) cap both lowered
  from 20 to 8.
- Fixed a crash opening a group's page (`TypeError: 'NoneType' object is
  not iterable`) from an incomplete `_filtered_tasks` edit.

## [2.9.0]

- Docker Compose deploy path (`deploy/docker/`): an alternative to
  `curodav-ctl`'s systemd install, app + Radicale as containers.
- README: app icon and screenshots, a new Docker Compose install section.
- Fixed `uv.lock`'s workspace manifest, stale since the v2.8.0
  `command-center` -> `curodav` rename -- `uv sync --frozen` (used by both
  the new Docker build and `curodav-ctl`'s own install/update) was failing
  outright with "Missing workspace member `curodav`".

## [2.8.0]

- Settings notifications reworked onto its own dedicated page; accent-color
  and banner pickers redesigned.
- Unscheduled Work panel redesigned, plus a "Labels in this group" widget.
- Row hover, header icons, and habit check-in styling standardized to one
  shared token across the app.
- Default banner/avatar photos restored as an operator-supplied, keyword-matched
  "flairs" system instead of bundled copyrighted images (see the Wiki's
  [Flairs](https://github.com/istorie-petru/curodav/wiki/Flairs) page).
- Icon set reverted to Lucide stroke icons.

## [2.7.0]

- Habits: amount habits, one Notifications settings page, per-habit reminder
  time, compact rows with a history panel, an approved edit-modal redesign.
- Calendar/Labels/flat-UI audit fixes merged: contrast, headers, now-line, day
  popover, agenda, label rail titles and icon fallback, banner icon chip.
- Typed date/time fields replace the old range picker app-wide.
- Contacts: single label per contact, grouped rows, a real archived flag.
- Groups: rename + member checklist, a dedicated dashboard widget.

## [2.6.0]

- Habits rebuilt as a dedicated feature: its own page, detail view (month
  calendar, day notes, log-a-day), amount units and avoid habits, vacation/
  pause, strength score and insights.
- Web Push notifications: VAPID subscriptions, a reminder scheduler for
  events/tasks/habits/sleep, configurable reminder types and a morning digest.
- Labels reorganized into modules: one page per label, old URLs redirect,
  text groups get their own pages, label preview modal.

## [2.5.0]

- Relative-date shorthand (Tmw/Yest), the card UI model removed app-wide in
  favor of flat pages, icon set swapped to Material Design Icons, design
  tokens tightened.
- Responsive tables via container queries; image editor aspect-ratio locking.
- Habits: first slice of the current model (a shared habit view over a
  habit-labeled task, schedule-aware streaks, a visible heatmap).

## [2.4.0]

- Contacts and label-color polish across task/event dots.
- Modal header restyle: circular close button, banner carries into edit.
- Labels table: grouped-row coloring and inheritance fixes.

## [2.3.0]

- Deploy hardening: `curodav-ctl` install/update reliability fixes, Radicale
  auth rate-limited via nginx.
- "Spaces" reworked into a labels-as-membership model (superseded again in
  2.6 by the label-modules rework).
- Published Lists gained negative (exclude) label filtering.
- Contact photos served transcoded to WebP regardless of source format.

## [2.2.0]

- `curodav-ctl` automates the DAVx5/Radicale public-access setup end to end.
- Published Lists' public URL fixed.

## [2.1.0]

- Settings reorganized: a merged Data & Maintenance hub, holidays and sleep/
  leisure time blocks moved onto the grouped-list + modal pattern.
- Kanban drag-and-drop, a reworked Calendar/Planner, Contacts field parity
  work, the bulk-actions bar relocated out of table headers.

## [2.0.0]

- The audit-fixes gate that closed out the 1.x series: a large pass of UI/UX
  fixes across Calendar, Dashboard, banners, published lists, and Settings.
- Deploy scaffolding for public CalDAV/CardDAV access (Cloudflare Tunnel +
  Radicale + nginx).
- README rewritten for first-time installers.

## [1.9.0]

- Tasks table pagination.
- The Schedule module and its University Space section removed entirely
  (superseded by ordinary recurring Calendar events with odd/even-week
  support, shipped in 1.6).

## [1.8.0]

- Offline-first PWA: installable app shell, a local IndexedDB mirror and
  write path, and tombstone garbage collection for the sync engine.

## [1.7.0]

- Information architecture rework: dedicated Today and Week planning
  surfaces (both later folded back into the Dashboard and Calendar once
  those covered the same ground — see 1.9's notes and the Wiki's
  [Feature Map](https://github.com/istorie-petru/curodav/wiki/Feature-Map) page).

## [1.6.0]

- Configurable recurrence terminology, manual per-occurrence recurrence
  exceptions, generalized holiday calendars, classes linked as project
  labels.

## [1.5.0]

- The deadline-vs-work-allocation distinction: a task's due date and its
  scheduled work sessions are explicitly separate concepts.

## [1.4.0]

- Work allocations (scheduled work sessions) and the project week calendar.

## [1.3.0]

- The project-enabled label stack: a project is a label with a date range,
  not a separate entity.

## [1.2.0]

- The task model settled: flat tasks plus work allocations, subtasks
  removed outright.

## [1.1.0]

- Virtual and derived task states (later replaced by the simpler, purely
  temporal derivation described in the Wiki's
  [Feature Map](https://github.com/istorie-petru/curodav/wiki/Feature-Map) page).

## [1.0.0]

- First stable release of the FastAPI webapp as the sole client: home
  dashboard, calendar, tasks, contacts, habits, and the universal label
  system.
