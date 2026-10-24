"""In-process event stream: replay from the log, then follow the bus without gaps."""

from collections.abc import AsyncGenerator, AsyncIterator

from git_manager.events.errors import SubscriberLaggedError
from git_manager.events.models import Event
from git_manager.events.protocols import EventHistory, EventSource

DEFAULT_PAGE_SIZE = 100


class EventStreamService:
    """``EventOperations`` over the bus and the event log.

    It subscribes before replaying, so an event emitted during the replay is not lost,
    and skips live events the replay already yielded. A subscriber the bus drops for
    falling behind catches up from the log and subscribes again, so a slow client sees
    every event once, in id order.
    """

    def __init__(
        self, *, source: EventSource, history: EventHistory, page_size: int = DEFAULT_PAGE_SIZE
    ) -> None:
        if page_size < 1:
            msg = "page_size must be at least 1"
            raise ValueError(msg)
        self._source = source
        self._history = history
        self._page_size = page_size

    async def stream(self, *, after: int | None = None) -> AsyncGenerator[Event]:
        last = after
        while True:
            with self._source.subscribe() as subscription:
                if last is not None:
                    async for event in self._replay(after=last):
                        yield event
                        last = event.id
                try:
                    async for event in subscription:
                        if last is not None and event.id <= last:
                            continue
                        yield event
                        last = event.id
                except SubscriberLaggedError as error:
                    # Everything up to ``error.last_id`` was yielded; the rest is in the log.
                    last = max(last or 0, error.last_id)
                    continue
            # The bus closed the subscription: the server is stopping.
            return

    async def _replay(self, *, after: int) -> AsyncIterator[Event]:
        while True:
            page = await self._history.list(after=after, limit=self._page_size)
            for event in page:
                yield event
                after = event.id
            if len(page) < self._page_size:
                return
