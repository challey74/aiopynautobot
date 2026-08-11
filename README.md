# aiopynautobot

[![CI](https://github.com/challey74/aiopynautobot/actions/workflows/ci.yml/badge.svg)](https://github.com/challey74/aiopynautobot/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Fully async Nautobot API client for Python, built on
[httpx](https://www.python-httpx.org/).

Inspired by [pynautobot](https://github.com/nautobot/pynautobot), redesigned
for asyncio, and a sister project to
[aiopynetbox](https://github.com/challey74/aiopynetbox). This is not a port:
pynautobot's core ergonomics (lazy attribute fetches, eagerly materialized
result lists, sync pagination) depend on Python protocols that cannot be
awaited, so the API surface here is deliberately different. **All I/O is
explicit and awaitable, and nothing does network I/O behind your back.**

## Requirements

- Python 3.11+
- Nautobot 2.4+ (including 3.x)

## Installation

```sh
uv add aiopynautobot   # or: pip install aiopynautobot
```

## Quick start

```python
import asyncio
import aiopynautobot


async def main():
    async with aiopynautobot.api("https://nautobot.example.com", token="...") as nb:
        # single object
        device = await nb.dcim.devices.get(name="sw-1")
        print(device.name, device.status, device.location)

        # filtered query, pages are fetched concurrently
        async for iface in nb.dcim.interfaces.filter(device=device.name):
            print(iface.name)

        # diff-based save: only changed fields are PATCHed
        device.serial = "ABC123"
        await device.save()


asyncio.run(main())
```

## Coming from pynautobot

The traversal (`nb.dcim.devices`), diff-based `save()`, and exception taxonomy
all carry over. What changes is that implicit I/O becomes explicit:

| pynautobot (sync)                   | aiopynautobot (async)                                        |
| ----------------------------------- | ------------------------------------------------------------ |
| `nb.dcim.devices.get(name="x")`     | `await nb.dcim.devices.get(name="x")`                        |
| `for d in nb.dcim.devices.all()`    | `async for d in nb.dcim.devices.all()`                       |
| `len(nb.dcim.devices.all())`        | `await nb.dcim.devices.count()`                              |
| `device.location.parent` (lazy GET) | `await device.location.full_details()` then `.parent`        |
| `nb.version` (property does I/O)    | `await nb.version()`                                         |
| `threading=True`                    | built in: concurrent page fan-out, bounded by `max_concurrency` |
| `filter("search-term")`             | `filter(q="search-term")`                                    |

Nested records come back *brief* (as Nautobot sends them). Touching a field
that isn't loaded raises `AttributeError` telling you to
`await record.full_details()`. It never fires a hidden HTTP request.

## Features

- **Explicit async everywhere**: `httpx.AsyncClient` under the hood, used as
  an async context manager so the connection pool closes deterministically.
- **Concurrent pagination**: after the first page reveals the count, the
  remaining pages are fetched in parallel (bounded by `max_concurrency`,
  default 4) and yielded in order.
- **Diff-based writes**: `save()` PATCHes only what you changed, with
  Nautobot's custom_fields merge semantics handled correctly.
- **GraphQL**: `await nb.graphql.query(...)` plus saved queries via
  `await nb.extras.graphql_queries.run(query_id)`.
- **Jobs**: `await nb.extras.jobs.run(job_id=...)` and
  `run_and_wait()`, which polls with `asyncio.sleep` and raises
  `JobTimeoutError` rather than blocking a thread.
- **API versioning**: `api_version="2.4"` pins
  `Accept: application/json; version=2.4` for every request.
- **Default filters**: `exclude_m2m=True` and
  `include_default="config_context,computed_fields"` are merged into every
  read, including `count()`.
- **Bulk operations**:
  `await nb.dcim.devices.filter(status="offline").update(comments="audit")`,
  `await recordset.delete()`, and list forms on the endpoint
  (`endpoint.update([...])` / `endpoint.delete([...])`).
- **IPAM allocation**: `await prefix.available_ips.create()` / `.list()`,
  plus `available_prefixes`. An exhausted pool raises `AllocationError`
  (Nautobot answers 204 No Content, not NetBox's 409).
- **Cable tracing**: `await interface.trace()` returns
  `[termination_a, cable, termination_b]` hops, with `None` where a path is
  unterminated.
- **Notes**: `record.notes.list()` / `.create({"note": "..."})` on any object.
- **Apps**: `nb.plugins.<app>.<endpoint>` and
  `await nb.plugins.installed_plugins()`.
- **Choices**: `await nb.dcim.devices.choices()` from OPTIONS metadata,
  handling both plain and list-typed choice fields.
- **Retries with backoff**: 429 responses are retried automatically for
  any method (honoring `Retry-After`); transient 502/503/504 and
  connection failures are retried for GETs only, since an ambiguous
  write may already have been processed. Exponential backoff with
  jitter; tune with `retries=`, disable with `retries=0`.
- **Custom models**: `aiopynautobot.register_model("plugins/bgp", "sessions",
  BgpSession)` maps app endpoints to your own Record subclasses;
  `app.endpoint("literal_name")` reaches endpoint slugs that contain
  real underscores.
- **Typed**: full type hints and a `py.typed` marker, plus generated
  hints so IDEs autocomplete endpoint names (`nb.dcim.devices`) and
  per-endpoint kwargs (`filter(name=...)`, `create(device_type=...)`).
  Hints never restrict anything at runtime: unknown endpoints, lookup
  expressions, and custom-field filters keep working.

## API tour

```python
async with aiopynautobot.api(url, token=token) as nb:
    # read (Nautobot primary keys are UUID strings)
    device = await nb.dcim.devices.get("0238a4e3-66f2-455a-831f-5f177215de0f")
    device = await nb.dcim.devices.get(name="sw-1")  # ValueError if >1
    total = await nb.dcim.devices.count(location="main")
    async for d in nb.dcim.devices.filter(status="active", tag=["prod", "core"]):
        ...
    async for d in nb.dcim.devices.all(limit=100, offset=200):  # single page
        ...

    # write
    new = await nb.dcim.devices.create(
        name="sw-9", device_type=dt_id, location=loc_id, role=role_id, status="Active"
    )
    device.serial = "XYZ"
    await device.save()  # PATCH {"serial": "XYZ"}
    await device.update({"serial": "XYZ", "comments": "..."})
    await device.delete()

    # bulk
    await nb.dcim.devices.filter(location="old").update(status="Decommissioning")
    await nb.dcim.devices.filter(status="Decommissioning").delete()

    # ipam allocation
    prefix = await nb.ipam.prefixes.get(prefix="10.0.0.0/24")
    ip = await prefix.available_ips.create({"status": "Active"})
    ips = await prefix.available_ips.create([{"status": "Active"}] * 2)

    # graphql
    result = await nb.graphql.query("query { devices { name } }")
    print(result.data["devices"])

    # jobs
    job = await nb.extras.jobs.run_and_wait(
        job_name="Verify Hostnames", data={"hostname_regex": ".*"}
    )
    print(job.job_result.status.value)

    # instance info
    print(await nb.version())  # "2.4"
    print(await nb.status())
```

### Long-lived apps (FastAPI, services)

Create the client once and share it; the async context manager is
one-shot, so enter it for the app's lifetime, not per request:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiopynautobot.api(url, token=token) as nb:
        app.state.nb = nb
        yield  # handlers use `await app.state.nb...`; pool closes on shutdown
```

One shared instance is safe under concurrent requests. See
[examples/fastapi_app.py](examples/fastapi_app.py) for a runnable app.

### Custom httpx client

Pass your own `httpx.AsyncClient` for custom SSL, proxies, event hooks, or
`MockTransport` in tests:

```python
client = httpx.AsyncClient(verify="/path/to/ca.pem", timeout=60)
async with aiopynautobot.api(url, token=token, client=client) as nb:
    ...
```

Per httpx convention, a client you pass in is yours to close: `aclose()`
and the context manager only close clients the Api created itself, so
one client can safely back several Api instances.

Response caching is deliberately not built in: Nautobot is a source of
truth, and the library can't know your staleness tolerance. If you want
HTTP caching, pass a client using [hishel](https://hishel.com/)'s
`AsyncCacheTransport` and set the policy yourself.

## Development

Managed with [uv](https://docs.astral.sh/uv/):

```sh
uv sync              # install environment
uv run pytest        # tests (in-memory fake Nautobot, no network)
uv run ruff check    # lint
uv run ruff format   # format
uv run pyright       # type check
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
