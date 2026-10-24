from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest

from git_manager.approvals import Authenticator
from git_manager.core import HttpOperations, Operations
from git_manager.health import HealthStatus
from git_manager.web.app import create_app
from tests.conftest import AUTH_HEADERS, TEST_VERSION

EXPECTED = HealthStatus(status="ok", version=TEST_VERSION)


@asynccontextmanager
async def in_process(
    service: Operations, _authenticator: Authenticator
) -> AsyncGenerator[Operations]:
    yield service


@asynccontextmanager
async def over_rest(
    service: Operations, authenticator: Authenticator
) -> AsyncGenerator[Operations]:
    app = create_app(operations=service, version=TEST_VERSION, authenticator=authenticator)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as client:
        yield HttpOperations(client)


@pytest.mark.parametrize("implementation", [in_process, over_rest], ids=["service", "http"])
async def test_operations_contract_health(
    service: Operations,
    authenticator: Authenticator,
    implementation: Callable[[Operations, Authenticator], AbstractAsyncContextManager[Operations]],
) -> None:
    async with implementation(service, authenticator) as operations:
        assert await operations.health.status() == EXPECTED
