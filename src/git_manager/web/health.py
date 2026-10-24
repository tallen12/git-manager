"""Health over REST: the route and its client mirror."""

from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import TypeAdapter

from git_manager.approvals import Scope
from git_manager.health import HealthOperations, HealthStatus
from git_manager.web.api_client import API_PREFIX, ApiClient
from git_manager.web.auth import Access
from git_manager.web.errors import ERROR_RESPONSES

HEALTH_PATH = f"{API_PREFIX}/healthz"

_STATUS = TypeAdapter(HealthStatus)


def health_router(operations: HealthOperations, *, access: Access) -> APIRouter:
    """Routes for ``HealthOperations``."""
    router = APIRouter(tags=["health"], responses=ERROR_RESPONSES)

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
        return await self.api.get(HEALTH_PATH, _STATUS)
