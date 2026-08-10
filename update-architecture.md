# 1. The Root Hierarchy (The Data Structure)

The entire system is contained within a master workspace. From here, the application is built around **entities** (`Events`, `Tasks`, and `Contacts`) and a flexible **Label** system.

> **Every event, task, and contact is an entity. Entities are classified with typed tags. Spaces are generated dynamically from tags with specific behaviors, while specialized modules like University extend those spaces with domain-specific functionality.**

Entities may remain **untagged**, in which case they exist globally and are accessible through the application's global views. Labels are optional, not mandatory.

### Spaces

A **Space** is **not** a stored object. It is a dynamic page generated from a Label that has the **Generate Space** behavior enabled.

Each generated Space enables a configurable set of modules depending on its purpose.

For example:

* **University** (generated from the `University` label)

  * Schedule
  * Events
  * Tasks
  * Contacts
  * Grades
  * Exams
  * Semester management
* **Personal** (generated from the `Personal` label)

  * Events
  * Tasks
  * Contacts
* **Writing**, **Debate**, **Research**, etc.

  * Each enables only the modules appropriate for that space.

This replaces the previous concept of a "Minimal Space." Every Space is built from the same underlying system, with functionality determined only by its enabled modules.

---

## University Space

The **University** Space is the primary specialized implementation.

Besides the common entity views (`Events`, `Tasks`, `Contacts`), it includes dedicated academic modules.

The most important is the **Schedule** module.

Unlike ordinary calendar events, the Schedule is a complete subsystem that generates semester timetables. During initial setup, the user configures courses, professors, rooms, recurrence patterns, semesters, and other academic information. From this, the Schedule automatically generates all corresponding calendar events while maintaining relationships with courses, professors, and other academic data.

This allows academic scheduling to remain structured instead of simply storing recurring calendar events.

---

# 2. The Relational Logic (The Network)

The core of the application is not the dashboard, but the relationship network built on Labels.

Labels supersede the underlying WebDAV / CalDAV storage by providing semantic relationships between entities while remaining independent from synchronization.

Each Label may optionally define one or more **behaviors**.

Examples include:

* **Generate Space**

  * Creates a dynamic Space page that aggregates every related entity.
* **Enable Modules**

  * Determines which modules are available inside that generated Space (Schedule, Grades, Semester, etc.).
* **Dashboard Presets**

  * Defines the default dashboard configuration for that Space.
* Additional behaviors can be added in the future without changing the underlying data model.

For example, the `University` label may generate a University Space with academic modules enabled, while `Personal` generates a Personal Space exposing only the common modules.

Labels that do not define behaviors simply act as organizational metadata.

For example:

* `Essay`
* `Conference`
* `20th Anniversary`

These labels provide filtering, organization, searching, dashboard aggregation, and cross-linking without generating dedicated Spaces.

The application intentionally does **not** separate labels into different categories. All labels are fundamentally the same object. Their behavior is determined solely by their configured behaviors rather than belonging to predefined label classes.

---

## Entity Relationships

Every entity may have zero or multiple Labels attached.

Examples:

* A task may be labeled:

  * University
  * Historiography
  * Essay

* An event may be labeled:

  * Personal
  * Family

* A contact may be labeled:

  * University
  * Professor

Spaces are simply dynamic aggregations of every entity carrying the corresponding Label, allowing the same entity to naturally appear wherever it is relevant without duplication.
