from dataclasses import dataclass, field
from datetime import datetime

import pytest

from git_manager.config.models import DockerConfig
from git_manager.verification import DockerCleanupError


@dataclass(frozen=True, slots=True)
class CleanupCall:
    run_id: str
    docker: DockerConfig
    run_started: datetime


@dataclass(slots=True)
class RecordingDockerCleaner:
    """``DockerCleaner`` that records calls, failing with ``error`` when set."""

    calls: list[CleanupCall] = field(default_factory=list)
    error: str | None = None

    async def clean_up(self, *, run_id: str, docker: DockerConfig, run_started: datetime) -> None:
        self.calls.append(CleanupCall(run_id, docker, run_started))
        if self.error is not None:
            raise DockerCleanupError(self.error)


@pytest.fixture
def cleaner() -> RecordingDockerCleaner:
    return RecordingDockerCleaner()
