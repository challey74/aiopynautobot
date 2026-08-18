"""App: attribute access to a Nautobot application's endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiopynautobot.endpoint import Endpoint, GraphqlEndpoint, JobsEndpoint

if TYPE_CHECKING:
    from aiopynautobot.api import Api

# Endpoints under `extras` that carry extra actions. Scoped to that app so
# a same-named plugin endpoint elsewhere isn't silently given a run().
SPECIAL_ENDPOINTS: dict[str, type[Endpoint]] = {
    "jobs": JobsEndpoint,
    "graphql_queries": GraphqlEndpoint,
}


class App:
    """Represents a Nautobot app (dcim, ipam, ...); any attribute access
    returns an Endpoint, e.g. nb.dcim.devices."""

    def __init__(self, api: Api, name: str) -> None:
        self._api = api
        self.name = name

    def __getattr__(self, name: str) -> Endpoint:
        if name.startswith("_"):
            raise AttributeError(name)
        if self.name == "extras" and name in SPECIAL_ENDPOINTS:
            return SPECIAL_ENDPOINTS[name](self._api, self, name)
        return Endpoint(self._api, self, name)

    def endpoint(self, name: str) -> Endpoint:
        """An Endpoint whose slug is used verbatim (no underscore-to-dash
        conversion), for plugin endpoints with literal underscores."""
        return Endpoint(self._api, self, name, literal_name=True)

    async def config(self) -> dict[str, Any]:
        """The app's `config` payload (e.g. nb.users.config())."""
        return await self._api._request(
            "GET", f"{self._api.base_url}/{self.name}/config/"
        )

    async def _drain(
        self, url: str, filters: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Concatenate every page of a paginated list route."""
        results: list[dict[str, Any]] = []
        params = filters
        while url:
            data = await self._api._request("GET", url, params=params)
            results.extend(data["results"])
            url = data.get("next")
            # The `next` link already carries the query string.
            params = None
        return results

    async def get_custom_fields(
        self, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Raw custom-field definitions for this app, across all pages."""
        return await self._drain(
            f"{self._api.base_url}/{self.name}/custom-fields/", filters
        )

    async def get_custom_field_choices(
        self, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Raw custom-field choice definitions for this app, across all pages."""
        return await self._drain(
            f"{self._api.base_url}/{self.name}/custom-field-choices/", filters
        )


class PluginsApp:
    """nb.plugins: attribute access routes into /api/plugins/<name>/...,
    e.g. nb.plugins.bgp.sessions -> /api/plugins/bgp/sessions/."""

    def __init__(self, api: Api) -> None:
        self._api = api

    def __getattr__(self, name: str) -> App:
        if name.startswith("_"):
            raise AttributeError(name)
        return App(self._api, "plugins/{}".format(name.replace("_", "-")))

    async def installed_plugins(self) -> list[dict[str, Any]]:
        """The apps/plugins installed on the Nautobot instance."""
        return await self._api._request(
            "GET", f"{self._api.base_url}/plugins/installed-plugins/"
        )
