# AGENTS.md

Guidance for AI coding agents working in this repository. CLAUDE.md points
here; this file is the single source.

## Project

`aiopynautobot` - a fully async Nautobot API client, built from scratch with
httpx. It is inspired by [pynautobot](https://github.com/nautobot/pynautobot)
(the sync client maintained by Network to Code) but is **not a port**:
pynautobot's core ergonomics depend on sync-only Python protocols that cannot
be awaited, so the API surface here is deliberately different (see Design
constraints below).

It is also the sister project to
[aiopynetbox](https://github.com/challey74/aiopynetbox), same author, same
design constraints, same layout. **aiopynetbox is the reference implementation
for anything that isn't Nautobot-specific** - match its structure, naming, and
idiom rather than inventing new ones, and port fixes between the two.

Package layout: `src/aiopynautobot/`, tests in `tests/`. Managed with `uv`.

**Status: 0.1.0, feature-complete against pynautobot.** [PLAN.md](PLAN.md)
tracks the phases; all of them are done, and the decisions they resolved are
recorded at the bottom of that file.

## Commands

- `uv sync` - install/update the environment (Python 3.11+)
- `uv run pytest` - run tests (`uv run pytest tests/test_foo.py::test_bar` for one test)
- `uv run ruff check` / `uv run ruff format` - lint and format (line length 88, isort + ASYNC lint rules enabled)
- `uv run pyright` - type check (src only)

pytest-asyncio runs in `asyncio_mode = "auto"` - async test functions need no decorator.

## Design constraints (why this isn't just "pynautobot with await")

These pynautobot behaviors are impossible or wrong in async and must NOT be replicated:

1. **Lazy attribute fetch** - pynautobot's `Record.__getattr__` transparently GETs the full object when you touch a missing attribute (`device.location.parent` may fire HTTP). `__getattr__` cannot be async. Here, fetching full details must be explicit: `await record.full_details()`.
2. **`len()` on result sets** - pynautobot's `filter()` returns an eagerly-materialized `list`, so `len()` is free but every query drains all pages up front. Result sets here are lazy; expose `await recordset.count()`.
3. **Sync pagination** - pynautobot's `Request.get()` loops `next` links inline and returns a list. Result sets here are async iterators (`__aiter__`/`__anext__`, consumed with `async for`).
4. **Properties that do I/O** - pynautobot's `Api.version` is a property that makes a request. Properties can't await; use methods (`await nb.version()`).
5. **Threading** - pynautobot bolts on `threading=True` + ThreadPoolExecutor for concurrent page fetches. Not needed: use `asyncio.gather` for page fan-out after the first page reveals the count.
6. **Blocking sleep in polling** - `JobsEndpoint.run_and_wait()` calls `time.sleep()`. Use `asyncio.sleep()`.

pynautobot ideas worth keeping (they're pure Python, no I/O): app/endpoint
attribute traversal (`nb.dcim.devices`), diff-based `save()` (snapshot at parse
+ `serialize()` diff -> PATCH only changed fields), endpoint-name-to-Record-subclass
mapping, the `JsonField` marker for fields that must stay raw dicts, and its
exception taxonomy (RequestError/ContentError/AllocationError).

## Nautobot vs NetBox (do not copy aiopynetbox blindly)

aiopynetbox is the structural reference, but these behaviors are
NetBox-specific and must **not** be carried over:

- **`nbt_` v2 tokens / `Bearer` auth** - NetBox 4.5+ only. Nautobot uses `Authorization: Token <token>` unconditionally. There is also no `/users/tokens/provision/` equivalent to `Api.create_token()`.
- **ETag optimistic locking** - `If-Match` / `If-None-Match` / 412 / 304 is NetBox 4.6+. Nautobot sends no `ETag` on detail responses (verified against demo.nautobot.com), so drop `_etag`, the conditional headers, and the 304 path.
- **Cursor pagination** - the `start` cursor is NetBox 4.6+. Nautobot is limit/offset only. Concurrent offset fan-out still applies.
- **`/api/schema/`** - Nautobot serves its OpenAPI document at `/api/swagger.json` (drf-spectacular, content type `application/vnd.oai.openapi+json`), and **requires a token to read it**, unlike demo.netbox.dev. Its schema paths also omit the `/api` prefix, which lives in the document's `servers` entry instead, so aiopynetbox's `^/api/...` list-path regex matches nothing here.

And these are Nautobot-specific additions with no NetBox counterpart:

- **UUID primary keys.** `get(pk)` takes a UUID string, not an int. Bulk delete/update payloads carry UUID `id`s. Nothing should assume `int`.
- **REST API versioning.** `Accept: application/json; version=<x.y>` pins the API contract. pynautobot exposes this as `Api(api_version=...)` plus a per-call `api_version=` override; the header is otherwise absent and the server picks its default.
- **Default filters.** `Api(exclude_m2m=..., include_default=...)` (Nautobot 2.4+) become `exclude_m2m` / `include` query params merged into every get/filter/all.
- **AllocationError fires on 204, not 409.** Nautobot returns `204 No Content` from `available-ips` / `available-prefixes` when there is no room.
- **GraphQL is first-class.** `nb.graphql.query(query, variables)` POSTs to `/api/graphql/`, and saved queries run via `/api/extras/graphql-queries/<id>/run/`. Nautobot's 400 responses carry an `errors` array, which pynautobot wraps in `GraphQLException`.
- **Jobs.** `/api/extras/jobs/<id-or-name>/run/` plus polling the resulting job result until its status leaves `RECEIVED`/`PENDING`/`STARTED`/`RETRY`.
- **`notes` detail endpoint** hangs off nearly every object, so it belongs on the base `Record`, not a subclass.
- **App-level helpers** with no NetBox analogue: `app.get_custom_fields()`, `app.get_custom_field_choices()` (both paginated, so both drain `next` links), `app.config()`. pynautobot's `app.choices()` is deliberately absent: `/<app>/_choices/` 404s on Nautobot 3.x.
- **Apps whose names contain dashes**: `data-validation` and `load-balancers` are reached as `nb.data_validation` / `nb.load_balancers`. The full set is circuits, cloud, core, data_validation, dcim, extras, ipam, load_balancers, tenancy, users, virtualization, vpn, wireless (core and load_balancers are absent from pynautobot).
- **Two OPTIONS choice formats.** Nautobot <= 2.3 returns `schema.properties[field].enum` / `.enumNames`; 2.4+ returns `actions.POST[field].choices`, and for list fields `actions.POST[field].child.choices`. aiopynetbox handles only the middle case.

## Architecture

All HTTP funnels through `Api._request_response()` ([api.py](src/aiopynautobot/api.py)):
auth header, the `Accept: application/json; version=` pin, User-Agent,
`default_filters` injection (GET and POST only, explicit params winning, and
merged into the url rather than passed to httpx, which would otherwise replace
a `next` link's own query string),
error raising (POST 204 -> `AllocationError`, other non-success ->
`RequestError`), and the retry loop (429 for any method honoring
Retry-After; 502/503/504 and `httpx.TransportError` for GET only, since
ambiguous writes may have been processed; `Api(retries=)` bounds attempts,
`_backoff()` does capped exponential backoff with jitter) all live there and
nowhere else. `Api._request()` adds JSON decoding (`_decode` -> `ContentError`).

`App.__getattr__` ([app.py](src/aiopynautobot/app.py)) turns any attribute into
an `Endpoint` ([endpoint.py](src/aiopynautobot/endpoint.py)), which builds URLs
(`_`->`-`) and returns `Record`/`RecordSet` ([response.py](src/aiopynautobot/response.py)).
Under `extras` only, `jobs` and `graphql_queries` resolve to `JobsEndpoint` /
`GraphqlEndpoint` instead, so a same-named plugin endpoint elsewhere is not
silently given a `run()`. `PluginsApp` routes `nb.plugins.<app>` into
`/api/plugins/<app>/`.

`Endpoint.__init__` resolves its Record subclass from `ENDPOINT_MODELS` in
[models.py](src/aiopynautobot/models.py) (`"<app>/<endpoint>"` keys).
`register_model()` is the public way to add entries. Path segments that come
from the caller (pk, job id/name, query id) go through `_segment()` in
endpoint.py, which is `quote(..., safe="/&")`: natural keys can contain `?`,
`#` and spaces, while job class paths contain slashes and composite natural
keys join their parts with `&`.

Import order is api -> app -> endpoint -> models -> response, and response only
TYPE_CHECKING-imports the others. **`DetailEndpoint` lives in response.py, not
models.py** (where aiopynetbox puts it) because `Record.notes` needs it on the
base class; putting it in models.py would make models and response mutually
importable. For the same reason `Jobs.run()` and `GraphqlQueries.run()` go
through `DetailEndpoint` rather than importing `JobsEndpoint`.

Key mechanics in `response.py`:

- `Record` snapshots `serialize()` (deep-copied) after every parse; `updates()` diffs current vs snapshot, with pynautobot's custom_fields merge semantics (only keys present now are compared). `save()` PATCHes only the diff to `record.url`.
- `serialize()` collapses nested Records to `id`, falling back to `value` (choice fields). `JSON_FIELDS` is a per-subclass frozenset (base: custom_fields, computed_fields, relationships) naming fields that stay plain dicts; subclasses extend it with `Record.JSON_FIELDS | {...}`. Prefer extending a subclass over widening the base, since Nautobot's raw-JSON field names (`data`, `filter`, `config`, `meta`) are far too generic to blanket-exempt.
- Records created by endpoint methods are `full=True`; nested ones are brief - missing attrs on brief records raise AttributeError pointing at `full_details()`. `_parse()` re-raises the opaque AttributeError from `setattr` onto a property (notes, napalm, elevation, ...) naming the field and the class.
- `RecordSet._iter()` fetches page 1, then fans out remaining offsets through a **sliding window** of at most `Api.max_concurrency` (default 4) tasks: the next task is created only as one is awaited, so breaking out early neither fetches nor buffers the rest; the `finally` cancels what is still in flight. It yields in offset order. Three response shapes are handled: a paginated envelope, a bare list (available-ips), and a plain object with no `results` key (device napalm), which yields exactly one record and counts as 1. An `offset` from either the constructor or the filters pins the query to one page, or the fan-out would duplicate records.
- `Record.__eq__`/`__hash__` key on `(url, id)`; records lacking either (choice fields) fall back to identity. This is deliberately not pynautobot's `(endpoint.name, id)`, which collides across plugin endpoints of the same name.
- `Endpoint.choices()` caches on the Endpoint **instance**, and attribute access builds a fresh Endpoint each time, so the cache only helps when a reference is held. Tests assert both halves of that.
- Job result status is a choice field, so `str(status)` gives the human label ("Pending"), not the Celery state ("PENDING"). the module-level `_status_value()` in endpoint.py reads `.value`; never compare `str(status)` against the state constants.

Typed endpoint hints live in [apps_generated.py](src/aiopynautobot/apps_generated.py)
and [hints_generated.pyi](src/aiopynautobot/hints_generated.pyi) - both GENERATED
by `scripts/generate_endpoints.py` from demo.nautobot.com's OpenAPI schema
(the demo's documented read-only token is the script's default, since Nautobot
authenticates every route), never edited by hand; a weekly workflow
(regenerate-endpoints.yml) opens a PR on drift. The per-app subclasses hold bare
class annotations (static analysis only, no runtime attributes); `App.__getattr__`
remains the real mechanism, so unlisted endpoints still work. hints_generated.pyi
is stub-only (never imported at runtime, hence pyright's reportMissingModuleSource
is disabled): per-endpoint TypedDicts (values Any, name-completion only) feed
Unpack overloads on filter/get/count/create, each with a `**kwargs: Any` fallback
overload so cf_* filters, lookup expressions, and app params stay legal.

Two traps when touching the generator, both covered by
[tests/test_generated.py](tests/test_generated.py):

- The `create` fallback overload must return `Record | list[Record]`, exactly the base signature. Narrowing it to `list[Devices]` makes pyright reject the whole override, because `list` is invariant.
- `extras/jobs` and `extras/graphql_queries` are `JobsEndpoint`/`GraphqlEndpoint` at runtime, so their stubs must subclass the same (via the generator's `ENDPOINT_BASES`), or `run()` disappears from the hints.

Tests run entirely against `FakeNautobot` in [tests/conftest.py](tests/conftest.py) -
an in-memory Nautobot behind `httpx.MockTransport` (no network, no mocking
library). Extend it when adding endpoints/behaviors.

Not implemented yet (deliberately, add only when needed): OpenAPI filter
validation, file uploads (multipart), integration tests against a live
Nautobot.

## Conventions

- httpx `AsyncClient` is the only HTTP transport; the client should be usable as an async context manager (`async with aiopynautobot.api(...) as nb:`) so the connection pool is closed deterministically. The context manager is one-shot; `aclose()` closes only clients the Api created - a `client=` passed in is the caller's to close (httpx convention).
- No sync wrapper/facade unless explicitly requested.
- Fully type-annotated, `from __future__ import annotations` everywhere, ships `py.typed`.
- Tests run against an in-memory fake behind `httpx.MockTransport` - no network, no mocking library.
- Never vendor pynautobot or pynetbox code without carrying its Apache 2.0 header and updating [NOTICE](NOTICE).
