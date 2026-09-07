# Audit fixes — the gate between 1.9 and 2.0

Source: `documentation/reports/full-app-audit-2026-09-07.md` (read that file
for the actual issue detail — location, severity, why). This doc is just the
**order** to work through those findings in, one slice per session, per
`STATE.md`'s own slice-discipline convention. Nothing here is a new feature;
it's the cleanup gate before calling the app 2.0.

Ordering logic: quick security gaps first (cheapest risk reduction), then
the one high-impact performance fix, then the two accessibility items rated
high/medium severity, then mechanical/low-risk cleanup, then cosmetic
consistency work, then the two items saved for last because they're either
the biggest/riskiest (CSP migration) or genuinely optional polish.

1. ~~**Session revocation.**~~ **Shipped 2026-09-07** — see `STATE.md`'s
   entry of the same date. Landed as secret rotation (`auth.
   rotate_session_secret`), not a separate per-account epoch field as
   first sketched here: it reuses the exact mechanism `purge_all` already
   had for forcing a re-login, so there was no new payload format or
   schema to add. Called from both `setup_submit` and
   `change_login_password` whenever persisted credentials change.

2. ~~**Silent-misconfiguration guards.**~~ **Shipped 2026-09-07** — see
   `STATE.md`'s entry of the same date. Both landed slightly differently
   than first sketched here, for reasons found while implementing:
   - The non-loopback warning couldn't actually run "at startup" as
     originally phrased — the ASGI app has no visibility into what host
     uvicorn was told to bind to (systemd's unit, `python -m src.main`'s
     hardcoded `0.0.0.0`, and a bare `uvicorn` CLI invocation all bypass
     any config this app owns). Landed as a request-time check instead
     (`AuthMiddleware._warn_if_exposed`, `auth.py`), reading the real local
     socket address off `scope["server"]` — logs once, the first time a
     request actually arrives via a non-loopback interface.
   - The Radicale-devpass fail-startup couldn't fire unconditionally either
     — every production deploy that runs standalone (no Radicale server at
     all, the common case per `scripts/curodav-ctl`'s commented-out
     `CC_RADICALE_*` template lines) would hit the fallback and be broken
     by a hard, unconditional failure, contradicting this doc's own "no
     behavior change for a correctly-configured deploy" framing. Landed
     gated on the bridge actually connecting (`main.py`'s lifespan, `else`
     branch of the existing Radicale-optional `try`) — only a production
     deploy where the devuser/devpass pair is live and reachable fails to
     boot; an unreachable/absent Radicale still boots exactly as before.

3. ~~**N+1 query fix on every list render.**~~ **Shipped 2026-09-07** — see
   `STATE.md`'s entry of the same date. New `_attach_tags_bulk`/
   `_attach_contact_phones_emails_bulk` (one `IN (...)` query per table for
   the whole result set) replace every per-row `_attach_tags`/
   `_attach_contact_phones_emails` call inside a `list_*`/`_search_*`
   function (14 call sites across events/tasks/notes/contacts) — the
   single-row `get_*` functions keep the original per-row helpers, since
   there's no N+1 to fix there. Isolated to db.py, no schema/row-shape
   change, so the existing suite covers it as-is (1970 passed, no test
   changes needed).

4. ~~**Modal keyboard focus trap.**~~ **Shipped 2026-09-07** — see
   `STATE.md`'s entry of the same date. `static/modal.js` gained
   Tab/Shift+Tab cycling (`trapTabKey`) within `#modal-dialog` alongside
   the existing Escape handler; `#modal-dialog` also gained `tabindex="-1"`
   in `base.html` as a fallback focus target for the (rare) zero-
   focusable-element case. No test harness for JS behavior in this suite,
   so verification was read-through + the full suite staying green (no
   markup assertions broken).

5. ~~**Icon-button accessible names.**~~ **Shipped 2026-09-07** — see
   `STATE.md`'s entry of the same date. Landed as a single global script
   (`static/a11y_icon_labels.js`), not even the macro option sketched here
   — it scans for `[title]` elements with no visible text and no existing
   `aria-label`/`aria-labelledby` and copies `title` onto `aria-label`, so
   zero templates needed hand-editing and any future icon-only control is
   covered automatically. A `MutationObserver` re-applies it to
   modal/region-refresh-injected content with no per-feature wiring.

6. ~~**Touch-target + skip-link + contrast bundle.**~~ **Shipped
   2026-09-07** — see `STATE.md`'s entry of the same date. All five items
   landed as sketched: coarse-pointer bumps for `.color-swatch-current`
   (20->32px) and `.heatmap-cell` (11->16px); `.stepper-btn` got both a
   coarse-pointer width bump (30->44px) and `tabindex="-1"` removed from
   all 12 occurrences; a new `.skip-link` in `base.html` jumps to a new
   `#main-content` on `<main>`; `--fg-tertiary` darkened `#8e8e93` ->
   `#737378` in light theme only (dark theme already cleared AA contrast);
   `.week-overview-grid`'s breakpoint moved `700px` -> `720px`.

