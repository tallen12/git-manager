"""Verification contracts."""

from pathlib import Path
from typing import Protocol

from git_manager.config.models import VerifyConfig
from git_manager.verification.models import VerifyCommands, VerifyOutcome


class Verifier(Protocol):
    """Runs a branch's verify commands in a run's worktree as ``gm-tests``."""

    async def verify(
        self, *, worktree: Path, commands: VerifyCommands, config: VerifyConfig, run_id: str
    ) -> VerifyOutcome:
        """Run setup, test and lint in order, stopping at the first failure."""
        ...
