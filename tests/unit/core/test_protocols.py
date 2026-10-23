from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest

from git_manager.cli.http_operations import HttpOperations
from git_manager.core import Operations
from git_manager.health import HealthStatus
from tests.conftest import TEST_VERSION

EXPECTED = HealthStatus(status="ok", version=TEST_VERSION)


@asynccontextmanager
async def in_process(service: Operations) -> AsyncGenerator[Operations]:
    yield service


@asynccontextmanager
async def over_fake_http(_service: Operations) -> AsyncGenerator[Operations]:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, content=EXPECTED.model_dump_json())
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield HttpOperations(client)


@pytest.mark.parametrize(
    "implementation", [in_process, over_fake_http], ids=["service", "http-client"]
)
async def test_every_implementation_reports_health(
    service: Operations,
    implementation: Callable[[Operations], AbstractAsyncContextManager[Operations]],
) -> None:
    async with implementation(service) as operations:
        assert await operations.health() == EXPECTED
