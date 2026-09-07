# Writing cleaner, more human-readable code in this repo

`CODE_READING_GUIDE.md` explains how to read what's already here.
`features/architecture.md` explains the design rules (data model, layering).
This one is different: it's a **critical look at what actually hurts
readability in this codebase today**, and concrete rules to write cleaner
code going forward — for you, and for any AI session that touches this repo
after you.

I'm not going to pretend everything here is already clean. Some of it is
genuinely good. Some of it actively works against readability, even though
it was written with good intentions. Both are below.

---

## 1. What's actually good here — keep doing this

- **One consistent shape for every feature** (db → optional pure logic →
  router → template → JS). This is the single biggest reason the codebase
  *can* be read by someone who isn't a full-time developer: once you know
  the shape, you're never starting from zero.
- **Plain dicts, plain SQL, no ORM magic.** A row is a dict with named keys
  you can `print()` and understand instantly. No hidden query-building
  layer to learn on top of Python and SQL.
- **Explicit naming** — `list_notes`, `create_work_allocation`,
  `_apply_status_filter`. You can usually guess what a function does from
  its name alone, without opening it.
- **Every write path has a test.** This one matters more for reliability
  than readability, but reliable code is easier to read *confidently* —
  you don't have to wonder if a function is even correct.

## 2. What actively hurts readability here — stop doing this

### 2.1 Comments that narrate history instead of stating the current rule

This is the biggest problem in the codebase right now. Look at a real
function, `create_task` in `routers/tasks.py`:

```python
# Same defensive-coercion pattern as start_at below -- target_per_day
# is a new Form field too, so any pre-existing direct caller of
# create_task() that doesn't pass it gets the literal Form(...) marker
# object as its default, not a real string.
if not isinstance(target_per_day, str):
    target_per_day = "1"
...
# Defensively coerced, same reasoning/pattern as _combine_tags's own
# tags_labels handling just above -- every pre-existing test in this
# suite (and any other direct caller bypassing FastAPI's real request
# parsing) posts every OTHER Form field explicitly but predates this
# one entirely, so `start_at`'s own `Form("")` default -- a FastAPI
# marker object, not an actual empty string, outside of real request
# handling -- would otherwise blow up the SQL insert below.
if not isinstance(start_at, str):
    start_at = ""
```

Two sentences of genuinely useful information (*"a non-string default here
means the caller bypassed real request parsing; coerce it"*) are buried
inside a paragraph about which past test predates which past field. That
history is true and was worth knowing **at the moment the code was
written** — but it doesn't help you today, and it makes the actual rule
harder to spot. Multiply this pattern across a 1,451-line router file and
a 4,707-line `db.py`, and the signal-to-noise ratio gets genuinely bad.

**The rule going forward:** a comment should describe the **current
invariant or reason**, in present tense, as if you were explaining it for
the first time — not a diary entry about how it got that way. If you're
tempted to write "same pattern as X" or "unlike the old version, which
did Y" — that belongs in the git commit message or `plans/STATE.md`
(which already exist for exactly this purpose), not stacked into the code
forever. The code should read the same whether it's the code's first day
or its thousandth.

Before/after, same information, much less noise:

```python
# Bad (history-as-comment):
# Same defensive-coercion pattern as start_at below -- target_per_day
# is a new Form field too, so any pre-existing direct caller of
# create_task() that doesn't pass it gets the literal Form(...) marker
# object as its default, not a real string.
if not isinstance(target_per_day, str):
    target_per_day = "1"

# Good (states the current rule, no archaeology):
# A caller that skips this Form field gets FastAPI's raw default
# marker, not a string -- coerce it before using it.
if not isinstance(target_per_day, str):
    target_per_day = "1"
```

When you're editing a function that already has a long historical comment
above it: **prune it down to the current reasoning as part of your edit.**
Don't add a third paragraph on top of the first two. Comments should be
maintained like code, not appended to forever.

### 2.2 Files that have grown too large to hold in your head

```
db.py            4,707 lines
routers/dashboard.py  2,564 lines
routers/tasks.py      1,451 lines
routers/calendar.py   1,340 lines
```

`db.py` alone is longer than most entire small apps. This didn't happen on
purpose — each feature added its own accessor functions to the one file
that already existed, which is a reasonable choice feature-by-feature and
a real problem in aggregate.

**The rule going forward — not a rewrite, a habit:** you don't need to
stop and split these files today (that's real, risky, cross-cutting work,
and this repo's own house rule is "no compatibility layer" — a split has
to be done fully, not half-migrated). But treat file size as a smell:
*next time you're already in `db.py` for unrelated work and a function you
need is hard to find, that's the signal it's time to split by domain*
(`db/tasks.py`, `db/events.py`, `db/labels.py`, ... re-exported from a
`db/__init__.py` so every existing `db.list_notes(...)` call site keeps
working unchanged). Don't do it as a side effect of an unrelated bug fix;
do it as its own deliberate, tested slice, same discipline as any other
change in `plans/STATE.md`'s workflow.

### 2.3 Long, flat parameter lists standing in for a real object

```python
def create_task(
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(""),
    start_at: str = Form(""),
    status: str = Form("active"),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    target_per_day: str = Form("1"),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
```

This is FastAPI's own convention for parsing an HTML form (each field its
own typed parameter), so it isn't "wrong" — but it means a function's
signature is 10+ lines before you reach a single line of logic. This is
fine and idiomatic as-is; just know that when a function's parameter list
scrolls off the screen, that's often a sign the function itself is doing
more than one job (parsing the form **and** validating **and** building
the row **and** saving) and could be split into "parse/validate" +
"build the row" + "save", each independently testable and readable on its
own.

