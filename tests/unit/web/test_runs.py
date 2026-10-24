from collections.abc import Callable

import pytest
from fastapi import APIRouter

from git_manager.errors import NotFoundError
from git_manager.rebasing.protocols import RunOperations
from git_manager.verification import StepOutcome, TestResult, VerifyStep
from git_manager.web.api_client import ApiError
from git_manager.web.auth import Access
from git_manager.web.runs import HttpRunOperations, run_path, runs_router
from tests.conftest import make_run
from tests.unit.cli.conftest import FakeRunOperations
from tests.unit.web.conftest import serving

RESULT = TestResult(
    step=VerifyStep.TEST,
    command="just test",
    outcome=StepOutcome.PASSED,
    exit_code=0,
    attempts=1,
    duration_s=1.5,
    output_tail="ok\n",
)
RUNS = [
    make_run(id="run-2", branch_id="branch-2"),
    make_run(id="run-1", tests=(RESULT,)),
]


def runs_of(fake: FakeRunOperations) -> Callable[[Access], APIRouter]:
    return lambda access: runs_router(fake, access=access)


async def test_list_filters_and_limits_like_the_service() -> None:
    fake = FakeRunOperations(runs=list(RUNS))
    async with serving(runs_of(fake), as_token="reader") as api:
        operations: RunOperations = HttpRunOperations(api)
        every = await operations.list()
        one_branch = await operations.list(branch="branch-1")
        first = await operations.list(limit=1)

    assert list(every) == RUNS
    assert [run.id for run in one_branch] == ["run-1"]
    assert [run.id for run in first] == ["run-2"]


async def test_show_diff_and_tests_of_one_run() -> None:
    diff = "diff --git a/x b/x\n+ünïcode\n"
    fake = FakeRunOperations(runs=list(RUNS), diffs={"run-1": diff})
    async with serving(runs_of(fake), as_token="reader") as api:
        operations = HttpRunOperations(api)
        run = await operations.get("run-1")
        text = await operations.diff("run-1")
        results = await operations.tests("run-1")

    assert run == RUNS[1]
    assert text == diff
    assert list(results) == [RESULT]


async def test_an_unknown_run_raises_not_found() -> None:
    async with serving(runs_of(FakeRunOperations())) as api:
        operations = HttpRunOperations(api)
        for call in (operations.get, operations.diff, operations.tests):
            with pytest.raises(NotFoundError, match="run not found: nope"):
                await call("nope")


async def test_runs_need_the_read_scope() -> None:
    async with serving(runs_of(FakeRunOperations()), as_token="nobody") as api:
        with pytest.raises(ApiError) as raised:
            await HttpRunOperations(api).list()

    assert raised.value.status_code == 401


def test_run_path_escapes_the_id() -> None:
    assert run_path("a/b") == "/api/v1/runs/a%2Fb"
    assert run_path("r", "diff") == "/api/v1/runs/r/diff"
