"""The event stream over REST: ``GET /api/v1/events`` as server-sent events, and its
client mirror.
"""

from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Header, Query
from pydantic import ValidationError
from sse_starlette import EventSourceResponse, ServerSentEvent

from git_manager.approvals import Scope
from git_manager.events import Event, EventOperations
from git_manager.web.api_client import API_PREFIX, ApiClient, ApiResponseError
from git_manager.web.auth import Access

EVENTS_PATH = f"{API_PREFIX}/events"


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


@dataclass(frozen=True, slots=True)
class SseFrame:
    """One server-sent event as read off the wire."""

    id: str | None
    data: str


async def sse_frames(lines: AsyncIterable[str]) -> AsyncGenerator[SseFrame]:
    """Parse an SSE body, line by line, into frames.

    A blank line ends a frame; its ``data`` lines are joined with newlines. Comments (the
    server's keep-alive pings), unknown fields and frames without data are skipped, as is
    a frame the stream ends in the middle of.
    """
    frame_id: str | None = None
    data: list[str] = []
    async for line in lines:
        if not line:
            if data:
                yield SseFrame(id=frame_id, data="\n".join(data))
            frame_id = None
            data = []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "data":
            data.append(value)
        elif name == "id":
            frame_id = value


@dataclass(frozen=True, slots=True)
class HttpEventOperations:
    """``EventOperations`` through the REST API's event stream."""

    api: ApiClient

    async def stream(self, *, after: int | None = None) -> AsyncGenerator[Event]:
        """Yield the daemon's events until it stops; close the iterator to leave.

        With ``after``, the daemon first replays the recorded events after that id. The
        stream is not resumed after a dropped connection: that raises
        ``ApiUnreachableError``, and the caller may reconnect with the last id it saw.
        """
        headers = {} if after is None else {"Last-Event-ID": str(after)}
        async with aclosing(self.api.stream_lines(EVENTS_PATH, headers=headers)) as lines:
            async for frame in sse_frames(lines):
                try:
                    event = Event.model_validate_json(frame.data)
                except ValidationError as error:
                    msg = f"unexpected event in the stream: {error.error_count()} error(s)"
                    raise ApiResponseError(msg) from error
                yield event
