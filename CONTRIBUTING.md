# Contributing

Thanks for your interest in aiopynautobot.

## Development setup

The project is managed with [uv](https://docs.astral.sh/uv/) and requires
Python 3.11+:

```sh
uv sync              # install the environment
uv run pytest        # run the test suite
uv run ruff check    # lint
uv run ruff format   # format
uv run pyright       # type check
```

All four checks run in CI and must pass.

## Testing conventions

Tests run entirely against `FakeNautobot` in `tests/conftest.py`, an
in-memory Nautobot served through `httpx.MockTransport`. Tests never touch
the network and never require a real Nautobot instance. If your change needs
an endpoint or behavior the fake doesn't model yet, extend the fake.

New features and bug fixes should come with tests.

## Design constraints

This library deliberately differs from pynautobot: all I/O is explicit and
awaitable. Before proposing API changes, read the design constraints in
[AGENTS.md](AGENTS.md), particularly the list of pynautobot behaviors that
must not be replicated (lazy attribute fetches, `len()` that does I/O,
properties that make requests).

Neither pynautobot nor pynetbox code is vendored here. If that ever changes,
the vendored file must keep its original copyright notice and Apache License
2.0 header, and [NOTICE](NOTICE) must be updated.

## Commits and pull requests

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`, ...).
- Keep changes focused; unrelated refactoring belongs in its own PR.
- User-visible changes get a line in `CHANGELOG.md` under Unreleased.
