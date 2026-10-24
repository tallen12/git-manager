import httpx
import pytest

from git_manager.core import HttpOperations, Operations, UnavailableError
from git_manager.health import HealthStatus


async def test_health_goes_through_the_api() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"status": "ok", "version": "1.2.3"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as client:
        operations: Operations = HttpOperations(client)
        status = await operations.health.status()

    assert status == HealthStatus(status="ok", version="1.2.3")


async def test_operations_not_in_the_api_yet_point_to_local_mode() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        msg = f"unexpected request {request.url}"
        raise AssertionError(msg)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(fail), base_url="http://test"
    ) as client:
        operations = HttpOperations(client)
        with pytest.raises(UnavailableError, match="local mode"):
            await operations.branches.status()
