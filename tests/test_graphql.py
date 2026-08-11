import json

import pytest

import aiopynautobot

QUERY = "query { devices { name } }"


async def test_query_returns_data(nb):
    result = await nb.graphql.query(QUERY)
    assert result.status_code == 200
    assert result.data["devices"][0]["name"] == "sw-1"
    assert result.errors == []


async def test_query_posts_to_graphql_endpoint(nb, fake):
    await nb.graphql.query(QUERY, variables={"name": "sw-1"})
    request = fake.requests[-1]
    assert request.url.path == "/api/graphql/"
    assert json.loads(request.content) == {
        "query": QUERY,
        "variables": {"name": "sw-1"},
    }


async def test_invalid_query_raises_graphql_error(nb):
    with pytest.raises(aiopynautobot.GraphQLError) as excinfo:
        await nb.graphql.query("query { bogus }")
    assert excinfo.value.status_code == 400
    assert "Cannot query field" in excinfo.value.errors[0]["message"]


async def test_non_400_failure_stays_a_request_error(nb, fake):
    fake.fail_next = [401]
    with pytest.raises(aiopynautobot.RequestError):
        await nb.graphql.query(QUERY)


async def test_query_type_is_checked(nb):
    with pytest.raises(TypeError, match="query must be a str"):
        await nb.graphql.query({"not": "a string"})


async def test_variables_type_is_checked(nb):
    with pytest.raises(TypeError, match="variables must be a dict"):
        await nb.graphql.query(QUERY, variables=["nope"])


async def test_record_repr_hides_body(nb):
    result = await nb.graphql.query(QUERY)
    assert repr(result) == "GraphQLRecord(status_code=200)"
    assert "devices" in str(result)
