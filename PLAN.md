# Plan: bringing aiopynautobot to pynautobot parity

The goal is the relationship aiopynetbox has with pynetbox: cover what
pynautobot covers, in an API surface redesigned so that every network call is
explicit and awaitable. aiopynetbox is the structural reference for everything
that isn't Nautobot-specific; this plan is mostly about the deltas.

Each phase has a success criterion. Phases 1 to 4 are the minimum for a usable
0.1.0; 5 to 8 are what make it a peer of pynautobot.

**Status as of 0.1.0: all phases done.** 120 tests pass with ruff, ruff format,
and pyright clean. The decisions the plan left open are recorded under Open
questions at the bottom.

---

## Phase 0: scaffold (done)

uv project, `src/` layout, ruff + pyright + pytest config, CI matrix over
Python 3.11 to 3.14, license/notice/contributing/security/changelog, and
`AGENTS.md` with the design constraints.

**Verify:** `uv sync && uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest` all pass.

---

## Phase 1: transport core (done)

`exceptions.py` and `api.py`. Port aiopynetbox's `Api` and strip the
NetBox-only parts.

- `Api(url, token=None, *, timeout, max_concurrency, retries, api_version=None, exclude_m2m=None, include_default=None, client=None)`.
  - Base URL is `{url}/api`. Async context manager; `aclose()` only closes a client the `Api` created.
  - Auth header is always `Authorization: Token <token>`. **Drop** the `nbt_`/`Bearer` v2 branch and `create_token()` - both are NetBox-only.
  - `api_version` sets `Accept: application/json; version=<x.y>` on every request, with a per-call override threaded through `_request_response`. Absent means the server picks.
  - `exclude_m2m` / `include_default` populate `self.default_filters` (`exclude_m2m`, `include`), merged into read query params. pynautobot merges these into get/filter/all/create/detail-endpoint calls but *not* into `count()`; match that, or fix it deliberately and note it.
  - Set a `User-Agent` of `python-aiopynautobot/<version>`, as pynautobot does.
- Single `_request_response()` chokepoint: merged headers, retry loop, error raising. `_request()` adds JSON decoding.
  - Retries: 429 for any method honoring `Retry-After`; 502/503/504 and `httpx.TransportError` for GET only. Capped exponential backoff with jitter. Same as aiopynetbox.
  - **`AllocationError` fires on `204 No Content` from a POST**, not 409. This is the one error-mapping difference from aiopynetbox and it is easy to get wrong.
  - **Drop** all ETag handling: no `If-Match`, no `If-None-Match`, no 412/304 paths. Nautobot sends no `ETag` (verified against demo.nautobot.com).
- `await nb.version()` reads the `API-Version` response header from `/api/`. Nautobot demo returns 403 without a token but still sets the header, so accept 403 the way aiopynetbox does.
- `await nb.status()` -> `/api/status/`. `await nb.openapi()` -> **`/api/swagger.json`**, cached in memory.

**Verify:** unit tests over `httpx.MockTransport` for auth header, `api_version` header (global and per-call), default-filter injection, each retry class, 204-to-`AllocationError`, and non-JSON-to-`ContentError`.

---

## Phase 2: app and endpoint traversal (done)

`app.py` and `endpoint.py`, ported from aiopynetbox with Nautobot's app list.

- `App.__getattr__` -> `Endpoint`, `_` to `-` in the slug. `App.endpoint(name)` keeps literal underscores.
- Apps on `Api`: `circuits`, `cloud`, `data_validation` (`data-validation`), `dcim`, `extras`, `ipam`, `tenancy`, `users`, `virtualization`, `vpn`, `wireless`, plus `plugins`. Note the two dashed app names.
- `PluginsApp` routes `nb.plugins.<plugin>.<endpoint>` into `/api/plugins/<plugin>/`; `await nb.plugins.installed_plugins()`.
- App-level helpers pynautobot has and aiopynetbox does not, all `async`:
  `await app.get_custom_fields(filters=None)`
  (`app.choices()` was planned here but dropped: `/<app>/_choices/` 404s on Nautobot 3.x),
  `await app.get_custom_field_choices(filters=None)`, `await app.config()`.
