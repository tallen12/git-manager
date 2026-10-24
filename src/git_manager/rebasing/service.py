"""In-process run operations: the run history, each run's diff and its test log."""

from collections.abc import Sequence

from git_manager.errors import ConflictError, NotFoundError
from git_manager.rebasing.models import Run
from git_manager.rebasing.protocols import Git
from git_manager.store.protocols import BranchRepository, RunRepository
from git_manager.verification.models import TestResult


class RunService:
    """``RunOperations`` over the run store, with diffs from the managed clone."""

    def __init__(self, *, runs: RunRepository, branches: BranchRepository, git: Git) -> None:
        self._runs = runs
        self._branches = branches
        self._git = git

    async def list(self, *, branch: str | None = None, limit: int = 50) -> Sequence[Run]:
        branch_id = None if branch is None else await self._branch_id(branch)
        return await self._runs.list(branch_id=branch_id, limit=limit)

    async def get(self, run_id: str) -> Run:
        run = await self._runs.get(run_id)
        if run is None:
            raise NotFoundError(kind="run", key=run_id)
        return run

    async def diff(self, run_id: str) -> str:
        """The rebased branch against the base it was rebased onto, as ``git diff`` prints it."""
        run = await self.get(run_id)
        head = run.heads[0].new_head
        if head is None:
            msg = f"run {run_id} has no rebased head to diff (it ended {run.outcome})"
            raise ConflictError(msg)
        # The rebased commits stay in the clone's object store after the run's worktree is
        # removed, whether or not they were pushed.
        return await self._git.diff(run.base_to, head)

    async def tests(self, run_id: str) -> Sequence[TestResult]:
        return (await self.get(run_id)).tests

    async def _branch_id(self, branch: str) -> str:
        """The id of the branch named ``branch``; else ``branch`` itself, taken as an id.

        Runs outlive ``untrack``, so an untracked branch's runs are still found by its id.
        """
        found = await self._branches.find(branch)
        return branch if found is None else found.id
