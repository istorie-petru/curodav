# Contacts

`routers/contacts.py` — the `contacts` pool. No special archived state (a plain
`Archived` label); organization is 100% by label.

- **List** (`/contacts`) — search (`q`) + single-select label dropdown, rows with
  avatar + name/org/phone + label pills.
- **Detail/Edit** — `contact_detail.html` (read-only modal with `tel:`/`mailto:`
  quick actions) and `contact_form.html`; shared `_modal_footer`.
- **Fields** — full_name, title, org, phone, email, address, notes, labels,
  photo. Photo upload capped 5MB with content-type allowlist (JPEG/PNG/GIF/
  WEBP), base64 in vCard PHOTO, avatar cropper (`avatar_cropper.js`).
  `title` (vCard TITLE, added 2026-08-15 — a person's job title, distinct
  from `org`'s organization name) shows combined with org as "Title at Org"
  on the detail header and list row (falling back to whichever is present),
  and is matched by contact search. First slice of Contacts field parity with
  Nextcloud Contacts — see `plans/open.md` for the remaining fields (multi-
  value Phone/Email/Website, structured Address, Birthday, Social network).
- **Routes** — `/contacts`, `/contacts/new`, `POST /contacts`,
  `/contacts/{uid}`, `/contacts/{uid}/edit`, `POST /contacts/{uid}`,
  `/contacts/{uid}/delete`.

Professor linking from Schedule writes `professor_contact_uid` on a schedule
class.
