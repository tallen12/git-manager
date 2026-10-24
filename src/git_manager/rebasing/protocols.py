"""Rebasing contracts: git itself, and the run operations every interface exposes."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol

from git_manager.branches.models import CommitSha
from git_manager.config.models import RepoConfig
from git_manager.rebasing.models import PushOutcome, RebaseOutcome, Run, RunTrigger
from git_manager.verification.models import TestResult


class Git(Protocol):
    """Git operations on the managed clone and its run worktrees.

    Implementations drive the ``git`` binary through a ``ProcessRunner`` as the
    orchestrator user; only they see git credentials. Unexpected git failures raise
    ``GitError``; expected outcomes (conflicts, lease rejections) are return values.
    """

    async def ls_remote(self, refs: Sequence[str]) -> Mapping[str, CommitSha]:
        """Return the remote hash of each branch in ``refs``; missing branches are absent."""
        ...

    async def fetch(self, refs: Sequence[str]) -> None:
        """Fetch ``refs`` from the remote into the clone's remote-tracking branches."""
        ...

    async def merge_base(self, first: str, second: str) -> CommitSha:
        """Return the best common ancestor of two commits."""
        ...

    async def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` is reachable from ``descendant``."""
        ...

    async def add_worktree(self, path: Path, commit: str) -> None:
        """Create a detached worktree at ``path`` checked out at ``commit``."""
        ...

    async def remove_worktree(self, path: Path) -> None:
        """Remove the worktree at ``path``, discarding any changes in it."""
        ...

    async def rebase_onto(
        self, worktree: Path, *, new_base: str, fork_point: str, rebase_merges: bool
    ) -> RebaseOutcome:
        """Run ``git rebase --onto new_base fork_point`` in ``worktree`` with rerere on."""
        ...

    async def abort_rebase(self, worktree: Path) -> None:
        """Abort the rebase in progress in ``worktree``."""
        ...

    async def push_with_lease(
        self, worktree: Path, *, branch: str, head: str, expected: str
    ) -> PushOutcome:
        """Push ``head`` to ``branch`` with ``--force-with-lease=branch:expected``."""
        ...

    async def create_branch(self, name: str, commit: str) -> None:
        """Create or move the local branch ``name`` (never pushed), e.g. ``gm/attempt/*``."""
        ...

    async def diff(self, start: str, end: str) -> str:
        """Return ``git diff start end``."""
        ...


class BranchLocks(Protocol):
    """One holder per tracked branch at a time, so two runs never rebase the same branch."""

    def hold(self, branch_id: str) -> AbstractAsyncContextManager[None]:
        """Wait until no one holds ``branch_id``, then hold it until the block ends."""
        ...


class RunExecutor(Protocol):
    """Carries out one rebase run of a tracked branch (the daemon's and ``sync``'s side)."""

    async def run(self, branch_id: str, *, trigger: RunTrigger, config: RepoConfig) -> Run:
        """Rebase, verify and push ``branch_id`` with ``config``; return the recorded run.

        The run ends in a state of the sync lifecycle, or in ``awaiting_approval`` with
        ``finished_at`` unset until the approval completes it. Raises ``NotFoundError``
        for an untracked branch, ``BranchOnHoldError`` when the branch's state holds it
        from a run with ``trigger`` (see ``branches.polling.may_start``) and
        ``RemoteBranchMissingError`` when its base or itself is gone from the remote.
        Any other error leaves the run and the branch in
        ``needs_human`` (no reason) and propagates.
        """
        ...


class RunOperations(Protocol):
    """Runs and their reports, as exposed by every interface."""

    async def list(self, *, branch: str | None = None, limit: int = 50) -> Sequence[Run]:
        """Return the newest runs first, optionally for one branch (name or id)."""
        ...

    async def get(self, run_id: str) -> Run:
        """Return one run. Raises ``NotFoundError``."""
        ...

    async def diff(self, run_id: str) -> str:
        """Return the run's diff against the new base. Raises ``NotFoundError``."""
        ...

    async def tests(self, run_id: str) -> Sequence[TestResult]:
        """Return the run's verify results with their output. Raises ``NotFoundError``."""
        ...
