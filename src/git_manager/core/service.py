"""In-process implementation of the operations."""

from dataclasses import dataclass

from git_manager.health import HealthReporter, HealthStatus


@dataclass(frozen=True, slots=True)
class Service:
    """Runs operations in this process, against injected domain capabilities."""

    reporter: HealthReporter

    async def health(self) -> HealthStatus:
        """Return the reporter's current status."""
        return self.reporter.status()