- `Endpoint`: `get(pk=None, /, **kwargs)`, `filter(**kwargs)`, `all(limit=0, offset=None)`, `count(**kwargs)`, `create(...)`, `update(list)`, `delete(list)`, `choices()`.
  - `get()` takes a **UUID string**. Nothing may assume `int` ids.
  - `filter()` stays kwargs-only. pynautobot's positional freeform-search arg maps to `q=`, so `filter(q="a3")` covers it without a positional; document the equivalence rather than adding `*args`.
  - `delete()` accepts UUID strings or `Record`s. Do not replicate pynautobot's `UUID(o)` validation of every string - it raises `ValueError` for legitimate composite keys and only guards against typos.
  - `choices()` must handle **both** OPTIONS shapes: `actions.POST[field].choices` and `actions.POST[field].child.choices` (Nautobot 2.4+), and `schema.properties[field].enum` + `.enumNames` (2.3 and earlier). Decide the minimum supported Nautobot version first; if it's 2.4, implement only the `actions` branch and raise a clear error on the legacy shape.

**Verify:** URL construction per app (including the dashed ones and plugins), `get()` by UUID and by filter, `get()` raising on multiple matches, and each app-level helper hitting the right path.

---

## Phase 3: records and result sets (done)

`response.py`, the largest port and the one with the most judgment calls.

