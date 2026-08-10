# Plan: Contacts field parity with Nextcloud Contacts

**Status:** Open, not started — planning only, per explicit instruction. No code changes in this pass.
**Target codebase:** `webapp/` (FastAPI), specifically `db.py`'s `contacts` table, `vcard_rows.py`, `routers/contacts.py`, `contact_form.html`/`contact_detail.html`/`contacts_list.html`.
**Source of the field list:** Nextcloud Contacts' own edit form, as supplied directly by you (see §1).
**Relationship to prior work:** builds on `plans/label-space-rework.md` (Phases 1–9c) — Contacts is currently a plain-label, no-special-states object type (Phase 9's "remove Active/Archived" change). This plan explicitly does **not** reopen that decision; see §3 for the two Nextcloud fields that don't carry over for exactly that reason.

---

## 1. The field list you gave, restated as a checklist

Name (Title, Company) · Phone (Home, + more) · Email (Home, + more) · Address (Home: PO box, extended address, postal code, city, state/province, country, + more) · Personal dates (Birthday) · Website (+ more) · Social network (+ more) · Notes · Address book · Archive · Contact groups.

## 2. What this app already has vs. what's genuinely new

| Nextcloud field | Current state in this app | Verdict |
|---|---|---|
| Name | `full_name` (single text field) exists | Has it, but see §4.1 for the Title/Company split |
| Title | Not stored anywhere | **New** |
| Company | `org` exists, single value | Has it |
| Phone | `phone` — **one value, no type label** | **Needs rework** — single field → multi-value with type |
| Email | `email` — **one value, no type label** | **Needs rework** — same shape problem as Phone |
| Address | `address` — **one free-text field**, not structured | **Needs rework** — Nextcloud's PO box/extended/postal/city/state/country breakdown doesn't exist at all |
| Personal dates / Birthday | Not stored | **New** |
| Website | Not stored | **New** |
| Social network | Not stored | **New** |
| Notes | `notes` exists, single text field | Has it |
| Contact groups | Not a separate concept — **labels already do this** (`object_labels`, same mechanism as tasks/events) | **Already covered, don't rebuild** — see §3 |
| Address book | **Deliberately removed** (Phase 1 of the label-space rework — no more multi-collection model) | **Do not re-add** — see §3 |
| Archive | **Deliberately removed** (Phase 9 — "remove active/archived logic, only labels") | **Do not re-add** — see §3 |

## 3. Two fields on Nextcloud's list this app should NOT copy — flagging before anyone builds them

Nextcloud's "Address book" and "Archive" aren't contact *data*, they're Nextcloud's own organizational model — and this app already ran through exactly that kind of decision twice this month and landed somewhere different on purpose:

- **Address book** (which CardDAV collection a contact lives in) — Phase 1 of the label-space rework removed the whole multi-collection model. Contacts live in one universal pool now; grouping is 100% by label. Reintroducing an address-book picker would be a straight reversal of a decision you made explicitly, not an addition.
- **Archive** — you told me directly, days ago, to "remove the active/archived logic for contacts, only labels." Nextcloud's Archive is exactly that special-cased state. If you still want an "archived" concept, tagging a contact `Archived` (a plain label) already does everything Nextcloud's Archive does, filterable the same way any label is.

**Contact groups** doesn't need new work either — Nextcloud's groups and this app's labels are the same idea (a contact belongs to zero or more named groupings). Labels already cover it; building a parallel "groups" field would just be the tag/label duplication this app's own house rules explicitly forbid.

Net: of Nextcloud's 11 field categories, 3 need no work (Notes, Company, Contact groups-via-labels) and 2 should be explicitly skipped (Address book, Archive). The real scope is: Title, multi-value Phone/Email/Website/Social network, structured multi-value Address, and Birthday.

## 4. Proposed model, field by field

### 4.1 Name split: Title
Nextcloud splits "Company" (already have: `org`) from a separate job "Title" (e.g. "Software Engineer" at "Acme Corp"). Add `title` as a new plain `contacts` column. Maps to vCard's `TITLE` property (a real, standard property — `vobject` already supports `.add("title")`, same pattern `org`/`fn` already use in `vcard_rows.py`). Single-value; Nextcloud doesn't multi-value this either.

### 4.2 Phone / Email — single value → multi-value with type
Both fields need the same shape change: today `contacts.phone`/`contacts.email` are single TEXT columns; Nextcloud allows any number of each, each tagged with a type (Home, Work, Mobile, Fax, etc.).

Proposed storage: `phones_json`/`emails_json`, each a JSON array of `{"type": "home", "value": "..."}` objects — same "JSON array column, not a child table" pattern this app already uses for `tags_json`/`exdates_json`/`reminders_json` elsewhere, consistent with the existing house convention rather than introducing a new one.

vCard mapping: multiple `TEL;TYPE=<type>:` and `EMAIL;TYPE=<type>:` lines per card — this is exactly how real phones/CardDAV clients already represent multi-value phone/email, so this is a **compatibility improvement**, not just a UI nicety: a contact with two phone numbers, synced in from a phone's native Contacts app today, is currently silently collapsed to one value by `vcard_to_contact_row`'s `hasattr(card, "tel")` (grabs only the first `TEL` line). This rework fixes real data loss on the import/sync-in path, not just adds a form field.

Type vocabulary: a fixed, small set (Home, Work, Mobile, Other for phone; Home, Work, Other for email) rather than freeform text — matches Nextcloud's own dropdown-of-known-types UI and keeps the vCard `TYPE=` values interoperable with other CardDAV clients (an arbitrary type string might not render sensibly in someone's phone contacts app).

