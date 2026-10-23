"""Run commands as the current user: the fallback outside the container, and the way the
daemon runs its own ``gm`` commands inside it.
"""

import asyncio
import contextlib
import logging
import os
import signal
import time
from collections.abc import Callable, Mapping
from datetime import timedelta

from git_manager.isolation.environment import INHERITED_VARIABLES, scrubbed_environment
from git_manager.runtime.models import (
    Command,
    ProcessCompleted,
    ProcessResult,
    ProcessTimedOut,
    ProcessUser,
)

_LOGGER = logging.getLogger(__name__)
_CHUNK = 64 * 1024
# How long to wait for pipes to close once the process group is gone. A process that left
# the group with setsid can hold them open forever; its output is then cut off.
_DRAIN_TIMEOUT = timedelta(seconds=1)


class LocalProcessRunner:
    """``ProcessRunner`` that runs every command as the current user.

    Each command gets a scrubbed environment and its own process group; on timeout the
    whole group gets ``SIGTERM``, then ``SIGKILL`` after ``kill_grace``. Group members left
    behind by a command that exited are killed too. The first command meant for
    ``gm-claude`` or ``gm-tests`` logs a warning that process isolation is off.
    """

    def __init__(
        self,
        *,
        inherited: Mapping[str, str],
        logger: logging.Logger = _LOGGER,
        monotonic: Callable[[], float] = time.monotonic,
        kill_grace: timedelta = timedelta(seconds=5),
    ) -> None:
        self._inherited = dict(inherited)
        self._logger = logger
        self._monotonic = monotonic
        self._kill_grace = kill_grace
        self._warned = False

    async def run(self, command: Command) -> ProcessResult:
        if command.user is not ProcessUser.ORCHESTRATOR and not self._warned:
            self._warned = True
            self._logger.warning(
                "process isolation is off: %s commands run as the current user "
                "(their environment is still scrubbed)",
                command.user,
            )
        env = scrubbed_environment(
            command.env, inherited=self._inherited, allowed=INHERITED_VARIABLES
        )
        return await self._spawn(command, env)

    async def _spawn(self, command: Command, env: Mapping[str, str]) -> ProcessResult:
        started = self._monotonic()
        process = await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=command.cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL if command.stdin is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = bytearray(), bytearray()
        io = [
            asyncio.create_task(_drain(process.stdout, stdout)),
            asyncio.create_task(_drain(process.stderr, stderr)),
        ]
        if command.stdin is not None:
            io.append(asyncio.create_task(_feed(process.stdin, command.stdin)))
        timeout = None if command.timeout is None else command.timeout.total_seconds()
        timed_out = False
        try:
            async with asyncio.timeout(timeout):
                await process.wait()
        except TimeoutError:
            timed_out = True
            await self._stop_group(process)
        except asyncio.CancelledError:
            await self._stop_group(process)
            raise
        finally:
            _signal_group(process.pid, signal.SIGKILL)
            await _finish(io)
        duration = timedelta(seconds=self._monotonic() - started)
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if timed_out:
            return ProcessTimedOut(stdout=out, stderr=err, duration=duration)
        # Set once wait() returned; negative when a signal ended the process.
        exit_code = process.returncode
        if exit_code is None:  # pragma: no cover - wait() returned, so it exited
            msg = "process exited without a return code"
            raise RuntimeError(msg)
        return ProcessCompleted(exit_code=exit_code, stdout=out, stderr=err, duration=duration)

    async def _stop_group(self, process: asyncio.subprocess.Process) -> None:
        _signal_group(process.pid, signal.SIGTERM)
        try:
            async with asyncio.timeout(self._kill_grace.total_seconds()):
                await process.wait()
        except TimeoutError:
            _signal_group(process.pid, signal.SIGKILL)
            await process.wait()


def _signal_group(pgid: int, signum: signal.Signals) -> None:
    # The group may already be empty (ESRCH), or hold only zombies (EPERM on macOS); either
    # way nothing is left running, which is the outcome we want.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signum)


async def _drain(stream: asyncio.StreamReader | None, sink: bytearray) -> None:
    if stream is None:  # pragma: no cover - always piped above
        return
    while chunk := await stream.read(_CHUNK):
        sink.extend(chunk)


async def _feed(stream: asyncio.StreamWriter | None, text: str) -> None:
    if stream is None:  # pragma: no cover - always piped when stdin is set
        return
    # A command may exit without reading its input; that is its choice, not an error.
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        stream.write(text.encode("utf-8"))
        await stream.drain()
    stream.close()


async def _finish(tasks: list[asyncio.Task[None]]) -> None:
    _done, pending = await asyncio.wait(tasks, timeout=_DRAIN_TIMEOUT.total_seconds())
    for task in pending:
        task.cancel()
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        # Cancelled readers are expected (BaseException); anything else is a real failure.
        if isinstance(result, Exception):
            raise result
