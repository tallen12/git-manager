"""``GET /api/v1/events`` over a real uvicorn server, a Unix socket and the SQLite log."""

import asyncio
import json
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn

from git_manager.approvals import TrustedAuthenticator
from git_manager.core import Service
from git_manager.core.unavailable import UnavailableBranches, UnavailableConfig, UnavailableRuns
from git_manager.events import Event, EventDraft, EventKind
from git_manager.events.bus import EventBus
from git_manager.events.stream import EventStreamService
from git_manager.health import HealthService, StaticHealthReporter
from git_manager.store.database import open_database
from git_manager.store.repositories import SqlEventRepository
from git_manager.web.app import create_app
from git_manager.web.events import EVENTS_PATH
from git_manager.web.listeners import unix_listener
from tests.conftest import TEST_VERSION, FixedClock

TIMEOUT = 10


@dataclass(frozen=True, slots=True)
class Running:
    """A served app: the bus behind it, its server and a client over its socket."""

    bus: EventBus
    server: uvicorn.Server
    client: httpx.AsyncClient


async def until(check: Callable[[], bool]) -> None:
    """Wait for ``check`` to pass; the server's state has no event to wait on."""
    async with asyncio.timeout(TIMEOUT):
        while True:
            if check():
                return
            await asyncio.sleep(0.01)


@pytest.fixture
async def running(tmp_path: Path) -> AsyncGenerator[Running]:
    reason = "not built in this test"
    # Unix socket paths are limited to about 100 bytes; pytest's tmp_path can be longer.
    with tempfile.TemporaryDirectory(prefix="gm-") as directory:
        async with open_database(tmp_path / "state.db") as database:
            log = SqlEventRepository(database)
            bus = EventBus(repository=log, clock=FixedClock())
            service = Service(
                health=HealthService(reporter=StaticHealthReporter(version=TEST_VERSION)),
                config=UnavailableConfig(reason),
                branches=UnavailableBranches(reason),
                runs=UnavailableRuns(reason),
                events=EventStreamService(source=bus, history=log),
            )
            app = create_app(
                operations=service, version=TEST_VERSION, authenticator=TrustedAuthenticator()
            )
            socket_path = Path(directory) / "api.sock"
            with unix_listener(socket_path) as listener:
                server = uvicorn.Server(
                    uvicorn.Config(app, fd=listener.fileno(), log_level="warning")
                )
                serving = asyncio.create_task(server.serve())
                await until(lambda: server.started)
                transport = httpx.AsyncHTTPTransport(uds=str(socket_path))
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://git-manager", timeout=TIMEOUT
                ) as client:
                    yield Running(bus=bus, server=server, client=client)
                bus.close()
                server.should_exit = True
                await asyncio.wait_for(serving, timeout=TIMEOUT)


async def frames(response: httpx.Response) -> AsyncIterator[tuple[str, Event]]:
    """Each SSE frame's id and event, skipping keep-alive comments."""
    fields: dict[str, str] = {}
    async for line in response.aiter_lines():
        if line:
            if not line.startswith(":"):
                name, _, value = line.partition(": ")
                fields[name] = value
            continue
        if "data" in fields:
            yield fields["id"], Event.model_validate(json.loads(fields["data"]))
        fields = {}


def draft(kind: EventKind = EventKind.TRACKED) -> EventDraft:
    return EventDraft(kind=kind, branch_id="branch-1")


async def test_streams_events_as_they_are_emitted(running: Running) -> None:
    async with running.client.stream("GET", EVENTS_PATH) as response:
        assert response.status_code == 200
        await until(lambda: running.bus.subscriber_count == 1)
        emitted = [await running.bus.emit(draft()), await running.bus.emit(draft(EventKind.PUSHED))]

        received: list[tuple[str, Event]] = []
        async with asyncio.timeout(TIMEOUT):
            async for frame in frames(response):
                received.append(frame)
                if len(received) == len(emitted):
                    break

    assert received == [(str(event.id), event) for event in emitted]


async def test_a_reconnecting_client_replays_what_it_missed(running: Running) -> None:
    first = await running.bus.emit(draft())
    missed = await running.bus.emit(draft(EventKind.UNTRACKED))
    headers = {"Last-Event-ID": str(first.id)}

    async with running.client.stream("GET", EVENTS_PATH, headers=headers) as response:
        async with asyncio.timeout(TIMEOUT):
            frame = await anext(frames(response))

    assert frame == (str(missed.id), missed)


async def test_a_disconnected_client_is_unsubscribed(running: Running) -> None:
    async with running.client.stream("GET", EVENTS_PATH) as response:
        assert response.status_code == 200
        await until(lambda: running.bus.subscriber_count == 1)

    # The server notices the closed connection and closes the stream's subscription.
    await until(lambda: running.bus.subscriber_count == 0)
    await running.bus.emit(draft())


async def test_closing_the_bus_ends_open_streams(running: Running) -> None:
    async with running.client.stream("GET", EVENTS_PATH) as response:
        await until(lambda: running.bus.subscriber_count == 1)

        running.bus.close()

        async with asyncio.timeout(TIMEOUT):
            assert [frame async for frame in frames(response)] == []
