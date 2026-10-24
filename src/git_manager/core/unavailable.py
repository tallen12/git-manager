"""Stand-ins for operation groups that a target cannot serve yet.

Until a domain's real implementation lands (in-process in M1, over REST in M2), its
operations raise ``UnavailableError`` with the reason, instead of being missing from
``Operations`` and breaking the shared contract.
"""

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import NoReturn

from git_manager.branches.models import RepoStatus, TrackedBranch
from git_manager.branches.results import SyncOutcome
from git_manager.config.models import RepoConfig
from git_manager.errors import UnavailableError
from git_manager.events.models import Event
from git_manager.rebasing.models import Run
from git_manager.verification.models import TestResult


@dataclass(frozen=True, slots=True)
class UnavailableConfig:
    """``ConfigOperations`` that always raise ``UnavailableError``."""

    reason: str

    async def show(self) -> RepoConfig:
        """Raise ``UnavailableError``."""
        raise UnavailableError("config show", reason=self.reason)


@dataclass(frozen=True, slots=True)
class UnavailableBranches:
    """``BranchOperations`` that always raise ``UnavailableError``."""

    reason: str

    def _fail(self, operation: str) -> NoReturn:
        raise UnavailableError(operation, reason=self.reason)

    async def status(self) -> RepoStatus:
        """Raise ``UnavailableError``."""
        self._fail("status")

    async def track(self, *, name: str, base: str) -> TrackedBranch:
        """Raise ``UnavailableError``."""
        self._fail("track")

    async def untrack(self, branch: str) -> None:
        """Raise ``UnavailableError``."""
        self._fail("untrack")

    async def sync(self, branch: str) -> SyncOutcome:
        """Raise ``UnavailableError``."""
        self._fail("sync")

    async def pause(self, branch: str) -> TrackedBranch:
        """Raise ``UnavailableError``."""
        self._fail("pause")

    async def resume(self, branch: str) -> TrackedBranch:
        """Raise ``UnavailableError``."""
        self._fail("resume")


@dataclass(frozen=True, slots=True)
class UnavailableRuns:
    """``RunOperations`` that always raise ``UnavailableError``."""

    reason: str

    def _fail(self, operation: str) -> NoReturn:
        raise UnavailableError(operation, reason=self.reason)

    async def list(self, *, branch: str | None = None, limit: int = 50) -> Sequence[Run]:
        """Raise ``UnavailableError``."""
        self._fail("runs")

    async def get(self, run_id: str) -> Run:
        """Raise ``UnavailableError``."""
        self._fail("show")

    async def diff(self, run_id: str) -> str:
        """Raise ``UnavailableError``."""
        self._fail("diff")

    async def tests(self, run_id: str) -> Sequence[TestResult]:
        """Raise ``UnavailableError``."""
        self._fail("logs")


@dataclass(frozen=True, slots=True)
class UnavailableEvents:
    """``EventOperations`` that always raise ``UnavailableError``."""

    reason: str

    def stream(self, *, after: int | None = None) -> AsyncGenerator[Event]:
        """Raise ``UnavailableError``."""
        raise UnavailableError("watch", reason=self.reason)
