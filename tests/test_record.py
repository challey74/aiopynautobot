import json

import pytest
from conftest import DEVICE_IDS, LOCATION_ID, make_api

from aiopynautobot.response import Record


async def test_nested_dicts_become_records(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert isinstance(device.location, Record)
    assert device.location.name == "Main Campus"


async def test_brief_record_attribute_raises_with_guidance(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    with pytest.raises(AttributeError, match="full_details"):
        device.location.time_zone  # noqa: B018


async def test_full_details_loads_brief_record(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert await device.location.full_details() is True
    assert device.location.time_zone == "America/Phoenix"


async def test_full_details_without_url_returns_false(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert await device.status.full_details() is False


async def test_save_patches_only_the_diff(nb, fake):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    device.serial = "XYZ789"
    assert await device.save() is True
    patch = [r for r in fake.requests if r.method == "PATCH"][-1]
    assert json.loads(patch.content) == {"serial": "XYZ789"}


async def test_save_without_changes_sends_nothing(nb, fake):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    before = len(fake.requests)
    assert await device.save() is False
    assert len(fake.requests) == before


async def test_updates_reports_diff(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    device.serial = "NEW"
    assert device.updates() == {"serial": "NEW"}


async def test_custom_fields_merge_semantics(nb):
    """Assigning a subset of custom_fields must not read as removals."""
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    device.custom_fields = {"billing_code": "NET-2"}
    assert device.updates() == {"custom_fields": {"billing_code": "NET-2"}}


async def test_custom_fields_unchanged_is_not_a_diff(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    device.custom_fields = {"billing_code": "NET-1"}
    assert device.updates() == {}


async def test_update_sets_then_saves(nb, fake):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert await device.update({"serial": "FROM-UPDATE"}) is True
    patch = [r for r in fake.requests if r.method == "PATCH"][-1]
    assert json.loads(patch.content) == {"serial": "FROM-UPDATE"}


async def test_serialize_collapses_nested_records(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    data = device.serialize()
    assert data["location"] == LOCATION_ID
    assert data["status"] == "active"  # choice fields collapse to their value


async def test_json_fields_stay_plain_dicts(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert isinstance(device.config_context, dict)
    assert device.config_context["ntp"] == ["10.0.0.1"]
    assert isinstance(device.custom_fields, dict)


async def test_delete(nb, fake):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert await device.delete() is True
    assert fake.requests[-1].method == "DELETE"
    assert DEVICE_IDS[0] not in fake.devices


async def test_equality_by_url_and_id(nb):
    a = await nb.dcim.devices.get(DEVICE_IDS[0])
    b = await nb.dcim.devices.get(DEVICE_IDS[0])
    c = await nb.dcim.devices.get(DEVICE_IDS[1])
    assert a == b and hash(a) == hash(b)
    assert a != c
    assert len({a, b, c}) == 2


async def test_records_without_identity_compare_by_identity(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    other = await nb.dcim.devices.get(DEVICE_IDS[1])
    assert device.status != other.status  # choice fields have no url/id


async def test_str_prefers_display(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert str(device) == "sw-1"


async def test_dict_cast_and_getitem(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    as_dict = dict(device)
    assert as_dict["name"] == "sw-1"
    assert as_dict["location"]["name"] == "Main Campus"
    assert device["serial"] == "ABC123"


async def test_filter_iterates_lazily(nb, fake):
    recordset = nb.dcim.devices.filter(name="sw-1")
    assert not fake.requests  # nothing fetched until iteration
    names = [d.name async for d in recordset]
    assert names == ["sw-1"]


async def test_pagination_fans_out_and_preserves_order(fake):
    fake.page_size = 2
    async with make_api(fake) as nb:
        names = [d.name async for d in nb.dcim.devices.all()]
    assert names == ["sw-1", "sw-2", "sw-3", "sw-4", "sw-5"]


async def test_explicit_offset_fetches_one_page(fake):
    fake.page_size = 2
    async with make_api(fake) as nb:
        names = [d.name async for d in nb.dcim.devices.all(limit=2, offset=2)]
    assert names == ["sw-3", "sw-4"]


async def test_count(nb):
    assert await nb.dcim.devices.count() == 5
    assert await nb.dcim.devices.count(name="sw-1") == 1


async def test_recordset_reruns_each_iteration(nb, fake):
    recordset = nb.dcim.devices.all()
    assert [d.name async for d in recordset]
    first = len(fake.requests)
    assert [d.name async for d in recordset]
    assert len(fake.requests) > first


async def test_bulk_update_via_recordset(nb, fake):
    updated = await nb.dcim.devices.filter(name="sw-2").update(serial="BULK")
    assert [r.serial for r in updated] == ["BULK"]
    patch = [r for r in fake.requests if r.method == "PATCH"][-1]
    assert json.loads(patch.content) == [{"id": DEVICE_IDS[1], "serial": "BULK"}]


async def test_bulk_update_empty_set_sends_nothing(nb, fake):
    before = len(fake.requests)
    assert await nb.dcim.devices.filter(name="nope").update(serial="X") == []
    assert not [r for r in fake.requests[before:] if r.method == "PATCH"]


async def test_bulk_delete_via_recordset(nb, fake):
    assert await nb.dcim.devices.filter(name="sw-2").delete() is True
    assert DEVICE_IDS[1] not in fake.devices


async def test_bulk_delete_empty_set_returns_false(nb):
    assert await nb.dcim.devices.filter(name="nope").delete() is False


async def test_endpoint_bulk_delete_accepts_ids_and_records(nb, fake):
    device = await nb.dcim.devices.get(DEVICE_IDS[2])
    assert await nb.dcim.devices.delete([DEVICE_IDS[1], device]) is True
    assert DEVICE_IDS[1] not in fake.devices
    assert DEVICE_IDS[2] not in fake.devices


async def test_create_single(nb):
    device = await nb.dcim.devices.create(name="sw-new")
    assert isinstance(device, Record)
    assert device.name == "sw-new"


async def test_create_bulk(nb):
    devices = await nb.dcim.devices.create([{"name": "a"}, {"name": "b"}])
    assert isinstance(devices, list)
    assert [d.name for d in devices] == ["a", "b"]
