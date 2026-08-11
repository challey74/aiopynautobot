"""Endpoint: actions available on a Nautobot API endpoint."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aiopynautobot.exceptions import JobTimeoutError, RequestError
from aiopynautobot.models import ENDPOINT_MODELS
from aiopynautobot.response import Record, RecordSet

if TYPE_CHECKING:
    from aiopynautobot.api import Api
    from aiopynautobot.app import App

# Celery states that mean "not finished yet".
ACTIVE_JOB_STATUSES = frozenset({"RECEIVED", "PENDING", "STARTED", "RETRY"})


def _status_value(status: Any) -> str:
    """Read a job result status as its raw value.

    Nautobot sends status as a choice field, which parses into a Record
    whose str() is the human label ("Pending"), not the Celery state
    ("PENDING"). Prefer `value` and fall back for plain-string payloads.
    """
    return str(getattr(status, "value", status) or "")


class Endpoint:
    """One Nautobot list endpoint, e.g. nb.dcim.devices."""

    def __init__(
        self, api: Api, app: App, name: str, literal_name: bool = False
    ) -> None:
        self.api = api
        self.name = name if literal_name else name.replace("_", "-")
        self.url = f"{api.base_url}/{app.name}/{self.name}/"
        self.record_class = ENDPOINT_MODELS.get(f"{app.name}/{self.name}", Record)
        self._choices: dict[str, list[dict[str, Any]]] | None = None

    async def get(self, pk: str | None = None, /, **kwargs: Any) -> Record | None:
        """Get a single Record by primary key or by filter kwargs.

        Args:
            pk: Primary key. Nautobot uses UUIDs, and 2.x also accepts a
                natural key, so this is a string rather than an int.
            **kwargs: Filter parameters (instead of a pk); must match at
                most one object.

        Returns:
            The Record, or None if nothing matches.

        Raises:
            ValueError: If kwargs match more than one object.
        """
        if pk is not None:
            try:
                data = await self.api._request("GET", f"{self.url}{pk}/")
            except RequestError as e:
                if e.status_code == 404:
                    return None
                raise
            return self.record_class(data, self.api, full=True)
        it = aiter(self.filter(**kwargs))
        try:
            first = await anext(it, None)
            if first is None:
                return None
            if await anext(it, None) is not None:
                raise ValueError(
                    "get() returned more than one result. Check that the "
                    "kwarg(s) passed are valid for this endpoint or use "
                    "filter() or all() instead."
                )
        finally:
            await it.aclose()
        return first

    def filter(self, **kwargs: Any) -> RecordSet:
        """Query the endpoint with filters; returns a lazy RecordSet.

        Args:
            **kwargs: Nautobot filter params. Lookup expressions work as
                keywords (name__isw="sw-"), list values OR-match
                (status=["active", "staged"]), and `q=` is the freeform
                search pynautobot exposes as a positional argument.

        Raises:
            ValueError: If called with no kwargs; use all() instead.
        """
        if not kwargs:
            raise ValueError("filter must be passed kwargs. Use all() instead.")
        return RecordSet(self, kwargs)

    def all(self, limit: int = 0, offset: int | None = None) -> RecordSet:
        """Return a RecordSet over every object on the endpoint.

        Args:
            limit: Page size for the query; 0 uses the server default.
            offset: Fetch only the single page starting here (requires
                limit) instead of iterating everything.

        Raises:
            ValueError: If offset is given without a limit.
        """
        if offset is not None and not limit:
            raise ValueError("offset requires a positive limit value")
        return RecordSet(self, limit=limit, offset=offset)

    async def count(self, **kwargs: Any) -> int:
        """Object count for the given filters (all objects if none)."""
        return await RecordSet(self, kwargs).count()

    async def create(
        self, *args: dict[str, Any] | list[dict[str, Any]], **kwargs: Any
    ) -> Record | list[Record]:
        """POST new objects.

        Args:
            *args: A single dict, or a list of dicts for bulk create.
            **kwargs: Fields for a single object (the usual form).

        Returns:
            A Record, or a list of Records for bulk input.
        """
        data = args[0] if args else kwargs
        resp = await self.api._request("POST", self.url, json=data)
        if isinstance(resp, list):
            return [self.record_class(i, self.api, full=True) for i in resp]
        return self.record_class(resp, self.api, full=True)

    async def update(self, objects: list[dict[str, Any]]) -> list[Record]:
        """Bulk PATCH a list of dicts, each of which must contain "id"."""
        resp = await self.api._request("PATCH", self.url, json=objects)
        return [self.record_class(i, self.api, full=True) for i in resp]

    async def delete(self, objects: list[str | Record]) -> bool:
        """Bulk DELETE objects given as primary keys or Records."""
        ids = [o.id if isinstance(o, Record) else o for o in objects]
        return await self.api._request(
            "DELETE", self.url, json=[{"id": i} for i in ids]
        )

    async def choices(self) -> dict[str, list[dict[str, Any]]]:
        """Choices for the endpoint's choice fields, from an OPTIONS request.

        Cached on this Endpoint instance. Attribute access builds a fresh
        Endpoint every time, so keep a reference (`endpoint = nb.dcim.devices`)
        for the cache to be of any use, and re-read it after a Nautobot
        upgrade adds choices.

        Raises:
            ValueError: If the response carries no writable-action
                metadata, which is what Nautobot returns for tokens
                without write permission on the endpoint (and what
                Nautobot 2.3 and earlier returned for everyone).
        """
        if self._choices is not None:
            return self._choices
        data = await self.api._request("OPTIONS", self.url)
        post = (data.get("actions") or {}).get("POST")
        if post is None:
            raise ValueError(
                f"Unexpected format in the OPTIONS response at {self.url}. "
                "aiopynautobot requires Nautobot 2.4+, or the token may lack "
                "write permission on this endpoint."
            )
        choices: dict[str, list[dict[str, Any]]] = {}
        for field, meta in post.items():
            if not isinstance(meta, dict):
                continue
            if "choices" in meta:
                choices[field] = meta["choices"]
            elif meta.get("type") == "list" and "choices" in (meta.get("child") or {}):
                choices[field] = meta["child"]["choices"]
        self._choices = choices
        return self._choices


class JobsEndpoint(Endpoint):
    """nb.extras.jobs, with the ability to enqueue a job run."""

    async def run(
        self, *, job_id: str | None = None, job_name: str | None = None, **kwargs: Any
    ) -> Record:
        """Enqueue a job run.

        Args:
            job_id: UUID of the job to run.
            job_name: Name of the job to run, as an alternative to job_id.
            **kwargs: The POST body, typically `data={...}`.

        Returns:
            The job run response, whose `job_result` carries the id to poll.

        Raises:
            ValueError: If neither job_id nor job_name is given.
        """
        job = job_id or job_name
        if not job:
            raise ValueError("Either job_id or job_name is required to run a job.")
        data = await self.api._request("POST", f"{self.url}{job}/run/", json=kwargs)
        return self.record_class(data, self.api, full=True)

    async def run_and_wait(
        self,
        *,
        job_id: str | None = None,
        job_name: str | None = None,
        interval: float = 5.0,
        # ASYNC109 wants asyncio.timeout rather than a timeout parameter; it
        # is used below, but the parameter stays because it is the public API.
        timeout: float = 250.0,  # noqa: ASYNC109
        **kwargs: Any,
    ) -> Record:
        """Enqueue a job and poll until its result reaches a terminal state.

        Args:
            job_id: UUID of the job to run.
            job_name: Name of the job to run, as an alternative to job_id.
            interval: Seconds between polls.
            timeout: Total seconds to wait before giving up.
            **kwargs: The POST body, typically `data={...}`.

        Returns:
            The job run response, refreshed once the job finished.

        Raises:
            JobTimeoutError: If the job is still active after `timeout`.
                The job itself keeps running; the error carries the job
                result id so it can be polled further.
        """
        if interval <= 0:
            raise ValueError("interval must be positive")
        job = await self.run(job_id=job_id, job_name=job_name, **kwargs)
        result = job.job_result
        try:
            async with asyncio.timeout(timeout):
                while _status_value(result.status) in ACTIVE_JOB_STATUSES:
                    await asyncio.sleep(interval)
                    await result.full_details()
        except TimeoutError:
            raise JobTimeoutError(getattr(result, "id", None), timeout) from None
        return job


class GraphqlEndpoint(Endpoint):
    """nb.extras.graphql_queries, with the ability to run a saved query."""

    async def run(self, query_id: str, **variables: Any) -> Record:
        """Execute a saved GraphQL query by id."""
        payload: dict[str, Any] = {"variables": variables} if variables else {}
        data = await self.api._request(
            "POST", f"{self.url}{query_id}/run/", json=payload
        )
        return self.record_class(data, self.api, full=True)
