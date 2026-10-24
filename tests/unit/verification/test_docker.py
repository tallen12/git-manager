from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from git_manager.config.models import DockerConfig, DockerMode
from git_manager.runtime import (
    Command,
    ProcessCompleted,
    ProcessResult,
    ProcessTimedOut,
    ProcessUser,
)
from git_manager.verification import (
    DockerCleanupError,
    DockerCliCleaner,
    UnsupportedDockerModeError,
    docker_environment,
)
from tests.conftest import FakeProcessRunner

RUN_STARTED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
DATA = Path("data")


def answer(*, exit_code: int = 0, stdout: str = "", stderr: str = "") -> ProcessResult:
    return ProcessCompleted(
        exit_code=exit_code, stdout=stdout, stderr=stderr, duration=timedelta(0)
    )


def test_dind_gives_tests_the_tls_client_settings_and_the_run_id() -> None:
    env = docker_environment(DockerConfig(), run_id="run-7")

    assert env == {
        "DOCKER_HOST": "tcp://localhost:2376",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": str(Path("/certs/client")),
        "GM_RUN_ID": "run-7",
    }


def test_no_docker_means_no_docker_variables() -> None:
    assert docker_environment(DockerConfig(mode=DockerMode.NONE), run_id="run-7") == {}


def test_host_socket_mode_is_not_supported_yet() -> None:
    with pytest.raises(UnsupportedDockerModeError, match="host_socket"):
        docker_environment(DockerConfig(mode=DockerMode.HOST_SOCKET), run_id="run-7")


async def test_cleanup_removes_what_the_run_labeled_as_gm_tests() -> None:
    def respond(command: Command) -> ProcessResult:
        return answer(stdout="abc\ndef\n" if command.argv[1] == "ps" else "")

    runner = FakeProcessRunner(respond=respond)
    cleaner = DockerCliCleaner(runner=runner, cwd=DATA)
    docker = DockerConfig(reset_between_runs=False)

    await cleaner.clean_up(run_id="run-7", docker=docker, run_started=RUN_STARTED)

    label = "label=gm.run=run-7"
    assert [command.argv for command in runner.commands] == [
        ("docker", "ps", "--all", "--quiet", "--filter", label),
        ("docker", "rm", "--force", "--volumes", "abc", "def"),
        ("docker", "network", "prune", "--force", "--filter", label),
        ("docker", "volume", "prune", "--all", "--force", "--filter", label),
    ]
    for command in runner.commands:
        assert command.user is ProcessUser.TESTS
        assert command.env["DOCKER_HOST"] == "tcp://localhost:2376"
        assert "GM_RUN_ID" not in command.env


async def test_reset_between_runs_prunes_what_predates_the_run_but_keeps_images() -> None:
    runner = FakeProcessRunner()
    cleaner = DockerCliCleaner(runner=runner, cwd=DATA)

    await cleaner.clean_up(run_id="run-7", docker=DockerConfig(), run_started=RUN_STARTED)

    until = "until=2026-01-05T09:00:00+00:00"
    argvs = [command.argv[1:] for command in runner.commands]
    assert ("ps", "--all", "--quiet", "--filter", "label=gm.run=run-7") in argvs
    assert not any(argv[0] == "rm" for argv in argvs)
    assert argvs[-3:] == [
        ("container", "prune", "--force", "--filter", until),
        ("network", "prune", "--force", "--filter", until),
        ("volume", "prune", "--force"),
    ]
    assert not any("image" in argv for argv in argvs)


async def test_cleanup_without_docker_does_nothing() -> None:
    runner = FakeProcessRunner()
    cleaner = DockerCliCleaner(runner=runner, cwd=DATA)

    await cleaner.clean_up(
        run_id="run-7", docker=DockerConfig(mode=DockerMode.NONE), run_started=RUN_STARTED
    )

    assert runner.commands == []


async def test_cleanup_tries_every_step_then_reports_each_failure() -> None:
    def respond(command: Command) -> ProcessResult:
        if command.argv[1] == "network":
            return ProcessTimedOut(stdout="", stderr="", duration=timedelta(minutes=2))
        return answer(exit_code=1, stderr="Cannot connect to the Docker daemon\n")

    runner = FakeProcessRunner(respond=respond)
    cleaner = DockerCliCleaner(runner=runner, cwd=DATA)

    with pytest.raises(DockerCleanupError) as raised:
        await cleaner.clean_up(run_id="run-7", docker=DockerConfig(), run_started=RUN_STARTED)

    message = str(raised.value)
    assert "docker ps --all" in message
    assert "exited 1: Cannot connect to the Docker daemon" in message
    assert "timed out" in message
    assert len(runner.commands) == 6


async def test_a_missing_docker_cli_is_a_cleanup_failure() -> None:
    def respond(_command: Command) -> ProcessResult:
        raise FileNotFoundError("docker")

    cleaner = DockerCliCleaner(runner=FakeProcessRunner(respond=respond), cwd=DATA)

    with pytest.raises(DockerCleanupError, match="docker"):
        await cleaner.clean_up(run_id="run-7", docker=DockerConfig(), run_started=RUN_STARTED)
