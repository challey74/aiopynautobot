"""Read-only integration tests against a live Nautobot.

Skipped unless AIOPYNAUTOBOT_DEMO_URL is set, so the default suite stays
offline. Point it at demo.nautobot.com (documented read-only token is the
default) or any instance you control:

    AIOPYNAUTOBOT_DEMO_URL=https://demo.nautobot.com uv run pytest tests/test_demo_integration.py

Everything here is a GET or a GraphQL query. No writes: the demo is a
shared instance.
"""

import os

import pytest

import aiopynautobot

DEMO_URL = os.environ.get("AIOPYNAUTOBOT_DEMO_URL")
DEMO_TOKEN = os.environ.get("AIOPYNAUTOBOT_DEMO_TOKEN", "a" * 40)

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
