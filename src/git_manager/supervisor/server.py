"""The supervisor's Unix socket: one JSON request line in, one answer line out.

The messages and framing are ``git_manager.isolation.models`` and ``isolation.wire``.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Coroutine
from pathlib import Path

from git_manager.isolation.errors import SupervisorProtocolError
from git_manager.isolation.models import SpawnErrorCode, SpawnFailed, SupervisorResponse
from git_manager.isolation.wire import (
    MAX_MESSAGE_BYTES,
    decode_supervisor_request,
    encode_response,
)
from git_manager.supervisor.protocols import PeerCredentials, RequestAnswerer


class SupervisorServer:
    """Serves a ``RequestAnswerer`` on a Unix socket, one request per connection.

    A peer that closes its end before the reply cancels the request, which kills a running
    command's process group.
    """

    def __init__(self, *, handler: RequestAnswerer, peers: PeerCredentials) -> None:
        self._handler = handler
        self._peers = peers

    @contextlib.asynccontextmanager
    async def serving(self, path: Path) -> AsyncGenerator[None]:
        """Listen on ``path`` (replacing a stale socket) until the context exits."""
        await asyncio.to_thread(path.unlink, missing_ok=True)
        server = await asyncio.start_unix_server(self._connection, path, limit=MAX_MESSAGE_BYTES)
        try:
            yield
        finally:
            server.close()
            server.abort_clients()
            await server.wait_closed()
            await asyncio.to_thread(path.unlink, missing_ok=True)

    async def _connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            reply = await self._answer(reader, writer)
            if reply is not None:
                writer.write(encode_response(reply))
                await writer.drain()
        except ConnectionError:
            pass  # The peer left; there is nobody to answer.
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def _answer(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> SupervisorResponse | None:
        connection = writer.get_extra_info("socket")
        peer_uid = self._peers.peer_uid(connection.fileno())
        try:
            line = await reader.readuntil(b"\n")
            request = decode_supervisor_request(line)
        except asyncio.LimitOverrunError:
            return _invalid(f"request over {MAX_MESSAGE_BYTES} bytes")
        except asyncio.IncompleteReadError:
            return None
        except SupervisorProtocolError as error:
            # Without a valid request there is no kind to answer in; spawns are the norm.
            return _invalid(str(error))
        return await unless_peer_leaves(self._handler.handle(request, peer_uid=peer_uid), reader)


async def unless_peer_leaves[T](
    work: Coroutine[object, object, T], reader: asyncio.StreamReader
) -> T | None:
    """Await ``work``, cancelling it if the peer closes its end first (``None``)."""
    task = asyncio.create_task(work)
    # The protocol allows nothing after the request line, so any read result means the
    # peer is gone or misbehaving.
    gone = asyncio.create_task(reader.read(1))
    try:
        await asyncio.wait({task, gone}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not task.done():
            task.cancel()
        gone.cancel()
        await asyncio.gather(task, gone, return_exceptions=True)
    if task.cancelled():
        return None
    return task.result()


def _invalid(message: str) -> SpawnFailed:
    return SpawnFailed(code=SpawnErrorCode.INVALID_REQUEST, message=message)
