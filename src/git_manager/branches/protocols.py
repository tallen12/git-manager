"""Branch operations, as exposed by every interface."""

from typing import Protocol

from git_manager.branches.models import RepoStatus, TrackedBranch
from git_manager.branches.results import SyncOutcome


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
