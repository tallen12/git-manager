import errno
import os
from pathlib import Path

import pytest

from git_manager.supervisor.enter import SPAWN_FAILED_EXIT, encode_failure, main


def test_a_missing_directory_is_reported_on_the_status_pipe(tmp_path: Path) -> None:
    read, write = os.pipe()
    try:
        with pytest.raises(SystemExit) as exit_:
            main([str(write), str(tmp_path / "gone"), "", "true"])
        os.close(write)

        assert exit_.value.code == SPAWN_FAILED_EXIT
        number, _, message = os.read(read, 4096).decode().partition("\n")
        assert int(number) == errno.ENOENT
        assert "gone" in message
    finally:
        os.close(read)


def test_too_few_arguments_print_usage() -> None:
    with pytest.raises(SystemExit, match="usage"):
        main(["3", "/data", ""])


def test_a_failure_encodes_errno_then_message() -> None:
    assert encode_failure(PermissionError(errno.EACCES, "denied")) == b"13\n[Errno 13] denied"
    assert encode_failure(OSError("plain")).startswith(b"0\n")


def test_unset_variables_are_removed_before_the_command_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LC_CTYPE", "C.UTF-8")
    monkeypatch.setenv("KEEP", "1")
    read, write = os.pipe()
    try:
        with pytest.raises(SystemExit):
            # A missing program stops before exec, after the environment was cleaned.
            main([str(write), str(tmp_path), "LC_CTYPE", "gm-no-such-program"])
    finally:
        os.close(read)
        os.close(write)

    assert "LC_CTYPE" not in os.environ
    assert os.environ["KEEP"] == "1"
