import pytest
from pydantic import ValidationError

from git_manager.approvals import Actor, ActorType
from git_manager.verification import (
    CommandSource,
    StepOutcome,
    TestResult,
    VerifyCommands,
    VerifyStep,
)


def test_commands_need_a_test_command() -> None:
    with pytest.raises(ValidationError):
        VerifyCommands(test="", source=CommandSource.CONFIG, source_hash="h")


def test_extracted_commands_record_who_confirmed_them() -> None:
    commands = VerifyCommands(
        setup="just setup",
        test="just test",
        source=CommandSource.AGENTS_MD,
        source_hash="abc",
        confirmed_by=Actor(type=ActorType.HUMAN_CLI, identity="tyler"),
    )

    assert VerifyCommands.model_validate_json(commands.model_dump_json()) == commands


def test_a_timed_out_step_has_no_exit_code() -> None:
    result = TestResult(
        step=VerifyStep.TEST,
        command="just test",
        outcome=StepOutcome.TIMED_OUT,
        exit_code=None,
        attempts=1,
        duration_s=1800.0,
        output_tail="...",
    )

    assert result.exit_code is None


def test_a_step_runs_at_least_once() -> None:
    with pytest.raises(ValidationError):
        TestResult(
            step=VerifyStep.TEST,
            command="just test",
            outcome=StepOutcome.PASSED,
            exit_code=0,
            attempts=0,
            duration_s=1.0,
            output_tail="",
        )
