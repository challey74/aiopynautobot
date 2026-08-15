import json
import re

import httpx
import pytest

import aiopynautobot

BASE = "http://nautobot.test"

# Nautobot uses UUID primary keys; these are fixed so tests can reference them.
DEVICE_IDS = [
    "11111111-1111-4111-8111-111111111101",
    "11111111-1111-4111-8111-111111111102",
    "11111111-1111-4111-8111-111111111103",
    "11111111-1111-4111-8111-111111111104",
    "11111111-1111-4111-8111-111111111105",
]
LOCATION_ID = "22222222-2222-4222-8222-222222222201"
PREFIX_ID = "33333333-3333-4333-8333-333333333301"
RACK_ID = "44444444-4444-4444-8444-444444444401"
JOB_ID = "55555555-5555-4555-8555-555555555501"
JOB_RESULT_ID = "55555555-5555-4555-8555-555555555502"
INTERFACE_ID = "66666666-6666-4666-8666-666666666601"
CABLE_ID = "66666666-6666-4666-8666-666666666602"
QUERY_ID = "88888888-8888-4888-8888-888888888801"


def make_device(pk, name, serial="", location_id=LOCATION_ID):
    return {
        "id": pk,
        "url": f"{BASE}/api/dcim/devices/{pk}/",
        "display": name,
        "name": name,
        "serial": serial,
        "status": {"value": "active", "label": "Active"},
        "location": {
            "id": location_id,
            "url": f"{BASE}/api/dcim/locations/{location_id}/",
            "display": "Main Campus",
            "name": "Main Campus",
        },
        "custom_fields": {"owner": None, "billing_code": "NET-1"},
        "config_context": {"ntp": ["10.0.0.1"]},
        "local_config_context_data": None,
        "tags": [],
    }


LOCATION_FULL = {
    "id": LOCATION_ID,
    "url": f"{BASE}/api/dcim/locations/{LOCATION_ID}/",
    "display": "Main Campus",
    "name": "Main Campus",
    "time_zone": "America/Phoenix",
    "description": "",
}

PREFIX_FULL = {
    "id": PREFIX_ID,
    "url": f"{BASE}/api/ipam/prefixes/{PREFIX_ID}/",
    "display": "10.0.0.0/29",
    "prefix": "10.0.0.0/29",
    "status": {"value": "active", "label": "Active"},
    "custom_fields": {},
}

RACK_FULL = {
    "id": RACK_ID,
    "url": f"{BASE}/api/dcim/racks/{RACK_ID}/",
    "display": "rack-1",
    "name": "rack-1",
}

DEVICE_OPTIONS = {
    "actions": {
        "POST": {
            "name": {"type": "string"},
            "status": {
                "type": "choice",
                "choices": [
                    {"value": "active", "display_name": "Active"},
                    {"value": "offline", "display_name": "Offline"},
                ],
            },
            "tags": {
                "type": "list",
                "child": {"choices": [{"value": "prod", "display_name": "Prod"}]},
            },
        }
    }
}


