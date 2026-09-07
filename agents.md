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

---

## Persistent Task Execution System

This repository includes a persistent task-execution system at `.opencode/` that helps agents complete multi-step tasks reliably.

### Key Files

- **`.opencode/instructions.md`** — Agent workflow instructions (read first)
- **`.opencode/USAGE.md`** — Complete usage guide
- **`.opencode/task_state.py`** — Python module for task state management
- **`webapp/src/task_cli.py`** — CLI entry point (installed as `task-state`)

### Quick Commands (from `webapp/` directory)

```bash
# Create a new task
python -m src.task_cli create <task-id> "<Task Name>" "Desc1" "Criterion1" "Desc2" "Criterion2" ...

# View current task state
python -m src.task_cli summary

# See next incomplete requirement
python -m src.task_cli next

# Mark requirement in progress
python -m src.task_cli start req-1

# Mark requirement complete (with verification)
python -m src.task_cli complete req-1 "Verified by running tests"

# Block a requirement (if stuck)
python -m src.task_cli block req-2 "Waiting for external dependency"

# Check if task is complete (exit code 0=complete, 1=incomplete)
python -m src.task_cli is-complete

# Archive completed task
python -m src.task_cli archive
```

### Agent Workflow

1. **Before starting**: Read `.opencode/instructions.md` → `task-state summary` → `task-state next`
2. **During execution**: Work on one step → verify → `task-state complete req-X "verification"`
3. **Before claiming done**: Re-read all criteria → run `pytest -q` → `git diff` → `task-state archive`
4. **Recovery**: New context reads `task-state summary` → continues from `current_step`

The system provides persistent state that survives context loss, mandatory verification at each step, explicit blocker tracking, and lightweight design without unnecessary bureaucracy.