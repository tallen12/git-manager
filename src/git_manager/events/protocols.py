"""Event contracts."""

from typing import Protocol

from git_manager.events.models import Event, EventDraft


class EventSink(Protocol):
    """Where domain code reports what happened; the bus persists and fans it out."""

    async def emit(self, draft: EventDraft) -> Event:
        """Record ``draft`` and deliver it to subscribers; return the recorded event."""
        ...