class FakeNautobot:
    """Minimal in-memory Nautobot served through httpx.MockTransport."""

    def __init__(self, devices=None, page_size=50):
        self.devices = {d["id"]: d for d in (devices or [])}
        self.page_size = page_size
        self.requests = []
        self.created = 0
        # Failure injection for retry tests: each entry is consumed by one
        # request before normal routing. An int is an HTTP status to return;
        # "transport" raises httpx.ConnectError.
        self.fail_next = []
        # Job result statuses handed out on successive polls.
        self.job_statuses = ["PENDING", "STARTED", "SUCCESS"]

    def handler(self, request):
        self.requests.append(request)
        if self.fail_next:
            failure = self.fail_next.pop(0)
            if failure == "transport":
                raise httpx.ConnectError("injected failure")
            return httpx.Response(
                failure, json={"detail": "injected"}, headers={"Retry-After": "0"}
            )
        path = request.url.path
        params = request.url.params

        if path == "/api/" and request.method == "GET":
            return httpx.Response(403, json={}, headers={"API-Version": "2.4"})
        if path == "/api/status/":
            return httpx.Response(200, json={"nautobot-version": "2.4.0"})
        if path == "/api/swagger.json":
            return httpx.Response(200, json={"openapi": "3.0.3", "paths": {}})
        if path == "/api/plugins/installed-plugins/":
            return httpx.Response(200, json=[{"name": "test_plugin", "version": "1.0"}])
        if path == "/api/graphql/":
            return self._graphql(request)

        if path == "/api/users/config/":
            return httpx.Response(200, json={"tables": {}})

        if response := self._custom_fields(request, path, params):
            return response
        if response := self._jobs(request, path):
            return response
        if response := self._ipam(request, path):
            return response
        if response := self._dcim_detail(request, path):
            return response
        if path == "/api/dcim/devices/":
            return self._devices_list(request, params)

        return httpx.Response(500, json={"error": f"unhandled path {path}"})

    def _custom_fields(self, request, path, params):
        """A paginated envelope, one item per page, so draining is exercised."""
        items = {
            "/api/extras/custom-fields/": [{"key": "billing_code"}, {"key": "owner"}],
            "/api/extras/custom-field-choices/": [
                {"value": "first"},
                {"value": "second"},
            ],
        }.get(path)
        if items is None:
            return None
        offset = int(params.get("offset", 0))
        has_next = offset + 1 < len(items)
        return httpx.Response(
            200,
            json={
                "count": len(items),
                # A real `next` link carries the original filters along.
                "next": str(request.url.copy_set_param("offset", offset + 1))
                if has_next
                else None,
                "previous": None,
                "results": items[offset : offset + 1],
            },
        )

    def _graphql(self, request):
        body = json.loads(request.content)
        if "bogus" in body["query"]:
            return httpx.Response(
                400, json={"errors": [{"message": 'Cannot query field "bogus".'}]}
            )
        return httpx.Response(200, json={"data": {"devices": [{"name": "sw-1"}]}})

    def _jobs(self, request, path):
        if path == f"/api/extras/jobs/{JOB_ID}/run/" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "job_result": {
                        "id": JOB_RESULT_ID,
                        "url": f"{BASE}/api/extras/job-results/{JOB_RESULT_ID}/",
                        "display": "job result",
                        "status": {"value": "PENDING", "label": "Pending"},
                    }
                },
            )
        if path == f"/api/extras/graphql-queries/{QUERY_ID}/run/":
            body = json.loads(request.content)
            variables = body.get("variables") or {}
            return httpx.Response(
                200, json={"data": {"devices": [{"name": variables.get("name", "*")}]}}
            )
        if path == f"/api/extras/job-results/{JOB_RESULT_ID}/":
            status = self.job_statuses.pop(0) if self.job_statuses else "SUCCESS"
            return httpx.Response(
                200,
                json={
                    "id": JOB_RESULT_ID,
                    "url": f"{BASE}/api/extras/job-results/{JOB_RESULT_ID}/",
                    "display": "job result",
                    "status": {"value": status, "label": status.title()},
                    "result": {"log": []},
                },
            )
        return None

    def _ipam(self, request, path):
        if path == f"/api/ipam/prefixes/{PREFIX_ID}/":
            return httpx.Response(200, json=PREFIX_FULL)
        if path == f"/api/ipam/prefixes/{PREFIX_ID}/available-prefixes/":
            if request.method == "GET":
                return httpx.Response(200, json=[{"prefix": "10.0.0.0/30"}])
            child = {
                "id": "33333333-3333-4333-8333-333333333302",
                "url": f"{BASE}/api/ipam/prefixes/33333302/",
                "display": "10.0.0.0/30",
                "prefix": "10.0.0.0/30",
            }
            child.update(json.loads(request.content))
            return httpx.Response(201, json=child)
        if path != f"/api/ipam/prefixes/{PREFIX_ID}/available-ips/":
            return None
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"family": 4, "address": f"10.0.0.{i}/29"} for i in (1, 2, 3)],
            )
        body = json.loads(request.content)
        items = body if isinstance(body, list) else [body]
        if len(items) > 3:
            # Nautobot signals an exhausted pool with an empty 204.
            return httpx.Response(204)
        created = []
        for n, item in enumerate(items, 1):
            ip = {
                "id": f"77777777-7777-4777-8777-77777777770{n}",
                "url": f"{BASE}/api/ipam/ip-addresses/7777777{n}/",
                "display": f"10.0.0.{n}/29",
                "address": f"10.0.0.{n}/29",
            }
            ip.update(item)
            created.append(ip)
        payload = created if isinstance(body, list) else created[0]
        return httpx.Response(201, json=payload)

    def _dcim_detail(self, request, path):
        if path == f"/api/dcim/locations/{LOCATION_ID}/":
            return httpx.Response(200, json=LOCATION_FULL)
        if path == f"/api/dcim/racks/{RACK_ID}/":
            return httpx.Response(200, json=RACK_FULL)
        if path == f"/api/dcim/racks/{RACK_ID}/elevation/":
            return httpx.Response(200, json=[{"id": 1, "display": "U1", "name": "U1"}])
        if path == f"/api/dcim/interfaces/{INTERFACE_ID}/":
            return httpx.Response(200, json=self._interface())
        if path == f"/api/dcim/interfaces/{INTERFACE_ID}/trace/":
            return httpx.Response(
                200,
                json=[
                    [
                        self._interface(),
                        {
                            "id": CABLE_ID,
                            "url": f"{BASE}/api/dcim/cables/{CABLE_ID}/",
                            "display": "cable-1",
                            "terminations": [{"raw": True}],
                        },
                        None,
                    ]
                ],
            )
        if m := re.fullmatch(r"/api/dcim/devices/([^/]+)/napalm/", path):
            # A detail route answering with a plain object, not a page.
            return httpx.Response(
                200, json={"get_facts": {"hostname": self.devices[m.group(1)]["name"]}}
            )
        # Any segment, not just a UUID, so percent-encoded keys route here.
        if m := re.fullmatch(r"/api/dcim/devices/([^/]+)/", path):
            return self._device_detail(request, m.group(1))
        return None

    def _interface(self):
        return {
            "id": INTERFACE_ID,
            "url": f"{BASE}/api/dcim/interfaces/{INTERFACE_ID}/",
            "display": "Ethernet1",
            "name": "Ethernet1",
        }

    def _device_detail(self, request, pk):
        device = self.devices.get(pk)
        if not device:
            return httpx.Response(404, json={"detail": "Not found."})
        if request.method == "PATCH":
            device.update(json.loads(request.content))
            return httpx.Response(200, json=device)
        if request.method == "DELETE":
            del self.devices[pk]
            return httpx.Response(204)
        return httpx.Response(200, json=device)

    def _devices_list(self, request, params):
        if request.method == "OPTIONS":
            return httpx.Response(200, json=DEVICE_OPTIONS)
        if request.method == "PATCH":
            updated = []
            for item in json.loads(request.content):
                device = self.devices[item["id"]]
                device.update({k: v for k, v in item.items() if k != "id"})
                updated.append(device)
            return httpx.Response(200, json=updated)
        if request.method == "DELETE":
            for item in json.loads(request.content):
                del self.devices[item["id"]]
            return httpx.Response(204)
        if request.method == "POST":
            body = json.loads(request.content)
            created = []
            for item in body if isinstance(body, list) else [body]:
                self.created += 1
                pk = f"99999999-9999-4999-8999-9999999999{self.created:02d}"
                device = make_device(pk, item.get("name", ""))
                device.update(item)
                self.devices[pk] = device
                created.append(device)
            payload = created if isinstance(body, list) else created[0]
            return httpx.Response(201, json=payload)
        matches = [
            d
            for d in self.devices.values()
            if all(
                str(d.get(k)) == v
                for k, v in params.items()
                if k not in ("limit", "offset", "exclude_m2m", "include")
            )
        ]
        limit = int(params.get("limit", 0)) or self.page_size
        offset = int(params.get("offset", 0))
        page = matches[offset : offset + limit]
        has_next = offset + limit < len(matches)
        return httpx.Response(
            200,
            json={
                "count": len(matches),
                "next": f"{BASE}/api/dcim/devices/?limit={limit}&offset={offset + limit}"
                if has_next
                else None,
                "previous": None,
                "results": page,
            },
        )


@pytest.fixture
def fake():
    return FakeNautobot(
        devices=[
            make_device(DEVICE_IDS[0], "sw-1", serial="ABC123"),
            make_device(DEVICE_IDS[1], "sw-2"),
            make_device(DEVICE_IDS[2], "sw-3"),
            make_device(DEVICE_IDS[3], "sw-4"),
            make_device(DEVICE_IDS[4], "sw-5"),
        ]
    )


def make_api(fake, token="abc123", **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return aiopynautobot.api(BASE, token=token, client=client, **kwargs)


@pytest.fixture
async def nb(fake):
    async with make_api(fake) as nb:
        yield nb
