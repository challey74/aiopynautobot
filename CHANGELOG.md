# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-15

Initial release. Requires Nautobot 2.4+.

### Added

- Fully async `Api` client on httpx, usable as an async context manager;
  `follow_redirects` enabled by default. A client passed via `client=`
  stays open on close (httpx convention); the Api closes only clients
  it creates.
- `Authorization: Token <token>` auth and a `python-aiopynautobot/<version>`
  User-Agent.
- REST API version pinning via `Api(api_version="2.4")`, sent as
  `Accept: application/json; version=2.4`.
- Client-wide default filters via `Api(exclude_m2m=..., include_default=...)`
  (Nautobot 2.4+), merged into every read and create. Unlike pynautobot
  these also apply to `count()`.
- App/endpoint attribute traversal (`nb.dcim.devices`) across circuits,
  cloud, data_validation, dcim, extras, ipam, load_balancers, tenancy,
  users, virtualization, vpn, and wireless, including the two dashed app
  slugs. Plus `nb.plugins.<app>.<endpoint>`,
  `nb.plugins.installed_plugins()`, and `App.endpoint(name)` for slugs
  with literal underscores.
- App-level helpers: `app.config()`, `app.get_custom_fields()`, and
  `app.get_custom_field_choices()`, the latter two draining every page.
- `get()` / `filter()` / `all()` / `count()` / `create()` on endpoints;
  result sets are lazy async iterators that fetch pages through a sliding
  window bounded by `max_concurrency`, so breaking out of an iteration
  early stops the fetching. Primary keys are UUID strings, and key path
  segments are percent-encoded.
- `Endpoint.choices()` from OPTIONS metadata, handling both plain choice
  fields and list fields whose choices live under `child`.
- Diff-based `Record.save()` (PATCHes only changed fields, with
  custom_fields merge semantics), `update()`, `delete()`, and explicit
  `full_details()` for brief nested records.
- Per-model JSON field marking, so `config_context`, `task_args`,
  `object_data`, `filter`, and the rest stay plain dicts instead of
  being coerced into nested Records.
- Bulk operations: `RecordSet.update(**fields)` / `RecordSet.delete()`
  and `Endpoint.update(list)` / `Endpoint.delete(list)`.
- IPAM allocation helpers: `prefix.available_ips` /
  `available_prefixes`. `AllocationError` is raised when Nautobot
  answers a POST with 204 No Content, its signal for an exhausted pool.
- Cable tracing via `await record.trace()` on interfaces, front/rear
  ports, power outlets/ports, console (server) ports, and cables.
- `record.notes` on every Record, plus read-only `device.napalm` and
  `rack.elevation`.
- GraphQL support: `await nb.graphql.query(query, variables)` returning a
  `GraphQLRecord`, raising `GraphQLError` with the parsed `errors` array
  on an invalid query. Saved queries run via
  `nb.extras.graphql_queries.run(query_id)` or `record.run()`.
- Jobs: `await nb.extras.jobs.run(job_id=... | job_name=...)` and
  `run_and_wait(interval=, timeout=)`, which polls with `asyncio.sleep`
  and raises `JobTimeoutError` carrying the job result id.
- Automatic retries with exponential backoff and jitter: 429 for any
  method (honoring `Retry-After`), transient 502/503/504 and
  connection failures for GETs only. Configurable via `Api(retries=)`,
  default 3.
- `register_model(app, endpoint, record_class)` to map app or custom
  endpoints to Record subclasses.
- Record equality/hashing by Nautobot identity (detail url + id).
- `Api.status()` and `Api.openapi()` (from `/api/swagger.json`, cached);
  `Api.version()` reads the `API-Version` header and tolerates the 403
  that instances with LOGIN_REQUIRED return.
- Full type hints with a `py.typed` marker, plus generated hints so IDEs
  autocomplete endpoint names and per-endpoint kwargs for `filter()` /
  `get()` / `count()` / `create()`. Hints never restrict runtime
  behavior; they regenerate weekly from demo.nautobot.com's OpenAPI
  schema. Covers 164 endpoints across 13 apps at Nautobot 3.2.
- `nb.core`, which pynautobot does not expose.
- A runnable FastAPI example (`examples/fastapi_app.py`) showing the
  app-state / lifespan usage pattern.

[unreleased]: https://github.com/challey74/aiopynautobot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/challey74/aiopynautobot/releases/tag/v0.1.0
