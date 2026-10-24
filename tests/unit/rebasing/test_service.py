import pytest

from git_manager.branches import BranchHeads, BranchState, Reason
from git_manager.errors import ConflictError, NotFoundError
from git_manager.rebasing import RunOperations
from git_manager.rebasing.service import RunService
from git_manager.verification import StepOutcome, TestResult, VerifyStep
from tests.conftest import FakeGit, InMemoryBranches, InMemoryRuns, make_branch, make_run, sha

RESULT = TestResult(
    step=VerifyStep.TEST,
    command="just test",
    outcome=StepOutcome.PASSED,
    exit_code=0,
    attempts=1,
    duration_s=2.0,
    output_tail="ok",
)


@pytest.fixture
def service(
    run_repository: InMemoryRuns, branch_repository: InMemoryBranches, git: FakeGit
) -> RunService:
    run_repository.rows["run-1"] = make_run(tests=(RESULT,))
    run_repository.rows["run-2"] = make_run(id="run-2", branch_id="branch-2")
    branch_repository.rows["branch-1"] = make_branch()
    return RunService(runs=run_repository, branches=branch_repository, git=git)


def test_service_implements_run_operations(service: RunService) -> None:
    operations: RunOperations = service
    assert operations is service


async def test_list_returns_newest_first(service: RunService) -> None:
    assert [run.id for run in await service.list()] == ["run-2", "run-1"]
    assert [run.id for run in await service.list(limit=1)] == ["run-2"]


@pytest.mark.parametrize("branch", ["feature/one", "branch-1"])
async def test_list_filters_by_branch_name_or_id(service: RunService, branch: str) -> None:
    assert [run.id for run in await service.list(branch=branch)] == ["run-1"]


async def test_list_finds_runs_of_an_untracked_branch_by_id(service: RunService) -> None:
    assert [run.id for run in await service.list(branch="branch-2")] == ["run-2"]


async def test_get_returns_the_run_or_raises(service: RunService) -> None:
    assert (await service.get("run-1")).id == "run-1"
    with pytest.raises(NotFoundError, match="run not found: run-9"):
        await service.get("run-9")


async def test_diff_compares_the_rebased_head_with_the_new_base(
    service: RunService, git: FakeGit
) -> None:
    git.diffs[(sha(3), sha(4))] = "diff --git a/f b/f\n"

    assert await service.diff("run-1") == "diff --git a/f b/f\n"


async def test_diff_of_a_run_without_a_rebased_head_is_a_conflict(
    service: RunService, run_repository: InMemoryRuns
) -> None:
    run_repository.rows["run-3"] = make_run(
        id="run-3",
        heads=(BranchHeads(branch="feature/one", old_head=sha(2)),),
        outcome=BranchState.NEEDS_HUMAN,
        reason=Reason.CONFLICT,
    )

    with pytest.raises(ConflictError, match=r"no rebased head .*needs_human"):
        await service.diff("run-3")


async def test_tests_returns_the_verify_results(service: RunService) -> None:
    assert await service.tests("run-1") == (RESULT,)
    with pytest.raises(NotFoundError):
        await service.tests("run-9")