### 4.3 Address — single free-text → structured, multi-value
Bigger change than phone/email: Nextcloud's address isn't just multi-value, each entry is *structured* into PO box, extended address, street, city, state/province, postal code, country — this maps directly onto vCard's `ADR` property, which has always been structured (`vobject.vcard.Address` already has `box`/`extended`/`street`/`city`/`region`/`code`/`country` fields — `vcard_rows.py`'s current `contact_row_to_vcard` only ever populates `street` today, silently dropping the rest even where a client provides it).

Proposed storage: `addresses_json`, a JSON array of `{"type": "home", "po_box": "", "extended": "", "street": "", "city": "", "region": "", "postal_code": "", "country": ""}` objects. Same multi-value-JSON-column pattern as §4.2.

This is the most involved form-UI change of the whole plan — seven sub-fields per address entry, potentially several entries — worth its own design pass on the add/remove-address-entry interaction (see §6, open question 3) rather than assuming a naive repeated-fieldset is fine.

### 4.4 Personal dates: Birthday
Add `birthday` (a date column, nullable — reuses the same date-field convention `tasks.due_at`/`events.start_at` already establish, though those are full datetimes and birthday is a date-only value, so treat it like `habit_entries.date` or `schedule_holidays.date_from` instead — this app already has a plain-date-string precedent, not just datetime ones). Maps to vCard `BDAY`. Nextcloud calls the section "Personal dates" (implying room for more than birthday — anniversary, etc.) but only ships Birthday itself in the field list you gave; scoping this to just `birthday` unless you want more date types, flagged as open question 4.

### 4.5 Website — multi-value
Add `websites_json`, JSON array of plain URL strings (no type needed the way phone/email have — Nextcloud's own UI doesn't type-label websites either, just numbers them). Maps to multiple vCard `URL` properties.

### 4.6 Social network — multi-value
Add `social_profiles_json`, JSON array of `{"network": "...", "value": "..."}` (e.g. network="Mastodon", value="@handle@instance"). vCard mapping is the one genuinely awkward part of this whole plan: `X-SOCIALPROFILE` is a real, moderately-common extension property (Nextcloud/Apple/others all write it) but isn't in the core vCard 3.0/4.0 spec the way `TEL`/`EMAIL`/`ADR`/`BDAY`/`URL`/`TITLE` all are — see open question 5 before building this one specifically, since it's the one field where "real, standard, portable data" (this app's own stated bar for what earns a schema column, per `architecture.md`) is genuinely in question.

## 5. Suggested build order (once you decide to implement)

1. **Title** (§4.1) — trivial, one new column, one new vCard property, no migration risk.
2. **Phone/Email multi-value** (§4.2) — fixes a real data-loss bug on the sync-in path, self-contained, no dependency on anything else here.
3. **Website** (§4.5) — same shape as phone/email but simpler (no type field), good warm-up for the harder Address work.
4. **Birthday** (§4.4) — simple, independent.
5. **Address** (§4.3) — the biggest single piece, do it once the multi-value-JSON-column pattern is proven out by phone/email/website above.
6. **Social network** (§4.6) — last, and only after open question 5 is resolved, since the vCard-portability answer might change the shape of what gets built.

Each step needs: a `db.py` schema/accessor change, a `vcard_rows.py` round-trip update (both directions — export *and* the import/sync-in parsing, since §4.2 already found a live bug in the import direction), a `contact_form.html` UI change (multi-value fields need add/remove-entry interaction, not just a wider input), `contact_detail.html`/`contacts_list.html` display updates, and its own test file — same phase discipline `plans/label-space-rework.md` used throughout (schema → tests → full suite green before moving on).

## 6. Open questions — need your call before implementation starts

1. **Type vocabulary for Phone/Email/Address** — is Nextcloud's own set (Home/Work/Mobile/Fax/Other, roughly) exactly what you want, or do you want a different/shorter list?
2. **Should existing single-value `phone`/`email`/`address` data migrate automatically** into the new multi-value columns as a single "Home" (or "Other") entry, or does this only matter for a fresh install? (Real question only if there's existing contact data worth preserving.)
3. **Address form UX** — seven sub-fields × N addresses is a lot of form surface. Worth a compact single-line "Street, City, Region Postal, Country" entry mode with an "edit full address" expansion, or is a full always-expanded fieldset per address fine?
4. **Personal dates: just Birthday, or more date types** (anniversary, etc.) — Nextcloud's own section name ("Personal dates," plural) leaves room for more than one; the field list you gave only named Birthday specifically.
5. **Social network's vCard property**: use the widely-supported-but-non-standard `X-SOCIALPROFILE` (works with Nextcloud/Apple, may not round-trip cleanly through every CardDAV client), or keep social links out of the vCard entirely and treat them as this-app-only metadata (loses portability, but avoids shipping a property that might confuse a strict CardDAV client)? This is the one field in the whole plan where the "real synced data, not an app-only bolt-on" bar isn't a clean yes.
