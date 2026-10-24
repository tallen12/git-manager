"""The in-process event bus: persist each event, then fan it out to subscribers."""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Self

from git_manager.events.errors import SubscriberLaggedError
from git_manager.events.models import Event, EventDraft
from git_manager.runtime.protocols import Clock
from git_manager.store.protocols import EventRepository

DEFAULT_QUEUE_SIZE = 256


@dataclass(frozen=True, slots=True)
class _Closed:
    """The subscription was closed; iteration stops after the queued events."""


@dataclass(frozen=True, slots=True)
class _Lagged:
    """The queue overflowed; iteration raises after the queued events."""

    last_id: int


type _Ending = _Closed | _Lagged


class Subscription:
    """One subscriber's bounded queue of events (an ``EventSubscription``)."""

    def __init__(
        self,
        *,
        accept: Callable[[Event], bool],
        queue_size: int,
        on_close: Callable[[Self], None],
    ) -> None:
        self._accept = accept
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=queue_size)
        self._on_close = on_close
        self._ending: _Ending | None = None
        self._last_queued = 0

    def offer(self, event: Event) -> None:
        """Queue ``event`` if accepted, without waiting; a full queue ends the subscription."""
        if self._ending is not None or not self._accept(event):
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Never wait for a slow subscriber: drop it and let it catch up from the log.
            self._end(_Lagged(last_id=self._last_queued))
            return
        self._last_queued = event.id

    def close(self) -> None:
        self._end(_Closed())

    def _end(self, ending: _Ending) -> None:
        if self._ending is not None:
            return
        self._ending = ending
        self._on_close(self)
        # Wake a reader waiting on an empty queue. A full queue has no waiting reader.
        if not self._queue.full():
            self._queue.put_nowait(None)

    async def _events(self) -> AsyncIterator[Event]:
        while True:
            if self._queue.empty() and self._ending is not None:
                break
            item = await self._queue.get()
            if item is None:
                break
            yield item
        if isinstance(self._ending, _Lagged):
            raise SubscriberLaggedError(last_id=self._ending.last_id)

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._events()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _accept_all(_event: Event) -> bool:
    return True


class EventBus:
    """Records events through the repository and delivers them to in-process subscribers.

    Emitting never waits on a subscriber: each has a bounded queue, and one that fills
    is dropped with ``SubscriberLaggedError``. Events reach subscribers in id order.
    """

    def __init__(
        self,
        *,
        repository: EventRepository,
        clock: Clock,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        if queue_size < 1:
            msg = "queue_size must be at least 1"
            raise ValueError(msg)
        self._repository = repository
        self._clock = clock
        self._queue_size = queue_size
        self._subscriptions: list[Subscription] = []
        # Holds append and fan-out together so concurrent emits reach subscribers in id order.
        self._lock = asyncio.Lock()

    async def emit(self, draft: EventDraft) -> Event:
        async with self._lock:
            event = await self._repository.append(draft, at=self._clock.now())
            for subscription in tuple(self._subscriptions):
                subscription.offer(event)
        return event

    def subscribe(self, *, accept: Callable[[Event], bool] | None = None) -> Subscription:
        subscription = Subscription(
            accept=accept or _accept_all,
            queue_size=self._queue_size,
            on_close=self._unsubscribe,
        )
        self._subscriptions.append(subscription)
        return subscription

    @property
    def subscriber_count(self) -> int:
        """How many subscriptions are open."""
        return len(self._subscriptions)

    def close(self) -> None:
        """End every subscription, e.g. on shutdown; emitting still records events."""
        for subscription in tuple(self._subscriptions):
            subscription.close()

    def _unsubscribe(self, subscription: Subscription) -> None:
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)
