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

5. **Icon-button accessible names.** Add an `aria-label` fallback (ideally
   a shared macro/JS default keyed off the existing `title`, not 30
   hand-edited templates) covering `_task_row.html:144`,
   `_habit_row.html:115`, `labels_manage.html:75`,
   `_labels_table_body.html:28`, `settings_holidays.html:61`,
   `settings_time_blocks.html:63,125`, and the widget/picker/relation-row
   templates listed in the audit. Mechanical, many touch points, low risk.

6. **Touch-target + skip-link + contrast bundle.** One CSS-mostly slice,
   same shape as the 2026-09-04 touch-target session: coarse-pointer size
   bump for `.color-swatch-current` and `.heatmap-cell`; fix `.stepper-btn`
   (both its missing coarse-pointer size and its `tabindex="-1"` removing
   it from keyboard tab order); add a skip-to-content link in `base.html`;
   darken `--fg-tertiary` (light theme) or restrict it to large/bold text;
   align `.week-overview-grid`'s `700px` breakpoint to the app's standard
   `720px`.

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

9. **Lower-priority UI consistency polish** (optional — doesn't block 2.0,
   but bundle if doing a cleanup pass anyway): promote
   `settings_data_maintenance.html`'s inline-styled "Needs attention" card
   to a `.card-danger`/`.card-tinted` utility class; extract the
   copy-pasted `.bulk-actions-bar` markup (three-plus copies across
   `settings_holidays.html`, `settings_time_blocks.html`,
   `labels_manage.html`) into one shared partial; confirm whether
   `_filter_dropdown.html`'s class-renaming wrapper over
   `_widget_list_multiselect.html` is still earning its keep.

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
