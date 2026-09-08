# Documentation

All project documentation lives here, organized by state, not by history.
GitHub renders this page automatically when you browse this folder.

| Doc | What it is |
|---|---|
| [`plans/STATE.md`](plans/STATE.md) | **Start here.** Current position on the roadmap, the next slice, and how to run a low-token session. Read only this at session start |
| [`webapp.md`](webapp.md) | The webapp subproject's own README — dev setup, running the pieces separately, env vars |
| [`features/README.md`](features/README.md) | Tour of what you can do today; links each area to its technical doc |
| [`features/architecture.md`](features/architecture.md) | The rulebook — data model, layering, design system, how a feature gets in. **Read this before touching code** |
| [`CODE_READING_GUIDE.md`](CODE_READING_GUIDE.md) | Plain-language guide to how files are structured and named, for editing the code yourself |
| [`CLEAN_CODE_GUIDE.md`](CLEAN_CODE_GUIDE.md) | Honest critique of what hurts readability today (giant files, history-as-comments) + rules for writing cleaner code going forward |
| [`CODING_STANDARDS.md`](CODING_STANDARDS.md) | Reference for naming files/functions/variables and where comments belong (file/class/function/inline) and how much |
| [`UI_CONSISTENCY_GUIDE.md`](UI_CONSISTENCY_GUIDE.md) | One canonical pattern per UI piece — cards, buttons, forms, tables, modals, tags, toolbars, empty states — and the "ask before inventing a new one" rule |
| [`SETTINGS_UI_GUIDE.md`](SETTINGS_UI_GUIDE.md) | Settings-specific canon: which layout for preferences vs. managed records vs. logs, and a reorg proposal for Advanced/Data health/Sync conflicts |
| [`plans/roadmap.md`](plans/roadmap.md) | The single build order across all open work, phased by release |
| [`plans/open-priority.md`](plans/open-priority.md) | Open work that reshapes the architecture/presentation (the rework) |
| [`plans/open.md`](plans/open.md) | Open work that is low-priority or app-local |
| [`plans/abandoned.md`](plans/abandoned.md) | What was deliberately cut or superseded, and why — plus the versioning/phase history |
| [`plans/quick-capture.md`](plans/quick-capture.md) | Quick-capture syntax spec |
| [`plans/ofline-first-pwa.md`](plans/ofline-first-pwa.md) | Offline-first PWA plan |
| [`plans/sidebar-redesign.md`](plans/sidebar-redesign.md) | Sidebar redesign plan |

The distinction matters: `features/` describes shipped behavior, `plans/`
tracks what hasn't shipped yet, and `plans/abandoned.md` records why things
won't come back without being re-litigated.

Two files are deliberately **not** here: root [`README.md`](../README.md)
(GitHub only renders a repo's landing page from the actual root) and root
[`CLAUDE.md`](../CLAUDE.md) / [`agents.md`](../agents.md) (tooling-convention
files that AI coding agents auto-load from the repo root — moving them would
break that auto-load, not just a link).
