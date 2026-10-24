import httpx

from git_manager.core import HttpOperations, NotFoundError, Operations
from git_manager.health import HealthStatus


async def test_health_goes_through_the_api() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/healthz"
        return httpx.Response(200, json={"status": "ok", "version": "1.2.3"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        operations: Operations = HttpOperations(client)
        status = await operations.health.status()

    assert status == HealthStatus(status="ok", version="1.2.3")


async def test_every_domain_goes_through_the_api() -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(f"{request.method} {request.url.path}")
        body = {
            "detail": "branch not found: f",
            "error": {"type": "not_found", "kind": "branch", "key": "f"},
        }
        return httpx.Response(404, json=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        operations = HttpOperations(client)
        for call in (
            operations.config.show,
            operations.branches.status,
            lambda: operations.branches.pause("f"),
            operations.runs.list,
        ):
            try:
                await call()
            except NotFoundError:
                pass

    assert paths == [
        "GET /api/v1/config",
        "GET /api/v1/repo",
        "POST /api/v1/branches/f/pause",
        "GET /api/v1/runs",
    ]


async def test_the_event_stream_goes_through_the_api() -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, text="")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        events = [event async for event in HttpOperations(client).events.stream()]

    assert events == []
    assert paths == ["GET /api/v1/events"]
