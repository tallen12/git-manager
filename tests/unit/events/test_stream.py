import asyncio
from collections.abc import AsyncGenerator

import pytest

from git_manager.events import Event, EventDraft, EventKind, EventOperations
from git_manager.events.bus import EventBus
from git_manager.events.stream import EventStreamService
from tests.conftest import FixedClock, InMemoryEvents


def draft(branch_id: str = "b") -> EventDraft:
    return EventDraft(kind=EventKind.TRACKED, branch_id=branch_id)


@pytest.fixture
def log() -> InMemoryEvents:
    return InMemoryEvents()


@pytest.fixture
def bus(log: InMemoryEvents, clock: FixedClock) -> EventBus:
    return EventBus(repository=log, clock=clock, queue_size=2)


@pytest.fixture
def events(bus: EventBus, log: InMemoryEvents) -> EventOperations:
    return EventStreamService(source=bus, history=log, page_size=2)


async def take(stream: AsyncGenerator[Event], count: int) -> list[int]:
    ids = [(await asyncio.wait_for(anext(stream), timeout=5)).id for _ in range(count)]
    await stream.aclose()
    return ids


async def started(stream: AsyncGenerator[Event]) -> asyncio.Task[Event]:
    """Start waiting for the first event, so the stream has subscribed."""
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    return task


async def test_without_after_only_new_events_arrive(bus: EventBus, events: EventOperations) -> None:
    await bus.emit(draft())
    stream = events.stream()
    first = await started(stream)

    await bus.emit(draft())

    assert (await asyncio.wait_for(first, timeout=5)).id == 2
    await stream.aclose()


async def test_after_replays_the_log_across_pages_then_follows_live(
    bus: EventBus, events: EventOperations
) -> None:
    for _ in range(5):
        await bus.emit(draft())
    stream = events.stream(after=1)

    replayed = [(await anext(stream)).id for _ in range(4)]
    following = await started(stream)
    await bus.emit(draft())

    assert replayed == [2, 3, 4, 5]
    assert (await asyncio.wait_for(following, timeout=5)).id == 6
    await stream.aclose()


async def test_events_emitted_during_the_replay_arrive_once(
    bus: EventBus, events: EventOperations
) -> None:
    await bus.emit(draft())
    stream = events.stream(after=0)

    assert (await anext(stream)).id == 1
    # Subscribed before the replay: this lands both in the log and in the queue.
    await bus.emit(draft())

    assert await take(stream, 1) == [2]


async def test_a_lagging_stream_catches_up_from_the_log(
    bus: EventBus, events: EventOperations
) -> None:
    stream = events.stream()
    first = await started(stream)
    await bus.emit(draft())
    assert (await asyncio.wait_for(first, timeout=5)).id == 1

    # Queue size 2: the third event unread drops the subscription.
    for _ in range(4):
        await bus.emit(draft())

    assert await take(stream, 4) == [2, 3, 4, 5]
    assert bus.subscriber_count == 0


async def test_closing_the_stream_ends_its_subscription(
    bus: EventBus, events: EventOperations
) -> None:
    stream = events.stream()
    waiting = await started(stream)
    assert bus.subscriber_count == 1

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await stream.aclose()

    assert bus.subscriber_count == 0


async def test_closing_the_bus_ends_the_stream(bus: EventBus, events: EventOperations) -> None:
    stream = events.stream()
    waiting = await started(stream)

    bus.close()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, timeout=5)


def test_page_size_must_be_positive(bus: EventBus, log: InMemoryEvents) -> None:
    with pytest.raises(ValueError, match="page_size"):
        EventStreamService(source=bus, history=log, page_size=0)
