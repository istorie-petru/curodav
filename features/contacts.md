# Contacts

`routers/contacts.py` — the `contacts` pool. No special archived state (a plain
`Archived` label); organization is 100% by label.

- **List** (`/contacts`) — search (`q`) + single-select label dropdown, rows with
  avatar + name/org/phone + label pills.
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
  redundant). See `plans/open.md` for the remaining fields (Website,
  structured Address, Birthday, Social network).
- **Routes** — `/contacts`, `/contacts/new`, `POST /contacts`,
  `/contacts/{uid}`, `/contacts/{uid}/edit`, `POST /contacts/{uid}`,
  `/contacts/{uid}/delete`.

Professor linking from Schedule writes `professor_contact_uid` on a schedule
class.
