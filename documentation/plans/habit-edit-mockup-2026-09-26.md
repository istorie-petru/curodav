# Habit edit modal ("Do it") -- text mockup for Peter's review

Status: **proposal, not built.** Peter asked (2026-09-26) for a text mockup
of the "Do it" edit modal to judge before it's implemented. Problems it
answers, in his words: items that don't take 100% width, non-custom
dropdowns, day chips instead of a dropdown checkbox menu, lots of useless
text.

Rules the mockup follows:

- Every control is full width, one per row. No side-by-side fields.
- Every choice is the app's own dropdown (`_widget_list_multiselect.html`
  trigger + portaled panel). No native `<select>`, no pills or chips in
  the modal body.
- No hint or helper text under any field. A dropdown's own trigger text
  says what it's set to.
- A sub-field appears only when its parent choice needs it, directly
  under that parent.

Already shipped the same day and kept as they are: Kind as a dropdown,
Look (colour + icon) as one dropdown, no hint text.

## Default state (a new "Do it" habit)

```
+------------------------------------------------------------+
| Edit habit                                               x |
+------------------------------------------------------------+
| TITLE                                                      |
| [ Meditate                                               ] |
|                                                            |
| LOOK                                                       |
| [ (moon) Purple . Moon                                 v ] |
|                                                            |
| KIND                                                       |
| [ Do it                                                v ] |
|                                                            |
| HOW OFTEN                                                  |
| [ Every day                                            v ] |
|                                                            |
| DAILY GOAL                                                 |
| [ Check it off once                                    v ] |
|                                                            |
| REMINDER                                                   |
| [ No reminder                                          v ] |
|                                                            |
| DESCRIPTION                                                |
| [                                                        ] |
|                                                            |
| Work sessions  +                                           |
+------------------------------------------------------------+
| < Cancel                              Delete    [ Save ]   |
+------------------------------------------------------------+
```

Order: what it is (Title, Look, Kind), then when (How often), then how
much (Daily goal), then the nudge (Reminder). Description drops to the
bottom because it's optional and rarely used.

## How often: the sub-row follows the choice

Options in the HOW OFTEN panel:

```
  (o) Every day
  ( ) On certain days
  ( ) Times a week
  ( ) Times a month
  ( ) Every 2 weeks (current)      <- only when the stored rule is unusual
```

**On certain days** adds one full-width checkbox dropdown right below it.
Days run in the Settings week order; the trigger summarises the pick:

```
| HOW OFTEN                                                  |
| [ On certain days                                      v ] |
| [ Mon, Wed, Fri                                        v ] |
|   +----------------------------------------------------+   |
|   | [x] Monday                                         |   |
|   | [ ] Tuesday                                        |   |
|   | [x] Wednesday                                      |   |
|   | [ ] Thursday                                       |   |
|   | [x] Friday                                         |   |
|   | [ ] Saturday                                       |   |
|   | [ ] Sunday                                         |   |
|   +----------------------------------------------------+   |
```

Trigger summaries: "Mon, Wed, Fri" / "Weekdays" / "Weekends" /
"Every day" (all seven ticked).

**Times a week / Times a month** adds one full-width single dropdown:

```
| [ Times a week                                         v ] |
| [ 3 times a week                                       v ] |   1..6
```
```
| [ Times a month                                        v ] |
| [ 2 times a month                                      v ] |   1..20
```

## Daily goal: check-off or an amount

```
  (o) Check it off once
  ( ) An amount...
```

**An amount...** adds two full-width rows below it, the number first:

```
| DAILY GOAL                                                 |
| [ An amount                                            v ] |
| [ -                        8                         +  ] |   stepper, full width
| [ glasses                                                ] |   unit, placeholder "unit"
```

## Reminder

Unchanged: the existing half-hour list plus "No reminder".

## "Avoid it"

Kind = Avoid it hides How often, Daily goal and Reminder. What's left:
Title, Look, Kind, Description, Work sessions.

## Questions for Peter

1. Description at the bottom, or cut from the habit form entirely? The
   view modal shows it, but habits rarely need one.
2. Daily goal as "check-off vs amount" plus a stepper, or a single
   number stepper where 1 means a check-off (fewer rows, less obvious)?
3. Should Work sessions be a collapsed row ("Work sessions . 2  >")
   rather than the full section? That would keep the form short when
   there are many.
