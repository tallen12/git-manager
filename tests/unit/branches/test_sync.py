from dataclasses import dataclass, field

import pytest

from git_manager.branches import BranchState
from git_manager.branches.protocols import BranchSyncer
from git_manager.branches.results import SyncCompleted
from git_manager.branches.sync import ForegroundSync
from git_manager.config.models import RepoConfig
from git_manager.errors import ConflictError
from git_manager.rebasing import RemoteBranchMissingError, Run, RunTrigger
from tests.conftest import make_branch, make_run
from tests.unit.branches.conftest import StaticConfig


@dataclass(frozen=True, slots=True)
class ExecutorCall:
    branch_id: str
    trigger: RunTrigger
    config: RepoConfig


@dataclass(slots=True)
class FakeExecutor:
    """``RunExecutor`` that records calls and returns ``run`` or raises ``error``."""

    run_result: Run = field(default_factory=make_run)
    error: Exception | None = None
    calls: list[ExecutorCall] = field(default_factory=list)

    async def run(self, branch_id: str, *, trigger: RunTrigger, config: RepoConfig) -> Run:
        self.calls.append(ExecutorCall(branch_id, trigger, config))
        if self.error is not None:
            raise self.error
        return self.run_result


async def test_runs_a_manual_run_with_the_current_config() -> None:
    executor = FakeExecutor()
    config = StaticConfig()
    syncer: BranchSyncer = ForegroundSync(executor=executor, config=config)

    outcome = await syncer.sync(make_branch())

    assert outcome == SyncCompleted(run=executor.run_result)
    assert executor.calls == [ExecutorCall("branch-1", RunTrigger.MANUAL, config.config)]


async def test_reports_a_missing_remote_branch_as_a_conflict() -> None:
    error = RemoteBranchMissingError(branch="feature/one", missing="main")
    syncer = ForegroundSync(executor=FakeExecutor(error=error), config=StaticConfig())

    with pytest.raises(ConflictError, match="main is not on the remote") as raised:
        await syncer.sync(make_branch(state=BranchState.IDLE))

    assert raised.value.__cause__ is error
