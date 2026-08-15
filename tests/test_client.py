import httpx
import pytest
from conftest import BASE, DEVICE_IDS, make_api

import aiopynautobot


async def test_token_uses_token_scheme(nb, fake):
    await nb.dcim.devices.get(DEVICE_IDS[0])
    assert fake.requests[-1].headers["Authorization"] == "Token abc123"


async def test_no_token_sends_no_auth_header(fake):
    async with make_api(fake, token=None) as nb:
        await nb.dcim.devices.get(DEVICE_IDS[0])
    assert "Authorization" not in fake.requests[-1].headers


async def test_user_agent_identifies_library(nb, fake):
    await nb.status()
    assert fake.requests[-1].headers["User-Agent"].startswith("python-aiopynautobot/")


async def test_accept_header_without_api_version(nb, fake):
    await nb.status()
    assert fake.requests[-1].headers["Accept"] == "application/json"


async def test_api_version_pins_accept_header(fake):
    async with make_api(fake, api_version="2.4") as nb:
        await nb.status()
    assert fake.requests[-1].headers["Accept"] == "application/json; version=2.4"


async def test_default_filters_applied_to_reads(fake):
    async with make_api(fake, exclude_m2m=True, include_default="config_context") as nb:
        await nb.dcim.devices.get(name="sw-1")
    params = fake.requests[-1].url.params
    assert params["exclude_m2m"] == "true"
    assert params["include"] == "config_context"


async def test_default_filters_reach_count(fake):
    """pynautobot omits them on count(); we apply them uniformly."""
    async with make_api(fake, exclude_m2m=True) as nb:
        await nb.dcim.devices.count()
    assert fake.requests[-1].url.params["exclude_m2m"] == "true"


async def test_explicit_param_beats_default_filter(fake):
    async with make_api(fake, include_default="config_context") as nb:
        await nb.dcim.devices.get(name="sw-1", include="computed_fields")
    assert fake.requests[-1].url.params["include"] == "computed_fields"


async def test_default_filters_not_sent_on_delete(fake):
    async with make_api(fake, exclude_m2m=True) as nb:
        device = await nb.dcim.devices.get(DEVICE_IDS[0])
        await device.delete()
    assert "exclude_m2m" not in fake.requests[-1].url.params


async def test_version_reads_header_through_403(nb):
    """Nautobot instances with LOGIN_REQUIRED answer 403 but still set it."""
    assert await nb.version() == "2.4"


async def test_status(nb):
    assert (await nb.status())["nautobot-version"] == "2.4.0"


async def test_openapi_uses_swagger_json_and_caches(nb, fake):
    spec = await nb.openapi()
    assert spec["openapi"] == "3.0.3"
    await nb.openapi()
    calls = [r for r in fake.requests if r.url.path == "/api/swagger.json"]
    assert len(calls) == 1


async def test_context_manager_closes_owned_client():
    api = aiopynautobot.api(BASE, token="x")
    async with api:
        pass
    assert api._client.is_closed


async def test_supplied_client_is_not_closed(fake):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    async with aiopynautobot.api(BASE, token="x", client=client) as nb:
        await nb.status()
    assert not client.is_closed
    await client.aclose()


async def test_request_error_carries_status_and_body(nb, fake):
    fake.fail_next = [400]
    with pytest.raises(aiopynautobot.RequestError) as excinfo:
        await nb.status()
    assert excinfo.value.status_code == 400
    assert "injected" in excinfo.value.error


async def test_content_error_on_non_json(nb, fake):
    fake.fail_next = []
    fake.handler = lambda request: httpx.Response(200, text="<html>nope</html>")
    async with make_api(fake) as bad:
        with pytest.raises(aiopynautobot.ContentError, match="not a Nautobot server"):
            await bad.status()


async def test_404_on_detail_returns_none(nb):
    assert await nb.dcim.devices.get("00000000-0000-4000-8000-000000000000") is None
