import httpx
import pytest
from conftest import BASE, DEVICE_IDS, make_api

from aiopynautobot.endpoint import GraphqlEndpoint, JobsEndpoint


def test_app_attribute_builds_endpoint_url(nb):
    assert nb.dcim.devices.url == f"{BASE}/api/dcim/devices/"


def test_underscores_become_dashes(nb):
    assert nb.ipam.ip_addresses.url == f"{BASE}/api/ipam/ip-addresses/"


def test_dashed_app_names(nb):
    """data-validation and load-balancers have dashes in the app slug."""
    assert nb.data_validation.rules.url == f"{BASE}/api/data-validation/rules/"
    assert (
        nb.load_balancers.health_monitors.url
        == f"{BASE}/api/load-balancers/health-monitors/"
    )


def test_all_apps_present(nb):
    for app in (
        "circuits",
        "cloud",
        "data_validation",
        "dcim",
        "extras",
        "ipam",
        "load_balancers",
        "tenancy",
        "users",
        "virtualization",
        "vpn",
        "wireless",
    ):
        assert getattr(nb, app).name


def test_plugins_routing(nb):
    assert (
        nb.plugins.bgp_models.sessions.url == f"{BASE}/api/plugins/bgp-models/sessions/"
    )


def test_literal_endpoint_keeps_underscores(nb):
    endpoint = nb.plugins.test_plugin.endpoint("under_scores")
    assert endpoint.url == f"{BASE}/api/plugins/test-plugin/under_scores/"


def test_private_attribute_raises(nb):
    with pytest.raises(AttributeError):
        nb.dcim._nope  # noqa: B018


def test_jobs_endpoint_type_scoped_to_extras(nb):
    assert isinstance(nb.extras.jobs, JobsEndpoint)
    assert isinstance(nb.extras.graphql_queries, GraphqlEndpoint)
    # A same-named endpoint under another app stays a plain Endpoint.
    assert not isinstance(nb.dcim.jobs, JobsEndpoint)


async def test_installed_plugins(nb):
    plugins = await nb.plugins.installed_plugins()
    assert plugins[0]["name"] == "test_plugin"


async def test_app_config(nb, fake):
    await nb.users.config()
    assert fake.requests[-1].url.path == "/api/users/config/"


def test_app_has_no_choices_helper(nb):
    """The /<app>/_choices/ route is gone in Nautobot 3.x."""
    assert not hasattr(type(nb.dcim), "choices")


async def test_app_custom_fields_drains_pages(nb, fake):
    fields = await nb.extras.get_custom_fields()
    assert [f["key"] for f in fields] == ["billing_code", "owner"]
    calls = [r for r in fake.requests if r.url.path == "/api/extras/custom-fields/"]
    assert len(calls) == 2


async def test_app_custom_field_choices_drains_pages_keeping_filters(nb, fake):
    choices = await nb.extras.get_custom_field_choices(
        filters={"field": "billing_code"}
    )
    assert [c["value"] for c in choices] == ["first", "second"]
    calls = [
        r for r in fake.requests if r.url.path == "/api/extras/custom-field-choices/"
    ]
    assert len(calls) == 2
    # The next link carries the filter, so page 2 stays on the same query.
    assert all(r.url.params["field"] == "billing_code" for r in calls)


async def test_endpoint_choices_parses_both_shapes(nb):
    choices = await nb.dcim.devices.choices()
    assert choices["status"][0]["value"] == "active"
    # A list field carries its choices under `child`.
    assert choices["tags"][0]["value"] == "prod"
    assert "name" not in choices


async def test_endpoint_choices_cached_per_instance(nb, fake):
    endpoint = nb.dcim.devices
    await endpoint.choices()
    await endpoint.choices()
    assert len([r for r in fake.requests if r.method == "OPTIONS"]) == 1


async def test_endpoint_attribute_access_builds_a_fresh_endpoint(nb, fake):
    """So the choices cache does not survive `nb.dcim.devices` twice."""
    await nb.dcim.devices.choices()
    await nb.dcim.devices.choices()
    assert len([r for r in fake.requests if r.method == "OPTIONS"]) == 2


async def test_endpoint_choices_rejects_legacy_shape(fake):
    """Nautobot 2.3 and earlier answered OPTIONS with a `schema` block."""
    real_handler = fake.handler

    def legacy(request):
        if request.method == "OPTIONS":
            return httpx.Response(200, json={"schema": {"properties": {}}})
        return real_handler(request)

    fake.handler = legacy
    async with make_api(fake) as nb:
        with pytest.raises(ValueError, match="requires Nautobot 2.4"):
            await nb.dcim.devices.choices()


async def test_get_by_filter_matching_many_raises(nb):
    # sw-2 through sw-5 all have an empty serial.
    with pytest.raises(ValueError, match="more than one result"):
        await nb.dcim.devices.get(serial="")


async def test_filter_requires_kwargs(nb):
    with pytest.raises(ValueError, match="Use all\\(\\) instead"):
        nb.dcim.devices.filter()


async def test_all_offset_requires_limit(nb):
    with pytest.raises(ValueError, match="offset requires a positive limit"):
        nb.dcim.devices.all(offset=10)


async def test_get_by_uuid(nb):
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert device is not None
    assert device.name == "sw-1"


async def test_get_percent_encodes_the_pk(nb, fake):
    """A natural key with ? or a space must not corrupt the URL."""
    assert await nb.dcim.devices.get("name with space?x") is None
    request = fake.requests[-1]
    assert request.url.raw_path == b"/api/dcim/devices/name%20with%20space%3Fx/"
    assert not request.url.query
