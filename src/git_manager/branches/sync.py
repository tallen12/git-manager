"""Local mode's ``sync``: the rebase runs to completion in the foreground."""

from git_manager.branches.models import TrackedBranch
from git_manager.branches.results import SyncCompleted, SyncOutcome
from git_manager.config.protocols import ConfigOperations
from git_manager.errors import ConflictError
from git_manager.rebasing.errors import RemoteBranchMissingError
from git_manager.rebasing.models import RunTrigger
from git_manager.rebasing.protocols import RunExecutor


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
