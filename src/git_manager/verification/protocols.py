"""Verification contracts."""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from git_manager.config.models import DockerConfig, VerifyConfig
from git_manager.verification.models import VerifyCommands, VerifyOutcome


class Verifier(Protocol):
    """Runs a branch's verify commands in a run's worktree as ``gm-tests``."""

    async def verify(
        self, *, worktree: Path, commands: VerifyCommands, config: VerifyConfig, run_id: str
    ) -> VerifyOutcome:
        """Run setup, test and lint in order, stopping at the first failure."""
        ...


class DockerCleaner(Protocol):
    """Removes what a run's tests left in the Docker daemon."""

    async def clean_up(self, *, run_id: str, docker: DockerConfig, run_started: datetime) -> None:
        """Remove containers, networks and volumes labeled ``gm.run=<run_id>``.

        With ``docker.reset_between_runs`` also prune what was created before
        ``run_started``. Does nothing when Docker is off. Raises ``DockerCleanupError``
        after trying every step if any failed.
        """
        ...
