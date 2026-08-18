import pytest
from conftest import CABLE_ID, DEVICE_IDS, INTERFACE_ID, PREFIX_ID, RACK_ID

import aiopynautobot
from aiopynautobot.models import (
    ENDPOINT_MODELS,
    Cables,
    Devices,
    Interfaces,
    IpAddresses,
    Prefixes,
    Racks,
    RackUnits,
)
from aiopynautobot.response import Record, RODetailEndpoint


def test_endpoint_resolves_model_class(nb):
    assert nb.dcim.devices.record_class is Devices
    assert nb.ipam.prefixes.record_class is Prefixes
    assert nb.dcim.racks.record_class is Racks


def test_unmapped_endpoint_falls_back_to_record(nb):
    assert nb.tenancy.tenants.record_class is Record


async def test_prefix_available_ips_list(nb):
    prefix = await nb.ipam.prefixes.get(PREFIX_ID)
    ips = [ip async for ip in prefix.available_ips.list()]
    assert [str(ip) for ip in ips] == ["10.0.0.1/29", "10.0.0.2/29", "10.0.0.3/29"]
    assert all(isinstance(ip, IpAddresses) for ip in ips)


async def test_prefix_available_ips_create_single(nb):
    prefix = await nb.ipam.prefixes.get(PREFIX_ID)
    ip = await prefix.available_ips.create()
    assert isinstance(ip, IpAddresses)
    assert ip.address == "10.0.0.1/29"


async def test_prefix_available_ips_create_many(nb):
    prefix = await nb.ipam.prefixes.get(PREFIX_ID)
    ips = await prefix.available_ips.create([{}, {}])
    assert isinstance(ips, list)
    assert len(ips) == 2


async def test_prefix_available_prefixes(nb, fake):
    prefix = await nb.ipam.prefixes.get(PREFIX_ID)
    listed = [p async for p in prefix.available_prefixes.list()]
    assert [str(p) for p in listed] == ["10.0.0.0/30"]
    child = await prefix.available_prefixes.create({"prefix_length": 30})
    assert isinstance(child, Prefixes)
    assert child.prefix == "10.0.0.0/30"
    assert fake.requests[-1].url.path.endswith("/available-prefixes/")


async def test_count_on_bare_list_route(nb):
    prefix = await nb.ipam.prefixes.get(PREFIX_ID)
    assert await prefix.available_ips.list().count() == 3


async def test_dynamic_group_members_url(nb):
    group = nb.extras.dynamic_groups.record_class(
        {"id": "1", "url": "http://nautobot.test/api/extras/dynamic-groups/1/"},
        nb,
        full=True,
    )
    assert group.members.url.endswith("/extras/dynamic-groups/1/members/")


async def test_allocation_error_on_204(nb):
    """Nautobot reports an exhausted pool with 204, not NetBox's 409."""
    prefix = await nb.ipam.prefixes.get(PREFIX_ID)
    with pytest.raises(aiopynautobot.AllocationError, match="could not be fulfilled"):
        await prefix.available_ips.create([{}, {}, {}, {}])


async def test_rack_elevation_is_read_only(nb):
    rack = await nb.dcim.racks.get(RACK_ID)
    units = [u async for u in rack.elevation.list()]
    assert isinstance(units[0], RackUnits)
    assert isinstance(rack.elevation, RODetailEndpoint)
    with pytest.raises(NotImplementedError):
        await rack.elevation.create({})


def test_rack_units_view_is_gone():
    """The /units/ route 404s on Nautobot 3.x; /elevation/ replaced it."""
    assert not hasattr(Racks, "units")


async def test_device_napalm_is_read_only(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert isinstance(device.napalm, RODetailEndpoint)
    with pytest.raises(NotImplementedError):
        await device.napalm.create({})


async def test_detail_route_returning_a_plain_object(nb):
    """napalm answers with one object, not a paginated envelope."""
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    recordset = device.napalm.list(method="get_facts")
    facts = [f async for f in recordset]
    assert len(facts) == 1
    assert facts[0].get_facts["hostname"] == "sw-1"
    assert await recordset.count() == 1


async def test_notes_on_any_record(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert device.notes.url.endswith(f"/dcim/devices/{DEVICE_IDS[0]}/notes/")


async def test_trace_maps_hops_to_model_classes(nb):
    interface = await nb.dcim.interfaces.get(INTERFACE_ID)
    assert isinstance(interface, Interfaces)
    hops = await interface.trace()
    assert len(hops) == 1
    termination_a, cable, termination_b = hops[0]
    assert isinstance(termination_a, Interfaces)
    assert isinstance(cable, Cables)
    assert cable.id == CABLE_ID
    # An unterminated far end comes back as None rather than a Record.
    assert termination_b is None


async def test_trace_cable_terminations_stay_raw_json(nb):
    interface = await nb.dcim.interfaces.get(INTERFACE_ID)
    _, cable, _ = (await interface.trace())[0]
    assert cable.terminations == [{"raw": True}]


def test_json_fields_inherit_the_base_set():
    assert "custom_fields" in Devices.JSON_FIELDS
    assert "config_context" in Devices.JSON_FIELDS
    assert "config_context" not in Record.JSON_FIELDS


def test_register_model(nb):
    class Widget(Record):
        pass

    aiopynautobot.register_model("plugins/test-plugin", "widgets", Widget)
    try:
        assert nb.plugins.test_plugin.widgets.record_class is Widget
    finally:
        del ENDPOINT_MODELS["plugins/test-plugin/widgets"]


def test_every_mapped_key_is_app_slash_endpoint():
    for key, cls in ENDPOINT_MODELS.items():
        assert key.count("/") == 1, key
        assert issubclass(cls, Record)
