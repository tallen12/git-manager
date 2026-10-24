"""FastAPI application factory and server entry point."""

import uvicorn
from fastapi import FastAPI

from git_manager.core import Connector, Operations, Target
from git_manager.web.health import health_router
from git_manager.web.settings import HttpSettings


def create_app(*, operations: Operations, version: str) -> FastAPI:
    """Build the REST application; every operation gets an endpoint."""
    app = FastAPI(title="Git Manager", version=version)
    # One router per domain; each mirrors that domain's operations protocol.
    app.include_router(health_router(operations.health))
    return app


async def serve(*, connect: Connector, target: Target, http: HttpSettings, version: str) -> None:
    """Serve REST for the operations ``target`` selects until the server stops."""
    async with connect(target) as operations:
        config = uvicorn.Config(
            create_app(operations=operations, version=version), host=http.host, port=http.port
        )
        await uvicorn.Server(config).serve()
