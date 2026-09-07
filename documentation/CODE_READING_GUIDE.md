# Reading and editing this codebase

For Peter, not for an AI session. `features/architecture.md` is the rulebook for
*why* things are built the way they are; this doc is the missing piece —
*what a file looks like* and *how to make a small, safe edit yourself* if you
know Linux/Docker/Git but this is your first real Python + Jinja codebase.

Read this once, keep it open in a tab, and use it as a map. You don't need to
understand FastAPI or Jinja from scratch — just recognize the five shapes below
whenever you open a file, and 90% of this app stops looking like noise.

---

## 1. The five file types, and the one pattern they all follow

Every feature in this app ("Notes", "Habits", "Tasks"...) is the same five
pieces, always in the same order. Once you've read one feature end-to-end, you
can read all of them, because they're deliberately not allowed to diverge.

| File | What it does | Analogy |
|---|---|---|
| `src/db.py` | Talks to SQLite. Plain functions: give it a connection and some data, it reads or writes rows. | The kitchen — where ingredients (data) are actually stored and fetched. |
| `src/<feature>.py` *(optional)* | Pure calculation, no database, no web. E.g. "given these habit entries, what's the streak?" | A calculator on the counter — no fridge access, just math. |
| `src/routers/<feature>.py` | The web layer. Receives a browser request, calls `db.py`, decides what page/JSON to send back. | The waiter — takes your order, passes it to the kitchen, brings back the plate. |
| `src/templates/<feature>.html` | The HTML that actually gets shown, written in Jinja (Python-flavored HTML). | The plate itself. |
| `src/static/<feature>.js` *(optional)* | Small bit of browser JavaScript for drag/drop, live updates, etc. — the page must still work with this disabled. | Garnish. Nice, not required. |

Worked example — the smallest real feature in the app, **Notes**
(`src/routers/notes.py`, `src/templates/notes.html`, `src/db.py`'s note
functions):

1. Browser does `GET /notes` →
2. `routers/notes.py::list_notes` runs, calls `db.list_notes(conn, q=q)` →
3. `db.py` runs a SQL query, returns a list of plain dicts →
4. the router hands that list to `templates.TemplateResponse("notes.html", {...})` →
5. `notes.html` (Jinja) loops over `notes` and prints `<tr>`s.

Every "list this stuff" page in the app is this same five-step trip. Once you
can trace it for Notes (the shortest one — read `notes.py` top to bottom, it's
~140 lines), you can trace it for Tasks or Calendar; those are just the same
shape with more fields.

---

## 2. Reading a Python file (`db.py`, `routers/*.py`)

Things that look consistent everywhere, so you can rely on them:

- **The module docstring at the very top explains *why*, not just what.**
  This codebase writes long comments — much longer than most Python code
  you'll see online. That's deliberate house style (see §5), not clutter.
  Skim the first paragraph for context, then skip straight to the code.
- **Functions in `db.py` always take `conn` (the database connection) as the
  first argument**, e.g. `db.list_notes(conn, q=None)`, `db.upsert_note(conn, row)`.
  A row in and out of these functions is a plain Python `dict` — not a class,
  not an ORM object. `{"uid": "...", "title": "...", ...}`.
- **A write function calls `conn.commit()` itself** — you never need to commit
  manually when calling one.
- **`uid` is the primary key everywhere** (tasks, events, contacts, notes,
  habits...), always a string (a UUID). There's no auto-increment integer id
  to worry about.
- **In a router file** (`routers/<name>.py`):
  - `router = APIRouter(prefix="/notes", ...)` at the top — every route in the
    file is relative to that prefix.
  - `@router.get("/new")`, `@router.post("")`, etc. — the decorator is the
    HTTP verb + path; the function under it is what runs.
  - `conn=Depends(get_db)` in a function's arguments is FastAPI's way of
    saying "give me a database connection for this one request." You'll see
    it on almost every route function — it's boilerplate, not something to
    puzzle over.
  - **A page load (`GET`) returns `templates.TemplateResponse("some.html", {...})`.**
    The dict is everything the template is allowed to see.
  - **A write (`POST`) redirects afterwards** — `return respond(x_requested_with, "/notes")`
    or a plain `RedirectResponse(..., status_code=303)`. This is a hard rule
    in this app (see `features/architecture.md` §2): a form submit never
    re-renders a page directly, it always redirects to a GET. `respond()`
    (in `deps.py`) just picks between "redirect the whole page" and "return
    JSON" depending on whether the request came from a JS fetch — you don't
    need to touch that function, only call it.

If you're only fixing a bug or tweaking behavior, you will spend almost all
your time inside one function in one router file, maybe touching one function
in `db.py`. You rarely need to understand the whole file.

---

## 3. Reading a template (`src/templates/*.html`)

This is Jinja2 — think "HTML where `{{ }}` prints a Python value and `{% %}`
runs Python-ish logic (`if`, `for`)."

- **`{% extends "base.html" %}`** at the top of almost every full-page
  template — it's filling in slots (`{% block content %}...{% endblock %}`)
  inside the shared page shell (`base.html` — nav bar, `<head>`, etc.). You
  will basically never edit `base.html` for a normal feature change.
