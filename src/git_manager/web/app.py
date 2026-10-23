"""FastAPI application factory and server entry point."""

import uvicorn
from fastapi import FastAPI

from git_manager.core import Connector, Operations, Target
from git_manager.health import HealthStatus


def create_app(*, operations: Operations, version: str) -> FastAPI:
    """Build the REST application; every operation gets an endpoint."""
    app = FastAPI(title="Git Manager", version=version)

    @app.get("/healthz")
    async def healthz() -> HealthStatus:
        return await operations.health()

    return app


async def serve(*, connect: Connector, target: Target, version: str, host: str, port: int) -> None:
    """Serve REST for the operations ``target`` selects until the server stops."""
    async with connect(target) as operations:
        config = uvicorn.Config(
            create_app(operations=operations, version=version), host=host, port=port
        )
        await uvicorn.Server(config).serve()
