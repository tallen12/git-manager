import asyncio
import signal
from dataclasses import dataclass, field

import pytest

from git_manager.web.daemon import run_until_stopped, stop_on_signals


@dataclass(slots=True)
class FakeDaemon:
    """``Stoppable`` that runs until ``stop``, or fails at once with ``error``."""

    error: Exception | None = None
    stops: int = 0
    stopped: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self) -> None:
        if self.error is not None:
            raise self.error
        await self.stopped.wait()

    def stop(self) -> None:
        self.stops += 1
        self.stopped.set()


class FakeServer:
    """``Server`` that serves until ``should_exit``, or ends by itself when ``finite``."""

    def __init__(self, *, finite: bool = False) -> None:
        self._finite = finite
        self._exit = asyncio.Event()

    @property
    def should_exit(self) -> bool:
        return self._exit.is_set()

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        if value:
            self._exit.set()

    async def serve(self) -> None:
        if not self._finite:
            await self._exit.wait()


async def test_stop_on_signals_calls_stop_and_restores_the_handlers() -> None:
    calls: list[str] = []
    before = signal.getsignal(signal.SIGTERM)

    with stop_on_signals(lambda: calls.append("stop")):
        signal.raise_signal(signal.SIGTERM)
        await asyncio.sleep(0)

    assert calls == ["stop"]
    assert signal.getsignal(signal.SIGTERM) == before


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT])
async def test_a_stop_signal_stops_the_daemon_and_the_server(number: signal.Signals) -> None:
    daemon, server = FakeDaemon(), FakeServer()
    task = asyncio.create_task(run_until_stopped(daemon, server))
    await asyncio.sleep(0)

    signal.raise_signal(number)
    await asyncio.wait_for(task, timeout=5)

    assert daemon.stopped.is_set()
    assert server.should_exit


async def test_the_daemon_stops_when_the_server_ends() -> None:
    daemon, server = FakeDaemon(), FakeServer(finite=True)

    await asyncio.wait_for(run_until_stopped(daemon, server), timeout=5)

    assert daemon.stops >= 1


async def test_a_failing_daemon_takes_the_server_down() -> None:
    daemon, server = FakeDaemon(error=RuntimeError("store gone")), FakeServer()

    with pytest.raises(RuntimeError, match="store gone"):
        await asyncio.wait_for(run_until_stopped(daemon, server), timeout=5)

    assert server.should_exit
