"""Per-endpoint Record subclasses.

Endpoints listed in ENDPOINT_MODELS return these Record subclasses so
Nautobot-specific helpers (available-ips allocation, cable tracing, job
runs) hang off the record, and so per-model JSON fields stay raw dicts
instead of being coerced into nested Records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiopynautobot.response import DetailEndpoint, Record, RODetailEndpoint

if TYPE_CHECKING:
    from aiopynautobot.api import Api

__all__ = [
    "ENDPOINT_MODELS",
    "Cables",
    "CircuitTerminations",
    "Circuits",
    "CloudNetworks",
    "CloudResourceTypes",
    "CloudServices",
    "ConfigContexts",
    "ConsolePorts",
    "ConsoleServerPorts",
    "ControllerManagedDeviceGroups",
    "Controllers",
    "CustomFieldChoices",
    "CustomFields",
    "DeviceTypes",
    "Devices",
    "DynamicGroups",
    "ExternalIntegrations",
    "FrontPorts",
    "GitRepositories",
    "GraphqlQueries",
    "Interfaces",
    "IpAddresses",
    "JobResults",
    "Jobs",
    "ObjectChanges",
    "Permissions",
    "Platforms",
    "PowerOutlets",
    "PowerPorts",
    "Prefixes",
    "RackUnits",
    "Racks",
    "RearPorts",
    "Relationships",
    "SavedViews",
    "Secrets",
    "TraceableRecord",
    "Users",
    "VirtualMachines",
    "register_model",
]


# ---------------------------------------------------------------- circuits


class Circuits(Record):
    """circuits/circuits record."""

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "cid", ""))


class CircuitTerminations(Record):
    """circuits/circuit-terminations record."""

    def __str__(self) -> str:
        base = super().__str__()
        if base:
            return base
        circuit = getattr(self, "circuit", None)
        return str(getattr(circuit, "cid", "")) if circuit else ""


# ------------------------------------------------------------------- cloud


class CloudResourceTypes(Record):
    """cloud/cloud-resource-types record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"config_schema"}


class CloudServices(Record):
    """cloud/cloud-services record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"extra_config"}


class CloudNetworks(Record):
    """cloud/cloud-networks record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"extra_config"}


# -------------------------------------------------------------------- dcim


class TraceableRecord(Record):
    """A cable-terminating record that supports `await record.trace()`."""

    async def trace(self) -> list[list[Record | None]]:
        """Follow the cable path from this termination.

        Returns:
            One `[termination_a, cable, termination_b]` triple per hop.
            Entries are None where the path is not fully terminated.
        """
        url = "{}/trace/".format(str(self.url).rstrip("/"))
        hops: list[list[Record | None]] = []
        for hop in await self._api._request("GET", url):
            parsed: list[Record | None] = []
            for item in hop:
                if not item:
                    parsed.append(None)
                    continue
                record_class = _record_class_for_url(self._api, item.get("url", ""))
                parsed.append(record_class(item, self._api, full=True))
            hops.append(parsed)
        return hops


class DeviceTypes(Record):
    """dcim/device-types record."""

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "model", ""))


class Devices(Record):
    """dcim/devices record."""

    JSON_FIELDS = Record.JSON_FIELDS | {
        "config_context",
        "local_config_context_data",
    }

    @property
    def napalm(self) -> RODetailEndpoint:
        """The read-only `napalm` sub-endpoint.

        `await device.napalm.list(method="get_facts")` proxies a live
        NAPALM call through Nautobot.
        """
        return RODetailEndpoint(self, "napalm")


class Interfaces(TraceableRecord):
    """dcim/interfaces record."""


class FrontPorts(TraceableRecord):
    """dcim/front-ports record."""


class RearPorts(TraceableRecord):
    """dcim/rear-ports record."""


class PowerOutlets(TraceableRecord):
    """dcim/power-outlets record."""


class PowerPorts(TraceableRecord):
    """dcim/power-ports record."""


class ConsolePorts(TraceableRecord):
    """dcim/console-ports record."""


class ConsoleServerPorts(TraceableRecord):
    """dcim/console-server-ports record."""


class Cables(TraceableRecord):
    """dcim/cables record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"terminations"}


class Platforms(Record):
    """dcim/platforms record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"napalm_args"}


class Controllers(Record):
    """dcim/controllers record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"capabilities"}


class ControllerManagedDeviceGroups(Record):
    """dcim/controller-managed-device-groups record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"capabilities"}


class RackUnits(Record):
    """A single rack unit, as returned by racks/<id>/elevation."""


class Racks(Record):
    """dcim/racks record with an elevation view.

    pynautobot's `units` view is not carried over: the /units/ route is
    gone in Nautobot 3.x (404), /elevation/ replaces it.
    """

    @property
    def elevation(self) -> RODetailEndpoint:
        return RODetailEndpoint(self, "elevation", record_class=RackUnits)


# ------------------------------------------------------------------ extras


class ConfigContexts(Record):
    """extras/config-contexts record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"data"}


class ObjectChanges(Record):
    """extras/object-changes record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"object_data", "object_data_v2"}


