"""GraphQL client for Nautobot's /api/graphql/ endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiopynautobot.exceptions import GraphQLError, RequestError

if TYPE_CHECKING:
    from aiopynautobot.api import Api


class GraphQLRecord:
    """The result of a GraphQL query.

    Attributes:
        json: The full response body, with `data` and possibly `errors`.
        status_code: The HTTP status of the response.
    """

    def __init__(self, json: dict[str, Any], status_code: int) -> None:
        self.json = json
        self.status_code = status_code

    @property
    def data(self) -> Any:
        """The `data` member of the response, or None if absent."""
        return self.json.get("data")

    @property
    def errors(self) -> list[Any]:
        """Errors returned alongside a 200 response.

        GraphQL can answer 200 with partial data plus errors; those do not
        raise, so check this when a field comes back unexpectedly null.
        """
        return self.json.get("errors") or []

    def __repr__(self) -> str:
        return f"GraphQLRecord(status_code={self.status_code})"

    def __str__(self) -> str:
        return str(self.json)


class GraphQLQuery:
    """nb.graphql: runs queries against Nautobot's GraphQL endpoint."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.url = f"{api.base_url}/graphql/"

    async def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> GraphQLRecord:
        """Run a GraphQL query.

        Args:
            query: The query string.
            variables: Values for the query's declared variables.

        Returns:
            A GraphQLRecord wrapping the response body.

        Raises:
            TypeError: If query is not a str or variables is not a dict.
                Checked up front because the server-side error for these
                is unhelpful.
            GraphQLError: If Nautobot rejects the query (HTTP 400),
                carrying the parsed `errors` array.
        """
        if not isinstance(query, str):
            raise TypeError(f"query must be a str, got {type(query).__name__}")
        if variables is not None and not isinstance(variables, dict):
            raise TypeError(f"variables must be a dict, got {type(variables).__name__}")
        payload = {"query": query, "variables": variables}
        try:
            resp = await self.api._request_response("POST", self.url, json=payload)
        except RequestError as e:
            # Nautobot answers an invalid query with 400 and an `errors`
            # array; anything else is a plain transport/auth failure.
            if e.status_code == 400:
                try:
                    errors = e.response.json().get("errors")
                except ValueError:
                    errors = None
                if errors is not None:
                    raise GraphQLError(e.response, errors) from None
            raise
        return GraphQLRecord(self.api._decode(resp), resp.status_code)
