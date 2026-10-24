from dataclasses import dataclass

from git_manager.core import Operations, Service
from git_manager.core.unavailable import UnavailableBranches, UnavailableConfig, UnavailableRuns
from git_manager.health import HealthStatus


@dataclass(frozen=True, slots=True)
class FixedHealth:
    """Returns one status, so the test shows the service passes it through."""

    fixed: HealthStatus

    async def status(self) -> HealthStatus:
        return self.fixed


async def test_service_exposes_each_injected_domain() -> None:
    expected = HealthStatus(status="ok", version="9.9.9")
    branches = UnavailableBranches("later")

    service: Operations = Service(
        health=FixedHealth(expected),
        config=UnavailableConfig("later"),
        branches=branches,
        runs=UnavailableRuns("later"),
    )

    assert await service.health.status() == expected
    assert service.branches is branches
