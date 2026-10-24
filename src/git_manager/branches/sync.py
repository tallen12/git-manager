"""How ``sync`` runs: in the foreground (local mode) or through the daemon's run queue."""

from enum import StrEnum

from git_manager.branches.models import TrackedBranch
from git_manager.branches.protocols import RunQueue
from git_manager.branches.results import SyncCompleted, SyncOutcome, SyncQueued
from git_manager.config.protocols import ConfigOperations
from git_manager.errors import ConflictError
from git_manager.rebasing.errors import RemoteBranchMissingError
from git_manager.rebasing.models import RunTrigger
from git_manager.rebasing.protocols import RunExecutor


class SyncMode(StrEnum):
    """Which ``BranchSyncer`` a runtime's service uses."""

    # Local-mode commands: the run happens while the command waits.
    FOREGROUND = "foreground"
    # ``serve``: the run joins the daemon's queue, one run at a time.
    QUEUED = "queued"


class ForegroundSync:
    """``BranchSyncer`` that runs the rebase itself and returns the finished run.

    There is no poller in local mode (see "Local mode runs to completion" in the spec), so
    the run happens while the caller waits, with the config as it is now.
    """

    def __init__(self, *, executor: RunExecutor, config: ConfigOperations) -> None:
        self._executor = executor
        self._config = config

    async def sync(self, branch: TrackedBranch) -> SyncOutcome:
        config = await self._config.show()
        try:
            run = await self._executor.run(branch.id, trigger=RunTrigger.MANUAL, config=config)
        except RemoteBranchMissingError as error:
            # The branch is already in base_missing or idle; the caller has to fix the remote.
            raise ConflictError(str(error)) from error
        return SyncCompleted(run=run)


class QueuedSync:
    """``BranchSyncer`` for the daemon: queue a manual run and return at once.

    The daemon's worker takes it in turn, so a sync never runs next to another run, and
    a request never waits for tests. Syncing a branch that already waits is not queued
    twice; the answer is where it waits.
    """

    def __init__(self, *, queue: RunQueue) -> None:
        self._queue = queue

    async def sync(self, branch: TrackedBranch) -> SyncOutcome:
        self._queue.put(branch.id, trigger=RunTrigger.MANUAL)
        waiting = [run.branch_id for run in self._queue.waiting()]
        running = 0 if self._queue.active is None else 1
        return SyncQueued(branch_id=branch.id, position=waiting.index(branch.id) + running)
