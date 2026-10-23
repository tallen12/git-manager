"""Health contracts."""

from typing import Protocol

from git_manager.health.models import HealthStatus


class HealthReporter(Protocol):
    """Reports whether the service is alive."""

    def status(self) -> HealthStatus:
        """Return the current health status."""
        ...


class HealthOperations(Protocol):
    """Health, as exposed by every interface (``doctor``, ``GET /healthz``)."""

    async def status(self) -> HealthStatus:
        """Report whether Git Manager is alive and which version is running."""
        ...
