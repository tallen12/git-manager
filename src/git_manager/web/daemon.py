"""``serve``: the REST server and the daemon's loops in one process, until a stop signal."""

import asyncio
import signal
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from datetime import timedelta
from types import FrameType
from typing import Protocol

import uvicorn

from git_manager.branches.daemon import DEFAULT_TICK, AsyncioSleeper, Daemon
from git_manager.branches.poller import Poller
from git_manager.branches.queue import FifoRunQueue
from git_manager.core.compose import LocalRuntime
from git_manager.web.app import create_app
from git_manager.web.settings import HttpSettings

STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


class Server(Protocol):
    """A server that runs until it is told to exit (``uvicorn.Server``)."""

    should_exit: bool

    async def serve(self) -> None:
        """Serve until ``should_exit`` is set or a stop signal arrives."""
        ...


class Stoppable(Protocol):
    """Runs until asked to stop (``Daemon``)."""

    async def run(self) -> None:
        """Run until ``stop``, then return once in-flight work has finished."""
        ...

    def stop(self) -> None:
        """Ask ``run`` to return."""
        ...


@contextmanager
def stop_on_signals(
    stop: Callable[[], None], *, signals: Sequence[signal.Signals] = STOP_SIGNALS
) -> Generator[None]:
    """Call ``stop`` on the event loop whenever one of ``signals`` arrives in the block.

    Installed with ``signal.signal`` rather than ``loop.add_signal_handler``: uvicorn
    replaces the handlers while it serves, then restores these and raises the signal it
    caught again, which lands here. Without them the re-raised SIGTERM would kill the
    process before the current run finishes.
    """
    loop = asyncio.get_running_loop()

    def handle(_number: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop)

    previous = {number: signal.signal(number, handle) for number in signals}
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


async def run_until_stopped(daemon: Stoppable, server: Server) -> None:
    """Run both until either ends; then stop the other and wait for it.

    A stop signal ends the server first (uvicorn handles it); the daemon then finishes its
    current run. A daemon that fails takes the server down with it. The first error is
    raised once both have ended.
    """
    with stop_on_signals(daemon.stop):
        tasks = [
            asyncio.create_task(daemon.run(), name="git-manager-daemon"),
            asyncio.create_task(server.serve(), name="git-manager-rest"),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            daemon.stop()
            server.should_exit = True
            await asyncio.wait(tasks)
        for task in tasks:
            if (error := task.exception()) is not None:
                raise error


async def serve_daemon(
    runtime: LocalRuntime, *, http: HttpSettings, version: str, tick: timedelta = DEFAULT_TICK
) -> None:
    """Serve REST for ``runtime`` and poll and run its branches until a stop signal.

    ``open_local`` holds the data-directory lock around this call, so the lock is released
    only after the last run has finished.
    """
    queue = FifoRunQueue(clock=runtime.clock)
    poller = Poller(
        git=runtime.git,
        branches=runtime.branches,
        events=runtime.events,
        queue=queue,
        clock=runtime.clock,
    )
    daemon = Daemon(
        poller=poller,
        queue=queue,
        executor=runtime.executor,
        config=runtime.service.config,
        branches=runtime.branches,
        sleeper=AsyncioSleeper(),
        tick=tick,
    )
    config = uvicorn.Config(
        create_app(operations=runtime.service, version=version), host=http.host, port=http.port
    )
    await run_until_stopped(daemon, uvicorn.Server(config))
