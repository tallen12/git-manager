"""The event stream over REST: ``GET /api/v1/events`` as server-sent events."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sse_starlette import EventSourceResponse, ServerSentEvent

from git_manager.approvals import Scope
from git_manager.events import Event, EventOperations
from git_manager.web.auth import Access

EVENTS_PATH = "/api/v1/events"


def event_frame(event: Event) -> ServerSentEvent:
    """One SSE frame: the event as JSON, with its id so a client can resume after it."""
    return ServerSentEvent(data=event.model_dump_json(), id=str(event.id))


async def _frames(events: AsyncGenerator[Event]) -> AsyncIterator[ServerSentEvent]:
    # ``aclosing``: when the client disconnects, the stream is closed here at once, which
    # ends its bus subscription, instead of whenever the generator is collected.
    async with aclosing(events) as stream:
        async for event in stream:
            yield event_frame(event)


def events_router(operations: EventOperations, *, access: Access) -> APIRouter:
    """Routes for ``EventOperations``."""
    router = APIRouter()

    @router.get(
        EVENTS_PATH,
        dependencies=[access.requires(Scope.READ)],
        response_class=EventSourceResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def events(
        after: Annotated[int | None, Query(ge=0)] = None,
        last_event_id: Annotated[int | None, Header(ge=0)] = None,
    ) -> EventSourceResponse:
        """Stream events as they happen; each frame's data is one ``Event`` as JSON.

        A reconnecting client sends ``Last-Event-ID`` (or ``?after=``) to replay what it
        missed first; the header wins when both are set.
        """
        start = last_event_id if last_event_id is not None else after
        return EventSourceResponse(_frames(operations.stream(after=start)))

    return router
