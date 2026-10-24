"""Health over REST: the route and its client mirror."""

from dataclasses import dataclass

from fastapi import APIRouter

from git_manager.approvals import Scope
from git_manager.health import HealthOperations, HealthStatus
from git_manager.web.api_client import ApiClient
from git_manager.web.auth import Access

HEALTH_PATH = "/healthz"


def health_router(operations: HealthOperations, *, access: Access) -> APIRouter:
    """Routes for ``HealthOperations``."""
    router = APIRouter()

    @router.get(HEALTH_PATH, dependencies=[access.requires(Scope.READ)])
    async def healthz() -> HealthStatus:
        return await operations.status()

    return router


@dataclass(frozen=True, slots=True)
class HttpHealthOperations:
    """``HealthOperations`` through the REST API."""

    api: ApiClient

    async def status(self) -> HealthStatus:
        """Report the daemon's health."""
        return await self.api.get(HEALTH_PATH, HealthStatus)
