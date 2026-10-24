from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.isolation import (
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SpawnResponse,
    SpawnTimedOut,
    SupervisedProcessRunner,
    SupervisorProtocolError,
)
from git_manager.isolation.supervised import process_result, spawn_request
from git_manager.runtime import Command, ProcessCompleted, ProcessTimedOut, ProcessUser
from tests.conftest import FakeProcessRunner
from tests.unit.isolation.conftest import FakeSupervisorChannel

INHERITED = {"PATH": "/usr/bin", "HOME": "/home/gm", "GH_TOKEN": "ghp_secret"}


def runner(channel: FakeSupervisorChannel, direct: FakeProcessRunner) -> SupervisedProcessRunner:
    return SupervisedProcessRunner(channel=channel, direct=direct, inherited=INHERITED)


@pytest.mark.parametrize("user", [ProcessUser.CLAUDE, ProcessUser.TESTS])
async def test_isolated_users_go_through_the_supervisor(
    user: ProcessUser, channel: FakeSupervisorChannel, process_runner: FakeProcessRunner
) -> None:
    command = Command(argv=("just", "test"), cwd=Path.cwd(), user=user)

    result = await runner(channel, process_runner).run(command)

    assert isinstance(result, ProcessCompleted)
    assert [request.user for request in channel.requests] == [user]
    assert process_runner.commands == []


async def test_orchestrator_commands_run_directly(
    channel: FakeSupervisorChannel, process_runner: FakeProcessRunner
) -> None:
    command = Command(argv=("git", "fetch"), cwd=Path.cwd())

    await runner(channel, process_runner).run(command)

    assert process_runner.commands == [command]
    assert channel.requests == []


def test_requests_carry_a_scrubbed_environment_without_the_orchestrator_home() -> None:
    command = Command(
        argv=("just", "test"),
        cwd=Path("relative"),
        env={"GM_RUN_ID": "run-1"},
        user=ProcessUser.TESTS,
        timeout=timedelta(minutes=30),
        stdin="y\n",
    )

    request = spawn_request(command, user=ProcessUser.TESTS, inherited=INHERITED)

    assert request.env == {"PATH": "/usr/bin", "GM_RUN_ID": "run-1"}
    assert request.cwd == Path("relative").absolute()
    assert request.timeout_s == 1800
    assert request.stdin == "y\n"


def test_answers_map_onto_process_results() -> None:
    completed = process_result(SpawnCompleted(exit_code=2, stdout="o", stderr="e", duration_s=3))
    timed_out = process_result(SpawnTimedOut(stdout="o", stderr="", duration_s=60))

    assert completed == ProcessCompleted(
        exit_code=2, stdout="o", stderr="e", duration=timedelta(seconds=3)
    )
    assert timed_out == ProcessTimedOut(stdout="o", stderr="", duration=timedelta(minutes=1))


async def test_a_program_that_cannot_start_raises_os_error(
    process_runner: FakeProcessRunner,
) -> None:
    def fail(_request: SpawnRequest) -> SpawnResponse:
        return SpawnFailed(code=SpawnErrorCode.START_FAILED, message="no such file: just")

    command = Command(argv=("just",), cwd=Path.cwd(), user=ProcessUser.TESTS)

    with pytest.raises(OSError, match="no such file"):
        await runner(FakeSupervisorChannel(respond=fail), process_runner).run(command)


def test_a_rejected_request_is_a_protocol_error() -> None:
    with pytest.raises(SupervisorProtocolError, match="rejected"):
        process_result(SpawnFailed(code=SpawnErrorCode.INVALID_REQUEST, message="version 2"))
