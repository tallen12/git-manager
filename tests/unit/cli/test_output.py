import pytest

from git_manager.cli.output import EXIT_FAILED, fail, reported, short, table
from git_manager.core import ApiUnreachableError, NotFoundError
from git_manager.rebasing import GitError


def test_fail_prints_one_line_and_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        fail(GitError(argv=["git", "push"], exit_code=1, stderr="remote:\n  rejected\n"))

    assert exit_.value.code == EXIT_FAILED
    assert capsys.readouterr().err == "error: git push exited 1: remote: rejected\n"


@pytest.mark.parametrize("error", [NotFoundError(kind="run", key="r"), ApiUnreachableError("down")])
def test_reported_turns_command_errors_into_exit_1(error: Exception) -> None:
    with pytest.raises(SystemExit) as exit_, reported():
        raise error

    assert exit_.value.code == EXIT_FAILED


def test_reported_lets_other_errors_through() -> None:
    with pytest.raises(KeyError), reported():
        raise KeyError("bug")


def test_short_abbreviates_hashes() -> None:
    assert short("0123456789abcdef0123") == "0123456789ab"
    assert short(None) == "-"


def test_table_aligns_columns_without_trailing_blanks() -> None:
    assert table(("A", "LONG"), [("xyz", ""), ("p", "q")]) == "A    LONG\nxyz\np    q"