### 2.4 Magic strings scattered instead of named once

Status strings like `"active"`, `"done"`, `"waiting"`, filter names like
`"this_week"`/`"overdue"`, and `app_meta` keys are typed as raw string
literals at every call site rather than defined once. `deps.py` already
does this correctly for settings keys (`WEEK_START_KEY = "calendar_week_start"`)
— that pattern should be the norm, not the exception, for any string that
means something specific and is typed more than twice. A typo in a raw
string fails silently (wrong filter, no error); a typo in a constant name
fails loudly (`NameError`) the moment you run it.

## 3. Rules for new/edited code, condensed

1. **Comment the current "why," not the history of how it got there.**
   Prune old reasoning down when you touch a function; don't stack new
   paragraphs on top of old ones. History lives in `git log` and
   `plans/STATE.md`, not in the function body forever.
2. **A function does one job.** If you can't summarize what a function
   does in one sentence without using "and," it's probably two functions.
3. **Guard clauses over nesting.** Return/raise early on the invalid case
   instead of wrapping the valid case in an `if`. Three levels of nested
   `if` is a hard ceiling — if you're about to add a fourth, restructure
   instead.
4. **Name a string once if you use it more than twice.** A status,
   filter value, or config key that appears in more than two places
   becomes a module-level constant, same pattern `deps.py` already uses
   for its `*_KEY` settings names.
5. **Treat file size as a signal, not a rule to enforce mid-fix.** A
   750+-line file is a candidate for splitting the *next* time you're
   properly working in it — plan it as its own slice, don't smuggle it
   into an unrelated bug fix.
6. **Prefer boring code.** This app already avoids frameworks-on-top-of-
   frameworks (no ORM, no JS build step, no templating abstraction beyond
   Jinja) — keep extending that instinct. The easiest code to read is the
   code with the fewest new concepts in it.
7. **Run a formatter so style stops being a decision.** There's currently
   no linter/formatter configured (`pyproject.toml` has no `[tool.ruff]`
   or `[tool.black]` section) — every file's exact spacing/quote-style is
   whatever that session happened to type. Adding `ruff format` (fast,
   zero-config-needed, one dependency) and running it as a final step
   before committing would make every file consistently formatted without
   you or any future session having to think about it. This is optional
   but genuinely the cheapest readability win available — it's a
   15-minute setup, one time, not an ongoing habit to maintain by hand.

## 4. What I'd deliberately *not* change

To be fair in the other direction: the "explain why, not just what" habit
itself is correct and worth keeping — the failure mode above is
*narrating history* inside that habit, not the habit of explaining
reasoning at all. A codebase edited across many disconnected sessions with
no continuous team memory genuinely needs more "why" than a codebase one
person holds in their head — don't over-correct into terse, comment-free
code either. The goal is comments that answer "why is it built this way,"
stated once, in the present tense — not comments that answer "what did
each past session think."
