# Schedule, Recurrence, and Academic Projects

The existing Schedule system should be reworked around the application's general event and label model rather than remaining a separate conceptual entity. A university class is fundamentally a recurring event associated with a project-enabled label. A course such as `Historiography` can therefore be represented by a project label covering the semester, with its regular lectures and seminars represented as recurring calendar events carrying that label. The course can simultaneously contain tasks, work allocations, and ordinary events related to the same project.

This means that a university course does not require a special class entity. The existing Schedule functionality becomes a specialized interface for creating and managing recurring events efficiently. It should continue to support the existing requirements of university timetables, including weekday schedules, alternating even/odd weeks, holidays, and conflict detection, but these are properties of recurring events and their recurrence rules rather than properties of a fundamentally different "class" object.

A project-enabled course label can therefore contain several kinds of information at once. Its recurring class events represent the institutional schedule, while its tasks represent work required for the course and its ordinary events represent additional activities such as guest lectures, office hours, examinations, or meetings. Work allocations can schedule time spent on those tasks. All of these entities share the same project label and consequently appear together in the course's project views without losing their individual semantics.

The recurrence system itself should be generalized so that any recurring event can specify how it behaves on non-working days. The system should not encode university-specific holiday behavior into the event model. Instead, recurrence rules should support a configurable non-working-day policy that determines whether occurrences falling on excluded dates are skipped.

Holiday calendars should be managed manually in Settings rather than retrieved automatically from an external service. The user can define the relevant non-working dates for each year, allowing the application to remain deterministic and avoiding dependence on external holiday databases. A holiday calendar can therefore contain the dates relevant to the user's country, university, workplace, or personal schedule. The settings interface should make it easy to create and maintain the calendar for each year.

Recurring events can then specify whether they respect the configured holiday calendar. This should be independent from weekend handling. A recurring event may exclude configured holidays while continuing to occur on weekends, exclude weekends while ignoring holidays, exclude both, or ignore both entirely. This allows the same recurrence engine to represent university classes, ordinary working schedules, personal routines, continuous operations, and other recurring activities without introducing separate scheduling systems.

The recurrence editor should therefore expose controls conceptually similar to:

`Holiday policy: None / Configured holidays / Custom`

and:

`Exclude Saturday: On/Off`
`Exclude Sunday: On/Off`

The exact interface can be simplified where appropriate, but the underlying data should retain these as independent constraints. A recurring event that belongs to a university course can, for example, use the manually maintained university holiday calendar and exclude weekends, while a recurring personal event can ignore both.

The terminology used for these settings should itself be configurable. The application should provide a conventional terminology mode suitable for a serious productivity application, while optionally allowing a playful terminology mode. For example, the conventional interface may use `Exclude public holidays` and `Exclude weekends`, while the playful mode may label the corresponding controls `Respects Labor Laws` and `Marx Weekend`. These labels are presentation-layer choices only. The database and internal APIs should retain neutral semantic names such as `exclude_holidays`, `exclude_saturday`, and `exclude_sunday`, so the terminology can change without affecting the underlying model.

This rework also makes the existing university timetable significantly less isolated from the rest of the application. The timetable is no longer a separate source of "class objects" that happen to produce calendar events. It is a convenient interface for defining recurring events within project contexts. Once those events exist, they participate in the same calendar, label, relation, and project systems as every other event. The specialized Schedule interface remains because manually creating dozens of recurring class events would be absurd, but the resulting data follows the application's general event model.
