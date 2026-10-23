"""FastAPI application factory."""

from fastapi import FastAPI

from git_manager.core import Operations
from git_manager.health import HealthStatus


def create_app(*, operations: Operations, version: str) -> FastAPI:
    """Build the REST application; every operation gets an endpoint."""
    app = FastAPI(title="Git Manager", version=version)

    @app.get("/healthz")
    async def healthz() -> HealthStatus:
        return await operations.health()

    return app
