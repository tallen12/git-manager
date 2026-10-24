import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from git_manager.approvals import ApiToken, Authenticator, Scope, TokenAuthenticator, TokensFile
from git_manager.branches import BranchState
from git_manager.events import Event, EventKind, EventOperations
from git_manager.web.auth import Access
from git_manager.web.events import EVENTS_PATH, event_frame, events_router
from tests.conftest import AUTH_HEADERS, START

EVENTS = (
    Event(id=4, at=START, kind=EventKind.RUN_STARTED, branch_id="b", run_id="r"),
    Event(
        id=5, at=START, kind=EventKind.STATE_CHANGED, branch_id="b", state=BranchState.TESTS_FAILED
    ),
)


@dataclass(slots=True)
class FiniteEvents:
    """``EventOperations`` that streams ``events`` and ends, recording each ``after``."""

    events: tuple[Event, ...] = EVENTS
    calls: list[int | None] = field(default_factory=list)
    closed: int = 0

    async def stream(self, *, after: int | None = None) -> AsyncGenerator[Event]:
        self.calls.append(after)
        try:
            for event in self.events:
                yield event
        finally:
            self.closed += 1


def app_for(operations: EventOperations, authenticator: Authenticator) -> FastAPI:
    app = FastAPI()
    app.include_router(events_router(operations, access=Access(authenticator)))
    return app


def parse(body: str) -> list[dict[str, str]]:
    """The SSE frames in ``body`` as field maps, keep-alive comments skipped."""
    frames: list[dict[str, str]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":")
        )
        if fields:
            frames.append(fields)
    return frames


def test_event_frame_carries_the_id_and_the_event_as_json() -> None:
    frame = event_frame(EVENTS[1])

    assert frame.id == "5"
    assert isinstance(frame.data, str)
    assert Event.model_validate_json(frame.data) == EVENTS[1]


def test_streams_each_event_as_a_frame(authenticator: Authenticator) -> None:
    operations = FiniteEvents()
    client = TestClient(app_for(operations, authenticator))

    response = client.get(EVENTS_PATH, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = parse(response.text)
    assert [frame["id"] for frame in frames] == ["4", "5"]
    assert [Event.model_validate(json.loads(frame["data"])) for frame in frames] == list(EVENTS)
    assert operations.calls == [None]
    assert operations.closed == 1


@pytest.mark.parametrize(
    ("query", "headers", "after"),
    [
        ("?after=3", {}, 3),
        ("", {"Last-Event-ID": "7"}, 7),
        ("?after=3", {"Last-Event-ID": "7"}, 7),
    ],
)
def test_resumes_after_last_event_id_or_the_after_query(
    authenticator: Authenticator, query: str, headers: dict[str, str], after: int
) -> None:
    operations = FiniteEvents()
    client = TestClient(app_for(operations, authenticator))

    response = client.get(EVENTS_PATH + query, headers={**AUTH_HEADERS, **headers})

    assert response.status_code == 200
    assert operations.calls == [after]


def test_rejects_a_negative_resume_id(authenticator: Authenticator) -> None:
    operations = FiniteEvents()
    client = TestClient(app_for(operations, authenticator))

    response = client.get(EVENTS_PATH + "?after=-1", headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert operations.calls == []


def test_needs_a_token_with_the_read_scope() -> None:
    token = "operate-only-token-0123456789abcdef0123"
    entry = ApiToken(name="agent", token=SecretStr(token), scopes=frozenset({Scope.OPERATE}))
    operations = FiniteEvents()
    client = TestClient(app_for(operations, TokenAuthenticator(TokensFile(tokens=(entry,)))))

    assert client.get(EVENTS_PATH).status_code == 401
    forbidden = client.get(EVENTS_PATH, headers={"Authorization": f"Bearer {token}"})
    assert forbidden.status_code == 403
    assert "read" in forbidden.json()["detail"]
    assert operations.calls == []
