"""In-process health operations."""

from dataclasses import dataclass

from git_manager.health.models import HealthStatus
from git_manager.health.protocols import HealthReporter


@dataclass(frozen=True, slots=True)
class HealthService:
    """Implements ``HealthOperations`` from an injected reporter."""

    reporter: HealthReporter

    async def status(self) -> HealthStatus:
        """Return the reporter's current status."""
        return self.reporter.status()
