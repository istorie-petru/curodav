# Contacts

`routers/contacts.py` — the `contacts` pool. No special archived state (a plain
`Archived` label); organization is 100% by label.

- **List** (`/contacts`) — search (`q`) + single-select label dropdown, rows with
  avatar + name/org/phone + label pills. **Bulk select** (2026-09-14): each row
  carries a `.row-select` checkbox (`_contacts_body.html`'s `.contact-row-wrap`,
  a sibling wrapper around the row's own click-to-open `<a>` so a checkbox
  click doesn't also open the contact); a Delete/Clear bar
  (`_bulk_actions_bar.html`) appears in the page header once a row is checked,
  driven by the shared `static/bulk_select.js` (same module Labels/Holidays/
  Time Blocks use) via `POST /contacts/bulk-delete`. Re-initializes after the
  page's own async-CRUD region swap (any contact create/edit/delete
  elsewhere refreshes `#contacts-body`) so the checkboxes don't go stale.
- **Detail/Edit** — `contact_detail.html` (read-only modal with `tel:`/`mailto:`
  quick actions) and `contact_form.html`; shared `_modal_footer`.
- **Fields** — full_name, title, org, phone(s), email(s), address, notes,
  labels, photo. Photo upload capped 5MB with content-type allowlist (JPEG/
  PNG/GIF/WEBP), base64 in vCard PHOTO, avatar cropper (`avatar_cropper.js`).
  `title` (vCard TITLE, added 2026-08-15 — a person's job title, distinct
  from `org`'s organization name) shows combined with org as "Title at Org"
  on the detail header and list row (falling back to whichever is present),
  and is matched by contact search. First slice of Contacts field parity with
  Nextcloud Contacts — see `plans/open.md` for the remaining fields
  (structured Address, Birthday, Social network).
- **Phone/email (multi-value)** — Contacts field parity slice 2 of 6,
  2026-08-15. A contact can have any number of phone numbers/email
  addresses, each tagged with a vCard/Nextcloud type — Home/Work/Cell/Fax/
  Pager/Other for phone, Home/Work/Other for email — stored in dedicated
  child tables (`db.py`'s `contact_phones`/`contact_emails`, owned rows keyed
  by `contact_uid`, no FOREIGN KEY constraint per this app's convention).
  The old single-value `contacts.phone`/`contacts.email` columns are still
  physically present (never force-dropped) but are dead — nothing writes
  them anymore; a pre-slice-2 database's existing value auto-migrates once,
  idempotently, into the new table as a single entry typed "Other"
  (`db.migrate_legacy_contact_phone_email`, run automatically at schema
  setup). vCard round-trips as multiple `TEL`/`EMAIL` lines with a `TYPE=`
  param (`TEL;TYPE=CELL:...`) — "Other" gets no `TYPE=` param at all, since
  vCard has no standard token for it (`vcard_rows.py`). The create/edit form
  submits every phone/email row together as parallel `phone_type[]`/
  `phone_value[]` (`email_type[]`/`email_value[]`) form arrays on the one
  Save button (rows added/removed client-side,
  `static/contact_phone_email_rows.js`), each with a plain `<select>` for
  its type. The detail page lists every phone/email with its type and a
  `tel:`/`mailto:` link; the list row and dashboard Contact List widget stay
  concise, showing only the first (lowest-position) entry of each. Contact
  search (`db.list_contacts`/`db._search_contacts`) matches values in the
  new tables (the dead legacy columns are still searched too, harmlessly
  redundant). See `plans/open.md` for the remaining fields (structured
  Address, Birthday, Social network).
- **Website (multi-value)** — Contacts field parity slice 3 of 6,
  2026-08-15. A contact can have any number of websites, each tagged Home/
  Work/Other (same vocabulary as email/address), stored in a new
  `contact_websites` child table (`db.py`, same owned-row shape as
  `contact_phones`/`contact_emails` — `contact_uid`, `type`, `position`,
  no FOREIGN KEY; the value column is named `url`, not `value`, to match
  vCard's own URL property name). There was never a pre-existing single-
  value website column anywhere in this app, so unlike Phone/Email there
  is no legacy data to auto-migrate. vCard round-trips as multiple `URL`
  lines with the same `TYPE=` convention ("Other" omits the param) —
  vCard's URL property isn't one of RFC 2426/6350's typed multi-instance
  properties the way TEL/EMAIL are, but vobject supports repeated
  `card.add("url")` calls and a `card.url_list` read-back identically,
  confirmed directly against vobject before writing `vcard_rows.py`. The
  create/edit form submits every website row together as parallel
  `website_type[]`/`website_url[]` form arrays (reusing
  `static/contact_phone_email_rows.js`'s add/remove-row wiring verbatim —
  it was already written generically enough for a third field group). The
  detail page lists every website with its type and an external link
  (`target="_blank" rel="noopener"`, matching event `meeting_url`'s
  convention). Left off the contacts-list row subtitle and dashboard
  Contact List widget — org/title/phone/email stay the more useful
  compact-row fields. Search matches website URLs too. See `plans/
  open.md` for the remaining fields (structured Address, Birthday, Social
  network).
- **Birthday (single-value)** — Contacts field parity slice 4 of 6,
  2026-08-16. Unlike Phone/Email/Website, a contact has at most one
  birthday, so this is a plain `contacts.birthday` column, not a child
  table. Stores vCard's own BDAY text verbatim — a full `YYYY-MM-DD` date,
  or a year-less `--MM-DD` date (green-lit, AskUserQuestion, 2026-08-15).
  `db.parse_contact_birthday` validates a create/edit form's raw text
  against both shapes using real calendar-date rules (`datetime.strptime`,
  not just a regex — rejects e.g. `1990-02-30`; a year-less date is
  checked against a dummy leap year so `--02-29` validates), the one call
  site `routers/contacts.py` uses before ever reaching `db.upsert_contact`
  — a 400 on anything else, never a partial write. `db.format_contact_
  birthday` is the display side: "May 17, 1990" / "May 17", falling back
  to the raw stored value unchanged for a shape this app didn't write
  itself (e.g. a bare `19900517` from another CardDAV client). vCard
  round-trips through a single BDAY line — vobject treats a string
  `.value` as opaque text on both write and read (confirmed directly
  against vobject before writing `vcard_rows.py`), so neither shape needs
  parsing into a `date` object anywhere in this app. The create/edit form
  uses a plain text input (`contact_form.html`), not a native
  `<input type="date">`, since a year-less birthday has no HTML
  date-input equivalent; the detail page renders it through a new
  `fmt_birthday` Jinja filter (`deps.py`). Not searched (`db._search_contacts`/
  `list_contacts`), a precedent Address (below) also follows. A contact with
  a birthday also gets a generated all-day, yearly-recurring Calendar event
  tagged "Birthday" (`db.sync_contact_birthday_event`) — see `features/
  calendar.md`'s own entry for how that's kept in sync.
- **Address (structured multi-value)** — Contacts field parity slice 5 of
  6, 2026-08-16. The old `contacts.address` free-text column is now
  `contact_addresses`, a full structured, multi-value vCard ADR (PO Box,
  Extended, Street, City, Region, Postal code, Country), each entry typed
  Home/Work/Other (same vocabulary as email/website). Same owned-child-
  row shape as phone/email/website, just seven value columns instead of
  one; a row is dropped on save only when every one of the seven fields
  is blank (unlike phone/email/website's single-value blank check).
  vCard round-trips as multiple `ADR` lines with `TYPE=` (Other omits
  it), via vobject's `card.add("adr")`/`adr_list` — ADR is one of RFC
  2426/6350's own typed multi-instance properties, confirmed directly
  against vobject before writing `vcard_rows.py`. The old flat
  `contacts.address` value auto-migrates once, idempotently, into a
  single "Other"-typed entry (the whole legacy string placed in
  `street`, every other structured field left blank —
  `db.migrate_legacy_contact_address`). The create/edit form renders
  each address as its own card (`.contact-address-row`, a 2-column field
  grid) rather than the single-line rows phone/email/website use — more
  fields per entry than a one-line layout could hold. The detail page
  renders each entry through a new `fmt_address` Jinja filter
  (`db.format_contact_address`), vCard's own multi-line layout (PO Box/
  Extended/Street each own line, then "City, Region PostalCode", then
  Country). Not searched — same precedent Birthday established.
- **Social network (`X-SOCIALPROFILE`)** — Contacts field parity slice 6
  of 6, 2026-08-16, closing out this effort. A contact can have any
  number of social profiles, each tagged with a network name (Twitter/
  Facebook/Instagram/LinkedIn/Mastodon/GitHub/Other —
  `db.CONTACT_SOCIAL_TYPES`), not the Home/Work/Other vocabulary every
  other typed contact field uses — "which network" is the meaningful
  distinction here. New `contact_social_profiles` table, same owned-
  child-row shape as phone/email/website (single `value` column). No
  pre-existing single-value column ever existed, so no auto-migration
  (same situation as Website). vCard round-trips as multiple
  `X-SOCIALPROFILE` lines with `TYPE=` naming the network (Other omits
  it) — an X- extension property, but vobject treats it identically to a
  core typed property (repeatable `card.add`, plural `_list` read-back),
  confirmed directly against vobject. The create/edit form uses the same
  one-line multi-row shape as Phone/Email/Website. The detail page
  renders a URL-shaped value (`http://`/`https://`) as an external link;
  a bare handle/username renders as plain text, since X-SOCIALPROFILE
  doesn't guarantee either shape. Contacts field parity with Nextcloud
  Contacts (`plans/open.md`) is now fully shipped.
- **Routes** — `/contacts`, `/contacts/new`, `POST /contacts`,
  `/contacts/{uid}`, `/contacts/{uid}/edit`, `POST /contacts/{uid}`,
  `/contacts/{uid}/delete`.

Professor linking from Schedule writes `professor_contact_uid` on a schedule
class.
