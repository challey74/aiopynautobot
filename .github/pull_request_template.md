## What does this change?

<!-- A sentence or two. Link the issue if there is one. -->

## Why?

<!-- What problem does it solve, or what Nautobot behavior does it match? -->

## Checklist

- [ ] `uv run pytest` passes
- [ ] `uv run ruff check` and `uv run ruff format --check` pass
- [ ] `uv run pyright` passes
- [ ] New behavior has tests, extending `FakeNautobot` in `tests/conftest.py` if needed
- [ ] User-visible changes have a `CHANGELOG.md` entry under Unreleased
- [ ] If this changes the async API surface, it does not reintroduce implicit I/O (see the design constraints in `AGENTS.md`)
