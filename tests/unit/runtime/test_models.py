from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.runtime import Command, ProcessCompleted, ProcessUser


def test_command_keeps_a_read_only_copy_of_its_environment() -> None:
    env = {"PATH": "/usr/bin"}
    command = Command(argv=("git", "status"), cwd=Path(), env=env)
    env["GH_TOKEN"] = "secret"

    assert dict(command.env) == {"PATH": "/usr/bin"}
    with pytest.raises(TypeError):
        command.env["GH_TOKEN"] = "secret"  # ty: ignore[invalid-assignment] -- proving it is read-only


def test_command_runs_as_the_orchestrator_with_an_empty_environment_by_default() -> None:
    command = Command(argv=("git",), cwd=Path())

    assert command.user is ProcessUser.ORCHESTRATOR
    assert dict(command.env) == {}


def test_command_needs_a_program() -> None:
    with pytest.raises(ValueError, match="program name"):
        Command(argv=(), cwd=Path())


@pytest.mark.parametrize(("exit_code", "succeeded"), [(0, True), (1, False)])
def test_completed_process_succeeds_only_on_exit_zero(*, exit_code: int, succeeded: bool) -> None:
    result = ProcessCompleted(exit_code=exit_code, stdout="", stderr="", duration=timedelta(0))

    assert result.succeeded is succeeded
