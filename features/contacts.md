# Contacts

`routers/contacts.py` — the `contacts` pool. No special archived state (a plain
`Archived` label); organization is 100% by label.

- **List** (`/contacts`) — search (`q`) + single-select label dropdown, rows with
  avatar + name/org/phone + label pills.
- **Detail/Edit** — `contact_detail.html` (read-only modal with `tel:`/`mailto:`
  quick actions) and `contact_form.html`; shared `_modal_footer`.
- **Fields** — full_name, org, phone, email, address, notes, labels, photo.
  Photo upload capped 5MB with content-type allowlist (JPEG/PNG/GIF/WEBP), base64
  in vCard PHOTO, avatar cropper (`avatar_cropper.js`).
- **Routes** — `/contacts`, `/contacts/new`, `POST /contacts`,
  `/contacts/{uid}`, `/contacts/{uid}/edit`, `POST /contacts/{uid}`,
  `/contacts/{uid}/delete`.

Professor linking from Schedule writes `professor_contact_uid` on a schedule
class.
