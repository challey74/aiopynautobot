"""Exception types raised by aiopynautobot."""

from __future__ import annotations

from typing import Any

import httpx


class RequestError(Exception):
    """Nautobot returned a non-success HTTP response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.status_code = response.status_code
        self.url = str(response.url)
        self.error = response.text
        if response.status_code == 404:
            self.message = f"The requested url: {response.url} could not be found."
        else:
            try:
                detail = response.json()
            except ValueError:
                detail = "(non-JSON response body)"
            self.message = (
                f"The request failed with code {response.status_code} "
                f"{response.reason_phrase}: {detail}"
            )
        super().__init__(self.message)


class AllocationError(Exception):
    """Nautobot returned 204 No Content for an allocation POST.

    Nautobot signals an exhausted pool (available-ips, available-prefixes)
    with an empty 204, where NetBox uses 409 Conflict.
    """

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.url = str(response.url)
        self.error = "The requested allocation could not be fulfilled."
        super().__init__(self.error)


class ContentError(Exception):
    """A successful response contained non-JSON content."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.url = str(response.url)
        self.error = (
            "The server returned invalid (non-json) data. Maybe not a Nautobot server?"
        )
        super().__init__(self.error)


class GraphQLError(Exception):
    """The GraphQL endpoint rejected a query.

    Attributes:
        errors: The `errors` array Nautobot returns describing what was
            wrong with the query.
    """

    def __init__(self, response: httpx.Response, errors: list[Any]) -> None:
        self.response = response
        self.status_code = response.status_code
        self.url = str(response.url)
        self.errors = errors
        super().__init__(str(errors))


class JobTimeoutError(Exception):
    """A job did not reach a terminal state within the allotted time."""

    def __init__(self, job_result_id: Any, timeout: float) -> None:
        self.job_result_id = job_result_id
        self.timeout = timeout
        super().__init__(
            f"Job result {job_result_id} did not finish within {timeout}s. It may "
            "still be running; keep polling it with await record.full_details()."
        )
