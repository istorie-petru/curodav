# Coding standards: naming, comments, structure

The other two guides are situational — `CODE_READING_GUIDE.md` gets you
oriented in this specific repo, `CLEAN_CODE_GUIDE.md` critiques what's
already here. This one is the reference you keep open while actually
writing a line of code: concrete rules for naming things and commenting
things, so every new piece of code looks like it was written by the same
disciplined person, not whoever happened to be typing that session.

None of this is arbitrary taste — each rule exists because of a specific
failure mode it prevents. Where that's not obvious, it's stated.

---

## 1. Naming files

| Type | Rule | Example |
|---|---|---|
| Python module | `snake_case`, a **noun** naming what it contains, not what it does | `db.py`, `derived_state.py`, not `process_data.py` |
| Router module | `snake_case`, matches the URL prefix it owns | `routers/habits.py` → `/habits` |
| Template, full page | `snake_case.html`, matches the feature/router it belongs to | `task_detail.html` |
| Template, partial/fragment | leading `_`, describes the fragment's content, not its caller | `_task_row.html`, `_widget_streak.html` |
| Static JS | `snake_case.js`, matches the template/feature it enhances | `tasks_table.js` |
| Test file | `tests/test_<feature>.py`, one file per feature, never per-bug-fix | `test_habits_router.py` |

**The one rule that matters most:** a filename should answer "what lives
here" without opening the file. If you can't name a new file in five
seconds, that's usually a sign the code inside it doesn't have a single
clear purpose yet — decide the purpose first, then the name falls out of
it, not the other way around.

Don't name files after a date, a ticket number, or "v2"/"new"/"final" —
`git log` already tracks history; the filename should describe what the
code *is*, permanently.

---

## 2. Naming functions

**Start with a verb that says what happens, not how.** The reader should
be able to guess the function's effect from its name alone, before
reading a single line inside it.

| Prefix | Means | Example |
|---|---|---|
| `get_` | fetch exactly one thing; may return `None` if absent | `get_note(conn, uid)` |
| `list_` | fetch zero or more things, always returns a list | `list_notes(conn, q=None)` |
| `create_` | insert a brand-new row | `create_work_allocation(...)` |
| `upsert_` | insert or update, whichever applies — used specifically when the caller shouldn't have to know which | `upsert_task(conn, row)` |
| `update_` / `set_` | change an existing row's field(s), row already known to exist | `set_relations_card(...)` |
| `delete_` | remove a row (or mark it deleted) | `delete_note(conn, uid)` |
| `is_` / `has_` / `wants_` | returns a `bool`, reads like a yes/no question | `wants_json(header)` |
| leading `_` | private to this module — never imported elsewhere | `_apply_status_filter(...)` |

**Don't mix concerns in one name.** `save_and_notify_task()` is doing two
things — split it, or if it must stay one function for a real reason
(e.g. they must happen in the same transaction), name it after the
*outcome*, not the steps: `complete_task(...)`, and let the docstring
explain that notification is part of completing a task.

**Avoid abbreviations that aren't already standard in this codebase.**
`conn` (connection), `uid` (unique id), `ctx` (context) are established
and fine — inventing new ones (`tsk`, `evt`, `desc`) forces the reader to
learn a private vocabulary. When in doubt, spell it out.

---

## 3. Naming variables and constants

- **Descriptive over short**, except for genuinely trivial scope: a loop
  index over 2-3 items (`for i, row in enumerate(rows)`) is fine; a loop
  variable that lives more than a few lines should be named for what it
  holds (`task` not `t`, `label_name` not `ln`).
- **Boolean variables read as a question**: `is_project`, `has_conflict`,
  `show_relations_card` — never a bare adjective (`project`, `conflict`)
  that leaves it ambiguous whether it's the flag or the thing itself.
- **A string/number used in more than two places becomes a named
  constant**, `UPPER_SNAKE_CASE`, defined once near the top of the module
  that owns it — same pattern `deps.py` already uses:
  ```python
  WEEK_START_KEY = "calendar_week_start"
  ```
  This isn't just tidiness: a typo in a raw string fails silently (wrong
  filter applied, no error, hard to notice); a typo in a constant name
  fails immediately and loudly (`NameError`) the moment the code runs.
- **Don't encode the type in the name** (`title_str`, `count_int`) — Python
  is typed via annotations now (`title: str`), the name doesn't need to
  repeat it.

---

## 4. Naming classes

`PascalCase`, a **noun**, named for the thing it represents —
`CalDavBridge`, `AuthMiddleware`. A class in this codebase is almost
always either (a) a thin wrapper around an external system (the CalDAV
bridge) or (b) a framework hook (a Starlette middleware, a `StaticFiles`
subclass) — not a general-purpose "business object," since this app
deliberately uses plain dicts for its data (see `CODE_READING_GUIDE.md`
§2). If you find yourself wanting to invent a new class to hold task/event/
contact data, that's a signal to stop and re-read
`features/architecture.md` §1 first — it's very likely supposed to be a
plain dict and a `db.py` function instead.

