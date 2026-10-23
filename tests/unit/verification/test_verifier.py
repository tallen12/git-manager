import logging
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.config import VerifyConfig
from git_manager.config.models import DockerConfig, DockerMode
from git_manager.runtime import (
    Command,
    ProcessCompleted,
    ProcessResult,
    ProcessTimedOut,
    ProcessUser,
)
from git_manager.verification import (
    CommandSource,
    CommandVerifier,
    InvalidCommandError,
    StepOutcome,
    VerifyCommands,
    VerifyFailed,
    VerifyPassed,
    VerifyStep,
)
from git_manager.verification.verifier import CANNOT_START_EXIT_CODE
from tests.conftest import START, FakeProcessRunner, FixedClock
from tests.unit.verification.conftest import RecordingDockerCleaner

ALL_STEPS = VerifyCommands(
    setup="just setup",
    test="just test",
    lint="just lint",
    source=CommandSource.CONFIG,
    source_hash="h",
)
NO_DOCKER = VerifyConfig(docker=DockerConfig(mode=DockerMode.NONE))


def completed(exit_code: int, stdout: str = "", stderr: str = "") -> ProcessResult:
    return ProcessCompleted(
        exit_code=exit_code, stdout=stdout, stderr=stderr, duration=timedelta(seconds=2)
    )


def scripted(*results: ProcessResult) -> FakeProcessRunner:
    remaining = list(results)

    def respond(_command: Command) -> ProcessResult:
        return remaining.pop(0)

    return FakeProcessRunner(respond=respond)