7. **Dead code cleanup.** Delete `db.py`'s `find_contact_by_name` and
   `list_task_label_names`, and templates `_labels_body.html`,
   `_widget_add_form.html`, `_task_relations.html`, `_event_relations.html`,
   `label_edit_modal.html` (the last three also carry retired CSS classes
   per the UI-consistency findings, so deleting them closes two report
   items at once). Before deleting `_task_heatmap.html`, actually check
   whether `task_detail.html` used to render a recurring-task heatmap and
   silently lost it (regression) versus the comment just being stale — do
   not delete on the assumption it's dead until that's confirmed.

8. **Settings page heading consistency.** Wrap `settings_holidays.html`'s
   and `settings_time_blocks.html`'s sections in the `.settings-group` +
   `.section-label` pattern `settings_general.html`/
   `settings_appearance.html`/`settings_data_maintenance.html` already use,
   instead of their current bare `<h1>`/inline-styled sub-headings.

9. ~~**Lower-priority UI consistency polish.**~~ **Shipped 2026-09-07** —
   see `STATE.md`'s entry of the same date. All three landed as sketched:
   `settings_data_maintenance.html`'s inline-styled "Needs attention" card
   now uses a new `.card-danger` utility class; the copy-pasted
   `.bulk-actions-bar` markup across `settings_holidays.html`,
   `settings_time_blocks.html` (Sleep + Leisure), and `labels_manage.html`
   is now one shared `_bulk_actions_bar.html` macro. `_filter_dropdown.
   html` turned out not to actually be a wrapper over `_widget_list_
   multiselect.html` (no include/extend relationship — a parallel
   template sharing CSS/JS by design, per its own header comment) — still
   earning its keep, left unchanged. Reached via a user-shared proposal
   to restructure `templates/` into a full layouts/components/widgets/
   pages split, evaluated and mostly declined (the codebase already has
   an equivalent, informally named) — see `roadmap.md`'s 2.0 section.

10. **Performance housekeeping.** Add `defer` to the 24 `<script>` tags in
    `templates/base.html:503-604` that don't need to block; confirm a
    dependency lockfile exists and pins exact versions (pyproject.toml's
    listed deps are all lower-bounded only). Quick, no risk, no user-facing
    change.

11. **CSP `unsafe-inline` migration.** `security_headers.py:52-62` — move to
    a nonce-based CSP for script-src/style-src. Saved for last on purpose:
    it's the largest and riskiest item (touches every inline script/style
    across templates), and the current state is an already-documented,
    accepted tradeoff rather than an active gap — worth doing before 2.0,
    but not worth doing first.

Not included above: items the audit report explicitly called "not a
finding" or "no action needed" (clean error handling, `detail_cover()`
macro adoption, `.icon-btn` naming consistency, existing DB indexes, etc.)
— those don't need a slice.

---

Items 12–15 below are a **second wave**, found 2026-09-07 during the same
UI-componentization discussion that produced item 9 (see `STATE.md`'s
item-9 entry and `roadmap.md`'s 2.0 section for that discussion's full
context) — a follow-up pass specifically comparing this app's CSS/template
conventions against a generic component-library checklist (Bootstrap's,
as a stand-in for "what does a mature UI system usually have") to find
real gaps, not just re-label existing ones. Independent of item 11 (CSP):
do them before or after it, in any order among themselves too — there's
no dependency chain, just the usual one-slice-per-session discipline.
Each item below is written to be actionable cold, without needing the
2026-09-07 conversation for context.

