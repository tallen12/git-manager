"""FastAPI application factory, its listeners and the server entry point."""

import asyncio
from collections.abc import Generator
from contextlib import ExitStack, contextmanager

import uvicorn
from fastapi import FastAPI

from git_manager.approvals import (
    Authenticator,
    TokenAuthenticator,
    TokensFileError,
    TrustedAuthenticator,
    load_tokens,
)
from git_manager.core import Connector, Operations, Target
from git_manager.web.auth import Access
from git_manager.web.branches import branches_router
from git_manager.web.config import config_router
from git_manager.web.errors import add_error_handlers
from git_manager.web.events import events_router
from git_manager.web.health import health_router
from git_manager.web.listeners import unix_listener
from git_manager.web.runs import runs_router
from git_manager.web.settings import HttpSettings

NO_TOKENS_FILE = (
    "serving REST needs http.tokens_file (GM_HTTP__TOKENS_FILE): every HTTP request needs a "
    "token from it"
)


def create_app(*, operations: Operations, version: str, authenticator: Authenticator) -> FastAPI:
    """Build the REST application; every operation gets an endpoint and a scope."""
    app = FastAPI(title="Git Manager", version=version)
    add_error_handlers(app)
    access = Access(authenticator)
    # One router per domain; each mirrors that domain's operations protocol.
    app.include_router(health_router(operations.health, access=access))
    app.include_router(config_router(operations.config, access=access))
    app.include_router(branches_router(operations.branches, access=access))
    app.include_router(runs_router(operations.runs, access=access))
    app.include_router(events_router(operations.events, access=access))
    return app


@contextmanager
def rest_servers(
    *, operations: Operations, http: HttpSettings, version: str
) -> Generator[list[uvicorn.Server]]:
    """The servers ``http`` asks for: TCP with tokens, plus the Unix socket if set.

    Raises ``TokensFileError`` without a valid tokens file. The socket is removed when the
    block ends.
    """
    if http.tokens_file is None:
        raise TokensFileError(NO_TOKENS_FILE)
    tokens = TokenAuthenticator(load_tokens(http.tokens_file))
    with ExitStack() as stack:
        servers = [
            uvicorn.Server(
                uvicorn.Config(
                    create_app(operations=operations, version=version, authenticator=tokens),
                    host=http.host,
                    port=http.port,
                )
            )
        ]
        if http.socket is not None:
            listener = stack.enter_context(unix_listener(http.socket))
            trusted = TrustedAuthenticator()
            servers.append(
                uvicorn.Server(
                    uvicorn.Config(
                        create_app(operations=operations, version=version, authenticator=trusted),
                        fd=listener.fileno(),
                    )
                )
            )
        yield servers


async def serve(*, connect: Connector, target: Target, http: HttpSettings, version: str) -> None:
    """Serve REST for the operations ``target`` selects until the servers stop."""
    async with connect(target) as operations:
        with rest_servers(operations=operations, http=http, version=version) as servers:
            async with asyncio.TaskGroup() as group:
                for server in servers:
                    group.create_task(server.serve())
