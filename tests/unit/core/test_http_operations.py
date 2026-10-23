import httpx
import pytest

from git_manager.core.http_operations import ApiError, ApiUnreachableError, HttpOperations
from git_manager.health import HealthStatus


async def test_health_parses_the_response_body() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"status": "ok", "version": "1.2.3"})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await HttpOperations(client).health()

    assert status == HealthStatus(status="ok", version="1.2.3")


async def test_error_status_raises_api_error() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(403, text="missing scope"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiError) as raised:
            await HttpOperations(client).health()

    assert raised.value.status_code == 403
    assert raised.value.detail == "missing scope"


async def test_transport_failure_raises_unreachable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(refuse), base_url="http://test"
    ) as client:
        with pytest.raises(ApiUnreachableError, match="connection refused"):
            await HttpOperations(client).health()
