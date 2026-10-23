"""Service health: the first capability shared by the CLI, REST and MCP adapters."""

from git_manager.health.models import HealthStatus
from git_manager.health.protocols import HealthReporter
from git_manager.health.reporters import StaticHealthReporter

__all__ = ["HealthReporter", "HealthStatus", "StaticHealthReporter"]
