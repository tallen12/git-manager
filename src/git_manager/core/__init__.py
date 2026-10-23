"""Service core: the operations every interface exposes, defined once, and where they run."""

from git_manager.core.connect import Connector, build_connector
from git_manager.core.http_operations import ApiError, ApiUnreachableError, HttpOperations
from git_manager.core.protocols import Operations
from git_manager.core.service import Service
from git_manager.core.settings import HttpTarget, LocalTarget, Settings, SocketTarget, Target

__all__ = [
    "ApiError",
    "ApiUnreachableError",
    "Connector",
    "HttpOperations",
    "HttpTarget",
    "LocalTarget",
    "Operations",
    "Service",
    "Settings",
    "SocketTarget",
    "Target",
    "build_connector",
]
