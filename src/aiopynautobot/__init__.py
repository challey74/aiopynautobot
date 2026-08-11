"""aiopynautobot: async Nautobot API client."""

from importlib.metadata import version as _version

from aiopynautobot.api import Api
from aiopynautobot.exceptions import (
    AllocationError,
    ContentError,
    GraphQLError,
    JobTimeoutError,
    RequestError,
)
from aiopynautobot.graphql import GraphQLRecord
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
    "GraphQLError",
    "GraphQLRecord",
    "JobTimeoutError",
    "RODetailEndpoint",
    "Record",
    "RecordSet",
    "RequestError",
    "__version__",
    "api",
    "register_model",
]
