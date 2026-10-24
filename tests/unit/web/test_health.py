import httpx
from fastapi import FastAPI

from git_manager.approvals import TrustedAuthenticator
from git_manager.health import HealthOperations, HealthService, StaticHealthReporter
from git_manager.web.api_client import ApiClient
from git_manager.web.auth import Access
from git_manager.web.health import HttpHealthOperations, health_router


async def test_client_mirror_reads_what_the_route_serves() -> None:
    app = FastAPI()
    health = HealthService(reporter=StaticHealthReporter(version="1.0"))
    app.include_router(health_router(health, access=Access(TrustedAuthenticator())))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        operations: HealthOperations = HttpHealthOperations(ApiClient(client))
        status = await operations.status()

    assert status.version == "1.0"