- **`{# a comment #}`** — Jinja's comment syntax, not `<!-- -->`. Same "explain
  the why" habit as the Python files; the top of most templates has one.
- **Filenames starting with `_` are partials/fragments**, not full pages —
  meant to be `{% include %}`'d or imported by another template. E.g.
  `_notes_body.html` is the `<table>` that both the full `notes.html` page
  *and* the JS-driven "refresh just this part of the page" endpoint both
  reuse, so the markup only exists once.
- **`{{ icon('trash') }}`**, **`{{ static_url('notes_list.js') }}`** — these
  look like template tags but are just Python functions registered as
  globals (`deps.py`). `icon()` prints one of the SVG icons already defined
  in the page; `static_url()` builds the `/static/...` URL with a cache-
  busting `?v=...` suffix so your browser doesn't serve a stale cached file
  after you edit it.
- **Colors and spacing come from CSS variables (`var(--accent)`, etc.), never
  a literal hex code**, so light/dark mode both stay correct automatically.
  If you're changing a color, change it in `src/static/style.css`'s token
  block near the top, not in the template.

---

## 4. Naming conventions cheat sheet

| Thing | Convention | Example |
|---|---|---|
| Python files/functions/variables | `snake_case` | `list_notes`, `task_uid` |
| Python classes | `PascalCase` | `CalDavBridge` |
| "Private, don't call from outside this file" | leading underscore | `_notes_list_context`, `_static_url` |
| Template files | `snake_case.html`; a leading `_` = partial/fragment | `note_form.html`, `_task_row.html` |
| Static JS/CSS files | `snake_case.js` | `tasks_table.js` |
| Test files | `tests/test_<feature>.py`, one per feature | `test_offline_sync.py` |
| Database tables/columns | `snake_case`, plural table names | `tasks`, `object_labels`, `due_at` |

---

## 5. Why the comments are so long (and why you should keep doing it)

You'll notice functions here often have a paragraph of comment above a few
lines of code. That's not accidental verbosity — it's the project's actual
convention, and it exists because this is a long-running personal project
edited across many separate sessions (by an AI, by you) with no teammate to
ask "wait, why is it built this way?" The comment *is* that teammate.

When you make an edit yourself: if the reason you did something a particular
way isn't obvious from the code alone, write a sentence above it explaining
the *why*, not the *what* (the code already shows the what). This is the
single most important habit for keeping this codebase editable by a
non-full-time developer — future-you will thank present-you.

---

## 6. Making a small edit, safely — a checklist

1. **Find the feature's five files.** Grep for the feature name — e.g.
   `grep -rl "habit" src/routers src/templates` — or just open
   `src/routers/<guess>.py` directly; the router prefix usually matches the
   URL you saw in the browser.
2. **Read the router function the URL maps to** (match the HTTP method + path
   to the `@router.get/post(...)` decorator). Trace what it calls in `db.py`
   and which template it renders.
3. **Make the smallest change that fixes the thing.** Don't restructure
   files while fixing a bug — separate changes are easier to undo if wrong.
4. **If you changed behavior, add or update a test** in
   `webapp/tests/test_<feature>.py`. Tests here don't spin up a browser —
   they call the router function directly with a fake `conn`, seed some
   data, call the function, and assert on the result. Copy the shape of an
   existing test in the same file; you don't need to write one from scratch.
5. **Run the whole test suite before you trust the change:**
   ```bash
   cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q
   ```
   All green, every time — a red test means something broke, even something
   you didn't touch directly (shared code has ripple effects).
6. **Commit with a message that says what changed and why**, same spirit as
   the in-code comments.

If the change is bigger than "fix this one thing" — a genuinely new feature —
read `plans/STATE.md` first; that file (not this one) governs how new
roadmap work gets planned and sliced.

---

## 7. Glossary — terms you'll hit constantly

- **`conn`** — a SQLite database connection/cursor, passed into almost every
  `db.py` function and most router functions.
- **`uid`** — the unique string ID of a row (task, event, contact, label...).
- **`Depends(get_db)`** — FastAPI's way of injecting a fresh `conn` per
  request; you'll see this in nearly every route's function signature.
- **303 redirect** — after a form POST, the server tells the browser "now go
  GET this other URL" instead of returning the new page directly. Prevents
  the classic "hit refresh, it submits the form again" bug.
- **`TemplateResponse`** — FastAPI/Jinja's way of saying "render this .html
  file with this data and send it back."
- **M3 / Material You tokens** — the CSS variable system (`--md-*`,
  `--accent`, ...) this app's whole look is built from; see
  `features/architecture.md` §3 before touching colors/spacing.
- **"Region" / async-crud fragment** — a small chunk of HTML (a `_foo_body.html`
  partial) the server can re-render on its own so JS can swap it into the
  page without a full reload. See `features/async-crud.md`.

---

## 8. Where to go deeper

- **`features/architecture.md`** — the actual rulebook: data model, why a
  feature must be built as the five-file slice above, the design-system
  contract, and a hard "don't" list. Read this before any change bigger than
  a one-line fix.
- **`plans/STATE.md`** — current position on the roadmap; read this (only
  this) before starting new feature work.
- **`webapp/README.md`** — stack overview, environment variables, deployment.
