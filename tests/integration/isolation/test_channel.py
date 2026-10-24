import asyncio
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.isolation import (
    SupervisedProcessRunner,
    SupervisorProtocolError,
    UnixSocketSupervisorChannel,
)
from git_manager.runtime import Command, ProcessCompleted, ProcessTimedOut, ProcessUser
from tests.conftest import FakeProcessRunner
from tests.integration.isolation.conftest import LocalSupervisor

ORCHESTRATOR_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/home/gm", "GH_TOKEN": "ghp_secret"}
PRINT_ENV = "import json, os; print(json.dumps(dict(os.environ)))"


def runner(supervisor: LocalSupervisor) -> SupervisedProcessRunner:
    return SupervisedProcessRunner(
        channel=UnixSocketSupervisorChannel(supervisor.path),
        direct=FakeProcessRunner(),
        inherited=ORCHESTRATOR_ENV,
    )


def isolated_command(code: str, *, timeout: timedelta | None = None) -> Command:
    return Command(
        argv=(sys.executable, "-c", code),
        cwd=Path.cwd(),
        env={"GM_RUN_ID": "run-1"},
        user=ProcessUser.TESTS,
        timeout=timeout,
    )


async def test_commands_run_through_the_socket_with_a_scrubbed_environment(
    supervisor: LocalSupervisor,
) -> None:
    result = await runner(supervisor).run(isolated_command(PRINT_ENV))

    assert isinstance(result, ProcessCompleted)
    env = json.loads(result.stdout)
    assert env["GM_RUN_ID"] == "run-1"
    assert env["PATH"] == "/usr/bin:/bin"
    assert "GH_TOKEN" not in env
    # The supervisor, not the orchestrator, chooses HOME.
    assert env["HOME"] != "/home/gm"
    assert [request.user for request in supervisor.requests] == [ProcessUser.TESTS]


async def test_large_output_crosses_the_socket(supervisor: LocalSupervisor) -> None:
    result = await runner(supervisor).run(isolated_command("print('x' * 5_000_000)"))

    assert isinstance(result, ProcessCompleted)
    assert len(result.stdout) == 5_000_001


async def test_timeouts_are_enforced_by_the_supervisor(supervisor: LocalSupervisor) -> None:
    code = "import time; print('started', flush=True); time.sleep(60)"

    result = await runner(supervisor).run(isolated_command(code, timeout=timedelta(seconds=1)))

    assert isinstance(result, ProcessTimedOut)
    assert result.stdout == "started\n"


async def test_a_program_that_cannot_start_raises_os_error(supervisor: LocalSupervisor) -> None:
    command = Command(argv=("gm-no-such-program",), cwd=Path.cwd(), user=ProcessUser.CLAUDE)

    with pytest.raises(OSError):
        await runner(supervisor).run(command)


async def test_an_answer_outside_the_contract_is_a_protocol_error(
    supervisor: LocalSupervisor,
) -> None:
    supervisor.raw_answer = b'{"kind": "exploded"}\n'

    with pytest.raises(SupervisorProtocolError):
        await runner(supervisor).run(isolated_command("pass"))


async def test_a_supervisor_that_hangs_up_is_a_protocol_error(
    supervisor: LocalSupervisor,
) -> None:
    supervisor.raw_answer = b""

    with pytest.raises(SupervisorProtocolError, match="without answering"):
        await runner(supervisor).run(isolated_command("pass"))


async def test_a_silent_supervisor_is_given_up_on_after_the_grace_period() -> None:
    async def never_answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        # Hold the request until the client gives up and closes the connection.
        await reader.read()
        writer.close()

    with tempfile.TemporaryDirectory(prefix="gm-") as directory:
        path = Path(directory) / "s.sock"
        server = await asyncio.start_unix_server(never_answer, path=path)
        async with server:
            channel = UnixSocketSupervisorChannel(path, answer_grace=timedelta(milliseconds=100))
            silent = SupervisedProcessRunner(
                channel=channel, direct=FakeProcessRunner(), inherited={}
            )
            with pytest.raises(SupervisorProtocolError, match="did not answer"):
                await silent.run(isolated_command("pass", timeout=timedelta(milliseconds=100)))
