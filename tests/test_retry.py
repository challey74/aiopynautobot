import httpx2
import pytest
from conftest import DEVICE_IDS, make_api

import aiopynautobot


async def test_429_retried_for_get(nb, fake):
    fake.fail_next = [429]
    device = await nb.dcim.devices.get(DEVICE_IDS[0])
    assert device is not None
    assert len(fake.requests) == 2


async def test_429_retried_for_write(nb, fake):
    """429 means the request was rejected unprocessed, so writes are safe."""
    fake.fail_next = [429]
    await nb.dcim.devices.create(name="sw-new")
    assert len(fake.requests) == 2


async def test_503_retried_for_get(nb, fake):
    fake.fail_next = [503, 503]
    assert await nb.dcim.devices.get(DEVICE_IDS[0]) is not None
    assert len(fake.requests) == 3


async def test_503_not_retried_for_write(nb, fake):
    """An ambiguous write may already have been processed server-side."""
    fake.fail_next = [503]
    with pytest.raises(aiopynautobot.RequestError) as excinfo:
        await nb.dcim.devices.create(name="sw-new")
    assert excinfo.value.status_code == 503
    assert len(fake.requests) == 1


async def test_transport_error_retried_for_get(nb, fake):
    fake.fail_next = ["transport"]
    assert await nb.dcim.devices.get(DEVICE_IDS[0]) is not None


async def test_transport_error_not_retried_for_write(nb, fake):
    fake.fail_next = ["transport"]
    with pytest.raises(httpx2.ConnectError):
        await nb.dcim.devices.create(name="sw-new")


async def test_retries_are_bounded(fake):
    async with make_api(fake, retries=2) as nb:
        fake.fail_next = [503, 503, 503, 503]
        with pytest.raises(aiopynautobot.RequestError):
            await nb.dcim.devices.get(DEVICE_IDS[0])
    assert len(fake.requests) == 3


async def test_retries_can_be_disabled(fake):
    async with make_api(fake, retries=0) as nb:
        fake.fail_next = [429]
        with pytest.raises(aiopynautobot.RequestError):
            await nb.dcim.devices.get(DEVICE_IDS[0])
    assert len(fake.requests) == 1


def test_backoff_honors_retry_after(nb):
    assert nb._backoff(0, "3") == 3.0


def test_backoff_caps_retry_after(nb):
    assert nb._backoff(0, "9999") == 60.0


def test_backoff_falls_back_on_http_date(nb):
    # An HTTP-date Retry-After isn't parseable as seconds; use exponential.
    assert 0 < nb._backoff(0, "Wed, 21 Oct 2026 07:28:00 GMT") <= 0.5
