from git_manager.rebasing import GitError


def test_git_error_names_the_command_and_its_stderr() -> None:
    error = GitError(argv=["git", "fetch", "origin"], exit_code=128, stderr="fatal: no remote\n")

    assert str(error) == "git fetch origin exited 128: fatal: no remote"
    assert error.argv == ("git", "fetch", "origin")


def test_git_error_reports_a_timeout() -> None:
    error = GitError(argv=["git", "fetch"], exit_code=None, stderr="")

    assert "timed out" in str(error)
