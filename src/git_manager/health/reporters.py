"""Health reporter implementations."""

from dataclasses import dataclass

from git_manager.health.models import HealthStatus


@dataclass(frozen=True, slots=True)
class StaticHealthReporter:
    """Reports liveness only; readiness checks (git, Docker sidecar) come later."""

    version: str

    def status(self) -> HealthStatus:
        """Return an ``ok`` status with the running version."""
        return HealthStatus(status="ok", version=self.version)
