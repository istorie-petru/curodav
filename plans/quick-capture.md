**Status:** implemented 2026-08-15, layered onto the command palette
(`static/command_palette.js`, `src/quick_capture.py`, `routers/
quick_capture.py`) — see `features/tasks.md` § Search & the command surface
for the outcome writeup and `features/notes.md` for the Notes entity this
introduced. Kept here as the reference grammar/spec, not rewritten into past
tense, per this repo's usual convention for a design doc that outlives its
own implementation slice. Noted simplifications where the shipped v1
narrows the spec: label resolution's "suggested for correction" tier
(between an automatic fuzzy match and a genuinely new label) has no
separate interactive review step yet — an automatic resolution doubles as
the accepted correction (`db.resolve_capture_label`'s own docstring).

### Introduction

Quick Capture is a single-field input method for creating entities without opening a dedicated creation form. Users enter a line of text containing the entity's content and any structured information they want to provide. The input is parsed by recognizing explicit entity markers, dates, times, labels, telephone numbers, and email addresses. The syntax is language-agnostic and relies on explicit structural notation rather than words whose meaning changes between languages.

Entity types are selected through compact markers that may appear anywhere in the input. `!t` creates a task, `!e` creates an event, `!c` creates a contact, and `!n` creates a note. Structured metadata is interpreted independently from the entity type, so dates and time intervals can be used consistently while the marker determines whether the captured entity is a task, event, contact, or note.

### Tasks

Tasks are created using the `!t` marker. The first standalone date following the task content is interpreted as the task's due date. Additional date-and-time ranges are interpreted as scheduled timeblocks for working on the same task. For example, `!t Write bibliography 15/09/2026 2/08 14:00-16:00 5/09 14:00-16:00 8/09 14:00-16:00 #history` creates one task titled “Write bibliography”, with a due date of 15 September 2026 and three separate timeblocks on 2, 5, and 8 September from 14:00 to 16:00.

A task may therefore have multiple timeblocks without creating multiple tasks. Each timeblock is an independent scheduled work period associated with the same task, while the first date remains the task's completion deadline. The presence of one or more timeblocks does not change the entity type: `!t` always produces a task, regardless of how many scheduled intervals are included.

The task syntax supports a mixture of a due date, one or more timeblocks, and labels in a single capture. For example, `!t Finish bibliography 15/09/2026 2/08 14:00-16:00 5/09 14:00-16:00 #history` separates the deadline from the planned work periods while keeping all information attached to one task. A task may also omit either component, allowing `!t Buy textbooks 15/09/2026` to contain only a due date or `!t Read article 2/08 14:00-15:00` to contain a scheduled work period without an explicitly provided deadline.

### Events

Events are created using the `!e` marker. Dates and times are extracted from the input and assigned as the event's temporal information. For example, `!e Medieval History lecture 15/09/2026 10:00-12:00 #university` creates an event titled “Medieval History lecture” beginning at 10:00 and ending at 12:00 on 15 September 2026.

An event may contain a date without a time, a start and end time, or other supported temporal information. Unlike task captures, event time intervals represent the actual occurrence of the event rather than periods reserved for working on it. The parser therefore interprets the same date and time syntax differently according to the explicitly declared entity type.

The `!e` marker may appear anywhere in the input and is removed from the resulting event title. Other recognized values, including labels, remain independent metadata. For example, `!e Debate tournament 20/09/2026 #debate` creates a dated event with the specified label without requiring a time.

### Contacts

Contacts are created using the `!c` marker. The remaining text is interpreted as the contact's identifying information, while recognizable telephone numbers and email addresses are extracted into their corresponding fields. For example, `!c Maria Popescu +40712345678` creates a contact named “Maria Popescu” with the detected telephone number.

Telephone numbers are recognized using supported international formats such as `+40xxxxxxxxx`. Email addresses are recognized using standard email syntax, including forms such as `name.whatever-name@domain.xyz`. Recognized values are extracted independently of their position in the input and are not included in the resulting contact name.

A single contact capture may contain multiple structured values. For example, `!c Maria Popescu +40712345678 maria.popescu@example.com #university` creates one contact containing the name, telephone number, email address, and label. Additional recognized fields can be added without changing the basic capture syntax.

### Notes

Notes are created using the `!n` marker. The text is treated as note content, while supported labels and other explicitly recognized metadata may be extracted separately. For example, `!n Important points from the medieval history lecture #university` creates a note containing the stated text and associates it with the `university` label.

Dates and times appearing in a note do not automatically change the entity type. `!n Reading list for 15/09/2026 #history` remains a note because the `!n` marker explicitly declares the type. Structured syntax should therefore be interpreted according to the rules associated with the selected entity type rather than allowing the parser to override the user's explicit declaration.

The note capture process removes recognized control syntax while preserving the remaining content. This allows notes to be entered naturally while still supporting the same label syntax and other structured capture mechanisms used by the other entity types.

### Labels and Approximate Matching

Labels are specified using the `#label` syntax and may appear anywhere in the capture text. A label is first matched against existing labels using an exact match. If an exact match does not exist, the input is compared against existing labels and known aliases to identify a likely intended value. For example, `#uunniversity`, `#universitty`, or `#unisity` may resolve to the existing `university` label instead of creating separate labels.

Approximate matching should use confidence thresholds. A very close match may be resolved automatically, while an uncertain match should be suggested for correction or left unresolved rather than silently creating or replacing a label. This keeps minor typing mistakes from fragmenting the label system while preserving the ability to create genuinely new labels.

User corrections may also be retained as aliases. Once `universitty` has been explicitly corrected to `university`, future uses of `#universitty` can resolve directly to the existing canonical label. The canonical label remains `university`, while aliases provide an additional layer for recognizing common misspellings and alternative forms.
