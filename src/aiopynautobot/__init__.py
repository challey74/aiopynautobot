"""aiopynautobot: async Nautobot API client."""

from importlib.metadata import version as _version

from aiopynautobot.api import Api
from aiopynautobot.endpoint import Endpoint, GraphqlEndpoint, JobsEndpoint
from aiopynautobot.exceptions import (
    AllocationError,
    ContentError,
    GraphQLError,
    JobTimeoutError,
    RequestError,
)
from aiopynautobot.graphql import GraphQLQuery, GraphQLRecord
from aiopynautobot.models import register_model
from aiopynautobot.response import (
    DetailEndpoint,
    Record,
    RecordSet,
    RODetailEndpoint,
)

__version__ = _version("aiopynautobot")

api = Api

__all__ = [
    "AllocationError",
    "Api",
    "ContentError",
    "DetailEndpoint",
    "Endpoint",
    "GraphQLError",
    "GraphQLQuery",
    "GraphQLRecord",
    "GraphqlEndpoint",
    "JobTimeoutError",
    "JobsEndpoint",
    "RODetailEndpoint",
    "Record",
    "RecordSet",
    "RequestError",
    "__version__",
    "api",
    "register_model",
]
