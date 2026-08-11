"""Record, RecordSet and DetailEndpoint: objects returned by endpoint queries."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncGenerator, Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiopynautobot.api import Api
    from aiopynautobot.endpoint import Endpoint


def _flatten_custom(custom: dict[str, Any]) -> dict[str, Any]:
    """Collapse custom_fields values to ids for serialization."""
    ret = {}
    for k, v in custom.items():
        if isinstance(v, dict):
            v = v.get("id", v)
        elif isinstance(v, list):
            v = [i.get("id", i) if isinstance(i, dict) else i for i in v]
        ret[k] = v
    return ret


def _serialize_value(v: Any) -> Any:
    if isinstance(v, Record):
        ident = getattr(v, "id", None)
        if ident is not None:
            return ident
        # Choice fields ({"value": ..., "label": ...}) collapse to their value.
        value = getattr(v, "value", None)
        if value is not None:
            return value
        return v.serialize()
    if isinstance(v, list):
        return [_serialize_value(i) for i in v]
    return v


class Record:
    """A Nautobot object parsed from an API response.

    Nested dicts become nested Records. Unlike pynautobot, accessing a field
    that is absent (e.g. on a brief nested record) never triggers a request;
    it raises AttributeError and the caller must `await full_details()`.

    Records compare equal (and hash together) when they refer to the same
    Nautobot object, meaning same detail url and id; records without both
    fall back to identity comparison.
    """

    url: str | None = None

    # Fields holding arbitrary JSON, which must never be coerced into Records.
    # These are the ones Nautobot can attach to any object; per-model fields
    # (config_context, task_args, ...) extend this on the models.py subclasses.
    JSON_FIELDS: frozenset[str] = frozenset(
        {"custom_fields", "computed_fields", "relationships"}
    )

    def __init__(self, values: dict[str, Any], api: Api, full: bool = False) -> None:
        self._has_details = full
        self._api = api
        self._snapshot: dict[str, Any] = {}
        self._parse(values)
        self._snapshot = copy.deepcopy(self.serialize())

    def _parse(self, values: dict[str, Any]) -> None:
        for k, v in values.items():
            if isinstance(v, dict) and k not in self.JSON_FIELDS:
                v = Record(v, self._api)
            elif isinstance(v, list) and k not in self.JSON_FIELDS:
                v = [Record(i, self._api) if isinstance(i, dict) else i for i in v]
            setattr(self, k, v)

    def __getattr__(self, k: str) -> Any:
        if k.startswith("_"):
            raise AttributeError(k)
        if self.url and not self._has_details:
            raise AttributeError(
                f"{k!r} is not loaded on this record. It may only be present on "
                "the full object; 'await record.full_details()' then retry."
            )
        raise AttributeError(f"Record has no attribute {k!r}")

    def _key(self) -> tuple[str, Any] | None:
        url = self.__dict__.get("url")
        ident = self.__dict__.get("id")
        if url is None or ident is None:
            return None
        return (url, ident)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Record):
            return NotImplemented
        key, other_key = self._key(), other._key()
        if key is None or other_key is None:
            return self is other
        return key == other_key

    def __hash__(self) -> int:
        key = self._key()
        return hash(key) if key is not None else id(self)

    def __iter__(self) -> Iterator[tuple[str, Any]]:
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            if isinstance(v, Record):
                yield k, dict(v)
            elif isinstance(v, list):
                yield k, [dict(i) if isinstance(i, Record) else i for i in v]
            else:
                yield k, v

    def __getitem__(self, k: str) -> Any:
        return dict(self)[k]

    def __str__(self) -> str:
        # Nautobot populates `display` on every object and it is what the UI
        # shows, so it wins over name/label (this is pynautobot's order).
        return (
            getattr(self, "display", None)
            or getattr(self, "name", None)
            or getattr(self, "label", None)
            or ""
        )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} ({self})>"

    def serialize(self) -> dict[str, Any]:
        """Return a flat, JSON-able dict: nested Records collapse to ids
        (or choice values), custom_fields values to ids."""
        ret = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            if k == "custom_fields" and isinstance(v, dict):
                ret[k] = _flatten_custom(v)
            elif k in self.JSON_FIELDS:
                ret[k] = v
            else:
                ret[k] = _serialize_value(v)
        return ret

    def updates(self) -> dict[str, Any]:
        """Diff current state against the state at parse time."""
        current = self.serialize()
        init = dict(self._snapshot)
        # custom_fields use merge semantics on PATCH: only compare keys present
        # in the current value so a subset assignment isn't seen as removals.
        current_cf, init_cf = current.get("custom_fields"), init.get("custom_fields")
        if isinstance(current_cf, dict) and isinstance(init_cf, dict):
            init["custom_fields"] = {
                k: v for k, v in init_cf.items() if k in current_cf
            }
        return {k: v for k, v in current.items() if k not in init or v != init[k]}

    async def full_details(self) -> bool:
        """Fetch and load the full object from its detail URL.

        Returns:
            True once details are loaded; False if the record has no
            detail url to fetch.
        """
        if not self.url:
            return False
        self._parse(await self._api._request("GET", self.url))
        self._has_details = True
        self._snapshot = copy.deepcopy(self.serialize())
        return True

    async def save(self) -> bool:
        """PATCH changed fields to Nautobot.

        Returns:
            True if a PATCH was sent; False when nothing changed.

        Raises:
            ValueError: If the record has no detail url.
        """
        updates = self.updates()
        if not updates:
            return False
        url = self.url
        if url is None:
            raise ValueError("Record has no url and cannot be saved")
        self._parse(await self._api._request("PATCH", url, json=updates))
        self._snapshot = copy.deepcopy(self.serialize())
        return True

    async def update(self, data: dict[str, Any]) -> bool:
        """Set fields from a dict and save(); see save() for semantics."""
        for k, v in data.items():
            setattr(self, k, v)
        return await self.save()

    async def delete(self) -> bool:
        """DELETE the object in Nautobot.

        Raises:
            ValueError: If the record has no detail url.
        """
        url = self.url
        if url is None:
            raise ValueError("Record has no url and cannot be deleted")
        return await self._api._request("DELETE", url)

    @property
    def notes(self) -> DetailEndpoint:
        """The object's `notes` sub-endpoint.

        Nautobot exposes /notes/ on nearly every object, so this lives on
        the base Record rather than a subclass.
        """
        return DetailEndpoint(self, "notes")


class DetailEndpoint:
    """A sub-endpoint nested under a record's detail URL,
    e.g. /api/ipam/prefixes/<uuid>/available-ips/."""

    def __init__(
        self, record: Record, name: str, record_class: type[Record] | None = None
    ) -> None:
        self.api: Api = record._api
        self.url = "{}/{}/".format(str(record.url).rstrip("/"), name)
        self.record_class: type[Record] = record_class or Record

    def list(self, **params: Any) -> RecordSet:
        """Lazy RecordSet over the detail endpoint."""
        return RecordSet(self, params)

    async def create(
        self, data: dict[str, Any] | list[dict[str, Any]] | None = None
    ) -> Record | list[Record]:
        """POST to the detail endpoint (e.g. allocate next available IPs).

        Args:
            data: A dict for one object, a list of dicts for several, or
                omitted to take the next single allocation. Nautobot
                assigns the actual values (address, prefix, ...).

        Returns:
            A Record, or a list of Records for list input.

        Raises:
            AllocationError: If the pool is exhausted (Nautobot answers
                with 204 No Content).
        """
        resp = await self.api._request("POST", self.url, json=data or {})
        if isinstance(resp, list):
            return [self.record_class(i, self.api, full=True) for i in resp]
        return self.record_class(resp, self.api, full=True)


class RODetailEndpoint(DetailEndpoint):
    """A detail sub-endpoint that only supports reads."""

    async def create(
        self, data: dict[str, Any] | list[dict[str, Any]] | None = None
    ) -> Record | list[Record]:
        """Always raises; this sub-endpoint is read-only."""
        raise NotImplementedError("Writes are not supported for this endpoint.")


class RecordSet:
    """Lazy async iterable of Records from a list endpoint.

    Nothing is fetched until iteration starts. After the first page, the
    remaining pages are fetched concurrently (bounded by Api.max_concurrency)
    and yielded in order. Each `async for` re-runs the query.
    """

    def __init__(
        self,
        endpoint: Endpoint | DetailEndpoint,
        filters: dict[str, Any] | None = None,
        limit: int = 0,
        offset: int | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.filters = filters or {}
        self.limit = limit
        self.offset = offset

    def __aiter__(self) -> AsyncGenerator[Record]:
        return self._iter()

    async def _iter(self) -> AsyncGenerator[Record]:
        api = self.endpoint.api
        record_class = self.endpoint.record_class
        params = dict(self.filters)
        if self.limit:
            params["limit"] = self.limit
        if self.offset is not None:
            params["offset"] = self.offset
        data = await api._request("GET", self.endpoint.url, params=params)
        if isinstance(data, list):
            # Non-paginated detail routes (e.g. available-ips) return a list.
            for item in data:
                yield record_class(item, api, full=True)
            return
        results = data["results"]
        for item in results:
            yield record_class(item, api, full=True)
        if self.offset is not None or not data.get("next") or not results:
            return
        page_size = len(results)
        sem = asyncio.Semaphore(api.max_concurrency)

        async def fetch(offset: int) -> Any:
            async with sem:
                page_params = dict(params)
                page_params.update(limit=page_size, offset=offset)
                return await api._request("GET", self.endpoint.url, params=page_params)

        tasks = [
            asyncio.create_task(fetch(offset))
            for offset in range(page_size, data["count"], page_size)
        ]
        try:
            for task in tasks:
                page = await task
                for item in page["results"]:
                    yield record_class(item, api, full=True)
        finally:
            for task in tasks:
                task.cancel()

    async def count(self) -> int:
        """Total object count for the query (replaces pynautobot's len())."""
        params = dict(self.filters)
        params["limit"] = 1
        data = await self.endpoint.api._request("GET", self.endpoint.url, params=params)
        if isinstance(data, list):
            # Non-paginated detail routes return the full list regardless.
            return len(data)
        return data["count"]

    async def update(self, **kwargs: Any) -> list[Record]:
        """Bulk PATCH the same field values onto every record in the set.

        Iterates the query to collect ids, then sends one list-body PATCH.

        Returns:
            The updated Records; [] for an empty set (no request sent).
        """
        ids = [r.id async for r in self]
        if not ids:
            return []
        api = self.endpoint.api
        data = await api._request(
            "PATCH", self.endpoint.url, json=[{"id": i, **kwargs} for i in ids]
        )
        return [self.endpoint.record_class(i, api, full=True) for i in data]

    async def delete(self) -> bool:
        """Bulk DELETE every record in the set.

        Returns:
            True on deletion; False for an empty set (no request sent).
        """
        ids = [r.id async for r in self]
        if not ids:
            return False
        return await self.endpoint.api._request(
            "DELETE", self.endpoint.url, json=[{"id": i} for i in ids]
        )
