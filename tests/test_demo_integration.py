"""Read-only integration tests against a live Nautobot.

Skipped unless AIOPYNAUTOBOT_DEMO_URL is set, so the default suite stays
offline. Point it at demo.nautobot.com (documented read-only token is the
default) or any instance you control:

    AIOPYNAUTOBOT_DEMO_URL=https://demo.nautobot.com uv run pytest tests/test_demo_integration.py

Read-only by default. The write tests additionally require
AIOPYNAUTOBOT_DEMO_WRITES=1: they create uniquely named objects and delete
them afterward, but only opt in on an instance whose data is disposable.
"""

import os
import uuid

import pytest

import aiopynautobot

DEMO_URL = os.environ.get("AIOPYNAUTOBOT_DEMO_URL")
DEMO_TOKEN = os.environ.get("AIOPYNAUTOBOT_DEMO_TOKEN", "a" * 40)
DEMO_WRITES = os.environ.get("AIOPYNAUTOBOT_DEMO_WRITES") == "1"

pytestmark = pytest.mark.skipif(
    not DEMO_URL, reason="AIOPYNAUTOBOT_DEMO_URL not set; live tests are opt-in"
)


@pytest.fixture
async def live():
    async with aiopynautobot.api(DEMO_URL, token=DEMO_TOKEN, timeout=60) as nb:
        yield nb


async def test_version_and_status(live):
    assert await live.version()
    assert "nautobot-version" in await live.status()


async def test_pagination_with_early_break_stays_bounded(live):
    assert await live.dcim.devices.count() > 0
    seen = 0
    async for _ in live.dcim.devices.all(limit=5):
        seen += 1
        if seen == 12:
            break
    assert seen == 12


async def test_get_by_uuid_and_missing(live):
    first = await anext(aiter(live.dcim.devices.all(limit=1)))
    got = await live.dcim.devices.get(first.id)
    assert got is not None and got.id == first.id
    missing = await live.dcim.devices.get("00000000-0000-4000-8000-000000000000")
    assert missing is None


async def test_nested_record_full_details(live):
    device = await anext(aiter(live.dcim.devices.all(limit=1)))
    location = device.location
    if location is None:
        pytest.skip("device has no location")
    assert await location.full_details() is True
    assert location._has_details


async def test_custom_fields_drain(live):
    assert isinstance(await live.extras.get_custom_fields(), list)


async def test_prefix_detail_endpoints(live):
    prefix = await anext(aiter(live.ipam.prefixes.all(limit=1)), None)
    if prefix is None:
        pytest.skip("no prefixes on instance")
    ips = [ip async for ip in prefix.available_ips.list(limit=3)]
    assert isinstance(ips, list)
    notes = [n async for n in prefix.notes.list()]
    assert isinstance(notes, list)


async def test_graphql_round_trip(live):
    result = await live.graphql.query("query { devices(limit: 2) { name } }")
    assert result.status_code == 200
    assert isinstance(result.data["devices"], list)
    with pytest.raises(aiopynautobot.GraphQLError) as excinfo:
        await live.graphql.query("query { bogus_field_xyz }")
    assert excinfo.value.errors


async def test_openapi(live):
    assert "paths" in await live.openapi()


needs_writes = pytest.mark.skipif(
    not DEMO_WRITES, reason="AIOPYNAUTOBOT_DEMO_WRITES=1 not set; writes are opt-in"
)


@needs_writes
async def test_write_lifecycle(live):
    """create -> diff save -> update -> bulk ops -> notes -> delete, then
    clean up everything tagged with this run's unique marker."""
    tag = f"aiopynb-it-{uuid.uuid4().hex[:8]}"
    try:
        tenant = await live.tenancy.tenants.create(name=f"{tag}-one")
        assert len(str(tenant.id)) == 36  # UUID pk

        tenant.description = "integration"
        assert await tenant.save() is True
        assert await tenant.save() is False  # clean record sends nothing
        refetched = await live.tenancy.tenants.get(tenant.id)
        assert refetched.description == "integration"

        assert await tenant.update({"comments": "updated"}) is True

        bulk = await live.tenancy.tenants.create(
            [{"name": f"{tag}-b1"}, {"name": f"{tag}-b2"}]
        )
        assert isinstance(bulk, list) and len(bulk) == 2

        updated = await live.tenancy.tenants.filter(q=tag).update(
            description="bulk-updated"
        )
        assert len(updated) == 3

        note = await tenant.notes.create({"note": f"{tag} note"})
        assert getattr(note, "id", None)
        notes = [n async for n in tenant.notes.list()]
        assert any(tag in str(n.note) for n in notes)

        assert await live.tenancy.tenants.delete([bulk[0], str(bulk[1].id)]) is True
    finally:
        async for leftover in live.tenancy.tenants.filter(q=tag):
            await leftover.delete()
        assert await live.tenancy.tenants.count(q=tag) == 0


@needs_writes
async def test_write_allocation(live):
    """Allocate the next free IP from a real prefix, then release it."""
    prefix = None
    async for p in live.ipam.prefixes.all(limit=20):
        if getattr(p, "type", None) and str(p.type) != "Container":
            prefix = p
            break
    if prefix is None:
        pytest.skip("no non-container prefix on instance")
    try:
        ip = await prefix.available_ips.create({"status": "Active"})
    except aiopynautobot.AllocationError:
        return  # pool exhausted: the 204 mapping is itself the assertion
    try:
        assert ip.address
    finally:
        assert await ip.delete() is True
