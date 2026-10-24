"""Service health: the first capability shared by the CLI, REST and MCP adapters."""

from git_manager.health.models import HealthStatus
from git_manager.health.protocols import HealthOperations, HealthReporter
from git_manager.health.reporters import StaticHealthReporter
from git_manager.health.service import HealthService

__all__ = [
    "HealthOperations",
    "HealthReporter",
    "HealthService",
    "HealthStatus",
    "StaticHealthReporter",
]
