from dataclasses import dataclass

from git_manager.core import Service
from git_manager.health import HealthStatus


@dataclass(frozen=True, slots=True)
class FixedReporter:
    """Returns one status, so the test shows the service passes it through."""

    fixed: HealthStatus

    def status(self) -> HealthStatus:
        return self.fixed


async def test_health_returns_reporter_status() -> None:
    expected = HealthStatus(status="ok", version="9.9.9")

    assert await Service(reporter=FixedReporter(expected)).health() == expected
