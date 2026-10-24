import json

import pytest

from git_manager.branches import BranchState, Reason
from git_manager.cli.runs import logs_text, runs_text
from git_manager.verification import StepOutcome, TestResult, VerifyStep
from tests.conftest import make_run, run_cli, sha
from tests.unit.cli.conftest import FakeRunOperations, operations_app

FAILED = TestResult(
    step=VerifyStep.TEST,
    command="just test",
    outcome=StepOutcome.FAILED,
    exit_code=1,
    attempts=2,
    duration_s=3.25,
    output_tail="E assert 1 == 2\n1 failed\n",
)


def test_runs_text_is_a_table_newest_first() -> None:
    runs = [
        make_run(id="run-2", outcome=BranchState.TESTS_FAILED, reason=Reason.VERIFY_FAILED),
        make_run(),
    ]

    lines = runs_text(runs).splitlines()

    assert lines[0].split() == ["RUN", "BRANCH", "TRIGGER", "OUTCOME", "REASON", "BASE", "STARTED"]
    assert lines[1].split() == [
        "run-2",
        "feature/one",
        "poll",
        "tests_failed",
        "verify_failed",
        sha(3)[:12],
        "2026-01-05T09:00:00+00:00",
    ]
    assert lines[2].split()[:4] == ["run-1", "feature/one", "poll", "idle"]
    assert runs_text([]) == "no runs"


def test_logs_text_shows_each_step_and_its_output() -> None:
    assert logs_text([FAILED]) == (
        "== test: just test (failed, exit 1, 2 attempt(s), 3.2s)\nE assert 1 == 2\n1 failed"
    )
    timed_out = FAILED.model_copy(update={"exit_code": None, "outcome": StepOutcome.TIMED_OUT})
    assert "(timed_out, timed out," in logs_text([timed_out])
    assert logs_text([]) == "no test results"


@pytest.fixture
def runs() -> FakeRunOperations:
    return FakeRunOperations(
        runs=[make_run(id="run-2", branch_id="branch-2"), make_run(tests=(FAILED,))],
        diffs={"run-1": "diff --git a/f b/f\n"},
    )


def test_runs_filters_and_limits(
    runs: FakeRunOperations, config_target: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    app = operations_app(runs=runs)

    assert run_cli(app, ["runs", "--branch", "branch-1", *config_target]) == 0
    assert run_cli(app, ["runs", "--limit", "1", *config_target]) == 0

    tables = capsys.readouterr().out.split("RUN ")
    assert [line.split()[0] for line in tables[1].splitlines()[1:]] == ["run-1"]
    assert [line.split()[0] for line in tables[2].splitlines()[1:]] == ["run-2"]


def test_show_diff_and_logs(
    runs: FakeRunOperations, config_target: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    app = operations_app(runs=runs)

    assert run_cli(app, ["show", "run-1", *config_target]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "run-1"
    assert run_cli(app, ["diff", "run-1", *config_target]) == 0
    assert capsys.readouterr().out == "diff --git a/f b/f\n"
    assert run_cli(app, ["logs", "run-1", *config_target]) == 0
    assert capsys.readouterr().out.startswith("== test: just test (failed")


@pytest.mark.parametrize("command", ["show", "diff", "logs"])
def test_unknown_run_is_reported(
    runs: FakeRunOperations,
    config_target: list[str],
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    status = run_cli(operations_app(runs=runs), [command, "run-9", *config_target])

    assert status == 1
    assert capsys.readouterr().err == "error: run not found: run-9\n"