---

## 5. Comments — the four levels, and what belongs at each

Every file in this codebase can have comments at up to four levels.
**Not every function needs all four** — most need just the first and
last. Here's what belongs where:

### 5.1 File-level (top of the module) — always

One docstring, first thing in the file. Answers: **what does this file
own, and why does it exist as its own file** (not folded into another
one)? This is the one place a little history is genuinely useful — "this
replaced X because Y" belongs here, once, not repeated at every function
inside.

```python
"""Notes -- the fourth Quick Capture entity type (`!n`), alongside the
pre-existing tasks/events/contacts. Deliberately minimal: a note is
free-text content plus labels, nothing else."""
```

### 5.2 Class-level — always, even for a short class

Answers: **what does an instance of this represent, and what does it
own**? A one-liner is fine if the class is simple.

```python
class _VersionedStaticFiles(StaticFiles):
    """Plain StaticFiles sets no Cache-Control, so browsers fall back to
    heuristic caching. Every static URL is cache-busted, so a long,
    aggressive cache here is safe."""
```

### 5.3 Function/method-level — when the name alone isn't enough

**Skip the docstring entirely when the function is genuinely
self-explanatory** — `list_notes(conn, q=None)` returning "notes matching
`q`" doesn't need three lines restating its own signature. A comment that
just repeats the function name in sentence form is noise, not
documentation.

**Write one when at least one of these is true:**
- The function has a **non-obvious side effect** (writes to two tables,
  triggers a background job, mutates something the caller passed in).
- There's a **subtle invariant or edge case** a caller must respect (what
  happens on `None`, on an empty list, on a duplicate).
- The **"why this approach"** isn't visible from reading the body (e.g.
  why this queries in two passes instead of one join).

Public/router-facing functions get more benefit of the doubt than small
private `_helpers` — a `@router.post(...)` endpoint is a contract other
code (and the browser) depends on, so it's worth a sentence even when it
looks simple, because its behavior is harder to change later without
breaking something.

```python
def create_work_allocation(conn, task_uid, event_uid=None, start_at=None, end_at=None):
    """Creates a work session for a task. Both start_at and end_at must be
    given together or both omitted -- an omitted pair creates an undated
    placeholder that keeps the task on the "Unscheduled work" panel until
    it's dragged onto a calendar slot."""
```

### 5.4 Inline (a line or two above specific code) — sparingly, for "why" only

An inline comment exists **only** to answer "why is this line doing
something a reader wouldn't expect," never to narrate what the line
already says in plain Python.

```python
# Bad -- restates the code, adds nothing:
# increment the counter
count += 1

# Good -- explains something the code can't say for itself:
# A caller that skips this Form field gets FastAPI's raw default
# marker, not a string -- coerce it before using it.
if not isinstance(target_per_day, str):
    target_per_day = "1"
```

If you catch yourself writing an inline comment and it's turning into a
paragraph, stop and ask: is this actually a **function-level** comment
that belongs on the function above it instead of buried mid-body? Most of
the time, yes — pull it up.

---

## 6. How much commenting is enough — a concrete test

Before adding a comment, ask: **"if I deleted this comment, would a
careful reader misunderstand the code, or just have to think for a
second?"** Only the first case earns a comment.

A rough calibration for this codebase:
- **A file with zero comments below the module docstring** is suspicious
  unless it's genuinely trivial (a handful of one-line pass-through
  functions).
- **A function where the comment is longer than the code it explains** is
  also suspicious — it usually means either the code should be simplified
  until it doesn't need that much explaining, or the comment has drifted
  into narrating history (see `CLEAN_CODE_GUIDE.md` §2.1) instead of
  stating the current reason.
- **The sweet spot**: one clear sentence at the function level for
  anything non-trivial, an inline comment only at the specific line where
  something genuinely surprising happens, and nothing else. Most
  functions in a clean version of this codebase should have 0-2 comments
  total, not 0 and not 10.

---

## 7. Docstring format used in this repo

Plain triple-quoted strings, first line (or first sentence) is a summary
you could read on its own; more detail can follow in the same paragraph.
No `:param:`/`:returns:`-style structured docstrings anywhere in this
codebase — stay consistent with that rather than introducing a second
format partway through.

```python
def note_title(note: dict) -> str:
    """First line of a note's content, used as its display title since
    notes have no separate title field."""
```

---

## 8. Quick checklist before committing a new function

- [ ] Name starts with the right verb prefix (§2) and says what it does.
- [ ] Any string/number reused 3+ times is a named constant, not repeated
      literals.
- [ ] Docstring present only if the name/signature don't already say
      everything (§5.3) — and if present, states the *current* reason,
      not a history of how it got there.
- [ ] No inline comment restates what the code already says.
- [ ] Nesting is at most 2-3 levels deep; a guard clause replaces a
      wrapping `if` where possible.
- [ ] If this is a new file: the filename alone tells the next reader
      what's inside (§1).