def make_verifier(
    runner: FakeProcessRunner, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> CommandVerifier:
    return CommandVerifier(runner=runner, cleaner=cleaner, clock=clock)


async def test_every_step_runs_in_order_as_gm_tests_in_the_worktree(
    tmp_path: Path,
    process_runner: FakeProcessRunner,
    cleaner: RecordingDockerCleaner,
    clock: FixedClock,
) -> None:
    config = VerifyConfig(timeout=timedelta(minutes=5))

    outcome = await make_verifier(process_runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=config, run_id="run-1"
    )

    assert isinstance(outcome, VerifyPassed)
    assert [result.step for result in outcome.results] == list(VerifyStep)
    assert [command.argv for command in process_runner.commands] == [
        ("just", "setup"),
        ("just", "test"),
        ("just", "lint"),
    ]
    for command in process_runner.commands:
        assert command.user is ProcessUser.TESTS
        assert command.cwd == tmp_path
        assert command.timeout == timedelta(minutes=5)


async def test_only_setup_and_test_reach_docker_and_nothing_else_is_passed(
    tmp_path: Path,
    process_runner: FakeProcessRunner,
    cleaner: RecordingDockerCleaner,
    clock: FixedClock,
) -> None:
    await make_verifier(process_runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=VerifyConfig(), run_id="run-1"
    )

    setup, test, lint = (dict(command.env) for command in process_runner.commands)
    expected = {
        "DOCKER_HOST": "tcp://localhost:2376",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": str(Path("/certs/client")),
        "GM_RUN_ID": "run-1",
    }
    assert setup == expected
    assert test == expected
    assert lint == {}


async def test_without_docker_steps_get_an_empty_environment(
    tmp_path: Path,
    process_runner: FakeProcessRunner,
    cleaner: RecordingDockerCleaner,
    clock: FixedClock,
) -> None:
    await make_verifier(process_runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=NO_DOCKER, run_id="run-1"
    )

    assert all(dict(command.env) == {} for command in process_runner.commands)


async def test_the_first_failing_step_stops_the_run(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    runner = scripted(completed(0), completed(1, stdout="1 failed\n", stderr="trace\n"))

    outcome = await make_verifier(runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=NO_DOCKER, run_id="run-1"
    )

    assert isinstance(outcome, VerifyFailed)
    assert outcome.failed_step is VerifyStep.TEST
    test = outcome.results[-1]
    assert (test.outcome, test.exit_code, test.attempts) == (StepOutcome.FAILED, 1, 1)
    assert test.output_tail == "1 failed\ntrace\n"
    assert test.command == "just test"
    assert test.duration_s == 2
    assert len(runner.commands) == 2


async def test_a_timeout_fails_the_step_without_an_exit_code(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    timed_out = ProcessTimedOut(stdout="slow\n", stderr="", duration=timedelta(minutes=30))
    runner = scripted(completed(0), timed_out)

    outcome = await make_verifier(runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=NO_DOCKER, run_id="run-1"
    )

    assert isinstance(outcome, VerifyFailed)
    test = outcome.results[-1]
    assert (test.outcome, test.exit_code, test.output_tail) == (
        StepOutcome.TIMED_OUT,
        None,
        "slow\n",
    )


async def test_a_pass_on_retry_is_flagged_by_its_attempts(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    runner = scripted(completed(0), completed(1), completed(0, stdout="ok\n"), completed(0))
    config = VerifyConfig(retries=2, docker=DockerConfig(mode=DockerMode.NONE))

    outcome = await make_verifier(runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=config, run_id="run-1"
    )

    assert isinstance(outcome, VerifyPassed)
    test = outcome.results[1]
    assert (test.outcome, test.attempts, test.output_tail) == (StepOutcome.PASSED, 2, "ok\n")
    assert test.duration_s == 4


async def test_retries_run_out_and_apply_only_to_the_test_step(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    config = VerifyConfig(retries=2, docker=DockerConfig(mode=DockerMode.NONE))
    failing_test = scripted(completed(0), completed(1), completed(1), completed(1))
    failing_setup = scripted(completed(1))

    test_outcome = await make_verifier(failing_test, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=config, run_id="run-1"
    )
    setup_outcome = await make_verifier(failing_setup, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=config, run_id="run-2"
    )

    assert isinstance(test_outcome, VerifyFailed)
    assert test_outcome.results[-1].attempts == 3
    assert isinstance(setup_outcome, VerifyFailed)
    assert setup_outcome.failed_step is VerifyStep.SETUP
    assert len(failing_setup.commands) == 1


async def test_a_program_that_cannot_start_fails_its_step(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    def respond(_command: Command) -> ProcessResult:
        raise FileNotFoundError(2, "No such file or directory", "just")

    runner = FakeProcessRunner(respond=respond)
    commands = VerifyCommands(test="just test", source=CommandSource.CONFIG, source_hash="h")

    outcome = await make_verifier(runner, cleaner, clock).verify(
        worktree=tmp_path, commands=commands, config=NO_DOCKER, run_id="run-1"
    )

    assert isinstance(outcome, VerifyFailed)
    result = outcome.results[0]
    assert result.exit_code == CANNOT_START_EXIT_CODE
    assert "cannot start 'just'" in result.output_tail


async def test_a_report_written_by_the_step_is_kept(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    report = '<testsuite name="unit" tests="1"/>\n'

    def respond(_command: Command) -> ProcessResult:
        # The fixed clock is in the past, so any file written now counts as new.
        (tmp_path / "junit.xml").write_text(report, encoding="utf-8")
        return completed(0)

    commands = VerifyCommands(test="just test", source=CommandSource.CONFIG, source_hash="h")

    outcome = await make_verifier(FakeProcessRunner(respond=respond), cleaner, clock).verify(
        worktree=tmp_path, commands=commands, config=NO_DOCKER, run_id="run-1"
    )

    assert isinstance(outcome, VerifyPassed)
    assert outcome.results[0].junit_xml == report


async def test_docker_is_cleaned_up_after_every_run(
    tmp_path: Path, cleaner: RecordingDockerCleaner, clock: FixedClock
) -> None:
    runner = scripted(completed(1))
    config = VerifyConfig()

    await make_verifier(runner, cleaner, clock).verify(
        worktree=tmp_path, commands=ALL_STEPS, config=config, run_id="run-1"
    )

    assert [(call.run_id, call.docker, call.run_started) for call in cleaner.calls] == [
        ("run-1", config.docker, START)
    ]


async def test_docker_is_cleaned_up_even_when_a_command_is_invalid(
    tmp_path: Path,
    process_runner: FakeProcessRunner,
    cleaner: RecordingDockerCleaner,
    clock: FixedClock,
) -> None:
    commands = VerifyCommands(test="pytest 'oops", source=CommandSource.CONFIG, source_hash="h")

    with pytest.raises(InvalidCommandError):
        await make_verifier(process_runner, cleaner, clock).verify(
            worktree=tmp_path, commands=commands, config=VerifyConfig(), run_id="run-1"
        )

    assert len(cleaner.calls) == 1


async def test_a_failed_cleanup_is_logged_and_does_not_change_the_outcome(
    tmp_path: Path,
    process_runner: FakeProcessRunner,
    clock: FixedClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cleaner = RecordingDockerCleaner(error="daemon down")

    with caplog.at_level(logging.ERROR):
        outcome = await make_verifier(process_runner, cleaner, clock).verify(
            worktree=tmp_path, commands=ALL_STEPS, config=VerifyConfig(), run_id="run-1"
        )

    assert isinstance(outcome, VerifyPassed)
    assert "run-1" in caplog.records[0].getMessage()
