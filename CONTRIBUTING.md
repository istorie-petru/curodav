# Contributing to Curodav

Thanks for taking a look. Curodav is a single-user, self-hosted app with a small, deliberately narrow scope — read the [Architecture](../../wiki/Architecture) page on the Wiki before proposing anything that adds a new top-level concept; it explains the guiding rule the whole data model follows and why a lot of "obvious" additions have already been considered and rejected.

## Before you start

- **Read the [Architecture](../../wiki/Architecture) page.** It's the rulebook for how a feature gets built here, and it'll save you from rebuilding something that already exists in a different shape.
- **Read [Code Style & Structure](../../wiki/Code-Style-and-Structure) and the [UI Design Guide](../../wiki/UI-Design-Guide)** before writing any code or markup. This codebase has a consistent, deliberate shape; a change that doesn't follow it will need to be redone before it can merge.
- **For anything nontrivial, open an issue first** describing what you want to change and why, before writing code. It's a lot cheaper to align on scope up front than to rework a finished PR.

## Development setup

See [Getting Started](../../wiki/Getting-Started) on the Wiki for running the app locally.

## Running the tests

```bash
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q
```

The whole suite has to be green before a change is considered done — a change that breaks an existing test needs the test updated in the same change, not left red.

## Making a change

1. Fork the repository and create a branch for your change.
2. Follow the shape described in [Architecture](../../wiki/Architecture) — a feature is a vertical slice (data layer, optional pure logic, router, template, optional JS), each with its own test file.
3. Add or update tests for anything you change. See [Code Style & Structure](../../wiki/Code-Style-and-Structure) for what a good test looks like here.
4. Run the full test suite and make sure it passes.
5. Write commit messages that say what changed and why, in the same spirit as the in-code comments the style guide describes — not "wip" or "fix".
6. Open a pull request describing the change and linking any relevant issue.

## Code style

Covered in full on the Wiki:

- [Code Style & Structure](../../wiki/Code-Style-and-Structure) — naming, comments, file organization
- [UI Design Guide](../../wiki/UI-Design-Guide) — the one canonical pattern per UI piece

The short version: comment the current reason something is built a certain way, not the history of how it got there; a filename should say what's inside it without opening the file; and before adding a new UI pattern that's a near-copy of an existing one, check whether one already covers your case.

## Reporting bugs

Open a GitHub issue with steps to reproduce, what you expected, and what actually happened. If it's a security issue, see [`SECURITY.md`](SECURITY.md) instead — please don't open a public issue for it.

## License

By contributing, you agree that your contributions will be licensed under the project's [AGPL-3.0 license](LICENSE).
