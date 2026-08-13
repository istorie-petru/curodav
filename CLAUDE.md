# Working on this repo

Read [`plans/STATE.md`](plans/STATE.md) first, and only that, before doing
anything else. It has the current release position, the next slice to build,
and the session workflow (one slice per session, cheap verification, update
STATE.md + commit at the end). Don't read `plans/roadmap.md`,
`plans/open-priority.md`, or `plans/open.md` in full — STATE.md tells you
which section of which file is relevant to the current slice.

Test command: `cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q`.
All tests green or a change isn't done.
