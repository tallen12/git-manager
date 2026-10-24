"""The supervisor channel over its Unix socket."""

import asyncio
from datetime import timedelta
from pathlib import Path

from git_manager.isolation.errors import SupervisorProtocolError, SupervisorUnavailableError
from git_manager.isolation.models import SpawnRequest, SpawnResponse
from git_manager.isolation.wire import MAX_MESSAGE_BYTES, decode_response, encode_request

DEFAULT_SOCKET = Path("/run/gm-supervisor/supervisor.sock")
"""Where the supervisor listens: mode 0600, owned by ``gm``, so only the daemon can ask.

Its own root-owned directory: ``/run/git-manager`` belongs to ``gm`` and ``gm-admin``, and
root without ``CAP_DAC_OVERRIDE`` could not replace a stale socket there.
"""


class UnixSocketSupervisorChannel:
    """``SupervisorChannel`` that opens one connection per request.

    The supervisor enforces the command's timeout. ``answer_grace`` bounds how much longer
    this side waits for the answer (killing and collecting output takes a moment) before
    it gives up and closes the connection, which makes the supervisor kill the command.
    """

    def __init__(
        self, path: Path = DEFAULT_SOCKET, *, answer_grace: timedelta = timedelta(seconds=30)
    ) -> None:
        self._path = path
        self._answer_grace = answer_grace

    async def spawn(self, request: SpawnRequest) -> SpawnResponse:
        try:
            reader, writer = await asyncio.open_unix_connection(self._path, limit=MAX_MESSAGE_BYTES)
        except OSError as error:
            msg = f"cannot reach the supervisor at {self._path}: {error}"
            raise SupervisorUnavailableError(msg) from error
        deadline = (
            None
            if request.timeout_s is None
            else request.timeout_s + self._answer_grace.total_seconds()
        )
        try:
            writer.write(encode_request(request))
            await writer.drain()
            async with asyncio.timeout(deadline):
                line = await reader.readline()
        except TimeoutError as error:
            msg = f"the supervisor did not answer within {deadline:.0f}s"
            raise SupervisorProtocolError(msg) from error
        except ValueError as error:
            # readline() raises ValueError when a line exceeds the reader's limit.
            msg = f"the supervisor's answer is over {MAX_MESSAGE_BYTES} bytes"
            raise SupervisorProtocolError(msg) from error
        except ConnectionError as error:
            msg = f"lost the connection to the supervisor: {error}"
            raise SupervisorUnavailableError(msg) from error
        finally:
            writer.close()
        return decode_response(line)
