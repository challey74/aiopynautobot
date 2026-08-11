"""Api: the entry point to aiopynautobot."""

from __future__ import annotations

import asyncio
import random
from importlib.metadata import version as _version
from types import TracebackType
from typing import Any, Self

import httpx

from aiopynautobot.app import PluginsApp
from aiopynautobot.apps_generated import (
    CircuitsApp,
    CloudApp,
    CoreApp,
    DataValidationApp,
    DcimApp,
    ExtrasApp,
    IpamApp,
    LoadBalancersApp,
    TenancyApp,
    UsersApp,
    VirtualizationApp,
    VpnApp,
    WirelessApp,
)
from aiopynautobot.exceptions import AllocationError, ContentError, RequestError
from aiopynautobot.graphql import GraphQLQuery


class Api:
    """Async Nautobot API client.

    Use as an async context manager so the connection pool is closed:

        async with aiopynautobot.api("https://nautobot", token="...") as nb:
            device = await nb.dcim.devices.get(name="sw-1")

    Every request-making method raises RequestError on a non-success
    response (AllocationError instead for a POST answered with 204) and
    ContentError when a successful response isn't JSON; transient
    failures are retried per `retries` before surfacing. Per-method
    Raises sections elsewhere list only conditions beyond these.

    Args:
        url: Base Nautobot URL without the /api suffix (it is appended).
        token: API token, sent as `Authorization: Token <token>`.
        timeout: Per-request timeout in seconds.
        max_concurrency: Concurrent page fetches per result-set iteration.
        retries: Bound on automatic retries with exponential backoff and
            jitter. 429 is retried for any method (honoring Retry-After);
            transient 502/503/504 and connection failures retry for GETs
            only, since an ambiguous write may have been processed. 0
            disables.
        api_version: Pins the Nautobot REST API version, sent as
            `Accept: application/json; version=<x.y>`. None lets the
            server choose its default.
        exclude_m2m: Nautobot 2.4+. Omits many-to-many relationships from
            read responses, which is a large speedup on wide objects.
        include_default: Comma-separated opt-in fields added to every read,
            e.g. "config_context,computed_fields".
        client: Custom httpx.AsyncClient (SSL config, proxies, mock
            transports). A supplied client is yours to close; the Api
            closes only clients it creates itself.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        max_concurrency: int = 4,
        retries: int = 3,
        api_version: str | None = None,
        exclude_m2m: bool | None = None,
        include_default: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = "{}/api".format(url.rstrip("/"))
        self.token = token
        self.max_concurrency = max_concurrency
        self.retries = retries
        self.api_version = api_version
        self._openapi: dict[str, Any] | None = None

        # Applied to every read (and to create, so the response carries the
        # same opt-in fields). Unlike pynautobot these also reach count().
        self.default_filters: dict[str, Any] = {}
        if exclude_m2m is not None:
            self.default_filters["exclude_m2m"] = exclude_m2m
        if include_default is not None:
            self.default_filters["include"] = include_default

        # follow_redirects matches requests/pynautobot behavior: Nautobot's
        # hyperlinked `url` fields may redirect (e.g. http->https behind a
        # proxy) and record methods fetch those urls directly.
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        )

        self.circuits = CircuitsApp(self, "circuits")
        self.cloud = CloudApp(self, "cloud")
        self.core = CoreApp(self, "core")
        self.data_validation = DataValidationApp(self, "data-validation")
        self.dcim = DcimApp(self, "dcim")
        self.extras = ExtrasApp(self, "extras")
        self.ipam = IpamApp(self, "ipam")
        self.load_balancers = LoadBalancersApp(self, "load-balancers")
        self.plugins = PluginsApp(self)
        self.tenancy = TenancyApp(self, "tenancy")
        self.users = UsersApp(self, "users")
        self.virtualization = VirtualizationApp(self, "virtualization")
        self.vpn = VpnApp(self, "vpn")
        self.wireless = WirelessApp(self, "wireless")
        self.graphql = GraphQLQuery(self)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the connection pool, if this Api created it.

        A client passed in via `client=` is the caller's to close
        (httpx convention), so sharing one client across Api instances
        is safe.
        """
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        accept = "application/json"
        if self.api_version:
            accept = f"{accept}; version={self.api_version}"
        headers = {
            "Accept": accept,
            "User-Agent": f"python-aiopynautobot/{_version('aiopynautobot')}",
        }
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        """Delay in seconds before retry `attempt` (0-based)."""
        if retry_after is not None:
            try:
                # Honor Retry-After, capped so a broken proxy can't stall us.
                return min(float(retry_after), 60.0)
            except ValueError:
                pass  # HTTP-date form; fall through to exponential backoff
        delay = min(0.5 * 2**attempt, 8.0)
        return delay * (0.5 + random.random() / 2)

    async def _request_response(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        merged = {**self._headers(), **(headers or {})}
        if method in ("GET", "POST"):
            # Explicit params win over the client-wide defaults.
            params = {**self.default_filters, **(params or {})}
        attempt = 0
        while True:
            retry_after = None
            try:
                resp = await self._client.request(
                    method, url, params=params, json=json, headers=merged
                )
            except httpx.TransportError:
                # An ambiguous failure is only safely repeatable for GETs:
                # a timed-out write may have been processed server-side.
                if method != "GET" or attempt >= self.retries:
                    raise
            else:
                if resp.status_code == 429 and attempt < self.retries:
                    # Rejected without processing; safe to retry any method.
                    retry_after = resp.headers.get("Retry-After")
                elif (
                    resp.status_code in (502, 503, 504)
                    and method == "GET"
                    and attempt < self.retries
                ):
                    pass
                else:
                    # Nautobot answers an exhausted allocation pool with an
                    # empty 204 rather than an error status.
                    if method == "POST" and resp.status_code == 204:
                        raise AllocationError(resp)
                    if not resp.is_success:
                        raise RequestError(resp)
                    return resp
            await asyncio.sleep(self._backoff(attempt, retry_after))
            attempt += 1

    @staticmethod
    def _decode(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            raise ContentError(resp) from None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        resp = await self._request_response(
            method, url, params=params, json=json, headers=headers
        )
        if method == "DELETE":
            return True
        return self._decode(resp)

    async def version(self) -> str:
        """The Nautobot REST API version string, read from response headers.

        Works with restricted tokens and on instances that require login:
        a 403 still carries the header.
        """
        resp = await self._client.get(f"{self.base_url}/", headers=self._headers())
        if resp.is_success or resp.status_code == 403:
            return resp.headers.get("API-Version", "")
        raise RequestError(resp)

    async def status(self) -> dict[str, Any]:
        """The /api/status/ payload (Nautobot version, apps, workers...)."""
        return await self._request("GET", f"{self.base_url}/status/")

    async def openapi(self) -> dict[str, Any]:
        """The OpenAPI spec, cached after the first call.

        Nautobot serves this at /api/swagger.json, not NetBox's
        /api/schema/.
        """
        if self._openapi is None:
            self._openapi = await self._request("GET", f"{self.base_url}/swagger.json")
        assert self._openapi is not None
        return self._openapi
