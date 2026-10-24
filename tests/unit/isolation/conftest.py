from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from git_manager.isolation import SpawnCompleted, SpawnRequest, SpawnResponse


def _exit_zero(_request: SpawnRequest) -> SpawnResponse:
    return SpawnCompleted(exit_code=0, stdout="", stderr="", duration_s=0)


@dataclass(slots=True)
class FakeSupervisorChannel:
    """``SupervisorChannel`` that records requests and answers with ``respond``."""

    respond: Callable[[SpawnRequest], SpawnResponse] = _exit_zero
    requests: list[SpawnRequest] = field(default_factory=list)

    async def spawn(self, request: SpawnRequest) -> SpawnResponse:
        self.requests.append(request)
        return self.respond(request)


@pytest.fixture
def channel() -> FakeSupervisorChannel:
    return FakeSupervisorChannel()
