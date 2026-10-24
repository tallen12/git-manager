"""Starts processes as other users with ``asyncio`` subprocesses."""

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from git_manager.isolation.models import (
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnTimedOut,
)
from git_manager.supervisor.models import Account, LaunchPlan, LaunchResult

_CHUNK = 64 * 1024
# How long output may keep flowing after the process exited and its group was killed,
# from a descendant that left the group (``setsid``) but kept the pipes open.
_DRAIN_GRACE_SECONDS = 5.0
# Variables the enter helper's Python may add itself (PEP 538 locale coercion); removed
# again unless the command asked for them.
_INTERPRETER_ADDED = frozenset({"LC_CTYPE"})
# Between SIGTERM and SIGKILL on timeout, as the daemon's local runner does.
TERMINATE_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class _Identity:
    user: int
    group: int
    extra_groups: tuple[int, ...]


def _identity(account: Account) -> _Identity | None:
    """The ids to switch to, or ``None`` when the process already runs as ``account``."""
    if account.uid == os.geteuid():
        return None
    return _Identity(user=account.uid, group=account.gid, extra_groups=account.groups)


async def tail_output(stream: asyncio.StreamReader | None, limit: int) -> str:
    """Read ``stream`` to its end, keeping only the last ``limit`` bytes."""
    if stream is None:
        return ""
    kept = bytearray()
    dropped = 0
    while chunk := await stream.read(_CHUNK):
        kept += chunk
        if len(kept) > limit:
            excess = len(kept) - limit
            del kept[:excess]
            dropped += excess
    text = kept.decode("utf-8", errors="replace")
    if dropped:
        return f"[git-manager: {dropped} earlier bytes dropped]\n{text}"
    return text


async def _feed(stream: asyncio.StreamWriter | None, data: str | None) -> None:
    if stream is None:
        return
    try:
        if data is not None:
            stream.write(data.encode("utf-8"))
            await stream.drain()
        stream.close()
        await stream.wait_closed()
    except BrokenPipeError, ConnectionResetError:
        pass  # The command exited without reading all of its input.


def _signal_group(process: asyncio.subprocess.Process, number: int) -> None:
    # The leader's pid is the group id (``process_group=0``); the group outlives the leader.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, number)


async def _terminate(process: asyncio.subprocess.Process, grace: float) -> None:
    """``SIGTERM`` the group, then ``SIGKILL`` it if the leader is still up after ``grace``."""
    _signal_group(process, signal.SIGTERM)
    try:
        async with asyncio.timeout(grace):
            await process.wait()
    except TimeoutError:
        pass  # Ignored SIGTERM; SIGKILL below cannot be ignored.
    _signal_group(process, signal.SIGKILL)
    await process.wait()


def read_status(fd: int) -> SpawnFailed | None:
    """The enter helper's report: nothing on success, ``errno\\nmessage`` on failure."""
    chunks: list[bytes] = []
    while chunk := os.read(fd, _CHUNK):
        chunks.append(chunk)
    if not chunks:
        return None
    text = b"".join(chunks).decode("utf-8", errors="replace")
    number, newline, message = text.partition("\n")
    if not (newline and number.isdigit()):
        message = text
    return SpawnFailed(code=SpawnErrorCode.START_FAILED, message=message)


class SubprocessLauncher:
    """``CommandLauncher`` that starts each command in its own process group.

    Commands start through ``entry`` (the ``enter`` helper), which changes into the
    working directory only after the switch to the command's user.
    """

    def __init__(
        self,
        *,
        entry: Sequence[str],
        terminate_grace: float = TERMINATE_GRACE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._entry = tuple(entry)
        self._terminate_grace = terminate_grace
        self._monotonic = monotonic

    async def run(self, plan: LaunchPlan) -> LaunchResult:
        """Run ``plan``; see ``CommandLauncher.run``."""
        status_read, status_write = os.pipe()
        try:
            return await self._run(plan, status_read, status_write)
        finally:
            # ``_run`` closes the write end itself, right after the start.
            os.close(status_read)

    async def _run(self, plan: LaunchPlan, status_read: int, status_write: int) -> LaunchResult:
        started = self._monotonic()
        try:
            identity = _identity(plan.account)
            process = await asyncio.create_subprocess_exec(
                *self._entry,
                str(status_write),
                str(plan.cwd),
                ",".join(sorted(_INTERPRETER_ADDED - plan.env.keys())),
                *plan.argv,
                env=dict(plan.env),
                stdin=asyncio.subprocess.PIPE
                if plan.stdin is not None
                else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                pass_fds=(status_write,),
                process_group=0,
                user=None if identity is None else identity.user,
                group=None if identity is None else identity.group,
                extra_groups=None if identity is None else list(identity.extra_groups),
            )
        except OSError as error:
            return SpawnFailed(code=SpawnErrorCode.START_FAILED, message=str(error))
        finally:
            # Only the child may hold the write end, so the read sees end of file.
            os.close(status_write)
        output = asyncio.gather(
            tail_output(process.stdout, plan.output_limit_bytes),
            tail_output(process.stderr, plan.output_limit_bytes),
        )
        feeding = asyncio.create_task(_feed(process.stdin, plan.stdin))
        try:
            timeout = None if plan.timeout is None else plan.timeout.total_seconds()
            try:
                async with asyncio.timeout(timeout):
                    exit_code = await process.wait()
                timed_out = False
            except TimeoutError:
                timed_out = True
                exit_code = None
                await _terminate(process, self._terminate_grace)
            # Whatever the leader left behind in its group goes with it.
            _signal_group(process, signal.SIGKILL)
            try:
                async with asyncio.timeout(_DRAIN_GRACE_SECONDS):
                    stdout, stderr = await output
            except TimeoutError:
                stdout, stderr = "", "[git-manager: output still open after exit; dropped]\n"
        finally:
            # Also reached on cancellation: never leave the command running.
            if process.returncode is None:
                _signal_group(process, signal.SIGKILL)
            output.cancel()
            feeding.cancel()
        duration = max(self._monotonic() - started, 0.0)
        if (failure := read_status(status_read)) is not None:
            return failure
        if timed_out or exit_code is None:
            return SpawnTimedOut(stdout=stdout, stderr=stderr, duration_s=duration)
        return SpawnCompleted(
            exit_code=exit_code, stdout=stdout, stderr=stderr, duration_s=duration
        )


class _DaemonChild:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    async def wait(self) -> int:
        return await self._process.wait()

    def signal(self, number: int) -> None:
        if self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.send_signal(number)


class SubprocessDaemonStarter:
    """``DaemonStarter`` that runs the daemon as a direct child."""

    async def start(
        self, argv: tuple[str, ...], *, account: Account, env: Mapping[str, str]
    ) -> _DaemonChild:
        """Start ``argv`` as ``account``; see ``DaemonStarter.start``.

        It inherits the supervisor's working directory: changing into ``account``'s home
        happens before the user switch, and root cannot enter a ``0700`` home it does not own.
        """
        identity = _identity(account)
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            user=None if identity is None else identity.user,
            group=None if identity is None else identity.group,
            extra_groups=None if identity is None else list(identity.extra_groups),
        )
        return _DaemonChild(process)
