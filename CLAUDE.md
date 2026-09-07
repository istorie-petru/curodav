# Working on this repo

Read [`documentation/plans/STATE.md`](documentation/plans/STATE.md) first, and
only that, before doing anything else. It has the current release position,
the next slice to build, and the session workflow (one slice per session,
cheap verification, update STATE.md + commit at the end). Don't read
`documentation/plans/roadmap.md`, `documentation/plans/open-priority.md`, or
`documentation/plans/open.md` in full — STATE.md tells you which section of
which file is relevant to the current slice.

Test command: `cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q`.
All tests green or a change isn't done.
