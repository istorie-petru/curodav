# Plan: Deferred / out-of-scope systems

**Status:** Not started, not scheduled — kept as a record of what was deliberately cut and why, so it isn't accidentally re-proposed without re-litigating the reasons below.

These were scoped out at the very first design pass (see [`systems/decisions-log.md`](systems/decisions-log.md)) and reconfirmed when the app was reworked from Flutter to PySide6. None of the current codebase (`desktop/src/`) touches them.

| Feature/system | Why deferred |
|---|---|
| Media tracker (TMDB / AniList / Steam integration) | Independent maintenance liability — external APIs churn, doesn't touch the core object model. Originally "Phase 5" in the pre-rework roadmap. |
| Infrastructure dashboard (Proxmox / Docker / Uptime Kuma) | Same as above — server-side pollers, external API surface, no relation to the core app. |
| Mobile (Android/iOS) | Abandoned outright in the PySide6 rework, not just deferred — Qt Widgets is a desktop-shaped UI toolkit; a mobile client would need a different UI layer entirely, not just a port. |
| Multi-user / sharing / teams / RBAC | Single-user is a load-bearing simplification (see `systems/architecture.md` §1.2) — adding this would touch the data model, the sync model, and every feature. |
| Real-time collaborative editing (CRDTs) | Not needed without multi-user; HLC/LWW per-field merge is sufficient for one person on N of their own devices. |
| Push notifications (FCM/APNs) | No mobile client, no server — tray notifications (`core/notifications/`) cover the single-desktop-app case. |
| Public API | No server to expose one from. |
| Budget tracking | Never speced past a name-check in the original ten-module wishlist. |
| Per-instance recurring-event exceptions | Calendar recurrence expands a master RRULE client-side; editing a single occurrence (vs. the whole series) needs an exception model that wasn't built. |

If any of these get picked back up, start by writing a proper plan doc here (replacing its row above with a link), not by reopening this file's row as the spec.
