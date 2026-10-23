import asyncio
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import assert_never

import pytest

from git_manager.isolation import (
    LocalProcessRunner,
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
    SpawnResponse,
    SpawnTimedOut,
    SupervisorProtocolError,
)
from git_manager.isolation.wire import MAX_MESSAGE_BYTES, decode_request, encode_response
from git_manager.runtime import Command, ProcessCompleted, ProcessTimedOut


@dataclass(slots=True)
class LocalSupervisor:
    """The supervisor side of the wire contract, running commands as the current user.

    F4b's PID 1 supervisor switches users; this stand-in checks everything else (framing,
    exact environment, timeouts, start failures) across a real socket.
    """

    path: Path
    requests: list[SpawnRequest] = field(default_factory=list)
    # Replaces the answer with raw bytes, to test a misbehaving supervisor.
    raw_answer: bytes | None = None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if self.raw_answer is not None:
                writer.write(self.raw_answer)
            else:
                writer.write(encode_response(await self._answer(line)))
            await writer.drain()
        finally:
            writer.close()

    async def _answer(self, line: bytes) -> SpawnResponse:
        try:
            request = decode_request(line)
        except SupervisorProtocolError as error:
            return SpawnFailed(code=SpawnErrorCode.INVALID_REQUEST, message=str(error))
        self.requests.append(request)
        # Exactly the request's env: nothing inherited from this process.
        runner = LocalProcessRunner(inherited={})
        command = Command(
            argv=request.argv,
            cwd=request.cwd,
            env={"HOME": str(request.cwd)} | request.env,
            timeout=None if request.timeout_s is None else timedelta(seconds=request.timeout_s),
            stdin=request.stdin,
        )
        try:
            result = await runner.run(command)
        except OSError as error:
            return SpawnFailed(code=SpawnErrorCode.START_FAILED, message=str(error))
        match result:
            case ProcessCompleted(exit_code=code, stdout=out, stderr=err, duration=duration):
                return SpawnCompleted(
                    exit_code=code, stdout=out, stderr=err, duration_s=duration.total_seconds()
                )
            case ProcessTimedOut(stdout=out, stderr=err, duration=duration):
                return SpawnTimedOut(stdout=out, stderr=err, duration_s=duration.total_seconds())
            case _ as unreachable:
                assert_never(unreachable)


@pytest.fixture
async def supervisor() -> AsyncIterator[LocalSupervisor]:
    # Unix socket paths are limited to about 100 bytes; pytest's tmp_path can be longer.
    with tempfile.TemporaryDirectory(prefix="gm-") as directory:
        stand_in = LocalSupervisor(path=Path(directory) / "supervisor.sock")
        server = await asyncio.start_unix_server(
            stand_in.handle, path=stand_in.path, limit=MAX_MESSAGE_BYTES
        )
        async with server:
            yield stand_in
