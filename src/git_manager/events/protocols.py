"""Event contracts."""

from collections.abc import AsyncIterator, Callable
from typing import Protocol, Self

from git_manager.events.models import Event, EventDraft


class EventSink(Protocol):
    """Where domain code reports what happened; the bus persists and fans it out."""

    async def emit(self, draft: EventDraft) -> Event:
        """Record ``draft`` and deliver it to subscribers; return the recorded event."""
        ...


class EventSubscription(Protocol):
    """Events delivered to one in-process subscriber, oldest first.

    Iteration ends when the subscription or the bus is closed, and raises
    ``SubscriberLaggedError`` after the last delivered event if the subscriber fell behind.
    """

    def __aiter__(self) -> AsyncIterator[Event]:
        """Iterate over delivered events."""
        ...

    def close(self) -> None:
        """Stop receiving events; events already queued are still delivered."""
        ...

    def __enter__(self) -> Self:
        """Return the subscription; leaving the block closes it."""
        ...

    def __exit__(self, *exc_info: object) -> None:
        """Close the subscription."""
        ...


class EventSource(Protocol):
    """Where SSE, webhooks and notifiers subscribe to events as they are emitted."""

    def subscribe(self, *, accept: Callable[[Event], bool] | None = None) -> EventSubscription:
        """Start receiving events emitted from now on that ``accept`` (default: all)."""
        ...
