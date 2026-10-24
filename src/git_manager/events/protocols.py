"""Event contracts."""

from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from typing import Protocol, Self

from git_manager.events.models import Event, EventDraft, Notification


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


class EventHistory(Protocol):
    """The recorded event log, read to replay what a client missed."""

    async def list(self, *, after: int = 0, limit: int = 100) -> Sequence[Event]:
        """Return events with an id above ``after``, oldest first."""
        ...


class EventOperations(Protocol):
    """The event stream behind ``GET /api/v1/events`` and ``git-manager watch``."""

    def stream(self, *, after: int | None = None) -> AsyncGenerator[Event]:
        """Yield events in id order until the server stops; close the iterator to leave.

        With ``after``, first replay recorded events with a higher id, so a client that
        reconnects with the last id it saw misses nothing. Without it, only new events.
        """
        ...


class Notifier(Protocol):
    """Shows a notification to the person at the host, e.g. a desktop notification."""

    async def notify(self, notification: Notification) -> None:
        """Show ``notification``; raise ``NotificationError`` if it could not be shown."""
        ...
