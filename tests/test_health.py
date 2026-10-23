from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from git_manager.cli.http_operations import ApiError, ApiUnreachableError, HttpOperations
from git_manager.core import Operations
from git_manager.health import HealthStatus
from git_manager.mcp.server import create_server
from git_manager.web.app import create_app
from tests.conftest import TEST_VERSION

EXPECTED = HealthStatus(status="ok", version=TEST_VERSION)


@asynccontextmanager
async def in_process(service: Operations) -> AsyncGenerator[Operations]:
    yield service


@asynccontextmanager
async def over_rest(service: Operations) -> AsyncGenerator[Operations]:
    transport = httpx.ASGITransport(app=create_app(operations=service, version=TEST_VERSION))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield HttpOperations(client)


@pytest.mark.parametrize("implementation", [in_process, over_rest], ids=["service", "http"])
async def test_operations_contract_health(
    service: Operations,
    implementation: Callable[[Operations], AbstractAsyncContextManager[Operations]],
) -> None:
    async with implementation(service) as operations:
        assert await operations.health() == EXPECTED


def test_rest_health_reports_ok(service: Operations) -> None:
    client = TestClient(create_app(operations=service, version=TEST_VERSION))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": TEST_VERSION}


async def test_mcp_health_tool_reports_ok(service: Operations) -> None:
    async with Client(create_server(operations=service)) as client:
        result = await client.call_tool("health", {})

    assert result.structured_content == {"status": "ok", "version": TEST_VERSION}


async def test_http_operations_raise_api_error_for_error_status() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(403, text="missing scope"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiError) as raised:
            await HttpOperations(client).health()

    assert raised.value.status_code == 403
    assert raised.value.detail == "missing scope"


async def test_http_operations_raise_unreachable_when_transport_fails() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(refuse), base_url="http://test"
    ) as client:
        with pytest.raises(ApiUnreachableError, match="connection refused"):
            await HttpOperations(client).health()
