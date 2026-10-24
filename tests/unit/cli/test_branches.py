import pytest

from git_manager.branches import BranchHeads, BranchState, Reason, RepoStatus
from git_manager.branches.results import SyncCompleted, SyncQueued
from git_manager.cli.branches import branch_line, status_text, sync_pushed, sync_text
from git_manager.core import ConflictError
from tests.conftest import make_branch, make_run, run_cli, sha
from tests.unit.cli.conftest import FakeBranchOperations, operations_app


def test_status_text_lists_branches_in_a_table() -> None:
    branch = make_branch(state=BranchState.TESTS_FAILED, reason=Reason.VERIFY_FAILED)

    text = status_text(RepoStatus(repo_id="repo", url="u", branches=(branch,)))

    assert text.splitlines() == [
        "repo u",
        "BRANCH       BASE  STATE         REASON         HEAD          FORK POINT",
        f"feature/one  main  tests_failed  verify_failed  {sha(2)[:12]}  {sha(1)[:12]}",
    ]


def test_status_text_without_branches() -> None:
    text = status_text(RepoStatus(repo_id="repo", url="u", branches=()))

    assert text == "repo u\nno tracked branches"


def test_branch_line_shows_the_reason_when_there_is_one() -> None:
    assert branch_line(make_branch()) == "feature/one on main: idle"
    paused = make_branch(state=BranchState.PAUSED, reason=Reason.PAUSED_BY_USER)
    assert branch_line(paused) == "feature/one on main: paused (paused_by_user)"


def test_sync_text_and_exit_follow_the_outcome() -> None:
    pushed = SyncCompleted(run=make_run())
    conflict = SyncCompleted(
        run=make_run(
            heads=(BranchHeads(branch="feature/one", old_head=sha(2)),),
            outcome=BranchState.NEEDS_HUMAN,
            reason=Reason.CONFLICT,
        )
    )
    queued = SyncQueued(branch_id="branch-1", position=2)

    assert sync_text(pushed) == (
        f"run run-1: idle\nfeature/one {sha(2)[:12]} -> {sha(4)[:12]} on {sha(3)[:12]}"
    )
    assert sync_text(conflict).splitlines()[0] == "run run-1: needs_human (conflict)"
    assert " -> - on " in sync_text(conflict)
    assert sync_text(queued) == "queued branch-1 behind 2 other run(s)"
    assert [sync_pushed(outcome) for outcome in (pushed, conflict, queued)] == [
        True,
        False,
        True,
    ]


def test_track_prints_the_tracked_branch(
    config_target: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    branches = FakeBranchOperations()

    status = run_cli(
        operations_app(branches=branches), ["track", "feature/x", "--base", "dev", *config_target]
    )

    assert status == 0
    assert branches.calls == ["track feature/x dev"]
    assert capsys.readouterr().out == (
        f"tracked feature/x on dev: idle, fork point {sha(1)[:12]}\n"
    )


def test_status_untrack_pause_and_resume(
    config_target: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    branches = FakeBranchOperations(branches={"feature/one": make_branch()})
    app = operations_app(branches=branches)

    for command in ("status", "pause feature/one", "resume feature/one", "untrack feature/one"):
        assert run_cli(app, [*command.split(), *config_target]) == 0

    assert branches.calls == [
        "status",
        "pause feature/one",
        "resume feature/one",
        "untrack feature/one",
    ]
    out = capsys.readouterr().out
    assert "feature/one on main: paused (paused_by_user)\n" in out
    assert "feature/one on main: idle\nuntracked feature/one\n" in out


@pytest.mark.parametrize(
    ("outcome", "exit_code"),
    [
        (BranchState.IDLE, 0),
        (BranchState.AWAITING_APPROVAL, 3),
        (BranchState.TESTS_FAILED, 3),
    ],
)
def test_sync_exits_3_when_the_run_did_not_push(
    config_target: list[str],
    capsys: pytest.CaptureFixture[str],
    outcome: BranchState,
    exit_code: int,
) -> None:
    branches = FakeBranchOperations(
        branches={"feature/one": make_branch()},
        sync_outcome=SyncCompleted(run=make_run(outcome=outcome)),
    )

    status = run_cli(operations_app(branches=branches), ["sync", "feature/one", *config_target])

    assert status == exit_code
    assert capsys.readouterr().out.startswith(f"run run-1: {outcome}\n")


def test_operation_errors_print_one_line_and_exit_1(
    config_target: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    branches = FakeBranchOperations(
        branches={"feature/one": make_branch()},
        error=ConflictError("cannot sync feature/one:\n it is paused"),
    )

    status = run_cli(operations_app(branches=branches), ["sync", "feature/one", *config_target])

    assert status == 1
    assert capsys.readouterr().err == "error: cannot sync feature/one: it is paused\n"


def test_unknown_branch_is_reported(
    config_target: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    status = run_cli(operations_app(), ["pause", "feature/x", *config_target])

    assert status == 1
    assert capsys.readouterr().err == "error: branch not found: feature/x\n"
