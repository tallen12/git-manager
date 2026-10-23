"""Health over REST: the route and its client mirror."""

from dataclasses import dataclass

from fastapi import APIRouter

from git_manager.health import HealthOperations, HealthStatus
from git_manager.web.api_client import ApiClient

HEALTH_PATH = "/healthz"


def health_router(operations: HealthOperations) -> APIRouter:
    """Routes for ``HealthOperations``."""
    router = APIRouter()

    @router.get(HEALTH_PATH)
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
