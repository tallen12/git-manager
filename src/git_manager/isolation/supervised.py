"""The container's ``ProcessRunner``: isolated users through the supervisor."""

from collections.abc import Mapping
from datetime import timedelta
from typing import assert_never

from git_manager.isolation.environment import SUPERVISED_INHERITED_VARIABLES, scrubbed_environment
from git_manager.isolation.errors import SupervisorProtocolError
from git_manager.isolation.models import (
    IsolatedUser,
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SpawnResponse,
    SpawnTimedOut,
)
from git_manager.isolation.protocols import SupervisorChannel
from git_manager.runtime.models import (
    Command,
    ProcessCompleted,
    ProcessResult,
    ProcessTimedOut,
    ProcessUser,
)
from git_manager.runtime.protocols import ProcessRunner


class SupervisedProcessRunner:
    """``ProcessRunner`` that sends ``gm-claude`` and ``gm-tests`` commands to the supervisor.

    ``gm`` commands are the daemon's own and run through ``direct`` (normally a
    ``LocalProcessRunner``, since the daemon already runs as ``gm``).
    """

    def __init__(
        self, *, channel: SupervisorChannel, direct: ProcessRunner, inherited: Mapping[str, str]
    ) -> None:
        self._channel = channel
        self._direct = direct
        self._inherited = dict(inherited)

    async def run(self, command: Command) -> ProcessResult:
        match command.user:
            case ProcessUser.ORCHESTRATOR:
                return await self._direct.run(command)
            case ProcessUser.CLAUDE | ProcessUser.TESTS:
                request = spawn_request(command, user=command.user, inherited=self._inherited)
                return process_result(await self._channel.spawn(request))
            case _ as unreachable:
                assert_never(unreachable)


def spawn_request(
    command: Command, *, user: IsolatedUser, inherited: Mapping[str, str]
) -> SpawnRequest:
    """The request that runs ``command`` as ``user`` with a scrubbed environment."""
    env = scrubbed_environment(
        command.env, inherited=inherited, allowed=SUPERVISED_INHERITED_VARIABLES
    )
    return SpawnRequest(
        user=user,
        argv=command.argv,
        cwd=command.cwd.absolute(),
        env=env,
        timeout_s=None if command.timeout is None else command.timeout.total_seconds(),
        stdin=command.stdin,
    )


def process_result(response: SpawnResponse) -> ProcessResult:
    """Map the supervisor's answer onto the ``ProcessRunner`` contract.

    Raises ``OSError`` when the program could not be started, as a local runner would, and
    ``SupervisorProtocolError`` when the supervisor rejected the request itself.
    """
    match response:
        case SpawnCompleted(exit_code=code, stdout=out, stderr=err, duration_s=seconds):
            return ProcessCompleted(
                exit_code=code, stdout=out, stderr=err, duration=timedelta(seconds=seconds)
            )
        case SpawnTimedOut(stdout=out, stderr=err, duration_s=seconds):
            return ProcessTimedOut(stdout=out, stderr=err, duration=timedelta(seconds=seconds))
        case SpawnFailed(code=code, message=message):
            match code:
                case SpawnErrorCode.START_FAILED:
                    raise OSError(message)
                case SpawnErrorCode.INVALID_REQUEST:
                    msg = f"the supervisor rejected the request: {message}"
                    raise SupervisorProtocolError(msg)
                case _ as unreachable:
                    assert_never(unreachable)
        case _ as unreachable:
            assert_never(unreachable)
