"""Service core: the operations every interface exposes, defined once, and where they run."""

from git_manager.core.connect import Connector, build_connector
from git_manager.core.http_operations import HttpOperations
from git_manager.core.protocols import Operations
from git_manager.core.service import Service
from git_manager.core.settings import Settings
from git_manager.core.targets import HttpTarget, LocalTarget, SocketTarget, Target
from git_manager.errors import (
    ConflictError,
    NotFoundError,
    OperationError,
    UnavailableError,
)
from git_manager.web.api_client import ApiError, ApiResponseError, ApiUnreachableError

__all__ = [
    "ApiError",
    "ApiResponseError",
    "ApiUnreachableError",
    "ConflictError",
    "Connector",
    "HttpOperations",
    "HttpTarget",
    "LocalTarget",
    "NotFoundError",
    "OperationError",
    "Operations",
    "Service",
    "Settings",
    "SocketTarget",
    "Target",
    "UnavailableError",
    "build_connector",
]
