from git_manager.branches import BranchState
from git_manager.errors import ConflictError
from git_manager.rebasing import (
    BranchOnHoldError,
    GitError,
    GitOutputError,
    RemoteBranchMissingError,
)


def test_git_error_names_the_command_and_its_stderr() -> None:
    error = GitError(argv=["git", "fetch", "origin"], exit_code=128, stderr="fatal: no remote\n")

    assert str(error) == "git fetch origin exited 128: fatal: no remote"
    assert error.argv == ("git", "fetch", "origin")


def test_git_error_reports_a_timeout() -> None:
    error = GitError(argv=["git", "fetch"], exit_code=None, stderr="")

    assert "timed out" in str(error)


def test_git_output_error_is_a_git_error_carrying_the_output() -> None:
    error = GitOutputError(argv=["git", "merge-base"], output="junk", problem="expected a hash")

    assert isinstance(error, GitError)
    assert error.output == "junk"
    assert str(error) == "git merge-base exited 0: expected a hash: 'junk'"


def test_remote_branch_missing_error_names_the_branch_and_what_is_gone() -> None:
    error = RemoteBranchMissingError(branch="feature/one", missing="main")

    assert str(error) == "cannot sync feature/one: main is not on the remote"
    assert (error.branch, error.missing) == ("feature/one", "main")


def test_branch_on_hold_is_a_conflict_naming_the_state() -> None:
    error = BranchOnHoldError(branch="feature/one", state=BranchState.PAUSED)

    assert isinstance(error, ConflictError)
    assert str(error) == "cannot run feature/one: it is paused"
