import json

import httpx
import pytest
from conftest import BASE, JOB_ID, JOB_RESULT_ID, QUERY_ID, make_api

import aiopynautobot

# Fast enough to keep the suite quick, positive enough to pass validation.
TICK = 0.001


async def test_run_posts_to_run_route(nb, fake):
    job = await nb.extras.jobs.run(job_id=JOB_ID, data={"regex": ".*"})
    assert job.job_result.id == JOB_RESULT_ID
    request = fake.requests[-1]
    assert request.url.path == f"/api/extras/jobs/{JOB_ID}/run/"
    assert json.loads(request.content) == {"data": {"regex": ".*"}}


async def test_run_accepts_job_name(nb, fake):
    fake.job_statuses = []
    with pytest.raises(aiopynautobot.RequestError):
        # The fake only routes the UUID form; this asserts the name is
        # what lands in the URL.
        await nb.extras.jobs.run(job_name="Verify Hostnames")
    request = fake.requests[-1]
    assert request.url.path == "/api/extras/jobs/Verify Hostnames/run/"
    # The space is percent-encoded on the wire.
    assert request.url.raw_path == b"/api/extras/jobs/Verify%20Hostnames/run/"


async def test_run_requires_a_job_identifier(nb):
    with pytest.raises(ValueError, match="job_id or job_name"):
        await nb.extras.jobs.run()


async def test_run_and_wait_polls_until_terminal(nb, fake):
    fake.job_statuses = ["PENDING", "STARTED", "SUCCESS"]
    job = await nb.extras.jobs.run_and_wait(job_id=JOB_ID, interval=TICK)
    # status is a choice field, so compare its value not its label.
    assert job.job_result.status.value == "SUCCESS"
    polls = [
        r
        for r in fake.requests
        if r.url.path == f"/api/extras/job-results/{JOB_RESULT_ID}/"
    ]
    assert len(polls) == 3


async def test_run_and_wait_skips_polling_when_already_terminal(fake):
    real_handler = fake.handler

    def finished(request):
        response = real_handler(request)
        if request.url.path.endswith("/run/"):
            body = response.json()
            body["job_result"]["status"] = {"value": "SUCCESS", "label": "Success"}
            return httpx.Response(201, json=body)
        return response

    fake.handler = finished
    async with make_api(fake) as nb:
        await nb.extras.jobs.run_and_wait(job_id=JOB_ID, interval=TICK)
    assert not [
        r
        for r in fake.requests
        if r.url.path == f"/api/extras/job-results/{JOB_RESULT_ID}/"
    ]


async def test_run_and_wait_rejects_an_unpollable_job_result(fake):
    """A job result without a url can never change status."""
    real_handler = fake.handler

    def no_url(request):
        response = real_handler(request)
        if request.url.path.endswith("/run/"):
            body = response.json()
            del body["job_result"]["url"]
            return httpx.Response(201, json=body)
        return response

    fake.handler = no_url
    async with make_api(fake) as nb:
        with pytest.raises(RuntimeError, match="no url to poll"):
            await nb.extras.jobs.run_and_wait(job_id=JOB_ID, interval=TICK)


async def test_run_and_wait_times_out(nb, fake):
    fake.job_statuses = ["PENDING"] * 500
    with pytest.raises(aiopynautobot.JobTimeoutError) as excinfo:
        await nb.extras.jobs.run_and_wait(job_id=JOB_ID, interval=TICK, timeout=0.05)
    assert excinfo.value.job_result_id == JOB_RESULT_ID
    assert "still be running" in str(excinfo.value)


async def test_run_and_wait_rejects_non_positive_interval(nb):
    with pytest.raises(ValueError, match="interval must be positive"):
        await nb.extras.jobs.run_and_wait(job_id=JOB_ID, interval=0)


async def test_job_record_run(nb, fake):
    """A Jobs record can enqueue itself through its own detail route."""
    job_record = nb.extras.jobs.record_class(
        {
            "id": JOB_ID,
            "url": f"{BASE}/api/extras/jobs/{JOB_ID}/",
            "display": "Verify Hostnames",
        },
        nb,
        full=True,
    )
    await job_record.run(data={"regex": ".*"})
    assert fake.requests[-1].url.path == f"/api/extras/jobs/{JOB_ID}/run/"


async def test_saved_graphql_query_run(nb, fake):
    result = await nb.extras.graphql_queries.run(QUERY_ID, name="sw-1")
    request = fake.requests[-1]
    assert request.url.path == f"/api/extras/graphql-queries/{QUERY_ID}/run/"
    assert json.loads(request.content) == {"variables": {"name": "sw-1"}}
    assert result.data["devices"][0]["name"] == "sw-1"


async def test_saved_graphql_query_record_run(nb, fake):
    """A GraphqlQueries record can execute itself via its detail route."""
    record = nb.extras.graphql_queries.record_class(
        {
            "id": QUERY_ID,
            "url": f"{BASE}/api/extras/graphql-queries/{QUERY_ID}/",
            "display": "saved query",
        },
        nb,
        full=True,
    )
    result = await record.run(name="sw-2")
    assert fake.requests[-1].url.path == f"/api/extras/graphql-queries/{QUERY_ID}/run/"
    assert result.data["devices"][0]["name"] == "sw-2"