12. **Z-index: no shared scale.** `static/style.css` has ~50 raw
    `z-index` declarations (values from -1 up to 1000, no CSS custom
    properties, no documented ladder — contrast Bootstrap's own explicit
    dropdown/sticky/fixed/modal/popover/tooltip scale). **This is not
    currently broken** — checked before writing this item: `.skip-link`
    and `.drag-ghost` both sit at `z-index:1000` deliberately (the
    skip-link's own comment says it copied `.drag-ghost`'s value on
    purpose, "the app's highest existing layer"); `.command-palette-
    overlay` and `.cropper-overlay` both sit at `z-index:200`, above
    `.modal-overlay`'s `z-index:100`, also deliberately (each one's own
    comment explains it needs to render above an already-open modal).
    So today's stacking is *correct*, just correct via a dozen scattered
    comments cross-referencing each other instead of one source of
    truth — the risk is a future edit changing one value (e.g. bumping a
    dropdown's `z-index:150` for an unrelated reason) breaking an
    implicit relationship nobody re-checks at edit time, because there's
    nowhere that documents the relationship exists.

    Scope: (1) grep `style.css` for every `z-index` declaration and group
    the found values by actual visual layer (base content -> drag/reorder
    handles -> dropdown/menu panels -> sticky nav/tabbar -> modal overlay
    -> stacked-above-modal overlays [command palette, cropper] -> toast/
    skip-link); (2) introduce CSS custom properties for each layer (e.g.
    `--z-dropdown`, `--z-modal`, `--z-modal-stacked`, `--z-toast`) next to
    the existing token block (`style.css` section 1, "Tokens"); (3)
    replace the raw numbers with the new variables, preserving every
    existing documented relationship (don't just sort-and-renumber — read
    each comment first, some orderings are load-bearing); (4) keep the
    explanatory comments, they're still useful, just point them at the
    variable name instead of a bare number. No visual change expected if
    done correctly — this is a refactor, not a redesign; the full test
    suite won't catch a stacking regression (no CSS-rendering harness in
    this suite, per `STATE.md`'s recurring note), so also do a manual
    check of: opening a modal, then the command palette from inside it;
    dragging a widget/task while a dropdown is open; focusing the skip
    link.

13. **Icon-button edit/delete pair, duplicated 4x.** Same shape as item
    9's `.bulk-actions-bar` extraction, not caught in that pass:
    `settings_holidays.html`, `settings_time_blocks.html`,
    `labels_manage.html`, and `_labels_table_body.html` each repeat an
    identical block —

    ```jinja
    <div class="action-buttons">
        <a href="{URL}/edit" class="icon-btn" data-modal title="Edit {X}">{{ icon('edit', 'icon-sm') }}</a>
        <form method="post" action="{URL}/delete" data-confirm-sheet="Delete &quot;{NAME}&quot;? {MESSAGE}">
            <button type="submit" class="icon-btn danger" title="Delete {X}">{{ icon('trash', 'icon-sm') }}</button>
        </form>
    </div>
    ```

    — differing only in the edit/delete URLs, the `title` noun, and the
    confirm-sheet message. Extract to a macro (new `_row_action_buttons.
    html`, following the exact convention `_bulk_actions_bar.html`
    established in item 9: header comment explaining what it replaces and
    why, `{% macro %}` + named params, imported via `{% from ... import
    ... %}` at each call site) — params should cover: edit URL, delete
    URL, the noun for `title`/aria text, and the confirm-sheet message
    (which varies enough per-caller — e.g. labels' "clears usage, not a
    real delete" wording — that it must stay a parameter, not be
    hardcoded). Grep `tests/` for `action-buttons`/`data-confirm-sheet`
    plus each of the 4 templates' own delete-button `title=` text before
    changing anything, same as item 9's process.

14. **Empty-state table row, duplicated 5x.** `_labels_table_body.html`,
    `labels_manage.html`, `settings_holidays.html`, and
    `settings_time_blocks.html` (twice — Sleep and Leisure) each repeat:

    ```jinja
    <tr id="empty-state-row">
        <td colspan="5" class="text-muted" style="font-size: var(--text-footnote);">No {X} yet</td>
    </tr>
    ```

    — differing only in the `colspan` (check each call site, don't assume
    it's always 5) and the message text. Extract to a macro alongside
    (or inside) `_bulk_actions_bar.html`/`_row_action_buttons.html`'s
    file, or its own `_empty_state_row.html` — whichever this app's
    existing convention favors for a partial this small (check how
    `_label_pill.html` — a similarly tiny one-line macro — was scoped,
    and match it). **Out of scope, deliberately:** `settings_data_
    maintenance.html:191`'s "No backups yet" text is a different shape
    entirely (a `<span>` in a plain list, not a `<tr>`/`<td>` in a table)
    — don't force it into this macro just because the copy reads
    similarly; that would fix a naming coincidence, not real duplication.

15. **Stale roadmap claim: Tasks-table pagination.** `roadmap.md`'s 1.9
    section says pagination "shipped 2026-08-15: `GET /tasks?page=&limit=`
    paginates the Table view's Open section." Confirmed via `git log`
    this is no longer true: commit `2162403` shipped it, but the later
    `d86a34d` ("Major rework session, 2026-08-28") retired it as a
    documented *consequence* of un-conditionally grouping the Tasks table
    (Project -> Habits -> Unassigned -> Completed) — that commit's own
    message says so explicitly ("pagination retired as a consequence").
    Not a bug, not something to restore — the grouped-table design this
    app settled on doesn't have an "Open section" to paginate anymore.
    Purely a documentation staleness fix: update `roadmap.md`'s 1.9
    section to stop claiming a retired feature is shipped (either drop
    the claim or note it shipped-then-was-superseded, matching how this
    doc already handles superseded decisions elsewhere). Two-minute fix,
    but do it before 2.0 ships — a roadmap that claims dead features
    exist is exactly the kind of thing that wastes a future session's
    time re-discovering this same dead end.