- `Record`: nested dicts become nested `Record`s; `serialize()` collapses them to `id` (falling back to a choice field's `value`); `updates()` diffs against a deep-copied snapshot taken at parse time; `save()` PATCHes only the diff.
- Brief nested records raise `AttributeError` pointing at `await record.full_details()` instead of firing a hidden GET.
- `__eq__`/`__hash__` key on `(url, id)`, falling back to identity. This is aiopynetbox's rule and it is better than pynautobot's `(endpoint.name, id)`, which collides across plugin endpoints of the same name.
- **Raw-JSON fields.** aiopynetbox hardcodes `RAW_JSON_FIELDS = {custom_fields, local_context_data, config_context}`. Nautobot has far more, and pynautobot marks them per-model with its `JsonField` sentinel: `config_context`, `local_config_context_data`, `custom_fields`, `constraints`, `data`, `result`, `task_args`, `task_kwargs`, `celery_kwargs`, `meta`, `object_data`, `object_data_v2`, `default`, `parameters`, `provided_contents`, `extra_config`, `headers`, `config`, `config_schema`, `source_filter`, `destination_filter`, `filter`, `napalm_args`, `capabilities`, `terminations`, `variables`, `config_data`.
  Pick one mechanism and use it everywhere: either a per-`Record`-subclass `JSON_FIELDS` set (pynautobot's model-scoped approach, precise) or a single global set (aiopynetbox's, simpler but over-broad). **Recommendation: per-subclass set with a small global base**, since names like `data`, `filter`, `config`, and `meta` are far too generic to blanket-exempt.
- `RecordSet`: lazy async iterator. Page 1 reveals `count`, remaining offsets fan out through tasks bounded by `Api.max_concurrency`, yielded in offset order, `finally` cancels pending tasks. **No cursor mode** - that is NetBox-only.
- `await recordset.count()`, `await recordset.update(**fields)`, `await recordset.delete()`; the plain-list branch for non-paginated detail routes.
- `Record.notes` -> a `DetailEndpoint` on the base class, since Nautobot exposes `/notes/` on nearly every object.
- Decide `__str__` precedence. pynautobot prefers `display` then `name` then `label`; aiopynetbox prefers `name` then `label` then `display`. **Recommendation: follow pynautobot** (`display` first) - Nautobot populates `display` universally and it is what users see in the UI.

**Verify:** the diff/save round trip including custom_fields merge semantics, brief-record `AttributeError`, concurrent fan-out ordering and cancellation, bulk update/delete, and one test per raw-JSON field family proving it stays a plain dict.

---

## Phase 4: models (done)

`models.py` - the `ENDPOINT_MODELS` map plus `register_model()`, keyed
`"<app>/<endpoint>"`.

Port only the pynautobot model behaviors that are real behavior, not
`__str__` sugar, first:

- `ipam/prefixes` -> `available_ips`, `available_prefixes` (`DetailEndpoint`).
- `dcim/racks` -> `elevation` (read-only detail endpoint; `units` was planned but 404s on Nautobot 3.x, so it was dropped).
- `dcim/devices` -> `napalm` (read-only). Confirm Nautobot still ships the napalm REST endpoint at the target version before porting it; NetBox dropped its equivalent and aiopynautobot should not carry a dead route.
- `extras/dynamic-groups` -> `members`.
- `extras/jobs` -> see Phase 6.
- `TraceableRecord.trace()` for `dcim/interfaces`, `front-ports`, `rear-ports`, `power-outlets`, `power-ports`, `console-ports`, `console-server-ports`. Nautobot returns a list of `(termination_a, cable, termination_b)` triples with `None`s for unterminated hops; map each hop's URL back to a Record class.

`__str__` overrides (`Circuits.cid`, `IpAddresses.address`, `DeviceTypes.model`,
`Users.username`, ...) are cheap and can land in the same pass.

**Verify:** allocation against a fake that returns 204 when exhausted, `trace()` shape including `None` hops, and `register_model()` for a plugin endpoint.

---

## Phase 5: GraphQL (done)

`graphql.py`. No aiopynetbox counterpart; port from pynautobot's
`core/graphql.py`.

- `await nb.graphql.query(query: str, variables: dict | None = None) -> GraphQLRecord` POSTs `{"query": ..., "variables": ...}` to `/api/graphql/`.
- `GraphQLError` (shipped name; the plan originally said GraphQLException) carries `errors`, `status_code`, and `url`. Raise it on 400 (Nautobot's shape for an invalid query); let other statuses surface as `RequestError`.
- Type-check `query` (str) and `variables` (dict) before sending, as pynautobot does - it turns a common mistake into a clear `TypeError` instead of a server-side parse error.
- Saved queries: `GraphqlEndpoint.run(query_id, ...)` POSTs `/api/extras/graphql-queries/<id>/run/`, and the `GraphqlQueries` record gets an `await record.run(...)`.
- Consider surfacing `errors` on a 200 response too. GraphQL can return `200` with a partial `data` plus `errors`; pynautobot silently hands that back as a successful `GraphQLRecord`. Leaving the raw json accessible is fine, but the behavior should be a documented choice rather than an accident.

**Verify:** a valid query, an invalid query raising `GraphQLException` with populated `errors`, `TypeError` on bad argument types, and a saved-query run.

---

## Phase 6: jobs (done)

`JobsEndpoint` on `nb.extras.jobs`, reached via `App.__getattr__` special-casing
`jobs` the way pynautobot does.

- `await jobs.run(job_id=... | job_name=..., data=..., ...)` POSTs `/api/extras/jobs/<job>/run/` and returns the job result record.
- `await jobs.run_and_wait(..., interval=5, max_rechecks=50)` polls with **`asyncio.sleep`**, refreshing via `await job_result.full_details()` until the status leaves `RECEIVED`/`PENDING`/`STARTED`/`RETRY`.
  - Prefer a `timeout` in seconds over `max_rechecks`; it is what callers actually reason about. Keep `interval`.
  - Raise a dedicated `JobTimeoutError` rather than pynautobot's bare `ValueError`, and include the job result id so the caller can keep polling.
- `Jobs` record gets `await record.run(**kwargs)`.

**Verify:** a fake that transitions a job through PENDING -> STARTED -> SUCCESS across polls, plus the timeout path.

---

## Phase 7: typed endpoint hints (done)

Generated from demo.nautobot.com (Nautobot 3.2.2, API version 3.2): 164
endpoints across 13 apps, roughly 2700 filter params (the exact count
drifts with each regeneration). The demo does require
authentication, but it publishes a documented read-only token, so it works as
a generation source the same way demo.netbox.dev does for aiopynetbox, and the
weekly workflow needs no secret.

Three Nautobot-specific corrections the plan did not anticipate, all now
covered by `tests/test_generated.py`:

- Nautobot's schema paths omit the `/api` prefix (it lives in the document's `servers` entry), so aiopynetbox's `^/api/...` regex matched **zero** endpoints on the first run. The regex now treats the prefix as optional.
- Generating revealed a `core` app that pynautobot does not expose and `Api` was missing entirely, so `nb.core` raised AttributeError. Now present.
- The `create` fallback overload must return the base's `Record | list[Record]`. Narrowing it to `list[Devices]` made pyright reject every model-backed endpoint (34 errors), because `list` is invariant.


`scripts/generate_endpoints.py` + `apps_generated.py` + `hints_generated.pyi`,
ported from aiopynetbox. This is the phase with the biggest environmental
difference.

- Source schema is **`/api/swagger.json`**, not `/api/schema/`.
- **demo.nautobot.com requires authentication for every endpoint** (verified: `/api/swagger.json` returns 403 `"Authentication credentials were not provided."`). There is no anonymous public schema the way `demo.netbox.dev` provides one, so aiopynetbox's "point the script at the demo instance" approach does not transfer.
  - **Recommendation: generate against a throwaway Nautobot container in CI.** pynautobot's own dev stack uses `ghcr.io/nautobot/nautobot-dev:<ver>` with a fixed superuser token (`0123456789abcdef0123456789abcdef01234567`), which makes the run hermetic and version-pinned instead of dependent on whatever the public demo is running.
  - Alternative: a repo secret holding a demo token. Simpler, but it silently breaks when the demo rotates credentials or changes version.
- The script takes the schema URL and a token as arguments either way, so a developer can point it at their own instance.
- Adjust the list-path regex: NetBox's is `^/api/([a-z]+)/([a-z0-9-]+)/$`, which **misses Nautobot's dashed app names** (`data-validation`, `load-balancers`). Use `^/api/([a-z-]+)/([a-z0-9-]+)/$` and map the app slug back to its attribute name.
- Keep the two-file split: `apps_generated.py` holds runtime-free class annotations, `hints_generated.pyi` is stub-only with `Unpack`ed TypedDicts plus a trailing `**kwargs: Any` overload so custom-field filters, lookup expressions, and plugin params stay legal.
- Only then add `.github/workflows/regenerate-endpoints.yml` (weekly, opens a PR on drift). It is deliberately absent today: a scheduled workflow calling a script that does not exist would fail every week.

**Verify:** a test asserting every annotation in `apps_generated.py` resolves to a class in the stub, and that `APP_CLASSES` covers every app on `Api`.

---

## Phase 8: docs, examples, release (done, except the release itself)

- `examples/fastapi_app.py`, mirroring aiopynetbox's lifespan/app-state pattern. Done.
- README API tour. Done.
- CHANGELOG 0.1.0 entry. Done.
- Still to do, and only you can do it: create the GitHub mirror, claim the PyPI name, configure trusted publishing plus the `pypi` GitHub environment, then tag 0.1.0.
- A compatibility matrix like pynautobot's is still worth adding once there is a second supported Nautobot release to compare against.

---

## Open questions

Resolved during implementation, recorded here because each is a divergence
someone will otherwise re-litigate:

1. **Minimum Nautobot version: 2.4+.** This drops the legacy OPTIONS `enum`/`enumNames` branch entirely (`Endpoint.choices()` raises a message naming the requirement instead) and makes `exclude_m2m` / `include` unconditional. Stated in the README and CHANGELOG.
2. **`Api.default_filters` apply uniformly, including `count()`.** pynautobot omits them there, which is an inconsistency rather than a decision. Covered by `test_default_filters_reach_count`.
3. **Raw-JSON fields are per-subclass**, via `Record.JSON_FIELDS | {...}`, with only custom_fields / computed_fields / relationships in the base. A global set would have to include `data`, `filter`, `config`, and `meta`, which are too generic to blanket-exempt.
4. **`__str__` prefers `display`**, matching pynautobot rather than aiopynetbox, because Nautobot populates it universally.
5. **`run_and_wait` takes `timeout=` seconds, not pynautobot's `max_rechecks`**, and raises `JobTimeoutError` carrying the job result id rather than a bare `ValueError`.

6. **Schema source: demo.nautobot.com with its documented read-only token.** Nautobot authenticates every route, but the demo's public token makes it usable without a CI secret. A pinned `ghcr.io/nautobot/nautobot-dev` container stays the fallback if the demo moves to a Nautobot major version this library does not support; the generator takes a URL and token for exactly that.

Still open:

7. **Integration tests against a live Nautobot: done, opt-in.** `tests/test_demo_integration.py` runs read-only checks (pagination fan-out, gets, full_details, custom-field draining, GraphQL, openapi) against any instance via `AIOPYNAUTOBOT_DEMO_URL`, defaulting the token to the demo's documented read-only one. Skipped when the env var is unset so the default suite stays offline. Verified green against demo.nautobot.com (Nautobot 3.2.2). Write-path tests (create/save/update/bulk/notes/allocation/delete, self-cleaning) are additionally gated on `AIOPYNAUTOBOT_DEMO_WRITES=1` and also verified green against the demo sandbox.
8. **Hosting: resolved.** `github.com/challey74/aiopynautobot` is the repo; CI, releases, and PRs all run there.
9. **GraphQL 200-with-errors.** Exposed as `result.errors` and documented, deliberately not raised, since partial data is often still useful. Revisit if it surprises people in practice.
