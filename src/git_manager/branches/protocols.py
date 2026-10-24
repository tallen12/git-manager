"""Branch contracts: the operations every interface exposes, and the run queue."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Protocol

from git_manager.branches.models import CommitSha, RepoStatus, TrackedBranch
from git_manager.branches.polling import Observation
from git_manager.branches.results import SyncOutcome
from git_manager.branches.runs import QueuedRun
from git_manager.config.models import RepoConfig
from git_manager.rebasing.models import RunTrigger


class BranchOperations(Protocol):
    """Track branches and control their syncing.

    ``branch`` arguments take a tracked branch's name or id. Unknown branches raise
    ``NotFoundError``.
    """

    async def status(self) -> RepoStatus:
        """Return the repository and every tracked branch with its state."""
        ...

    async def track(self, *, name: str, base: str) -> TrackedBranch:
        """Start tracking ``name`` on ``base``, with the fork point from ``merge-base``.

        Raises ``ConflictError`` if the branch is already tracked.
        """
        ...

    async def untrack(self, branch: str) -> None:
        """Stop tracking a branch; its runs stay in the history."""
        ...

    async def sync(self, branch: str) -> SyncOutcome:
        """Rebase now, ignoring the cadence and any stop state but ``paused``."""
        ...

    async def pause(self, branch: str) -> TrackedBranch:
        """Stop polling and syncing a branch without losing its state."""
        ...

    async def resume(self, branch: str) -> TrackedBranch:
        """Leave ``paused`` (or a stop state a human settled) and poll again."""
        ...


class RunScheduler(Protocol):
    """Adds branches to the run queue and takes them out again (the poller's side)."""

    def put(self, branch_id: str, *, trigger: RunTrigger) -> bool:
        """Queue a run for ``branch_id`` last in line; ``False`` if one is already waiting."""
        ...

    def discard(self, branch_id: str) -> bool:
        """Drop the waiting run for ``branch_id``; ``False`` if none was waiting."""
        ...


class RunQueue(RunScheduler, Protocol):
    """First in, first out, one run at a time per container (the daemon's side)."""

    def waiting(self) -> Sequence[QueuedRun]:
        """Runs waiting for their turn, next first."""
        ...

    def take(self) -> AbstractAsyncContextManager[QueuedRun]:
        """Wait until no run is active and one is waiting, then hold it until the block ends.

        The next run is handed out only after the block exits, normally or not.
        """
        ...


class RemoteRefs(Protocol):
    """The one git capability the poller needs; ``Git`` provides it."""

    async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, CommitSha]:
        """Return the remote hash of each branch in ``refs``; missing branches are absent."""
        ...


class BranchSyncer(Protocol):
    """How ``sync`` carries out a run: in the foreground (local mode) or queued (daemon)."""

    async def sync(self, branch: TrackedBranch) -> SyncOutcome:
        """Start a manual run of ``branch``, which is tracked and not paused."""
        ...


class BranchPoller(Protocol):
    """Polls the tracked branches that are due and feeds the run queue (``Poller``)."""

    async def tick(self, config: RepoConfig) -> Sequence[Observation]:
        """Poll every tracked branch whose ``poll_interval`` has passed under ``config``."""
        ...


class Sleeper(Protocol):
    """Waits for time to pass; the daemon's only way to wait, so tests never really sleep."""

    async def sleep(self, delay: timedelta) -> None:
        """Return once ``delay`` has passed."""
        ...
