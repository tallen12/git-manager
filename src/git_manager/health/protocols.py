"""Health contracts."""

from typing import Protocol

from git_manager.health.models import HealthStatus


class HealthReporter(Protocol):
    """Reports whether the service is alive."""

    def status(self) -> HealthStatus:
        """Return the current health status."""
        ...