class CustomFields(Record):
    """extras/custom-fields record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"default"}


class CustomFieldChoices(Record):
    """extras/custom-field-choices record."""

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "value", ""))


class JobResults(Record):
    """extras/job-results record."""

    JSON_FIELDS = Record.JSON_FIELDS | {
        "celery_kwargs",
        "data",
        "meta",
        "result",
        "task_args",
        "task_kwargs",
    }


class Jobs(Record):
    """extras/jobs record."""

    async def run(self, **kwargs: Any) -> Record:
        """Enqueue this job. See JobsEndpoint.run for the arguments."""
        result = await DetailEndpoint(self, "run").create(kwargs)
        assert isinstance(result, Record)
        return result


class GraphqlQueries(Record):
    """extras/graphql-queries record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"variables"}

    async def run(self, **variables: Any) -> Record:
        """Execute this saved query, optionally with variables."""
        payload: dict[str, Any] = {"variables": variables} if variables else {}
        result = await DetailEndpoint(self, "run").create(payload)
        assert isinstance(result, Record)
        return result


class DynamicGroups(Record):
    """extras/dynamic-groups record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"filter"}

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "id", ""))

    @property
    def members(self) -> DetailEndpoint:
        """The group's resolved members."""
        return DetailEndpoint(self, "members")


class Secrets(Record):
    """extras/secrets record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"parameters"}


class GitRepositories(Record):
    """extras/git-repositories record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"provided_contents"}


class ExternalIntegrations(Record):
    """extras/external-integrations record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"extra_config", "headers"}


class SavedViews(Record):
    """extras/saved-views record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"config"}


class Relationships(Record):
    """extras/relationships record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"source_filter", "destination_filter"}


# -------------------------------------------------------------------- ipam


class IpAddresses(Record):
    """ipam/ip-addresses record."""

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "address", ""))


class Prefixes(Record):
    """ipam/prefixes record with available-ips/-prefixes allocation."""

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "prefix", ""))

    @property
    def available_ips(self) -> DetailEndpoint:
        return DetailEndpoint(self, "available-ips", record_class=IpAddresses)

    @property
    def available_prefixes(self) -> DetailEndpoint:
        return DetailEndpoint(self, "available-prefixes", record_class=Prefixes)


# ------------------------------------------------------------------- users


class Users(Record):
    """users/users record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"config_data"}

    def __str__(self) -> str:
        return super().__str__() or str(getattr(self, "username", ""))


class Permissions(Record):
    """users/permissions record."""

    JSON_FIELDS = Record.JSON_FIELDS | {"constraints"}


# ---------------------------------------------------------- virtualization


class VirtualMachines(Record):
    """virtualization/virtual-machines record."""

    JSON_FIELDS = Record.JSON_FIELDS | {
        "config_context",
        "local_config_context_data",
    }


ENDPOINT_MODELS: dict[str, type[Record]] = {
    "circuits/circuits": Circuits,
    "circuits/circuit-terminations": CircuitTerminations,
    "cloud/cloud-networks": CloudNetworks,
    "cloud/cloud-resource-types": CloudResourceTypes,
    "cloud/cloud-services": CloudServices,
    "dcim/cables": Cables,
    "dcim/console-ports": ConsolePorts,
    "dcim/console-server-ports": ConsoleServerPorts,
    "dcim/controller-managed-device-groups": ControllerManagedDeviceGroups,
    "dcim/controllers": Controllers,
    "dcim/device-types": DeviceTypes,
    "dcim/devices": Devices,
    "dcim/front-ports": FrontPorts,
    "dcim/interfaces": Interfaces,
    "dcim/platforms": Platforms,
    "dcim/power-outlets": PowerOutlets,
    "dcim/power-ports": PowerPorts,
    "dcim/racks": Racks,
    "dcim/rear-ports": RearPorts,
    "extras/config-contexts": ConfigContexts,
    "extras/custom-field-choices": CustomFieldChoices,
    "extras/custom-fields": CustomFields,
    "extras/dynamic-groups": DynamicGroups,
    "extras/external-integrations": ExternalIntegrations,
    "extras/git-repositories": GitRepositories,
    "extras/graphql-queries": GraphqlQueries,
    "extras/job-results": JobResults,
    "extras/jobs": Jobs,
    "extras/object-changes": ObjectChanges,
    "extras/relationships": Relationships,
    "extras/saved-views": SavedViews,
    "extras/secrets": Secrets,
    "ipam/ip-addresses": IpAddresses,
    "ipam/prefixes": Prefixes,
    "users/permissions": Permissions,
    "users/users": Users,
    "virtualization/virtual-machines": VirtualMachines,
}


def register_model(app: str, endpoint: str, record_class: type[Record]) -> None:
    """Register a Record subclass for an endpoint, e.g. a plugin's:

        register_model("plugins/bgp", "sessions", BgpSession)

    The endpoint name is converted like attribute access (`_` to `-`).
    """
    ENDPOINT_MODELS["{}/{}".format(app, endpoint.replace("_", "-"))] = record_class


def _record_class_for_url(api: Api, url: str) -> type[Record]:
    """Resolve the Record subclass for a detail url, for trace() hops."""
    if not url.startswith(api.base_url):
        return Record
    parts = url[len(api.base_url) :].strip("/").split("/")
    if parts[0] == "plugins" and len(parts) >= 3:
        key = f"plugins/{parts[1]}/{parts[2]}"
    elif len(parts) >= 2:
        key = f"{parts[0]}/{parts[1]}"
    else:
        return Record
    return ENDPOINT_MODELS.get(key, Record)
