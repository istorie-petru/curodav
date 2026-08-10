# Plan: Webapp usability pass + DAVx5 mobile rollout

**Status:** Open, not started · logged 2026-08-02
**Feature areas:** [`../features/design-system.md`](../features/design-system.md), [`../features/tasks.md`](../features/tasks.md), [`../features/calendar.md`](../features/calendar.md), [`../features/dashboard.md`](../features/dashboard.md)
**Supersedes/consumes:** this doc is the implementation schedule for two already-written analysis docs -- [`webapp-action-pipelines-audit.md`](webapp-action-pipelines-audit.md) (Phase A below) and [`webapp-ui-design-direction.md`](webapp-ui-design-direction.md) (Phase B below). Neither of those is duplicated here; read them for the *why*, this doc is the *what, in what order*. Once each phase ships, fold its outcome into `../features/` and delete or stub the corresponding source doc per [`README.md`](README.md)'s workflow.

Three independent workstreams, scoped together because they were all requested in the same conversation, but they can ship on separate timelines and none blocks the others:

- **Phase A** -- pipeline/interaction fixes. Checked against current code before writing this plan: **already fully shipped**, ahead of its own source audit's dateline. Kept here as a record of that check, not a to-do.
- **Phase B** -- visual/design rework. Also checked against current code: 3 of 5 original items are done; 2 real gaps remain (pagination/collapsible sections; a project's own Databases section + the larger projects-as-widgets question).
- **Phase C** -- DAVx5 mobile access via a public server + reverse proxy. Genuinely new, unbuilt -- infra, not app code, separate from A/B entirely. (Originally also framed as unblocking a separate desktop app's CalDAV bridge sharing the same Radicale -- moot since `desktop/` was deleted 2026-08-07 as the final phase of `label-space-rework.md`; `webapp/` is now the sole client, so Phase C is just about mobile access via DAVx5.)

---

## Phase A -- Pipeline/interaction fixes

**Status: already shipped.** Source: `webapp-action-pipelines-audit.md`'s "Suggested priority order," logged 2026-08-01. Before writing this plan as a to-do list, checked the current code directly rather than trusting the audit doc's dateline, since a lot can change in a day on this project. Verified against the actual templates/JS, not the audit's prose:

1. **Task/Event delete -> real undo or a specific confirm message.** Done -- `tasks_list.html`/`task_detail.html` split delete into `data-delete-undo` (plain task) vs. `data-confirm-sheet` with an explicit subtask-count warning (task with subtasks); `event_form.html` has `data-delete-undo` too. Code comments cite this exact audit doc as the source.
2. **Redundant "Mark done" checkbox.** Gone -- the checkbox in `tasks_list.html`'s row is now `row-select` (bulk-selection, a different, newly-added feature -- see item 5), not a duplicate status toggle. Status is set via the pill `<select>` only, through `tasks_table.js`'s fetch-based `update-field` path.
3. **Calendar/Schedule drag-to-move reload-on-success.** Fixed -- `calendar.js`'s `end()` now POSTs to `/events/{uid}/reschedule` optimistically and only reverts + toasts on a non-OK response (comment block explicitly documents the before/after and why). Not independently re-checked in `schedule_grid.js` line-by-line, but its own comment references the same fix.
4. **Dashboard "Add widget" above the fold.** Done, and further along than the audit anticipated -- `_widget_workspace.html` (new, 2026-08-02) puts the widget grid, live preview, and Add-widget disclosure in one shared partial reused by both Home *and* a new "Space" (project-group) detail page, not just moved higher up Home's own footer.
5. **Lower-priority items.** Also done: a quick-add form (`#quick-add-form`) sits above the Tasks table; the habit check-in widget (`habit_checkin.js`) is fetch-based, not a full-reload form; a full bulk-select/bulk-action system (shift-click, drag-paint, bulk status/list/tag/delete) was added on top of the audit's own "no bulk actions" finding.

No action needed here. Leaving this section in the plan (rather than deleting it) as the record that Phase A's source audit was checked against real code before Phase B/C work started, per this project's own stated verification standard.

---

## Phase B -- Visual/design rework

Source: `webapp-ui-design-direction.md`, which proposed a 5-step sequence. Checked each step against the current code before scheduling it here -- two of the five are already done, same "verify, don't assume the plan doc is current" pass as Phase A:

- **Icon library swap -- done.** `projects_manage.html`/`project_detail.html` have a real icon-picker (radio swatches over the sprite set, `icon-picker`/`icon-dropdown` classes) with a fallback (`project.icon or 'folder'`) for anything unset. Not independently re-checked for `databases.icon`/`habits.icon` specifically -- worth a quick grep before assuming those two followed the same pattern, but the mechanism clearly exists and is wired up for at least Projects.
- **List vs. Project IA cleanup -- done.** `base.html`'s nav has a comment dated 2026-08-01 ("Phase B nav rework: Projects/Habits/Contacts pulled off...") confirming task lists/calendars no longer present as peers of Projects in primary nav.

Two of the five remain genuinely open, confirmed by reading the actual templates (not the design doc's description of them):

1. **Shared pagination + collapsible-section components -- still missing.** No `?page=`/`?limit=` convention or pager partial exists anywhere in `src/templates/`. `project_detail.html`'s Events section is the clearest example of the gap it was supposed to fix: it hardcodes `events[:20]` with a bare "...and N more" line, not a real "show more"/paginate control. Schedule table and a Database's row table still render everything unconditionally. Build one shared pattern (pager partial + a Jinja macro or include, not a per-page bespoke slice), apply to Tasks table first (highest traffic), then Schedule/Database/habit history.

2. **Projects-as-widgets + Databases-ownership move -- still missing, and worth re-scoping now that Spaces (project *groups*) already got a widget system.** `_widget_workspace.html` (2026-08-02) gave the dashboard-widget machinery to a "Space" detail page (`routers/projects.py`'s `space_detail`) -- but an individual **project's own** detail page (`project_detail.html`) is still the original fixed-section layout (Task lists / Events / Contacts / Courses, hardcoded order, no reorder/hide, and critically **no Databases section at all** -- a database's only link to its project today is its own `project_uid` field, invisible on the project page itself). Two ways to close this, worth deciding rather than guessing:
   - (a) extend `_widget_workspace.html` one level further, scoping it to a single project (`config.project_uid` already exists per-widget) the same way it was just extended from Home to Space; or
   - (b) keep `project_detail.html`'s simpler fixed-section layout but just add the missing Databases section to it, matching the existing Task lists/Events/Contacts pattern, and treat full widget-driven customization as a separate, larger follow-up.
   Recommend (b) first as a fast, low-risk fix to the concrete "Databases don't show up on their own project's page" gap, with (a) as the real fulfillment of the design doc's ask once there's time for a proper widget-system extension (this is a bigger change than it looks -- `_widget_workspace.html`'s docstring already shows it wasn't a small lift to extend from Home to Space, and doing it again per-project needs the same care).

**Acceptance for the two remaining Phase B items:** live verification with a realistic-volume dataset (the source doc's whole premise was that low-volume placeholder data hid these problems before) -- an actual walkthrough or screenshots, not just "the template renders."

### Open design question, unresolved either way

The source doc also flagged "minimalist vs. gamified" (streaks/progress rings/celebrations) as needing a mood-board pass before touching shared CSS broadly. Neither remaining item above requires resolving that question first -- pagination and a Databases section are structural, not decorative -- so it's not blocking Phase B's two real gaps. Still open for whenever broader visual/CSS work (not scoped here) is picked up.

---

## Phase C -- DAVx5 mobile access via public server + reverse proxy

Not covered by either source doc -- new content. Goal: a phone running DAVx5 (Android CalDAV/CardDAV sync client) syncs tasks/calendar/contacts directly against Radicale, from anywhere, without the phone needing to be on a private mesh network. DAVx5 talks to Radicale directly over CalDAV/CardDAV -- it does not go through the FastAPI webapp at all, so this phase is pure infra, not app code. Chosen over Tailscale specifically because "from anywhere, no VPN app on the phone" was the stated goal -- that tradeoff means real TLS and real auth are not optional hardening, they're the whole security model.

### What exists today (starting point)

`webapp/.dev/radicale/config` is dev-only by its own header comment: plaintext htpasswd, bound to `127.0.0.1:5232`, `owner_only` rights. Its own comment already says the real deployment "needs bcrypt auth (or better, sits behind Tailscale + its own hardened config)" -- since Tailscale was explicitly not the chosen path here, the "or better" branch is bcrypt auth + reverse proxy + real TLS, all three, not a substitute for each other. No docker/nginx/Caddy/tailscale files exist anywhere in the repo yet -- this is greenfield.

### Design

```
Phone (DAVx5) ──HTTPS:443──▶ Reverse proxy (Caddy) ──HTTP:5232──▶ Radicale
                              - real cert (Let's Encrypt/ACME)      (bcrypt auth,
                              - rate limiting                        owner_only rights,
                              - fail2ban on repeated auth failures    bound to 127.0.0.1
                              - terminates TLS, proxies to           or a private
                                localhost-only Radicale                docker network)
```

1. **Reverse proxy: Caddy**, not raw nginx+certbot. Reasoning: automatic ACME cert issuance and renewal with no separate certbot cron/systemd timer to babysit, and a `Caddyfile` for "reverse-proxy this subdomain to that local port with basic hardening" is a handful of lines, not a template. This is the "robust and secure default" pick -- nginx+certbot is equally securable but is more moving parts to keep patched and renewing correctly for a single-maintainer setup.
   - Requires: a domain name (subdomain, e.g. `dav.yourdomain.tld`) pointed at the server's public IP, ports 80/443 open for ACME HTTP-01 challenge + normal traffic.
   - Radicale itself stays bound to `127.0.0.1:5232` (or a Docker-internal network if containerized) -- never listens on a public interface directly. The proxy is the only public-facing process.

2. **Real auth on Radicale**, replacing the dev htpasswd file:
   - `htpasswd_encryption = bcrypt` (Radicale supports this natively) instead of `plain` -- the current dev config's plaintext scheme must not be copied forward.
   - A dedicated Radicale user distinct from any webapp/desktop dev credentials, with a long random password (DAVx5 stores it in Android's encrypted credential store, so length isn't a usability cost the way it would be for something typed daily).
   - Keep `type = owner_only` under `[rights]` -- single-user, no reason to loosen this.

3. **Hardening beyond TLS + auth**, since this is now internet-facing:
   - Rate-limit auth attempts at the proxy layer (Caddy's `rate_limit` or a small fail2ban jail watching Radicale's auth-failure log lines) -- CalDAV/CardDAV endpoints are a known bruteforce target once public.
   - Restrict the proxy to Radicale's actual path prefix only; don't accidentally also expose the webapp's FastAPI port (8000) through the same public hostname unless that's separately decided and separately hardened (it has **no auth at all** today per its own README -- "Known gaps" -- so it must not ride along on Phase C's public exposure without its own auth story first. Treat "expose the webapp too" as an explicit future decision, not a side effect of this phase).
   - Firewall: only 80/443 (proxy) reachable publicly; 5232 (Radicale) and 8000 (webapp) reachable only on localhost/private network, enforced at the OS firewall level, not just by "nothing else listens there."

4. **DAVx5 setup (verification steps once the above is live):**
   - Add account -> "Login with URL and username" -> base URL `https://dav.yourdomain.tld/<principal>/` (Radicale's principal path, matching `CC_RADICALE_URL`'s shape today, just swapped from `127.0.0.1:5232` to the public HTTPS host).
   - Confirm calendar/task-list/address-book collections are discovered (DAVx5 does CalDAV/CardDAV auto-discovery from the principal URL).
   - Create a task/event/contact on the phone via DAVx5's native calendar/tasks/contacts app, confirm it appears in the webapp within one sync interval (`CC_SYNC_INTERVAL`, default 60s) or immediately if the webapp's own write path triggers it.
   - Edit the same object from the webapp, confirm DAVx5 picks up the change on its next sync.
   - Confirm TLS cert validates (no "accept this certificate" prompt) and auth actually rejects a wrong password (don't just confirm the happy path).

5. **Update `webapp/README.md`'s "Deploying for real" section** once this ships, replacing "not covered yet" with what was actually built -- same documentation convention every other phase in that file already follows (a dated update paragraph, not a rewrite of the whole file).

### Note on `architecture.md` / `expansion-deferred.md`'s "Mobile: abandoned"

Both docs record "Mobile (Android/iOS)" as abandoned in the desktop rework -- but that decision was about building a native mobile *app* (Qt Widgets can't do that; a real client would need a different UI toolkit entirely). DAVx5 is a third-party, pre-built CalDAV/CardDAV client pointed at Radicale -- no mobile app gets built or maintained by this project. This phase doesn't reopen that decision; it's a deployment/infra change to an already-existing server component (Radicale), not new client code. Worth a one-line cross-reference added to `expansion-deferred.md`'s Mobile row when this ships, clarifying the distinction so a future reader doesn't think the row is stale or contradicted.

### Acceptance for Phase C

End-to-end live verification only -- a cert-validity check and an auth-rejection check are not optional (see step 4's last bullet), plus the two-way sync check (phone-created object appears in webapp, webapp-edited object appears on phone). No code in `webapp/src` changes in this phase; it's entirely `.dev/radicale`-equivalent config for production, a new `Caddyfile` (or nginx+certbot equivalent), and firewall rules -- worth a `deploy/` directory in the repo root to hold these as tracked, reviewable config rather than something that only exists on the server itself.

---

## Sequencing across all three phases

Phase A needs no further work -- it shipped before this plan was written. What's actually left is Phase B's two items (pagination/collapsible sections; a project's own Databases section, plus the larger project-widgets question) and Phase C in full (DAVx5/hosting). No dependency between the two -- B is templates/routers, C is infra config, disjoint files. Recommend the Databases-section fix (B, option b) first since it's the smallest, most concrete gap found in this pass; pagination next; C on its own timeline whenever the domain/server side of the hosting decision is ready to act on.
