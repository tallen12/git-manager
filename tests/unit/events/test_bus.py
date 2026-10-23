import asyncio
from datetime import datetime, timedelta
from typing import override

import pytest

from git_manager.branches import BranchState
from git_manager.events import (
    Event,
    EventDraft,
    EventKind,
    EventSink,
    EventSource,
    SubscriberLaggedError,
)
from git_manager.events.bus import EventBus, Subscription
from tests.conftest import START, FixedClock, InMemoryEvents


def draft(branch_id: str = "b", kind: EventKind = EventKind.TRACKED) -> EventDraft:
    return EventDraft(kind=kind, branch_id=branch_id)


async def collect(subscription: Subscription) -> list[int]:
    return [event.id async for event in subscription]


@pytest.fixture
def log() -> InMemoryEvents:
    return InMemoryEvents()


@pytest.fixture
def bus(log: InMemoryEvents, clock: FixedClock) -> EventBus:
    return EventBus(repository=log, clock=clock, queue_size=3)


async def test_emit_persists_with_the_clock_time(
    bus: EventBus, log: InMemoryEvents, clock: FixedClock
) -> None:
    sink: EventSink = bus
    first = await sink.emit(draft())
    clock.advance(timedelta(minutes=1))
    second = await sink.emit(draft(kind=EventKind.UNTRACKED))

    assert log.rows == [first, second]
    assert [(event.id, event.at) for event in log.rows] == [
        (1, START),
        (2, START + timedelta(minutes=1)),
    ]


async def test_emit_with_no_subscribers_only_records(bus: EventBus, log: InMemoryEvents) -> None:
    await bus.emit(draft())

    assert len(log.rows) == 1
    assert bus.subscriber_count == 0


async def test_subscribers_each_receive_events_emitted_after_subscribing(bus: EventBus) -> None:
    source: EventSource = bus
    await bus.emit(draft("before"))
    first = source.subscribe()
    second = source.subscribe()

    await bus.emit(draft("x"))
    await bus.emit(draft("y"))
    bus.close()

    assert await collect(first) == [2, 3]
    assert await collect(second) == [2, 3]
    assert bus.subscriber_count == 0


async def test_accept_filters_what_a_subscriber_receives(bus: EventBus) -> None:
    subscription = bus.subscribe(accept=lambda event: event.branch_id == "wanted")

    await bus.emit(draft("other"))
    await bus.emit(draft("wanted"))
    subscription.close()

    assert await collect(subscription) == [2]


async def test_a_waiting_subscriber_wakes_on_emit(bus: EventBus) -> None:
    received: list[Event] = []

    async def consume(subscription: Subscription) -> None:
        async for event in subscription:
            received.append(event)

    with bus.subscribe() as subscription:
        task = asyncio.create_task(consume(subscription))
        await asyncio.sleep(0)
        await bus.emit(draft())
        await asyncio.sleep(0)
        assert [event.id for event in received] == [1]
    await asyncio.wait_for(task, timeout=1)


async def test_closing_keeps_queued_events_and_stops_further_delivery(bus: EventBus) -> None:
    subscription = bus.subscribe()
    await bus.emit(draft())
    subscription.close()
    await bus.emit(draft())

    assert await collect(subscription) == [1]
    assert bus.subscriber_count == 0


async def test_closing_twice_is_harmless(bus: EventBus) -> None:
    with bus.subscribe() as subscription:
        subscription.close()

    assert await collect(subscription) == []


async def test_a_full_subscriber_is_dropped_without_blocking_the_emitter(
    bus: EventBus, log: InMemoryEvents
) -> None:
    slow = bus.subscribe()
    fast = bus.subscribe()
    consumer = asyncio.create_task(collect(fast))

    for _ in range(5):
        await asyncio.wait_for(bus.emit(draft()), timeout=1)
        await asyncio.sleep(0)

    assert len(log.rows) == 5
    assert bus.subscriber_count == 1
    bus.close()
    assert await asyncio.wait_for(consumer, timeout=1) == [1, 2, 3, 4, 5]
    delivered: list[int] = []
    with pytest.raises(SubscriberLaggedError) as lagged:
        async for event in slow:
            delivered.append(event.id)
    assert delivered == [1, 2, 3]
    assert lagged.value.last_id == 3


async def test_lag_counts_only_events_the_subscriber_accepted(
    log: InMemoryEvents, clock: FixedClock
) -> None:
    bus = EventBus(repository=log, clock=clock, queue_size=1)
    subscription = bus.subscribe(accept=lambda event: event.id > 1)

    await bus.emit(draft())
    await bus.emit(draft())
    await bus.emit(draft())

    with pytest.raises(SubscriberLaggedError) as lagged:
        await collect(subscription)
    assert lagged.value.last_id == 2


async def test_concurrent_emits_reach_subscribers_in_id_order(clock: FixedClock) -> None:
    class SlowFirstAppend(InMemoryEvents):
        @override
        async def append(self, draft: EventDraft, *, at: datetime) -> Event:
            event = await super().append(draft, at=at)
            if event.id == 1:
                await asyncio.sleep(0.01)
            return event

    bus = EventBus(repository=SlowFirstAppend(), clock=clock, queue_size=10)
    subscription = bus.subscribe()

    await asyncio.gather(bus.emit(draft("a")), bus.emit(draft("b")))
    bus.close()

    assert await collect(subscription) == [1, 2]


def test_queue_size_must_be_positive(log: InMemoryEvents, clock: FixedClock) -> None:
    with pytest.raises(ValueError, match="queue_size"):
        EventBus(repository=log, clock=clock, queue_size=0)


async def test_state_change_events_carry_their_state(bus: EventBus) -> None:
    event = await bus.emit(
        EventDraft(kind=EventKind.STATE_CHANGED, branch_id="b", state=BranchState.BEHIND)
    )

    assert event.state is BranchState.BEHIND
